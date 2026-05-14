"""
aura_field.py — v0.4
The field protocol. UDP multicast. No server.

New in v0.4:
  - Cryptographic Identity (Ed25519)
  - Private Aura / Peer Encryption (X25519 + ChaCha20-Poly1305)
  - Partial Field Visibility (Multicast Channels)
"""

import os
import json
import socket
import struct
import time
import shutil
import threading
import uuid
import base64
import hashlib
import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path
from aura_folder import FolderAura

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.exceptions import InvalidSignature

# ==============================================================================
# CLOSED IF SET CORE
# ==============================================================================

class ClosedIfSet:
    __slots__ = ('value', 'cache', '_ts')
    def __init__(self, value: Any):
        self.value = value
        self.cache = None
        self._ts = 0.0

class Affirm(ClosedIfSet):
    """Direct path - always recomputes. Use for dynamic data."""
    def test(self, fn: Callable) -> Any:
        return fn(self.value)
    def flip(self) -> 'ClosedIfSet':
        return Deny(self.value)

class Deny(ClosedIfSet):
    """Memory path - computes once, caches. Use for expensive/static."""
    def test(self, fn: Callable) -> Any:
        if self.cache is None:
            self.cache = fn(self.value)
            self._ts = time.time()
        return self.cache
    def flip(self) -> 'ClosedIfSet':
        return Affirm(self.value)
    def invalidate(self):
        self.cache = None
        self._ts = 0.0
    def age(self) -> float:
        return time.time() - self._ts if self._ts else float('inf')

def cond(value: Any, cached: bool = False) -> ClosedIfSet:
    return Deny(value) if cached else Affirm(value)


# ==============================================================================
# INTELLIGENCE LEDGER (NOT Money)
# ==============================================================================

class IntelligenceLedger:
    def __init__(self, aura_dir: Path):
        self.path = aura_dir / "ledger.json"
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {"balance": 0.0, "history": []}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self._data, indent=2))
        except Exception:
            pass

    def credit(self, points: float, reason: str):
        if points <= 0: return
        with self._lock:
            self._data["balance"] += points
            self._data["history"].append({
                "ts": time.time(),
                "points": round(points, 4),
                "reason": reason
            })
            # keep last 50 entries
            self._data["history"] = self._data["history"][-50:]
            self._save()

    @property
    def balance(self) -> float:
        return self._data["balance"]

# ==============================================================================
# PELL-LUCAS TEMPORAL SPINE
# Compresses infinite history into O(log n) hierarchical levels
# ==============================================================================

class PellLucasSpine:
    SILVER = 1.0 + math.sqrt(2)  # ~2.414

    def __init__(self, max_levels: int = 16):
        self.max_levels = max_levels
        self._pell = self._compute_pell(max_levels + 2)

    def _compute_pell(self, n: int) -> List[int]:
        p = [0, 1]
        for i in range(2, n):
            p.append(2 * p[-1] + p[-2])
        return p

    def level_of(self, t: int) -> int:
        if t <= 0:
            return 0
        return min(int(math.log(max(t, 1)) / math.log(self.SILVER)), self.max_levels)

    def context_window(self, level: int) -> int:
        return self._pell[min(level + 1, len(self._pell) - 1)]

    def encode(self, history: List[float], levels: int = 8) -> List[float]:
        """Compress history into multi-scale features using Pell window sizes."""
        result = []
        for lvl in range(min(levels, self.max_levels)):
            window = self.context_window(lvl)
            slice_ = history[-window:] if len(history) >= window else history
            if slice_:
                avg = sum(slice_) / len(slice_)
                variance = sum((x - avg) ** 2 for x in slice_) / len(slice_)
                result.append(avg)
                result.append(math.sqrt(variance + 1e-10))
            else:
                result.extend([0.0, 0.0])
        return result


# ── Wire protocol ─────────────────────────────────────────────────────────
FIELD_GROUP   = "239.77.77.77"
FIELD_PORT    = 7777
MAGIC         = b"\xA0\x52"
PROTO_VER     = 4   # v0.4

MSG_ANNOUNCE  = 0x01  # "my folder is here, here is its aura"
MSG_SEEK      = 0x02  # "I want X"
MSG_RESONATE  = 0x03  # "I match your seek"
MSG_ROUTE     = 0x04  # "delivering a file to your in/"
MSG_PULL_REQ  = 0x05  # "send me file X from your shared/"
MSG_PULL_DATA = 0x06  # "here is the file you asked for"
MSG_TALK_OPEN = 0x07  # "I want a bidirectional session"
MSG_TALK_LINE = 0x08  # "one line in a talk session"
MSG_LEAVE     = 0x09  # "I am going offline"


def _enc(msg_type: int, payload: dict, private_key: ed25519.Ed25519PrivateKey = None, x_pub_bytes: bytes = None) -> bytes:
    # include public key in payload if we are signing
    if private_key:
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        payload["pub"] = base64.b64encode(pub_bytes).decode()
    
    if x_pub_bytes:
        payload["x_pub"] = base64.b64encode(x_pub_bytes).decode()

    body   = json.dumps(payload, separators=(",",":")).encode()
    
    # signature
    sig_bytes = b""
    if private_key:
        sig_bytes = private_key.sign(body)
    
    header = MAGIC + bytes([PROTO_VER, msg_type])
    # [MAGIC 2][VER 1][TYPE 1][BODY_LEN 2][SIG_LEN 2] = 8 bytes header
    full_header = header + struct.pack("!HH", len(body), len(sig_bytes))
    return full_header + sig_bytes + body

def _dec(data: bytes):
    if len(data) < 8 or data[:2] != MAGIC:
        return None
    
    msg_type = data[3]
    body_len, sig_len = struct.unpack("!HH", data[4:8])
    
    sig_start = 8
    body_start = sig_start + sig_len
    
    sig_bytes = data[sig_start:body_start]
    body_bytes = data[body_start:body_start+body_len]
    
    try:
        payload = json.loads(body_bytes.decode())
        
        # verify signature if present
        if sig_len > 0 and "pub" in payload:
            pub_bytes = base64.b64decode(payload["pub"])
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
            public_key.verify(sig_bytes, body_bytes)
            payload["_verified"] = True
        else:
            payload["_verified"] = False
            
        return msg_type, payload
    except Exception:
        return None


class AuraField:
    """
    One node in the AURA field.
    Manages a folder, announces its aura, routes files, speaks the protocol.
    """

    def __init__(self, folder_path: str, name: str = None, channel: str = None):
        self.channel  = channel
        self.field_group = FIELD_GROUP
        self.field_port  = FIELD_PORT
        
        if channel:
            # Derive port/group from channel name
            h = hashlib.md5(channel.encode()).digest()
            # map to 239.x.y.z where x,y,z are from hash
            self.field_group = f"239.{h[0]}.{h[1]}.{h[2]}"
            # map to port 7000-8000
            self.field_port = 7000 + (struct.unpack(">H", h[3:5])[0] % 1000)

        self.folder   = FolderAura(folder_path).scan()
        pub_bytes = self.folder.get_public_key_bytes()
        self.node_id  = hashlib.sha256(pub_bytes).hexdigest()[:16]
        # AYR Wallet Address derived from pub key
        self.wallet_addr = "AYR" + hashlib.sha256(pub_bytes).hexdigest()[:32].upper()
        self.ledger = IntelligenceLedger(self.folder.aura_dir)
        self.spine = PellLucasSpine()
        self.resonance_history = []
        
        self.name     = name or self.folder.meta.get("name", Path(folder_path).name)
        self.peers:   dict[str, dict] = {}
        self._lock    = threading.Lock()
        self._running = False
        self._tx = self._rx = None

        # callbacks
        self._on_peer      = []
        self._on_seek      = []
        self._on_route     = []   # file arrived in in/
        self._on_talk      = []   # someone opened a talk session
        self._talk_sessions: dict[str, list] = {}  # session_id → lines

        self._ensure_structure()
        self._write_lock()

    # ── structure ─────────────────────────────────────────────────────────

    def _ensure_structure(self):
        """Create in/ out/ shared/ if they don't exist."""
        base = self.folder.path
        for d in ("in", "out", "shared"):
            (base / d).mkdir(exist_ok=True)

    def _write_lock(self):
        """Write aura.lock — runtime state of this node."""
        lock = {
            "node_id":   self.node_id,
            "name":      self.name,
            "pid":       os.getpid(),
            "started":   time.time(),
            "field":     f"{self.field_group}:{self.field_port}",
            "channel":   self.channel,
            "proto":     f"v0.{PROTO_VER}",
        }
        try:
            (self.folder.path / "aura.lock").write_text(
                json.dumps(lock, indent=2)
            )
        except Exception:
            pass

    def _clear_lock(self):
        try:
            (self.folder.path / "aura.lock").unlink(missing_ok=True)
        except Exception:
            pass

    # ── lifecycle ─────────────────────────────────────────────────────────

    def join(self):
        self._setup_sockets()
        self._running = True
        threading.Thread(target=self._rx_loop,       daemon=True, name="aura-rx").start()
        threading.Thread(target=self._announce_loop, daemon=True, name="aura-tx").start()
        threading.Thread(target=self._watch_out,     daemon=True, name="aura-out").start()
        threading.Thread(target=self._rescan_loop,   daemon=True, name="aura-scan").start()

    def leave(self):
        if self._running:
            self._send(MSG_LEAVE, {"node_id": self.node_id, "name": self.name})
            self._running = False
        self._clear_lock()
        try: self._tx.close()
        except: pass
        try: self._rx.close()
        except: pass

    # ── actions ───────────────────────────────────────────────────────────

    def seek(self, query: str) -> list[dict]:
        """Broadcast seek. Score all known peers. Return sorted matches."""
        self._send(MSG_SEEK, {
            "node_id": self.node_id,
            "name":    self.name,
            "query":   query,
            "ts":      time.time(),
        })
        results = []
        with self._lock:
            for pid, peer in self.peers.items():
                fa = _peer_aura(peer)
                score = fa.resonate(query)
                if score > 0.05:
                    results.append({
                        "node_id":     pid,
                        "name":        peer.get("name"),
                        "score":       round(score, 3),
                        "addr":        peer.get("addr", ""),
                        "tags":        list(peer.get("summary",{}).get("tags",{}).keys())[:8],
                        "entry":       peer.get("summary",{}).get("entry"),
                        "description": peer.get("summary",{}).get("description",""),
                        "path":        peer.get("summary",{}).get("path",""),
                        "structure":   peer.get("summary",{}).get("structure",{}),
                    })
        results.sort(key=lambda x: -x["score"])
        return results

    def route_file(self, target_node_id: str, file_path: str):
        """
        Drop a file into another node's in/ folder.
        This is shadow mail. No app. Just a file moving.
        If target is local — copy directly.
        If remote — announce over the field (future: direct TCP transfer).
        """
        p = Path(file_path)
        if not p.exists():
            return False, "file not found"

        with self._lock:
            peer = self.peers.get(target_node_id)

        content = p.read_bytes()
        encrypted = False
        nonce_b64 = None

        if peer and "x_pub" in peer:
            try:
                # Diffie-Hellman
                peer_x_pub = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(peer["x_pub"]))
                shared_key = self.folder.get_x_private_key().exchange(peer_x_pub)
                
                # KDF
                derived_key = HKDF(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=None,
                    info=b"aura-v4-file-encryption",
                ).derive(shared_key)
                
                # Encrypt
                chacha = ChaCha20Poly1305(derived_key)
                nonce = os.urandom(12)
                ciphertext = chacha.encrypt(nonce, content, None)
                
                content = base64.b64encode(ciphertext).decode()
                nonce_b64 = base64.b64encode(nonce).decode()
                encrypted = True
            except Exception:
                content = content.decode(errors="ignore")[:4096]
        else:
            content = content.decode(errors="ignore")[:4096]

        self._send(MSG_ROUTE, {
            "node_id":    self.node_id,
            "name":       self.name,
            "target":     target_node_id,
            "filename":   p.name,
            "content":    content,
            "encrypted":  encrypted,
            "nonce":      nonce_b64,
            "ts":         time.time(),
        })
        return True, "announced to field"

    def pull(self, target_node_id: str, filename: str) -> str | None:
        """
        Copy a file from another node's shared/ into our in/.
        If the peer is local, copy directly.
        """
        with self._lock:
            peer = self.peers.get(target_node_id)

        if not peer:
            return None

        target_path = peer.get("summary", {}).get("path")
        if not target_path:
            return None

        src = Path(target_path) / "shared" / filename
        if not src.exists():
            return None

        dest = self.folder.path / "in" / filename
        shutil.copy2(str(src), str(dest))
        return str(dest)

    def talk(self, target_node_id: str, line: str, session_id: str = None) -> str | None:
        """
        Send a line to another node's entry point.
        Returns response if the peer is local (entry point executes and responds).
        """
        if not session_id:
            session_id = str(uuid.uuid4())[:6]

        with self._lock:
            peer = self.peers.get(target_node_id)

        if not peer:
            return None

        target_path = peer.get("summary", {}).get("path")
        if not target_path:
            return None

        fa = FolderAura(target_path).scan()
        proc = fa.run_entry(env_extra={
            "AURA_VISITOR":    self.node_id,
            "AURA_QUERY":      line,
            "AURA_SESSION":    session_id,
            "AURA_TALK_INPUT": line,
        })
        if not proc:
            return None

        try:
            out, _ = proc.communicate(timeout=5)
            return out.strip()
        except Exception:
            return None

    def shared_files(self, node_id: str = None) -> list[dict]:
        """List files in shared/ — own or a peer's."""
        if node_id is None:
            shared = self.folder.path / "shared"
        else:
            with self._lock:
                peer = self.peers.get(node_id)
            if not peer:
                return []
            path = peer.get("summary",{}).get("path","")
            shared = Path(path) / "shared" if path else None
            if not shared:
                return []

        if not shared.exists():
            return []
        return [
            {
                "name":     f.name,
                "size":     f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in sorted(shared.iterdir())
            if f.is_file() and not f.name.startswith(".")
        ]

    def in_files(self) -> list[dict]:
        """What arrived in your in/ folder."""
        d = self.folder.path / "in"
        if not d.exists():
            return []
        return [
            {
                "name":     f.name,
                "size":     f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in sorted(d.iterdir())
            if f.is_file() and not f.name.startswith(".")
        ]

    # ── callbacks ─────────────────────────────────────────────────────────

    def on_peer(self, fn):  self._on_peer.append(fn)
    def on_seek(self, fn):  self._on_seek.append(fn)
    def on_route(self, fn): self._on_route.append(fn)
    def on_talk(self, fn):  self._on_talk.append(fn)

    def peers_list(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "node_id":   pid,
                    "name":      p.get("name"),
                    "tags":      list(p.get("summary",{}).get("tags",{}).keys())[:6],
                    "entry":     p.get("summary",{}).get("entry"),
                    "addr":      p.get("addr",""),
                    "last_seen": p.get("last_seen",0),
                    "structure": p.get("summary",{}).get("structure",{}),
                }
                for pid, p in self.peers.items()
            ]

    # ── shadow routing: watch out/, route when there's resonance ──────────

    def _watch_out(self):
        """
        Watches out/ folder.
        When a new file appears — scans the field for resonant peers
        and routes the file to their in/ folders.
        This is shadow mail. No send button. Files move by resonance.
        """
        out_dir = self.folder.path / "out"
        seen: set = set()

        while self._running:
            time.sleep(2)
            if not out_dir.exists():
                continue

            current = {f.name for f in out_dir.iterdir() if f.is_file()}
            new_files = current - seen
            seen = current

            for fname in new_files:
                fpath = out_dir / fname
                self._shadow_route(fpath)

    def _shadow_route(self, file_path: Path):
        """
        Route a file from out/ to resonant peers' in/ folders.
        The filename + content determine who receives it.
        """
        # build a tiny aura from just this file
        query_words = (
            file_path.stem.lower()
            .replace("_"," ").replace("-"," ").split()
        )
        # try to read text content for more signal
        try:
            content = file_path.read_text(errors="ignore")[:500]
            query_words += [w for w in content.lower().split()
                            if len(w) > 4][:10]
        except Exception:
            pass

        query = " ".join(set(query_words[:12]))

        with self._lock:
            peers = list(self.peers.items())

        routed_to = []
        for pid, peer in peers:
            fa  = _peer_aura(peer)
            scr = fa.resonate(query)
            if scr > 0.15:
                target_path = peer.get("summary",{}).get("path","")
                if target_path:
                    dest_dir = Path(target_path) / "in"
                    dest_dir.mkdir(exist_ok=True)
                    dest = dest_dir / file_path.name
                    try:
                        shutil.copy2(str(file_path), str(dest))
                        routed_to.append(peer.get("name","?"))
                        for fn in self._on_route:
                            fn(pid, peer.get("name","?"), file_path.name, scr)
                    except Exception:
                        pass

        return routed_to

    # ── networking ────────────────────────────────────────────────────────

    def _log(self, msg: str):
        log_file = self.folder.aura_dir / "field.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_file, "a") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def _setup_sockets(self):
        try:
            self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
            self._tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._rx.bind(("", self.field_port))
            except OSError as e:
                self._log(f"Error binding to port {self.field_port}: {e}")
                # Try binding to all interfaces if empty string fails on some systems
                self._rx.bind(("0.0.0.0", self.field_port))
                
            mreq = struct.pack("4sL", socket.inet_aton(self.field_group), socket.INADDR_ANY)
            self._rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self._rx.settimeout(1.0)
        except Exception as e:
            self._log(f"Socket setup failed: {e}")
            raise

    def _send(self, msg_type: int, payload: dict):
        try:
            pkt = _enc(msg_type, payload, self.folder.get_private_key())
            self._tx.sendto(pkt, (self.field_group, self.field_port))
        except Exception:
            pass

    def _announce(self):
        payload = {
            "node_id": self.node_id,
            "name":    self.name,
            "summary": self.folder.summary(),
            "ts":      time.time(),
            "x_pub":   base64.b64encode(self.folder.get_x_public_key_bytes()).decode()
        }
        self._send(MSG_ANNOUNCE, payload)

    def _announce_loop(self):
        self._announce()
        while self._running:
            time.sleep(15)
            self._announce()

    def _rx_loop(self):
        while self._running:
            try:
                data, addr = self._rx.recvfrom(65535)
                dec = _dec(data)
                if dec is None:
                    continue
                msg_type, payload = dec
                if payload.get("node_id") == self.node_id:
                    continue
                
                # Enforce signature verification for v0.4
                if not payload.get("_verified"):
                    self._log(f"Rejected unverified packet from {addr[0]}")
                    continue

                self._handle(msg_type, payload, addr[0])
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                self._log(f"Malformed JSON from {addr[0]}")
            except Exception as e:
                self._log(f"RX error: {e}")
                continue

    def _handle(self, msg_type: int, payload: dict, addr: str):
        pid  = payload.get("node_id")
        name = payload.get("name", "?")

        if msg_type == MSG_ANNOUNCE:
            with self._lock:
                self.peers[pid] = {
                    "name":      name,
                    "summary":   payload.get("summary", {}),
                    "addr":      addr,
                    "last_seen": time.time(),
                    "x_pub":     payload.get("x_pub")
                }
            for fn in self._on_peer:
                fn(pid, name, payload.get("summary", {}))

        elif msg_type == MSG_SEEK:
            query = payload.get("query", "")
            score = self.folder.resonate(query)
            if score > 0.05:
                self._send(MSG_RESONATE, {
                    "node_id": self.node_id,
                    "name":    self.name,
                    "score":   round(score, 3),
                    "summary": self.folder.summary(),
                })
                # Award intelligence points for high resonance responses
                if score > 0.5:
                    pts = (score - 0.5) * 2.0
                    self.ledger.credit(pts, f"Resonated to seek: {query[:20]}...")

            for fn in self._on_seek:
                fn(pid, name, query, score)

        elif msg_type == MSG_RESONATE:
            with self._lock:
                if pid not in self.peers:
                    self.peers[pid] = {}
                self.peers[pid].update({
                    "name":      name,
                    "summary":   payload.get("summary", {}),
                    "addr":      addr,
                    "last_seen": time.time(),
                })

        elif msg_type == MSG_ROUTE:
            # someone is routing a file to us
            if payload.get("target") == self.node_id:
                # Award points for receiving routed content
                self.ledger.credit(0.1, "Received routed file")
                
                fname   = os.path.basename(payload.get("filename", "received"))
                content = payload.get("content", "")
                encrypted = payload.get("encrypted", False)
                nonce_b64 = payload.get("nonce")
                
                if encrypted and nonce_b64 and "pub" in payload:
                    try:
                        # Decrypt
                        peer_x_pub_bytes = base64.b64decode(payload.get("x_pub", ""))
                        if not peer_x_pub_bytes:
                            # If x_pub not in route, we might have it from announce
                            with self._lock:
                                peer_x_pub_bytes = base64.b64decode(self.peers.get(pid, {}).get("x_pub", ""))
                        
                        if peer_x_pub_bytes:
                            peer_x_pub = x25519.X25519PublicKey.from_public_bytes(peer_x_pub_bytes)
                            shared_key = self.folder.get_x_private_key().exchange(peer_x_pub)
                            derived_key = HKDF(
                                algorithm=hashes.SHA256(),
                                length=32,
                                salt=None,
                                info=b"aura-v4-file-encryption",
                            ).derive(shared_key)
                            
                            chacha = ChaCha20Poly1305(derived_key)
                            nonce = base64.b64decode(nonce_b64)
                            ciphertext = base64.b64decode(content)
                            content_bytes = chacha.decrypt(nonce, ciphertext, None)
                            
                            dest = self.folder.path / "in" / fname
                            (self.folder.path / "in").mkdir(exist_ok=True)
                            dest.write_bytes(content_bytes)
                            for fn in self._on_route:
                                fn(pid, name, fname, 1.0)
                    except Exception:
                        pass
                else:
                    dest = self.folder.path / "in" / fname
                    (self.folder.path / "in").mkdir(exist_ok=True)
                    try:
                        if isinstance(content, str):
                            dest.write_text(content)
                        else:
                            dest.write_bytes(content)
                        for fn in self._on_route:
                            fn(pid, name, fname, 1.0)
                    except Exception:
                        pass

        elif msg_type == MSG_LEAVE:
            with self._lock:
                self.peers.pop(pid, None)

    def _rescan_loop(self):
        """Re-scan folder every 30s. If fingerprint changed, re-announce."""
        last = self.folder.fingerprint()
        while self._running:
            time.sleep(30)
            try:
                self.folder = FolderAura(str(self.folder.path)).scan()
                fp = self.folder.fingerprint()
                if fp != last:
                    last = fp
                    self._announce()
                    self._write_lock()
            except Exception:
                pass


# ── helpers ───────────────────────────────────────────────────────────────

def _peer_aura(peer: dict) -> FolderAura:
    """Build a lightweight FolderAura from a peer's summary for scoring."""
    fa       = object.__new__(FolderAura)
    fa.tags  = peer.get("summary", {}).get("tags", {})
    fa.files = []
    fa.meta  = {}
    fa.entry = None
    fa.path  = Path(peer.get("summary", {}).get("path", "/"))
    return fa

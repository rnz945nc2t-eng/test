"""
aura_field.py — v0.3
The field protocol. UDP multicast. No server.

New in v0.3:
  - Shadow routing: files in out/ get routed to resonant in/ folders
  - Field watcher: detects changes in out/ and routes them
  - Talk protocol: bidirectional entry point sessions
  - Pull: copy a file from another node's shared/
  - aura.lock: runtime state written per node
"""

import os
import json
import socket
import struct
import time
import shutil
import threading
import uuid
from pathlib import Path
from aura_folder import FolderAura

# ── Wire protocol ─────────────────────────────────────────────────────────
FIELD_GROUP   = "239.77.77.77"
FIELD_PORT    = 7777
MAGIC         = b"\xA0\x52"
PROTO_VER     = 3   # v0.3

MSG_ANNOUNCE  = 0x01  # "my folder is here, here is its aura"
MSG_SEEK      = 0x02  # "I want X"
MSG_RESONATE  = 0x03  # "I match your seek"
MSG_ROUTE     = 0x04  # "delivering a file to your in/"
MSG_PULL_REQ  = 0x05  # "send me file X from your shared/"
MSG_PULL_DATA = 0x06  # "here is the file you asked for"
MSG_TALK_OPEN = 0x07  # "I want a bidirectional session"
MSG_TALK_LINE = 0x08  # "one line in a talk session"
MSG_LEAVE     = 0x09  # "I am going offline"


def _enc(msg_type: int, payload: dict) -> bytes:
    body   = json.dumps(payload, separators=(",",":")).encode()
    header = MAGIC + bytes([PROTO_VER, msg_type])
    return header + struct.pack("!H", len(body)) + body

def _dec(data: bytes):
    if len(data) < 6 or data[:2] != MAGIC:
        return None
    msg_type = data[3]
    length   = struct.unpack("!H", data[4:6])[0]
    try:
        return msg_type, json.loads(data[6:6+length].decode())
    except Exception:
        return None


class AuraField:
    """
    One node in the AURA field.
    Manages a folder, announces its aura, routes files, speaks the protocol.
    """

    def __init__(self, folder_path: str, name: str = None):
        self.node_id  = str(uuid.uuid4())[:8]
        self.folder   = FolderAura(folder_path).scan()
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
            "field":     f"{FIELD_GROUP}:{FIELD_PORT}",
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

        if peer:
            target_path = peer.get("summary", {}).get("path")
            if target_path:
                dest = Path(target_path) / "in" / p.name
                try:
                    shutil.copy2(str(p), str(dest))
                    return True, str(dest)
                except Exception as e:
                    pass  # fall through to field announce

        # announce over field (remote nodes will handle it)
        content = ""
        try:
            content = p.read_text(errors="ignore")[:4096]
        except Exception:
            pass

        self._send(MSG_ROUTE, {
            "node_id":    self.node_id,
            "name":       self.name,
            "target":     target_node_id,
            "filename":   p.name,
            "content":    content,
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

    def _setup_sockets(self):
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
        self._tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._rx.bind(("", FIELD_PORT))
        mreq = struct.pack("4sL", socket.inet_aton(FIELD_GROUP), socket.INADDR_ANY)
        self._rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._rx.settimeout(1.0)

    def _send(self, msg_type: int, payload: dict):
        try:
            self._tx.sendto(_enc(msg_type, payload), (FIELD_GROUP, FIELD_PORT))
        except Exception:
            pass

    def _announce(self):
        self._send(MSG_ANNOUNCE, {
            "node_id": self.node_id,
            "name":    self.name,
            "summary": self.folder.summary(),
            "ts":      time.time(),
        })

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
                self._handle(msg_type, payload, addr[0])
            except socket.timeout:
                continue
            except Exception:
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
                fname   = payload.get("filename", "received")
                content = payload.get("content", "")
                dest    = self.folder.path / "in" / fname
                (self.folder.path / "in").mkdir(exist_ok=True)
                try:
                    dest.write_text(content)
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

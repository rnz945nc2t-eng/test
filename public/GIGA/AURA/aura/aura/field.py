"""
aura.field — Production field protocol (UDP multicast + TCP transfer)

The field is a UDP multicast mesh. Every node announces itself,
listens for peers, responds to seeks, and routes files.

For files larger than UDP_MAX_PAYLOAD, the field negotiates a direct
TCP connection between nodes (TCP_OFFER / TCP_ACCEPT).

For WAN deployment, nodes register with relay servers which forward
packets across network boundaries.

Architecture:
  - UDP multicast socket (rx/tx) — discovery, seeks, small messages
  - TCP server thread           — large file transfers, talk streams
  - Relay client thread         — WAN forwarding (optional)
  - Out-folder watcher          — auto-routes files dropped in out/
  - Re-scan loop                — detects folder changes, re-announces
"""

from __future__ import annotations
import os
import socket
import struct
import time
import uuid
import base64
import shutil
import hashlib
import logging
import threading
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .crypto import (
    Identity,
    MSG_ANNOUNCE, MSG_SEEK, MSG_RESONATE, MSG_ROUTE,
    MSG_PULL_REQ, MSG_PULL_DATA, MSG_TALK_OPEN, MSG_TALK_LINE,
    MSG_LEAVE, MSG_RELAY_REG, MSG_RELAY_FWD, MSG_PING, MSG_PONG,
    MSG_TCP_OFFER, MSG_ACK,
)
from .folder  import FolderAura
from .ledger  import IntelligenceLedger
from .config  import Config

log = logging.getLogger("aura.field")

UDP_MAX_PAYLOAD = 60_000   # bytes — switch to TCP above this
CHUNK_SIZE      = 65_536   # 64 KB per TCP chunk


# ── Peer record ───────────────────────────────────────────────────────────────

class Peer:
    __slots__ = (
        "node_id", "name", "addr", "tcp_port",
        "summary", "x_pub", "last_seen", "ed_pub",
    )

    def __init__(self, node_id: str, name: str, addr: str):
        self.node_id  = node_id
        self.name     = name
        self.addr     = addr
        self.tcp_port: Optional[int] = None
        self.summary:  dict          = {}
        self.x_pub:    Optional[str] = None
        self.ed_pub:   Optional[str] = None
        self.last_seen = time.time()

    def to_dict(self) -> dict:
        return {
            "node_id":   self.node_id,
            "name":      self.name,
            "addr":      self.addr,
            "tcp_port":  self.tcp_port,
            "summary":   self.summary,
            "x_pub":     self.x_pub,
            "last_seen": self.last_seen,
            "tags":      list((self.summary.get("tags") or {}).keys())[:8],
            "entry":     self.summary.get("entry"),
            "structure": self.summary.get("structure", {}),
        }


# ── AuraField ────────────────────────────────────────────────────────────────

class AuraField:
    """
    One node in the AURA field.
    Call join() to start broadcasting, leave() to shut down cleanly.
    """

    def __init__(
        self,
        folder_path: str | Path,
        name: Optional[str] = None,
        channel: Optional[str] = None,
    ):
        self._cfg     = Config()
        self.folder   = FolderAura(folder_path).scan()
        self.identity = self.folder.identity
        self.node_id  = self.identity.node_id
        self.wallet   = self.identity.wallet_addr
        self.name     = name or self.folder.meta.get("name", self.folder.path.name)
        self.channel  = channel
        self.ledger   = IntelligenceLedger(self.folder.aura_dir)

        # resolve multicast parameters
        self.field_group, self.field_port = self._resolve_field(channel)
        self.tcp_port = self._cfg.get("transfer", "tcp_port", default=7780)

        # peer registry
        self._peers:   Dict[str, Peer] = {}
        self._lock     = threading.Lock()
        self._running  = False

        # sockets
        self._tx_sock: Optional[socket.socket] = None
        self._rx_sock: Optional[socket.socket] = None
        self._tcp_srv: Optional[socket.socket] = None

        # event callbacks
        self._on_peer:  List[Callable] = []
        self._on_seek:  List[Callable] = []
        self._on_route: List[Callable] = []
        self._on_leave: List[Callable] = []

        # talk sessions: session_id → list of lines
        self._talk_sessions: Dict[str, List[str]] = {}

        # relay
        self._relay_sock: Optional[socket.socket] = None
        self._relay_addr: Optional[Tuple[str, int]] = None

        # logging to .aura/field.log
        self._setup_logging()
        self.folder.ensure_structure()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def join(self):
        """Start participating in the field."""
        self._setup_sockets()
        self._running = True
        self.folder.write_lock(
            self.node_id, self.name,
            f"{self.field_group}:{self.field_port}",
            self.channel, os.getpid(),
        )
        # start background threads
        threading.Thread(target=self._rx_loop,       daemon=True, name="aura.rx").start()
        threading.Thread(target=self._announce_loop, daemon=True, name="aura.tx").start()
        threading.Thread(target=self._tcp_server,    daemon=True, name="aura.tcp").start()
        threading.Thread(target=self._watch_out,     daemon=True, name="aura.out").start()
        threading.Thread(target=self._rescan_loop,   daemon=True, name="aura.scan").start()
        threading.Thread(target=self._evict_loop,    daemon=True, name="aura.evict").start()
        # connect to relays if configured
        relays = self._cfg.get("field", "relays", default=[])
        if relays:
            threading.Thread(target=self._relay_connect, args=(relays,),
                             daemon=True, name="aura.relay").start()
        log.info(f"Joined field {self.field_group}:{self.field_port} as {self.name} [{self.node_id}]")

    def leave(self):
        """Announce departure and shut down all sockets/threads."""
        if self._running:
            try:
                self._send(MSG_LEAVE, {"node_id": self.node_id, "name": self.name})
            except Exception:
                pass
            self._running = False
        self.folder.clear_lock()
        for sock in (self._tx_sock, self._rx_sock, self._tcp_srv, self._relay_sock):
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
        log.info(f"Left field — {self.name} [{self.node_id}]")

    # ── Field actions ──────────────────────────────────────────────────────────

    def seek(self, query: str) -> List[dict]:
        """Broadcast seek and return locally scored results."""
        self._send(MSG_SEEK, {
            "node_id": self.node_id, "name": self.name,
            "query": query, "ts": time.time(),
        })
        with self._lock:
            peers = list(self._peers.values())
        results = []
        for peer in peers:
            fa    = self._peer_aura(peer)
            score = fa.resonate(query)
            if score > 0.05:
                results.append({**peer.to_dict(), "score": round(score, 3)})
        results.sort(key=lambda x: -x["score"])
        return results

    def who(self) -> List[dict]:
        """List all currently known peers."""
        with self._lock:
            return [p.to_dict() for p in self._peers.values()]

    def shared_files(self, node_id: Optional[str] = None) -> List[dict]:
        """List shared/ files. node_id=None → your own."""
        if node_id is None:
            return self.folder.shared_files()
        with self._lock:
            peer = self._peers.get(node_id)
        if not peer:
            return []
        path = peer.summary.get("path")
        if path and Path(path).exists():
            return FolderAura(path).shared_files()
        return []

    def in_files(self) -> List[dict]:
        return self.folder.in_files()

    def pull(self, target_id: str, filename: str) -> Optional[str]:
        """Copy a file from a peer's shared/ into our in/."""
        with self._lock:
            peer = self._peers.get(target_id)
        if not peer:
            return None
        path = peer.summary.get("path")
        if path:
            src = Path(path) / "shared" / filename
            if src.exists():
                dest = self.folder.path / "in" / filename
                shutil.copy2(str(src), str(dest))
                self.ledger.credit(0.2, f"pulled:{filename}", target_id)
                return str(dest)
        return None

    def route_file(self, target_id: str, file_path: str | Path) -> Tuple[bool, str]:
        """Route a file to a peer's in/ folder."""
        p = Path(file_path)
        if not p.exists():
            return False, "file not found"
        with self._lock:
            peer = self._peers.get(target_id)
        if not peer:
            return False, "peer not found"

        # local shortcut
        local_path = peer.summary.get("path")
        if local_path and Path(local_path).exists():
            dest = Path(local_path) / "in" / p.name
            dest.parent.mkdir(exist_ok=True)
            shutil.copy2(str(p), str(dest))
            return True, "delivered locally"

        # network: encrypt if peer has x_pub
        content = p.read_bytes()
        payload: dict = {
            "node_id": self.node_id, "name": self.name,
            "target": target_id, "filename": p.name, "ts": time.time(),
        }
        if peer.x_pub and len(content) < UDP_MAX_PAYLOAD:
            try:
                peer_xb  = base64.b64decode(peer.x_pub)
                ct, nonce = self.identity.encrypt_for(peer_xb, content)
                payload.update({
                    "content":   base64.b64encode(ct).decode(),
                    "nonce":     base64.b64encode(nonce).decode(),
                    "encrypted": True,
                })
            except Exception:
                payload.update({
                    "content":   base64.b64encode(content).decode(),
                    "encrypted": False,
                })
        elif len(content) >= UDP_MAX_PAYLOAD:
            # offer TCP transfer
            return self._tcp_offer(peer, p)
        else:
            payload.update({
                "content":   base64.b64encode(content).decode(),
                "encrypted": False,
            })
        self._send(MSG_ROUTE, payload)
        return True, "sent"

    def talk(self, target_id: str, line: str, session_id: Optional[str] = None) -> Optional[str]:
        """Send a line to a peer's entry point and return the response."""
        if not session_id:
            session_id = str(uuid.uuid4())[:6]
        with self._lock:
            peer = self._peers.get(target_id)
        if not peer:
            return None
        local_path = peer.summary.get("path")
        if not local_path or not Path(local_path).exists():
            return None
        fa = FolderAura(local_path).scan()
        proc = fa.run_entry(env_extra={
            "AURA_VISITOR":    self.node_id,
            "AURA_QUERY":      line,
            "AURA_SESSION":    session_id,
        })
        if not proc:
            return None
        try:
            out, _ = proc.communicate(timeout=8)
            return out.strip() if out else None
        except Exception:
            return None

    def peers_list(self) -> List[dict]:
        with self._lock:
            return [p.to_dict() for p in self._peers.values()]

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_peer(self,  fn: Callable): self._on_peer.append(fn)
    def on_seek(self,  fn: Callable): self._on_seek.append(fn)
    def on_route(self, fn: Callable): self._on_route.append(fn)
    def on_leave(self, fn: Callable): self._on_leave.append(fn)

    # ── Socket setup ──────────────────────────────────────────────────────────

    def _setup_sockets(self):
        # TX
        self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._tx_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                                  self._cfg.get("field", "ttl", default=8))
        self._tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # RX
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        self._rx_sock.bind(("", self.field_port))
        mreq = struct.pack("4sL", socket.inet_aton(self.field_group), socket.INADDR_ANY)
        self._rx_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._rx_sock.settimeout(1.0)

    def _setup_logging(self):
        fh = logging.FileHandler(self.folder.aura_dir / "field.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        log.setLevel(logging.DEBUG)

    def _log(self, msg: str):
        log.info(msg)

    # ── Wire ──────────────────────────────────────────────────────────────────

    def _send(self, msg_type: int, payload: dict):
        try:
            pkt = self.identity.encode(msg_type, payload)
            self._tx_sock.sendto(pkt, (self.field_group, self.field_port))
            if self._relay_sock and self._relay_addr:
                self._relay_sock.sendto(pkt, self._relay_addr)
        except Exception as e:
            log.debug(f"send error: {e}")

    # ── Announce ──────────────────────────────────────────────────────────────

    def _announce(self):
        self._send(MSG_ANNOUNCE, {
            "node_id":  self.node_id,
            "name":     self.name,
            "summary":  self.folder.summary(),
            "tcp_port": self.tcp_port,
            "ts":       time.time(),
        })

    def _announce_loop(self):
        self._announce()
        interval = self._cfg.get("node", "announce_interval", default=15)
        while self._running:
            time.sleep(interval)
            if self._running:
                self._announce()

    # ── RX loop ───────────────────────────────────────────────────────────────

    def _rx_loop(self):
        while self._running:
            try:
                data, addr = self._rx_sock.recvfrom(65535)
                dec = Identity.decode(data, require_sig=True)
                if dec is None:
                    continue
                msg_type, payload = dec
                if payload.get("node_id") == self.node_id:
                    continue
                self._handle(msg_type, payload, addr[0])
            except socket.timeout:
                continue
            except Exception as e:
                log.debug(f"rx error: {e}")

    def _handle(self, msg_type: int, payload: dict, addr: str):
        pid  = payload.get("node_id", "")
        name = payload.get("name", "?")

        if msg_type == MSG_ANNOUNCE:
            with self._lock:
                peer = self._peers.get(pid)
                if peer is None:
                    peer = Peer(pid, name, addr)
                    self._peers[pid] = peer
                peer.name      = name
                peer.addr      = addr
                peer.summary   = payload.get("summary", {})
                peer.x_pub     = payload.get("x_pub")
                peer.ed_pub    = payload.get("pub")
                peer.tcp_port  = payload.get("tcp_port")
                peer.last_seen = time.time()
            for fn in self._on_peer:
                try: fn(pid, name, peer.summary)
                except Exception: pass

        elif msg_type == MSG_SEEK:
            query = payload.get("query", "")
            score = self.folder.resonate(query)
            if score > 0.05:
                self._send(MSG_RESONATE, {
                    "node_id": self.node_id, "name": self.name,
                    "score": round(score, 3),
                    "summary": self.folder.summary(),
                })
                if score > 0.5:
                    pts = round((score - 0.5) * 2.0, 4)
                    self.ledger.credit(pts, f"seek:{query[:24]}", pid)
            for fn in self._on_seek:
                try: fn(pid, name, query, score)
                except Exception: pass

        elif msg_type == MSG_RESONATE:
            with self._lock:
                peer = self._peers.setdefault(pid, Peer(pid, name, addr))
                peer.summary   = payload.get("summary", {})
                peer.x_pub     = payload.get("x_pub")
                peer.last_seen = time.time()

        elif msg_type == MSG_ROUTE:
            target = payload.get("target")
            if target != self.node_id:
                return
            fname     = os.path.basename(payload.get("filename", "received"))
            encrypted = payload.get("encrypted", False)
            content_b64 = payload.get("content", "")
            nonce_b64   = payload.get("nonce")
            in_dir      = self.folder.path / "in"
            in_dir.mkdir(exist_ok=True)
            dest = in_dir / fname
            try:
                if encrypted and nonce_b64:
                    with self._lock:
                        peer = self._peers.get(pid)
                    x_pub_b64 = (peer.x_pub if peer else None) or payload.get("x_pub")
                    if x_pub_b64:
                        peer_xb = base64.b64decode(x_pub_b64)
                        ct      = base64.b64decode(content_b64)
                        nonce   = base64.b64decode(nonce_b64)
                        plaintext = self.identity.decrypt_from(peer_xb, ct, nonce)
                        dest.write_bytes(plaintext)
                    else:
                        dest.write_bytes(base64.b64decode(content_b64))
                else:
                    dest.write_bytes(base64.b64decode(content_b64))
                self.ledger.credit(0.1, f"received:{fname}", pid)
                for fn in self._on_route:
                    try: fn(pid, name, fname, 1.0)
                    except Exception: pass
                log.info(f"Received {fname} from {name}")
            except Exception as e:
                log.warning(f"Route delivery failed for {fname}: {e}")

        elif msg_type == MSG_PING:
            self._send(MSG_PONG, {"node_id": self.node_id, "name": self.name})

        elif msg_type == MSG_LEAVE:
            with self._lock:
                self._peers.pop(pid, None)
            for fn in self._on_leave:
                try: fn(pid, name)
                except Exception: pass

        elif msg_type == MSG_TALK_LINE:
            session = payload.get("session_id", "")
            line    = payload.get("line", "")
            if target := payload.get("target"):
                if target == self.node_id:
                    self._talk_sessions.setdefault(session, []).append(line)
                    proc = self.folder.run_entry(env_extra={
                        "AURA_VISITOR": pid,
                        "AURA_QUERY":   line,
                        "AURA_SESSION": session,
                    })
                    if proc:
                        try:
                            out, _ = proc.communicate(timeout=8)
                            if out and out.strip():
                                self._send(MSG_TALK_LINE, {
                                    "node_id":    self.node_id,
                                    "name":       self.name,
                                    "target":     pid,
                                    "session_id": session,
                                    "line":       out.strip(),
                                })
                        except Exception:
                            pass

        elif msg_type == MSG_TCP_OFFER:
            if payload.get("target") == self.node_id:
                self._tcp_accept(payload, addr)

    # ── TCP server ────────────────────────────────────────────────────────────

    def _tcp_server(self):
        """Accept inbound TCP connections for large file transfers."""
        try:
            self._tcp_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp_srv.bind(("", self.tcp_port))
            self._tcp_srv.listen(16)
            self._tcp_srv.settimeout(1.0)
        except Exception as e:
            log.warning(f"TCP server failed to bind on {self.tcp_port}: {e}")
            return
        while self._running:
            try:
                conn, addr = self._tcp_srv.accept()
                threading.Thread(
                    target=self._tcp_receive, args=(conn, addr),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _tcp_receive(self, conn: socket.socket, addr: tuple):
        """Handle one inbound TCP file transfer."""
        try:
            # header: [node_id 16B][filename_len 2B][filename][file_size 8B][nonce 12B or 0]
            raw = conn.recv(2)
            fname_len = struct.unpack("!H", raw)[0]
            fname_bytes = conn.recv(fname_len)
            fname = fname_bytes.decode(errors="replace")
            raw   = conn.recv(8)
            fsize = struct.unpack("!Q", raw)[0]
            raw   = conn.recv(12)
            nonce = raw if any(raw) else None

            in_dir = self.folder.path / "in"
            in_dir.mkdir(exist_ok=True)
            dest = in_dir / os.path.basename(fname)
            received = 0
            with open(dest, "wb") as fh:
                while received < fsize:
                    chunk = conn.recv(min(CHUNK_SIZE, fsize - received))
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
            self.ledger.credit(0.15, f"tcp_recv:{fname}", addr[0])
            log.info(f"TCP received {fname} ({received} bytes) from {addr[0]}")
        except Exception as e:
            log.warning(f"TCP receive error: {e}")
        finally:
            conn.close()

    def _tcp_offer(self, peer: Peer, file_path: Path) -> Tuple[bool, str]:
        """Offer a TCP transfer for a large file."""
        if not peer.tcp_port:
            return False, "peer has no TCP port"
        self._send(MSG_TCP_OFFER, {
            "node_id":  self.node_id, "name": self.name,
            "target":   peer.node_id,
            "filename": file_path.name,
            "size":     file_path.stat().st_size,
            "tcp_port": self.tcp_port,
        })
        # connect and send
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((peer.addr, peer.tcp_port))
            fname_bytes = file_path.name.encode()
            sock.sendall(struct.pack("!H", len(fname_bytes)) + fname_bytes)
            sock.sendall(struct.pack("!Q", file_path.stat().st_size))
            sock.sendall(b"\x00" * 12)  # no nonce for unencrypted TCP
            with open(file_path, "rb") as fh:
                while chunk := fh.read(CHUNK_SIZE):
                    sock.sendall(chunk)
            sock.close()
            return True, "sent via TCP"
        except Exception as e:
            return False, f"TCP send failed: {e}"

    def _tcp_accept(self, payload: dict, addr: str):
        """Peer is offering a TCP transfer — connect to receive it."""
        tcp_port = payload.get("tcp_port")
        if not tcp_port:
            return
        # The actual receive happens when the sender connects to our _tcp_server.
        # This handler just logs the offer.
        log.info(f"TCP offer from {payload.get('name')} for {payload.get('filename')}")

    # ── Out-folder watcher ────────────────────────────────────────────────────

    def _watch_out(self):
        """Watch out/ for new files and route them to the best peer."""
        out_dir = self.folder.path / "out"
        out_dir.mkdir(exist_ok=True)
        seen: set = set()
        while self._running:
            try:
                current = {f for f in out_dir.iterdir() if f.is_file()}
                new_files = current - seen
                for f in new_files:
                    self._auto_route(f)
                seen = current
            except Exception:
                pass
            time.sleep(2)

    def _auto_route(self, file_path: Path):
        """Find the best-resonating peer and route the file."""
        query = file_path.stem.replace("_", " ").replace("-", " ")
        results = self.seek(query)
        if results:
            target = results[0]["node_id"]
            ok, msg = self.route_file(target, file_path)
            if ok:
                log.info(f"Auto-routed {file_path.name} → {results[0]['name']}")

    # ── Rescan loop ───────────────────────────────────────────────────────────

    def _rescan_loop(self):
        last_fp = self.folder.fingerprint()
        interval = self._cfg.get("node", "rescan_interval", default=30)
        while self._running:
            time.sleep(interval)
            try:
                self.folder = FolderAura(str(self.folder.path)).scan()
                fp = self.folder.fingerprint()
                if fp != last_fp:
                    last_fp = fp
                    self._announce()
                    log.info("Folder changed — re-announced")
            except Exception:
                pass

    # ── Peer eviction ─────────────────────────────────────────────────────────

    def _evict_loop(self):
        ttl = self._cfg.get("node", "peer_ttl", default=90)
        while self._running:
            time.sleep(30)
            now = time.time()
            with self._lock:
                stale = [pid for pid, p in self._peers.items()
                         if now - p.last_seen > ttl]
                for pid in stale:
                    del self._peers[pid]
                    log.debug(f"Evicted stale peer {pid}")

    # ── Relay ─────────────────────────────────────────────────────────────────

    def _relay_connect(self, relays: list):
        """Attempt to register with the first reachable relay."""
        for relay in relays:
            try:
                host, port = relay.rsplit(":", 1)
                port = int(port)
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(5)
                # send registration packet
                pkt = self.identity.encode(MSG_RELAY_REG, {
                    "node_id": self.node_id,
                    "name":    self.name,
                    "channel": self.channel or "",
                })
                sock.sendto(pkt, (host, port))
                self._relay_sock = sock
                self._relay_addr = (host, port)
                log.info(f"Registered with relay {relay}")
                # keep-alive pings
                while self._running:
                    time.sleep(30)
                    self._send(MSG_PING, {"node_id": self.node_id})
                break
            except Exception as e:
                log.debug(f"Relay {relay} unreachable: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_field(channel: Optional[str]) -> Tuple[str, int]:
        cfg = Config()
        if not channel:
            return (
                cfg.get("field", "group", default="239.77.77.77"),
                cfg.get("field", "port",  default=7777),
            )
        import hashlib as _h
        d = _h.md5(channel.encode()).digest()
        group = f"239.{d[0]}.{d[1]}.{d[2]}"
        port  = 7000 + (struct.unpack(">H", d[3:5])[0] % 1000)
        return group, port

    @staticmethod
    def _peer_aura(peer: Peer) -> FolderAura:
        fa = object.__new__(FolderAura)
        fa.tags  = (peer.summary.get("tags") or {})
        fa.files = []
        fa.meta  = {}
        fa.entry = None
        fa.path  = Path(peer.summary.get("path", "/"))
        return fa

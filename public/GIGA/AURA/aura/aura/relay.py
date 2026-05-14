"""
aura.relay — WAN Relay Server

A relay bridges AURA nodes that are on different networks.
It's a stateless UDP forwarder — it does not store or decrypt anything.

Architecture:
  - Nodes register with MSG_RELAY_REG
  - When a packet arrives from a registered node, the relay forwards it
    to all other registered nodes in the same channel
  - Registrations expire after 120s (keep-alive via MSG_PING)
  - The relay never decrypts packets — it forwards signed, encrypted bytes

Run a relay:
  python -m aura relay --port 7779

Or:
  aura relay --port 7779
"""

from __future__ import annotations
import socket
import struct
import time
import threading
import logging
import argparse
from typing import Dict, Tuple, Optional

from .crypto import Identity, MSG_RELAY_REG, MSG_PING, MSG_LEAVE
from .config import Config

log = logging.getLogger("aura.relay")

PEER_TTL  = 120   # seconds before unresponsive peer is dropped
MAX_PEERS = 512


class RelayPeer:
    __slots__ = ("node_id", "addr", "channel", "last_seen", "name")

    def __init__(self, node_id: str, addr: tuple, channel: str, name: str):
        self.node_id   = node_id
        self.addr      = addr
        self.channel   = channel
        self.name      = name
        self.last_seen = time.time()


class AuraRelay:
    """
    Stateless UDP relay for AURA nodes on different networks.
    Forwards all field packets between peers in the same channel.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 7779):
        cfg        = Config()
        self.host  = host
        self.port  = port or cfg.get("relay", "port", default=7779)
        self.max_peers = cfg.get("relay", "max_peers", default=MAX_PEERS)
        self._peers: Dict[str, RelayPeer] = {}   # node_id → peer
        self._lock  = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._running = False

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(1.0)
        self._running = True
        threading.Thread(target=self._evict_loop, daemon=True, name="relay.evict").start()
        log.info(f"AURA relay listening on {self.host}:{self.port}")
        print(f"  AURA relay  {self.host}:{self.port}")
        print(f"  max peers   {self.max_peers}")
        print(f"  peer TTL    {PEER_TTL}s")
        print()
        self._rx_loop()

    def stop(self):
        self._running = False
        if self._sock:
            self._sock.close()

    # ── Core loop ─────────────────────────────────────────────────────────────

    def _rx_loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(65535)
                dec = Identity.decode(data, require_sig=True)
                if dec is None:
                    continue
                msg_type, payload = dec
                node_id = payload.get("node_id", "")
                channel = payload.get("channel", "") or ""
                name    = payload.get("name", "?")

                if msg_type == MSG_RELAY_REG:
                    self._register(node_id, addr, channel, name)
                elif msg_type == MSG_PING:
                    self._touch(node_id)
                elif msg_type == MSG_LEAVE:
                    self._deregister(node_id)
                else:
                    self._forward(data, node_id, channel, addr)
            except socket.timeout:
                continue
            except Exception as e:
                log.debug(f"relay rx error: {e}")

    def _register(self, node_id: str, addr: tuple, channel: str, name: str):
        with self._lock:
            if len(self._peers) >= self.max_peers and node_id not in self._peers:
                log.warning(f"Max peers reached — rejecting {node_id}")
                return
            peer = self._peers.get(node_id)
            if peer is None:
                peer = RelayPeer(node_id, addr, channel, name)
                self._peers[node_id] = peer
                log.info(f"Registered  {name} [{node_id}] channel={channel!r} from {addr[0]}:{addr[1]}")
            peer.addr      = addr
            peer.channel   = channel
            peer.last_seen = time.time()

    def _deregister(self, node_id: str):
        with self._lock:
            peer = self._peers.pop(node_id, None)
        if peer:
            log.info(f"Departed {peer.name} [{node_id}]")

    def _touch(self, node_id: str):
        with self._lock:
            peer = self._peers.get(node_id)
            if peer:
                peer.last_seen = time.time()

    def _forward(self, data: bytes, sender_id: str, channel: str, sender_addr: tuple):
        with self._lock:
            recipients = [
                p for pid, p in self._peers.items()
                if pid != sender_id and p.channel == channel
            ]
        for peer in recipients:
            try:
                self._sock.sendto(data, peer.addr)
            except Exception as e:
                log.debug(f"forward to {peer.name} failed: {e}")

    def _evict_loop(self):
        while self._running:
            time.sleep(30)
            now = time.time()
            with self._lock:
                stale = [pid for pid, p in self._peers.items()
                         if now - p.last_seen > PEER_TTL]
                for pid in stale:
                    peer = self._peers.pop(pid)
                    log.info(f"Evicted stale peer {peer.name} [{pid}]")

    def status(self) -> dict:
        with self._lock:
            peers = [
                {"node_id": p.node_id, "name": p.name,
                 "channel": p.channel, "addr": f"{p.addr[0]}:{p.addr[1]}",
                 "age": round(time.time() - p.last_seen, 1)}
                for p in self._peers.values()
            ]
        return {"port": self.port, "peers": peers, "count": len(peers)}


def main():
    cfg = Config()
    parser = argparse.ArgumentParser(description="AURA relay server")
    parser.add_argument("--host",  default="0.0.0.0",
                        help="Bind address (default 0.0.0.0)")
    parser.add_argument("--port",  type=int,
                        default=cfg.get("relay", "port", default=7779),
                        help="UDP port (default 7779)")
    parser.add_argument("--max-peers", type=int,
                        default=cfg.get("relay", "max_peers", default=MAX_PEERS))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    relay = AuraRelay(host=args.host, port=args.port)
    relay.max_peers = args.max_peers
    try:
        relay.start()
    except KeyboardInterrupt:
        relay.stop()
        print("\n  relay stopped")


if __name__ == "__main__":
    main()

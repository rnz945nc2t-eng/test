"""Tests for aura.field — peer management, routing, and ledger integration."""
import tempfile
import time
import base64
from pathlib import Path

import pytest
from aura.crypto import Identity, MSG_ANNOUNCE, MSG_SEEK, MSG_ROUTE, MSG_LEAVE
from aura.field  import AuraField, Peer
from aura.folder import FolderAura


@pytest.fixture()
def node1(tmp_path):
    d = tmp_path / "node1"
    d.mkdir()
    for sub in ("in", "out", "shared", "private"):
        (d / sub).mkdir()
    (d / "aura.meta").write_text("name: NodeOne\ntags: python, code\n")
    return d


@pytest.fixture()
def node2(tmp_path):
    d = tmp_path / "node2"
    d.mkdir()
    for sub in ("in", "out", "shared", "private"):
        (d / sub).mkdir()
    (d / "aura.meta").write_text("name: NodeTwo\ntags: music, audio\n")
    return d


class TestPeer:
    def test_peer_creation(self):
        p = Peer("abc123", "TestNode", "192.168.1.1")
        assert p.node_id == "abc123"
        assert p.name == "TestNode"
        assert p.addr == "192.168.1.1"

    def test_peer_to_dict(self):
        p = Peer("abc123", "TestNode", "192.168.1.1")
        d = p.to_dict()
        assert d["node_id"] == "abc123"
        assert "last_seen" in d


class TestFieldConstruction:
    def test_basic_field_init(self, node1):
        f = AuraField(str(node1))
        assert f.node_id is not None
        assert len(f.node_id) == 16

    def test_wallet_derived(self, node1):
        f = AuraField(str(node1))
        assert f.wallet.startswith("AYR")

    def test_channel_resolves_different_group(self, node1):
        f1 = AuraField(str(node1))
        f2 = AuraField(str(node1), channel="mychannel")
        assert f1.field_group != f2.field_group or f1.field_port != f2.field_port

    def test_channel_is_deterministic(self, node1):
        f2 = AuraField(str(node1), channel="testchan")
        f3 = AuraField(str(node1), channel="testchan")
        assert f2.field_group == f3.field_group
        assert f2.field_port == f3.field_port


class TestMessageHandling:
    def test_announce_adds_peer(self, node1, node2):
        f1 = AuraField(str(node1))
        fa2 = FolderAura(str(node2)).scan()
        id2 = fa2.identity

        payload = {
            "node_id":  id2.node_id,
            "name":     "NodeTwo",
            "summary":  fa2.summary(),
            "tcp_port": 7780,
            "ts":       time.time(),
            "pub":      base64.b64encode(id2.ed_public_bytes).decode(),
            "x_pub":    base64.b64encode(id2.x_public_bytes).decode(),
            "_verified": True,
        }
        f1._handle(MSG_ANNOUNCE, payload, "127.0.0.1")
        peers = f1.who()
        assert any(p["node_id"] == id2.node_id for p in peers)

    def test_leave_removes_peer(self, node1, node2):
        f1 = AuraField(str(node1))
        fa2 = FolderAura(str(node2)).scan()
        id2 = fa2.identity

        announce = {
            "node_id": id2.node_id, "name": "NodeTwo",
            "summary": {}, "ts": time.time(),
            "pub": base64.b64encode(id2.ed_public_bytes).decode(),
            "x_pub": base64.b64encode(id2.x_public_bytes).decode(),
            "_verified": True,
        }
        f1._handle(MSG_ANNOUNCE, announce, "127.0.0.1")
        assert any(p["node_id"] == id2.node_id for p in f1.who())

        leave = {"node_id": id2.node_id, "name": "NodeTwo", "_verified": True}
        f1._handle(MSG_LEAVE, leave, "127.0.0.1")
        assert not any(p["node_id"] == id2.node_id for p in f1.who())

    def test_seek_credits_ledger(self, node1):
        f1 = AuraField(str(node1))
        old_balance = f1.ledger.balance
        # inject matching tag so score > 0.5
        f1.folder.tags = {"python": 1.0, "code": 1.0}
        f1._handle(MSG_SEEK, {
            "node_id": "other",
            "name":    "Seeker",
            "query":   "python code",
            "_verified": True,
        }, "127.0.0.1")
        assert f1.ledger.balance > old_balance

    def test_route_delivers_file(self, node1, node2):
        f2 = AuraField(str(node2))
        content = b"hello from node1"
        payload = {
            "node_id":  "abc",
            "name":     "sender",
            "target":   f2.node_id,
            "filename": "test_transfer.txt",
            "content":  base64.b64encode(content).decode(),
            "encrypted": False,
            "_verified": True,
        }
        f2._handle(MSG_ROUTE, payload, "127.0.0.1")
        dest = node2 / "in" / "test_transfer.txt"
        assert dest.exists()
        assert dest.read_bytes() == content

    def test_route_credits_ledger(self, node2):
        f2 = AuraField(str(node2))
        old = f2.ledger.balance
        payload = {
            "node_id": "abc", "name": "sender",
            "target": f2.node_id,
            "filename": "ledger_test.txt",
            "content": base64.b64encode(b"data").decode(),
            "encrypted": False,
            "_verified": True,
        }
        f2._handle(MSG_ROUTE, payload, "127.0.0.1")
        assert f2.ledger.balance > old

    def test_encrypted_route_delivered(self, node1, node2):
        f1 = AuraField(str(node1))
        f2 = AuraField(str(node2))
        secret = b"top secret payload"
        ct, nonce = f1.identity.encrypt_for(f2.identity.x_public_bytes, secret)
        payload = {
            "node_id":   f1.node_id,
            "name":      "NodeOne",
            "target":    f2.node_id,
            "filename":  "encrypted.bin",
            "content":   base64.b64encode(ct).decode(),
            "nonce":     base64.b64encode(nonce).decode(),
            "encrypted": True,
            "x_pub":     base64.b64encode(f1.identity.x_public_bytes).decode(),
            "_verified": True,
        }
        f2._handle(MSG_ROUTE, payload, "127.0.0.1")
        dest = node2 / "in" / "encrypted.bin"
        assert dest.exists()
        assert dest.read_bytes() == secret


class TestLocalRouting:
    def test_route_file_local(self, node1, node2, tmp_path):
        f1 = AuraField(str(node1))
        f2 = AuraField(str(node2))
        # inject peer record for f2
        from aura.field import Peer
        peer = Peer(f2.node_id, "NodeTwo", "127.0.0.1")
        peer.summary  = {"path": str(node2)}
        peer.x_pub    = base64.b64encode(f2.identity.x_public_bytes).decode()
        peer.tcp_port = 7780
        with f1._lock:
            f1._peers[f2.node_id] = peer

        src = tmp_path / "payload.txt"
        src.write_text("hello field")
        ok, msg = f1.route_file(f2.node_id, str(src))
        assert ok
        dest = node2 / "in" / "payload.txt"
        assert dest.exists()
        assert dest.read_text() == "hello field"

    def test_pull_file(self, node1, node2):
        f2 = AuraField(str(node2))
        # place file in node2's shared/
        (node2 / "shared" / "gift.txt").write_text("shared treasure")

        f1 = AuraField(str(node1))
        peer = Peer(f2.node_id, "NodeTwo", "127.0.0.1")
        peer.summary = {"path": str(node2)}
        with f1._lock:
            f1._peers[f2.node_id] = peer

        dest = f1.pull(f2.node_id, "gift.txt")
        assert dest is not None
        assert Path(dest).read_text() == "shared treasure"

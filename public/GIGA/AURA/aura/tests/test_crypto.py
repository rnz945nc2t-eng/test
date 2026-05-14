"""Tests for aura.crypto — identity, signing, and encryption."""
import os
import tempfile
from pathlib import Path

import pytest
from aura.crypto import Identity, MSG_ANNOUNCE, MSG_SEEK


@pytest.fixture()
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture()
def alice(tmpdir):
    return Identity(tmpdir / "alice")


@pytest.fixture()
def bob(tmpdir):
    return Identity(tmpdir / "bob")


class TestIdentity:
    def test_node_id_is_16_chars(self, alice):
        assert len(alice.node_id) == 16

    def test_node_id_is_deterministic(self, tmpdir):
        i1 = Identity(tmpdir / "node")
        i2 = Identity(tmpdir / "node")
        assert i1.node_id == i2.node_id

    def test_wallet_starts_with_ayr(self, alice):
        assert alice.wallet_addr.startswith("AYR")
        assert len(alice.wallet_addr) == 35

    def test_two_identities_differ(self, alice, bob):
        assert alice.node_id != bob.node_id
        assert alice.wallet_addr != bob.wallet_addr

    def test_x_public_key_length(self, alice):
        assert len(alice.x_public_bytes) == 32

    def test_ed_public_key_length(self, alice):
        assert len(alice.ed_public_bytes) == 32

    def test_keys_persist(self, tmpdir):
        i1 = Identity(tmpdir / "persistent")
        nid1 = i1.node_id
        i2 = Identity(tmpdir / "persistent")
        assert i2.node_id == nid1


class TestWireEncoding:
    def test_encode_decode_round_trip(self, alice):
        pkt = alice.encode(MSG_ANNOUNCE, {"node_id": alice.node_id, "name": "alice"})
        result = Identity.decode(pkt)
        assert result is not None
        msg_type, payload = result
        assert msg_type == MSG_ANNOUNCE
        assert payload["name"] == "alice"
        assert payload["_verified"] is True

    def test_tampered_packet_rejected(self, alice):
        pkt = alice.encode(MSG_SEEK, {"node_id": alice.node_id, "query": "test"})
        # tamper with the body
        corrupted = bytearray(pkt)
        corrupted[-5] ^= 0xFF
        result = Identity.decode(bytes(corrupted))
        assert result is None

    def test_wrong_magic_rejected(self, alice):
        pkt = alice.encode(MSG_ANNOUNCE, {"node_id": alice.node_id})
        bad = b"\xDE\xAD" + pkt[2:]
        assert Identity.decode(bad) is None

    def test_pub_key_embedded(self, alice):
        pkt = alice.encode(MSG_ANNOUNCE, {"node_id": alice.node_id})
        _, payload = Identity.decode(pkt)
        import base64
        recovered = base64.b64decode(payload["pub"])
        assert recovered == alice.ed_public_bytes

    def test_x_pub_embedded(self, alice):
        pkt = alice.encode(MSG_ANNOUNCE, {"node_id": alice.node_id})
        _, payload = Identity.decode(pkt)
        import base64
        recovered = base64.b64decode(payload["x_pub"])
        assert recovered == alice.x_public_bytes


class TestEncryption:
    def test_encrypt_decrypt(self, alice, bob):
        plaintext = b"hello from alice"
        ct, nonce = alice.encrypt_for(bob.x_public_bytes, plaintext)
        recovered = bob.decrypt_from(alice.x_public_bytes, ct, nonce)
        assert recovered == plaintext

    def test_wrong_key_fails(self, alice, bob, tmpdir):
        charlie = Identity(tmpdir / "charlie")
        plaintext = b"secret data"
        ct, nonce = alice.encrypt_for(bob.x_public_bytes, plaintext)
        with pytest.raises(Exception):
            charlie.decrypt_from(alice.x_public_bytes, ct, nonce)

    def test_tampered_ciphertext_fails(self, alice, bob):
        plaintext = b"tamper test"
        ct, nonce = alice.encrypt_for(bob.x_public_bytes, plaintext)
        bad_ct = bytearray(ct)
        bad_ct[0] ^= 0xFF
        with pytest.raises(Exception):
            bob.decrypt_from(alice.x_public_bytes, bytes(bad_ct), nonce)

    def test_large_payload(self, alice, bob):
        plaintext = os.urandom(256 * 1024)  # 256 KB
        ct, nonce = alice.encrypt_for(bob.x_public_bytes, plaintext)
        recovered = bob.decrypt_from(alice.x_public_bytes, ct, nonce)
        assert recovered == plaintext

    def test_encryption_is_randomised(self, alice, bob):
        msg = b"same message"
        ct1, n1 = alice.encrypt_for(bob.x_public_bytes, msg)
        ct2, n2 = alice.encrypt_for(bob.x_public_bytes, msg)
        # nonces should be random → ciphertexts differ
        assert ct1 != ct2 or n1 != n2

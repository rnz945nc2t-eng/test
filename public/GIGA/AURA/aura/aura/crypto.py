"""
aura.crypto — Cryptographic identity for AURA nodes

Every node has:
  - An Ed25519 signing keypair     (.aura/identity.key + .aura/aura.pub)
  - An X25519 key exchange keypair (.aura/encryption.key + .aura/encryption.pub)

node_id  = SHA-256(ed25519_public_bytes)[:16]  — hex string
wallet   = "AYR" + SHA-256(ed25519_public_bytes)[:32].upper()

Every outbound wire packet is signed with the Ed25519 private key.
Inbound packets that fail signature verification are silently dropped.

Peer-to-peer file encryption uses X25519 ECDH → HKDF-SHA256 → ChaCha20-Poly1305.
"""

from __future__ import annotations
import hashlib
import base64
import os
import struct
import json
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.exceptions import InvalidSignature

# ── Wire constants ────────────────────────────────────────────────────────────

MAGIC     = b"\xA0\x52"
PROTO_VER = 4

MSG_ANNOUNCE  = 0x01
MSG_SEEK      = 0x02
MSG_RESONATE  = 0x03
MSG_ROUTE     = 0x04
MSG_PULL_REQ  = 0x05
MSG_PULL_DATA = 0x06
MSG_TALK_OPEN = 0x07
MSG_TALK_LINE = 0x08
MSG_LEAVE     = 0x09
MSG_RELAY_REG = 0x0A   # register with a relay
MSG_RELAY_FWD = 0x0B   # relay forwarding a packet
MSG_PING      = 0x0C
MSG_PONG      = 0x0D
MSG_TCP_OFFER = 0x0E   # offer a direct TCP transfer
MSG_ACK       = 0x0F

# ── Header layout ─────────────────────────────────────────────────────────────
# [MAGIC 2][VER 1][TYPE 1][BODY_LEN 2][SIG_LEN 2] = 8 bytes
HEADER_FMT  = "!HH"   # body_len, sig_len
HEADER_SIZE = 8

_HKDF_INFO = b"aura-v1-file-encryption"


class Identity:
    """
    Manages the cryptographic identity of an AURA node.
    Lazily generates keys on first use.
    """

    def __init__(self, aura_dir: Path):
        self._dir = Path(aura_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ed_priv: Optional[ed25519.Ed25519PrivateKey] = None
        self._x_priv:  Optional[x25519.X25519PrivateKey]  = None
        self._ensure()

    # ── Key lifecycle ─────────────────────────────────────────────────────────

    def _ensure(self):
        self._ensure_signing()
        self._ensure_encryption()

    def _ensure_signing(self):
        key_path = self._dir / "identity.key"
        pub_path = self._dir / "aura.pub"
        if not key_path.exists():
            priv = ed25519.Ed25519PrivateKey.generate()
            key_path.write_bytes(priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            key_path.chmod(0o600)
            pub_path.write_bytes(priv.public_key().public_bytes(
                serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH,
            ))

    def _ensure_encryption(self):
        key_path = self._dir / "encryption.key"
        pub_path = self._dir / "encryption.pub"
        if not key_path.exists():
            priv = x25519.X25519PrivateKey.generate()
            key_path.write_bytes(priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            key_path.chmod(0o600)
            pub_path.write_bytes(priv.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ))

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def ed_private(self) -> ed25519.Ed25519PrivateKey:
        if self._ed_priv is None:
            raw = (self._dir / "identity.key").read_bytes()
            self._ed_priv = serialization.load_ssh_private_key(raw, None)
        return self._ed_priv

    @property
    def ed_public_bytes(self) -> bytes:
        return self.ed_private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @property
    def x_private(self) -> x25519.X25519PrivateKey:
        if self._x_priv is None:
            raw = (self._dir / "encryption.key").read_bytes()
            self._x_priv = serialization.load_pem_private_key(raw, None)
        return self._x_priv

    @property
    def x_public_bytes(self) -> bytes:
        return (self._dir / "encryption.pub").read_bytes()

    @property
    def node_id(self) -> str:
        return hashlib.sha256(self.ed_public_bytes).hexdigest()[:16]

    @property
    def wallet_addr(self) -> str:
        return "AYR" + hashlib.sha256(self.ed_public_bytes).hexdigest()[:32].upper()

    # ── Packet encoding/decoding ──────────────────────────────────────────────

    def encode(self, msg_type: int, payload: dict,
               x_pub_bytes: Optional[bytes] = None) -> bytes:
        """Encode and sign a wire packet."""
        payload = dict(payload)
        payload["pub"]   = base64.b64encode(self.ed_public_bytes).decode()
        payload["x_pub"] = base64.b64encode(self.x_public_bytes).decode()
        if x_pub_bytes:
            payload["x_pub_enc"] = base64.b64encode(x_pub_bytes).decode()

        body    = json.dumps(payload, separators=(",", ":")).encode()
        sig     = self.ed_private.sign(body)
        header  = MAGIC + bytes([PROTO_VER, msg_type])
        header += struct.pack(HEADER_FMT, len(body), len(sig))
        return header + sig + body

    @staticmethod
    def decode(data: bytes, require_sig: bool = True) -> Optional[Tuple[int, dict]]:
        """Decode and verify a wire packet. Returns (msg_type, payload) or None."""
        if len(data) < HEADER_SIZE or data[:2] != MAGIC:
            return None
        msg_type            = data[3]
        body_len, sig_len   = struct.unpack(HEADER_FMT, data[4:8])
        sig_start           = HEADER_SIZE
        body_start          = sig_start + sig_len
        sig_bytes           = data[sig_start:body_start]
        body_bytes          = data[body_start:body_start + body_len]
        try:
            payload = json.loads(body_bytes)
            if sig_len > 0 and "pub" in payload:
                pub_bytes  = base64.b64decode(payload["pub"])
                pub_key    = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
                pub_key.verify(sig_bytes, body_bytes)
                payload["_verified"] = True
            elif require_sig:
                return None
            else:
                payload["_verified"] = False
            return msg_type, payload
        except (InvalidSignature, Exception):
            return None

    # ── Peer encryption ───────────────────────────────────────────────────────

    def encrypt_for(self, peer_x_pub_bytes: bytes, plaintext: bytes) -> Tuple[bytes, bytes]:
        """
        Encrypt plaintext for a peer using X25519 ECDH + ChaCha20-Poly1305.
        Returns (ciphertext, nonce).
        """
        peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_x_pub_bytes)
        shared   = self.x_private.exchange(peer_pub)
        key      = HKDF(hashes.SHA256(), 32, None, _HKDF_INFO).derive(shared)
        nonce    = os.urandom(12)
        ct       = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)
        return ct, nonce

    def decrypt_from(self, peer_x_pub_bytes: bytes,
                     ciphertext: bytes, nonce: bytes) -> bytes:
        """
        Decrypt ciphertext from a peer.
        Raises on authentication failure.
        """
        peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_x_pub_bytes)
        shared   = self.x_private.exchange(peer_pub)
        key      = HKDF(hashes.SHA256(), 32, None, _HKDF_INFO).derive(shared)
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, None)

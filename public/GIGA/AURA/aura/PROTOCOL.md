# AURA Protocol Specification v0.4

**Status:** Stable  
**Author:** Aethyr Global  
**Repository:** https://github.com/aethyr-global/aura

---

## 1. Overview

AURA (Autonomous Universal Resonance Architecture) is a decentralised peer-to-peer protocol where folders are nodes. The protocol is connectionless at the discovery layer (UDP multicast) and connection-oriented at the transfer layer (TCP). Every packet is cryptographically signed. File payloads are end-to-end encrypted.

There is no central server, no DNS, no routing table. Nodes find each other through semantic resonance.

---

## 2. Transport

### 2.1 Discovery (UDP Multicast)

| Parameter | Value |
|---|---|
| Default group | `239.77.77.77` |
| Default port | `7777` |
| IP TTL | `8` (configurable) |
| Max payload | `65,535 bytes` |
| Packet size limit | `60,000 bytes` (switch to TCP above this) |

### 2.2 Transfer (TCP)

When a file exceeds `60,000 bytes`, the sender:
1. Sends `MSG_TCP_OFFER` over UDP to the target node
2. Opens a direct TCP connection to the target's `tcp_port` (default: `7780`)
3. Streams the file in `65,536`-byte chunks

TCP frame:
```
[fname_len: 2B big-endian]
[filename: N bytes UTF-8]
[file_size: 8B big-endian]
[nonce: 12B (zeros if unencrypted)]
[file data: chunked]
```

### 2.3 WAN (Relay)

For nodes on different networks, a relay server forwards UDP packets between registered nodes:

1. Node sends `MSG_RELAY_REG` to relay
2. Relay registers `(node_id, addr, channel)`
3. All subsequent packets from the node are forwarded to other nodes in the same channel
4. Relay is stateless — it never decrypts or stores packets

---

## 3. Cryptography

### 3.1 Identity (Ed25519)

Every node generates an Ed25519 keypair on first run:
- Private key: `~/<node>/.aura/identity.key` (PEM, chmod 600)
- Public key: `~/<node>/.aura/aura.pub`

```
node_id     = SHA-256(ed25519_pub_bytes)[0:16]  # hex string, 16 chars
wallet_addr = "AYR" + SHA-256(ed25519_pub_bytes)[0:32].upper()  # 35 chars
```

Every outbound packet is signed with the Ed25519 private key. Packets that fail signature verification are silently dropped.

### 3.2 Encryption (X25519 + ChaCha20-Poly1305)

Every node also generates an X25519 keypair:
- Private key: `~/<node>/.aura/encryption.key` (PEM, chmod 600)
- Public key: `~/<node>/.aura/encryption.pub` (raw 32 bytes)

File encryption:
```
shared_secret = X25519(my_private, peer_public)
key           = HKDF-SHA256(shared_secret, info=b"aura-v1-file-encryption", length=32)
nonce         = random 12 bytes
ciphertext    = ChaCha20-Poly1305(key).encrypt(nonce, plaintext)
```

Decryption reverses this using the sender's X25519 public key (carried in every `pub`/`x_pub` packet field).

---

## 4. Wire Format

### 4.1 Header (8 bytes)

```
Offset  Size  Field       Description
0       2     MAGIC       0xA0 0x52
2       1     VER         Protocol version (0x04)
3       1     TYPE        Message type (see §5)
4       2     BODY_LEN    Body length in bytes (big-endian)
6       2     SIG_LEN     Signature length in bytes (big-endian)
```

### 4.2 Payload

```
[HEADER 8B][SIGNATURE SIG_LEN B][BODY BODY_LEN B]
```

- **SIGNATURE**: Ed25519 signature over BODY bytes
- **BODY**: UTF-8 JSON object

### 4.3 Required JSON fields (all packets)

| Field | Type | Description |
|---|---|---|
| `node_id` | string | Sender's 16-char node ID |
| `name` | string | Sender's human-readable name |
| `pub` | string | Base64 Ed25519 public key (for verification) |
| `x_pub` | string | Base64 X25519 public key |

---

## 5. Message Types

### `0x01` ANNOUNCE

Sent periodically (default: every 15 seconds) and on join.

```json
{
  "node_id": "a1b2c3d4e5f6g7h8",
  "name": "my-node",
  "summary": {
    "name": "my-node",
    "path": "/home/user/my-node",
    "description": "A music collection",
    "tags": {"music": 1.0, "audio": 0.8, "flac": 0.6},
    "file_count": 42,
    "entry": "aura.py",
    "fingerprint": "a1b2c3d4e5f6",
    "structure": {
      "has_in": true, "has_out": true,
      "has_shared": true, "has_private": true,
      "in_count": 3, "out_count": 0, "shared_count": 42
    }
  },
  "tcp_port": 7780,
  "ts": 1700000000.0
}
```

### `0x02` SEEK

Broadcast semantic query.

```json
{
  "node_id": "...", "name": "...",
  "query": "python music analysis",
  "ts": 1700000000.0
}
```

### `0x03` RESONATE

Reply to a seek with resonance score.

```json
{
  "node_id": "...", "name": "...",
  "score": 0.85,
  "summary": { ... }
}
```

Resonance score formula:
```
score = Σ(tag_weight for query_word in node.tags) / query_word_count
```
Clipped to `[0.0, 1.0]`. Nodes only respond if score > 0.05.

### `0x04` ROUTE

File delivery. Target is a `node_id`.

**Unencrypted:**
```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "filename": "report.pdf",
  "content": "<base64-encoded file bytes>",
  "encrypted": false,
  "ts": 1700000000.0
}
```

**Encrypted:**
```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "filename": "secret.pdf",
  "content": "<base64-encoded ciphertext>",
  "nonce": "<base64-encoded 12-byte nonce>",
  "encrypted": true,
  "ts": 1700000000.0
}
```

### `0x05` PULL_REQ

Request a specific file from a peer's `shared/`.

```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "filename": "song.mp3"
}
```

### `0x07` TALK_OPEN

Open a named talk session with a peer.

```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "session_id": "a1b2c3"
}
```

### `0x08` TALK_LINE

Single line in a talk session.

```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "session_id": "a1b2c3",
  "line": "what music do you have?"
}
```

The target's entry point receives this via `AURA_QUERY` environment variable. Its stdout becomes the reply (`TALK_LINE` sent back).

### `0x09` LEAVE

Graceful departure from the field.

```json
{ "node_id": "...", "name": "..." }
```

### `0x0A` RELAY_REG

Register with a WAN relay.

```json
{
  "node_id": "...", "name": "...",
  "channel": "my-channel"
}
```

### `0x0C` PING / `0x0D` PONG

Keep-alive (for relays and peer TTL management).

### `0x0E` TCP_OFFER

Offer a direct TCP transfer for a file too large for UDP.

```json
{
  "node_id": "...", "name": "...",
  "target": "<target_node_id>",
  "filename": "large-dataset.zip",
  "size": 104857600,
  "tcp_port": 7780
}
```

---

## 6. Node Aura (Semantic Fingerprint)

A node's "aura" is a weighted tag dictionary:

```json
{
  "music": 1.0,
  "audio": 0.87,
  "flac": 0.72,
  "python": 0.63,
  "analysis": 0.51,
  "spectral": 0.44
}
```

Tags are derived from:
1. `aura.meta` `tags:` field (weight 1.0)
2. `aura.meta` `description:` keywords (weight 0.3)
3. Filename stems and path components (weight 0.22 × scale)
4. File extensions → semantic categories (weight 0.18 × scale)
5. Text content keyword frequency (weight up to 0.32 × scale)
6. Files in `shared/` (scale 0.85), root files (scale 1.0)
7. Private/ is never indexed

Tags are normalised so the maximum weight is always 1.0.

---

## 7. Intelligence Ledger (NOT Money)

Intelligence points (AYR) are earned by useful participation:

| Event | Points |
|---|---|
| Seek resonance > 0.5 | `(score - 0.5) × 2.0` AYR |
| File received via ROUTE | `0.1` AYR |
| File pulled by peer | `0.2` AYR |
| TCP receive | `0.15` AYR |

Points are never transferred. They accumulate at the node. The ledger is persisted to `.aura/ledger.json` with full transaction history (last 200 transactions).

---

## 8. Channel Isolation

```python
import hashlib, struct

d = hashlib.md5(channel_name.encode()).digest()
multicast_group = f"239.{d[0]}.{d[1]}.{d[2]}"
port = 7000 + (struct.unpack(">H", d[3:5])[0] % 1000)
```

Nodes on different channels cannot see each other.  
The default channel uses `239.77.77.77:7777` directly.

---

## 9. Security Considerations

1. **Every packet is signed.** Unsigned or tampered packets are dropped.
2. **Private keys never leave the node.** They are stored at chmod 600.
3. **File encryption is peer-to-peer.** No third party can decrypt.
4. **The relay never decrypts.** It forwards signed, encrypted bytes only.
5. **Channel names are hashed.** Knowing the multicast address does not reveal the channel name.
6. **`private/` is never scanned.** No content from private/ is ever included in the aura.
7. **Relay is unauthenticated by design.** Anyone can register. For private relays, firewall the port.

---

## 10. Interoperability

Any language can implement AURA. The minimum required:
- UDP multicast send/receive
- Ed25519 sign/verify
- JSON serialization
- Base64 encoding
- SHA-256

Optional (for full compatibility):
- X25519 ECDH + ChaCha20-Poly1305 (for encrypted file transfer)
- TCP server (for large files)
- HKDF-SHA256 (key derivation)

---

*AURA Protocol v0.4 — Aethyr Global — MIT License*

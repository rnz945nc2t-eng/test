# AURA — Autonomous Universal Resonance Architecture

> **The new internet. A folder is a node. Its files are the aura.**
> No addresses. No index. No central server. Just resonance.

[![PyPI](https://img.shields.io/pypi/v/aura-protocol?color=7c3aed&label=aura-protocol)](https://pypi.org/project/aura-protocol/)
[![Python](https://img.shields.io/pypi/pyversions/aura-protocol?color=06b6d4)](https://pypi.org/project/aura-protocol/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/protocol-v0.4-blueviolet)](PROTOCOL.md)

---

## What is AURA?

AURA is a decentralised peer-to-peer protocol where **any folder becomes a node on an intelligent mesh network**.

- Drop a folder on the network. It announces itself.
- Other nodes hear it and build a semantic understanding of what it contains.
- When you seek something, nodes that resonate respond.
- Files route themselves to where they are needed.
- No DNS. No IP addresses exchanged. No central broker.

This is not BitTorrent. This is not IPFS. This is not the web.  
This is something new.

---

## Install

```bash
pip install aura-protocol
```

Or from source:

```bash
git clone https://github.com/aethyr-global/aura
cd aura
pip install -e .
```

**Requirements:** Python 3.9+, `cryptography>=42`

---

## Quick Start

```bash
# 1. Create a new node
aura new ./my-node

# 2. Add your files to shared/
cp my-music.mp3 ./my-node/shared/

# 3. Join the field
aura join ./my-node

# 4. From another terminal — seek for things
aura seek ./other-node "music"

# 5. Pull a file from a peer
aura pull ./other-node <peer_node_id> my-music.mp3
```

---

## Node Structure

```
my-node/
├── aura.meta        ← identity: name, description, tags, protocol
├── aura.py          ← entry point: receives seeks, talk, queries
├── aura.lock        ← written when joined (pid, node_id, field addr)
├── in/              ← incoming files from the field
├── out/             ← files to send (auto-routed to best peer)
├── shared/          ← files visible to all peers on the field
└── private/         ← never indexed, never shared
    └── .aura/
        ├── identity.key    ← Ed25519 signing private key (chmod 600)
        ├── aura.pub        ← Ed25519 public key
        ├── encryption.key  ← X25519 key exchange private key (chmod 600)
        ├── encryption.pub  ← X25519 public key
        ├── ledger.json     ← intelligence points ledger
        └── field.log       ← protocol activity log
```

---

## Protocol

AURA v0.4 uses:

| Layer | Technology |
|---|---|
| Discovery | UDP multicast `239.77.77.77:7777` |
| Identity | Ed25519 — every packet signed |
| Encryption | X25519 ECDH → HKDF-SHA256 → ChaCha20-Poly1305 |
| Large files | TCP direct transfer (files > 60 KB) |
| WAN | Relay servers (`aura relay`) |
| Economy | NOT Money — intelligence points earned in place |

### Wire packet

```
[MAGIC 2][VER 1][TYPE 1][BODY_LEN 2][SIG_LEN 2][SIGNATURE][JSON_BODY]
```

Every packet is signed with the sender's Ed25519 key. Unsigned or tampered packets are silently dropped.

### Message types

| Code | Name | Purpose |
|---|---|---|
| `0x01` | `ANNOUNCE` | Node joins / heartbeat |
| `0x02` | `SEEK` | Broadcast query |
| `0x03` | `RESONATE` | Reply to seek with score |
| `0x04` | `ROUTE` | File delivery (encrypted) |
| `0x05` | `PULL_REQ` | Request a shared file |
| `0x06` | `PULL_DATA` | File delivery response |
| `0x07` | `TALK_OPEN` | Open a talk session |
| `0x08` | `TALK_LINE` | Single line in a talk session |
| `0x09` | `LEAVE` | Graceful departure |
| `0x0A` | `RELAY_REG` | Register with a relay |
| `0x0B` | `RELAY_FWD` | Relay packet forwarding |
| `0x0C` | `PING` | Keep-alive |
| `0x0D` | `PONG` | Keep-alive response |
| `0x0E` | `TCP_OFFER` | Negotiate direct TCP transfer |
| `0x0F` | `ACK` | Acknowledgement |

### Channels

By default all nodes join `239.77.77.77:7777`. You can create private channels:

```bash
aura join ./my-node --channel my-secret-channel
```

Channel names are hashed (MD5) to derive a unique multicast group and port. Nodes on different channels are completely invisible to each other.

---

## CLI Reference

```
aura new   <path>              Scaffold a new node
aura join  [path]              Join the field (default: .)
aura seek  [path] <query...>   Seek the field for nodes
aura who   [path]              List peers
aura send  [path] <id> <file>  Route a file to a peer
aura pull  [path] <id> <file>  Pull a file from a peer's shared/
aura talk  [path] <id>         Talk to a peer's entry point
aura in    [path]              List in/ files
aura shared [path]             List your shared/ files
aura ledger [path]             Show intelligence balance
aura relay                     Run a WAN relay server
aura api   [path]              Start local HTTP API
aura init-config               Write default ~/.aura/config.toml
```

### Options for `aura join`

```
--channel, -c   Private channel name
--name,    -n   Override node name
--no-api        Disable local HTTP API
```

---

## Local HTTP API

When you run `aura join`, an HTTP API starts automatically on `http://127.0.0.1:7778`.

```
GET  /status     Node status (name, id, wallet, balance, peers)
GET  /peers      All known peers
POST /seek       { "query": "music" }
GET  /shared     Your shared/ files
GET  /in         Your in/ files
POST /route      { "target": "<node_id>", "file": "/path/to/file" }
POST /pull       { "target": "<node_id>", "file": "name.ext" }
GET  /ledger     Intelligence points summary
GET  /health     Health check
```

Disable with `aura join --no-api` or `AURA_API_ENABLED=false`.

---

## WAN Relay

For nodes on different networks (internet-scale):

```bash
# On a server with a public IP
aura relay --port 7779

# Each node connects to the relay
aura join ./my-node --relay relay.example.com:7779
```

Or in `~/.aura/config.toml`:
```toml
[field]
relays = ["relay.example.com:7779"]
```

The relay is stateless — it never stores or decrypts packets.

---

## Entry Points

Your `aura.py` (or `aura.sh`, `aura.js`, `aura.rs`) receives seeks and talk sessions:

```python
# aura.py
import os

AURA_QUERY   = os.environ.get("AURA_QUERY",   "")
AURA_VISITOR = os.environ.get("AURA_VISITOR", "anonymous")
AURA_SESSION = os.environ.get("AURA_SESSION", "")
AURA_IN      = os.environ.get("AURA_IN",  "in")
AURA_OUT     = os.environ.get("AURA_OUT", "out")
AURA_SHARED  = os.environ.get("AURA_SHARED", "shared")

def respond(query, visitor):
    if "music" in query.lower():
        return "I have 47 tracks in shared/"
    return f"I heard you, {visitor}: {query}"

if __name__ == "__main__":
    if AURA_QUERY:
        print(respond(AURA_QUERY, AURA_VISITOR))
```

---

## Configuration

Config is read from `~/.aura/config.toml` (or `~/.aura/config.json`):

```toml
[field]
group   = "239.77.77.77"
port    = 7777
ttl     = 8
relays  = ["relay.aethyr-global.com:7779"]

[node]
announce_interval = 15     # seconds between heartbeats
rescan_interval   = 30     # seconds between folder re-scans
peer_ttl          = 90     # drop peers not seen in N seconds

[api]
host    = "127.0.0.1"
port    = 7778
enabled = true

[relay]
port      = 7779
max_peers = 512

[transfer]
tcp_port   = 7780
chunk_size = 65536
timeout    = 30
```

Generate defaults: `aura init-config`

Environment variables override config:

```bash
AURA_FIELD_GROUP=239.1.2.3
AURA_FIELD_PORT=8888
AURA_API_PORT=9999
AURA_API_ENABLED=false
AURA_RELAY_PORT=8779
```

---

## Python API

```python
from aura import AuraField, FolderAura
from aura.api import AuraAPI

# Scan a folder
fa = FolderAura("./my-node").scan()
print(fa.summary())
print(fa.resonate("music"))   # 0.0–1.0

# Join the field
field = AuraField("./my-node", channel="my-channel")
field.join()

# Start API
api = AuraAPI(field).start()
print(f"API: {api.url}")

# React to events
field.on_peer(lambda id, name, summary: print(f"Peer: {name}"))
field.on_route(lambda id, name, file, score: print(f"Got: {file}"))

# Seek
results = field.seek("python music data")
for r in results:
    print(r["name"], r["score"])

# Route a file
field.route_file(results[0]["node_id"], "./my-report.pdf")

# Talk to a peer
response = field.talk(results[0]["node_id"], "what can you do?")
print(response)

# Leave cleanly
field.leave()
```

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

```
tests/test_crypto.py   — identity, signing, ECDH encryption
tests/test_folder.py   — folder scanning, resonance scoring
tests/test_field.py    — peer management, routing, ledger
```

---

## Intelligence Points (NOT Money)

Every useful action earns intelligence points (AYR):

| Action | Points |
|---|---|
| Respond to a seek (score > 0.8) | 0.6 AYR |
| Respond to a seek (score 0.5–0.8) | 0.0–0.6 AYR |
| Peer pulls a file from your shared/ | 0.2 AYR |
| You receive a routed file | 0.1 AYR |
| Relay a TCP transfer | 0.15 AYR |

Points are earned in place. They are never transferred. They accumulate in your `ledger.json`.

```bash
aura ledger ./my-node
```

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-feature`
3. Make changes and run `pytest`
4. Submit a PR

Please keep protocol changes in a separate PR with a protocol version bump.

---

## License

MIT © Aethyr Global — see [LICENSE](LICENSE)

---

## Roadmap

- [ ] WebRTC transport for browser nodes
- [ ] DHT-based peer discovery (no relay needed)  
- [ ] AURA name system (resolve names to node fingerprints)
- [ ] Streaming talk sessions (WebSocket)
- [ ] File versioning and sync
- [ ] Visual field explorer (already at [aura.aethyr-global.com](https://aura.aethyr-global.com))

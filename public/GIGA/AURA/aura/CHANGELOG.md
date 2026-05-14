# Changelog

All notable changes to AURA are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2025-01-01

### Added
- Production-ready Python package (`pip install aura-protocol`)
- `aura.crypto` — clean cryptographic identity module (Ed25519 + X25519)
- `aura.folder` — semantic folder scanner with keyword extraction and resonance scoring
- `aura.field` — full field protocol with TCP fallback for large files (> 60 KB)
- `aura.ledger` — persistent intelligence points ledger (NOT Money)
- `aura.config` — `~/.aura/config.toml` configuration with env var overrides
- `aura.relay` — stateless WAN relay server for internet-scale operation
- `aura.api` — local HTTP REST API on `127.0.0.1:7778`
- `aura.cli` — full CLI: `new`, `join`, `seek`, `who`, `send`, `pull`, `talk`, `in`, `shared`, `ledger`, `relay`, `api`, `init-config`
- TCP file transfer protocol for files > 60 KB (chunked, 64 KB/chunk)
- Auto-routing: files placed in `out/` are automatically sent to best-resonating peer
- Folder re-scan loop: detects changes and re-announces automatically
- Peer eviction: stale peers automatically removed after configurable TTL
- Relay keep-alive: nodes send `PING` to relay every 30 seconds
- Out-of-the-box `on_peer`, `on_seek`, `on_route`, `on_leave` callbacks
- 40+ unit tests (crypto, folder, field)
- Full docstrings, type annotations, and `py.typed` marker

### Changed
- Wire format: header is now `[MAGIC 2][VER 1][TYPE 1][BODY_LEN 2][SIG_LEN 2]` (8 bytes)
- Packet body is always JSON; signature precedes body in the wire packet
- `MSG_RELAY_REG` / `MSG_RELAY_FWD` / `MSG_PING` / `MSG_PONG` / `MSG_TCP_OFFER` / `MSG_ACK` added as new message types
- `channel` hashing upgraded from MD5 to deterministic multicast group derivation

### Fixed
- Race condition in peer registry (all mutations now lock-guarded)
- Lock file atomically written then replaced (no partial reads)
- Key files chmod'd to 0o600 on creation

---

## [0.4.0] — 2024-10-01 (AURA v0.4 protocol freeze)

### Added
- Ed25519 signing on every UDP packet
- X25519 ECDH peer-to-peer file encryption (ChaCha20-Poly1305)
- Wallet address: `AYR` prefix + SHA-256 of public key (35 chars)
- Custom channel support (MD5-derived multicast parameters)
- Intelligence ledger persistence (`ledger.json`)
- `aura field` — join the multicast mesh
- `aura seek` — broadcast a semantic query
- `aura route` — send a file to a peer
- `aura talk` — run a peer's entry point
- Language templates: Python, Shell, Node.js, Rust

### Changed
- Protocol version bumped to `0x04`

---

## [0.3.0] — 2024-07-01

### Added
- Folder-based node architecture (`in/`, `out/`, `shared/`, `private/`)
- Semantic tag extraction from filenames, extensions, and text content
- Resonance scoring (cosine-like weighted tag overlap)
- `aura.meta` file format

---

## [0.2.0] — 2024-04-01

### Added
- UDP multicast discovery (`239.77.77.77:7777`)
- `ANNOUNCE` / `SEEK` / `RESONATE` message types
- Basic peer registry

---

## [0.1.0] — 2024-01-01

### Added
- Initial proof of concept
- UDP multicast field
- Single-file implementation

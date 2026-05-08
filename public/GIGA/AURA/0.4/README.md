# AURA v0.4 — Protocol Specification

## The single idea

A folder is a node.
Files inside it are the content.
The field finds it.
Any language runs it.

There are no apps.

---

## What's new in v0.4

AURA v0.4 focuses on **production readiness**:
- **Cryptographic Identity**: Nodes are now identified by Ed25519 public keys. All messages are signed.
- **Private Aura / Peer Encryption**: Files can now be encrypted for specific recipients using X25519 key exchange and secure symmetric encryption.
- **Partial Field Visibility**: Users can now join specific "Channels" by specifying a sub-topic, isolating their field from others.
- **Robustness**: Improved error handling for network issues and malformed protocol packets.

---

## Folder anatomy

```
~/me/
    .aura/
        identity.key    ← your private Ed25519 key
        aura.pub        ← your public Ed25519 key
        field.log       ← node-specific logs
    aura.meta          ← who you are (plain text, optional)
    aura.py            ← your entry point (any language)
    aura.lock          ← runtime state (auto-generated)

    in/                ← things that arrived for you
    out/               ← things you are sending into the field
    shared/            ← permanently in the field, anyone can seek it
    private/           ← never leaves, never indexed
```

---

## Cryptographic Identity

The `node_id` is now a hash of your Ed25519 public key.
Every packet sent into the field is signed by your private key.
Other nodes verify the signature before processing.

---

## Peer Encryption

When you know a peer's public key (from their heartbeats), AURA can establish a secure channel:
1. Diffie-Hellman (X25519) derives a shared secret.
2. File content is encrypted before being sent into the field or routed.
3. Only the recipient with the corresponding private key can decrypt it.

---

## Multicast Channels

Join a specific sub-field:
```bash
aura field --channel "secret-project"
```
This isolates your node's heartbeats and seeks to a specific multicast port/group assigned to that channel name.

---

## Versions

- v0.1 — UDP multicast, basic heartbeat, seek/resonate
- v0.2 — folder scanning, aura.meta, entry point execution, file sharing
- v0.3 — in/out routing, field watcher, shadow routing, aura.lock, talk protocol, pull
- v0.4 — cryptographic identity, private aura, multicast channels, NOT Money (Intelligence Points), production hardening

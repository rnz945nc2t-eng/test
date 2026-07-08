# AURA v0.3 — Protocol Specification

## The single idea

A folder is a node.
Files inside it are the content.
The field finds it.
Any language runs it.

There are no apps.

---

## What replaces apps

In AURA there is no such thing as "an email app" or "a file manager."
There is only: **you have a file. someone else has a file. the field connects them.**

Sending something = dropping a file into your folder.
Receiving something = a file appears in your folder.
Finding someone = seeking in the field by what you need.
A "document" = any file in any format your entry point can read.
"A conversation" = two folders whose entry points speak the same protocol.

The folder IS the interface.
The field IS the network.
The entry point IS the OS.

---

## Folder anatomy

```
~/me/
    aura.meta          ← who you are (plain text, optional)
    aura.py            ← your entry point (any language)
    aura.lock          ← runtime state (auto-generated)

    in/                ← things that arrived for you
    out/               ← things you are sending into the field
    shared/            ← permanently in the field, anyone can seek it
    private/           ← never leaves, never indexed
```

No fixed schema. Add any folder. Remove any folder.
The aura scanner reads what you have — not what you declared.

---

## The entry point

`aura.py` / `aura.sh` / `aura.js` / `aura.rs` / anything executable.

When another node opens yours, this runs.
It receives context via environment variables:

```
AURA_NODE      = path to this folder
AURA_VISITOR   = node_id of who opened you (if known)
AURA_QUERY     = what they were seeking when they found you
AURA_IN        = path to in/ folder
AURA_OUT       = path to out/ folder
AURA_FIELD     = multicast group address
```

It can output anything to stdout.
It can write files to out/.
It can read files from in/.
It can speak back to the visitor.

The entry point IS the experience. Not an app. Not a UI framework.
A Python script that prints. A shell script that moves files.
A Rust binary that renders. Anything.

---

## How "sending" works

There is no send button.

You write a file into your `out/` folder.
The field watcher sees it.
It checks if the filename or content matches any seeker in the field.
If it does — that file resonates to their `in/` folder.
They didn't request it. The field routed it.

This is shadow mail. Not an app called shadow mail.
Just files, moving through resonance.

---

## How "finding" works

```bash
aura seek "sound design mixing"
```

Every node in the field scores itself against your query.
Those above threshold respond.
You get a list of nodes — not URLs, not profiles, not search results.
Just folders that resonate.

You can then:
- `aura open <node>` — run their entry point
- `aura ls <node>` — see what's in their shared/ folder
- `aura pull <node> <file>` — copy a file from their shared/
- `aura talk <node>` — bidirectional entry point session

---

## File formats

AURA has no preferred format.
You work in whatever your entry point speaks.
A "document" to one node is a `.txt`.
To another it's a `.py` that generates output.
To another it's a binary.

When two nodes talk, they negotiate format via the entry point.
No standard. No schema. Just files speaking to files.

This is how "CAD files", "presentations", "spreadsheets" work in AURA:
they are files your entry point knows how to make and read.
The field doesn't care what's inside them.

---

## Versions

- v0.1 — UDP multicast, basic heartbeat, seek/resonate
- v0.2 — folder scanning, aura.meta, entry point execution, file sharing
- v0.3 — in/out routing, field watcher, shadow routing, aura.lock, talk protocol, pull
- v0.4 (planned) — cryptographic identity, private aura, partial field visibility
- v0.5 (planned) — NOT Money integration, intelligence point accumulation per interaction

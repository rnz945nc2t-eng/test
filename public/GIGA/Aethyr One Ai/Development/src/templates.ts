export type Lang = 'py' | 'sh' | 'js' | 'rs';

export const LANG_LABELS: Record<Lang, string> = {
  py: 'Python',
  sh: 'Shell',
  js: 'Node.js',
  rs: 'Rust',
};

export const ENTRY_FILENAME: Record<Lang, string> = {
  py: 'aura.py',
  sh: 'aura.sh',
  js: 'aura.js',
  rs: 'aura.rs',
};

export const EXT_MEANING: Record<string, string[]> = {
  '.py':   ['python','code','script'],
  '.js':   ['javascript','web','script'],
  '.ts':   ['typescript','frontend'],
  '.rs':   ['rust','systems'],
  '.go':   ['golang','systems'],
  '.sh':   ['shell','automation'],
  '.md':   ['writing','docs'],
  '.txt':  ['text','notes'],
  '.png':  ['image','visual'],
  '.svg':  ['vector','design'],
  '.mp3':  ['audio','music'],
  '.wav':  ['audio','sound'],
  '.mp4':  ['video'],
  '.csv':  ['data','table'],
  '.json': ['data','config'],
  '.sql':  ['database','query'],
};

export function getEntryTemplate(lang: Lang, nodeName: string): string {
  const templates: Record<Lang, string> = {
    py: `#!/usr/bin/env python3
"""
${nodeName} — AURA node entry point (Python)
Runs when someone opens this folder from the field.

Environment variables available:
  AURA_NODE     — path to this folder
  AURA_VISITOR  — node_id of the visitor
  AURA_QUERY    — what they were seeking
  AURA_IN       — path to in/
  AURA_OUT      — path to out/
  AURA_SHARED   — path to shared/
"""
import os
from pathlib import Path

node    = Path(os.environ.get("AURA_NODE", "."))
visitor = os.environ.get("AURA_VISITOR", "unknown")
query   = os.environ.get("AURA_QUERY", "")
shared  = Path(os.environ.get("AURA_SHARED", node / "shared"))

print(f"  node: {node.name}")
if query:
    print(f"  visitor sought: {query}")
print()

files = sorted(shared.glob("*")) if shared.exists() else []
if files:
    print("  shared:")
    for f in files:
        print(f"    {f.name}  ({f.stat().st_size} bytes)")
else:
    print("  shared/ is empty — drop files there to share them")
`,
    sh: `#!/bin/bash
# ${nodeName} — AURA node entry point (Shell)
# Runs when someone opens this folder from the field.

echo "  node: $(basename $AURA_NODE)"
[ -n "$AURA_QUERY" ] && echo "  visitor sought: $AURA_QUERY"
echo

if [ -d "$AURA_SHARED" ] && [ "$(ls -A $AURA_SHARED 2>/dev/null)" ]; then
  echo "  shared:"
  ls -1 "$AURA_SHARED" | while read f; do echo "    $f"; done
else
  echo "  shared/ is empty"
fi
`,
    js: `#!/usr/bin/env node
// ${nodeName} — AURA node entry point (Node.js)
// Runs when someone opens this folder from the field.

const fs   = require('fs');
const path = require('path');

const node   = process.env.AURA_NODE   || '.';
const query  = process.env.AURA_QUERY  || '';
const shared = process.env.AURA_SHARED || path.join(node, 'shared');

console.log(\`  node: \${path.basename(node)}\`);
if (query) console.log(\`  visitor sought: \${query}\`);
console.log();

let files = [];
try { files = fs.readdirSync(shared); } catch(e) {}

if (files.length) {
  console.log('  shared:');
  files.forEach(f => {
    const st = fs.statSync(path.join(shared, f));
    console.log(\`    \${f}  (\${st.size} bytes)\`);
  });
} else {
  console.log('  shared/ is empty');
}
`,
    rs: `// ${nodeName} — AURA node entry point (Rust)
// Compile: rustc aura.rs -o aura_entry && chmod +x aura_entry
// Then rename executable to "aura" (no extension) in the folder root.

use std::{env, fs, path::Path};

fn main() {
    let node   = env::var("AURA_NODE").unwrap_or(".".into());
    let query  = env::var("AURA_QUERY").unwrap_or_default();
    let shared = env::var("AURA_SHARED")
        .unwrap_or_else(|_| format!("{}/shared", node));

    println!("  node: {}",
        Path::new(&node).file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("?"));

    if !query.is_empty() {
        println!("  visitor sought: {}", query);
    }
    println!();

    match fs::read_dir(&shared) {
        Ok(entries) => {
            println!("  shared:");
            for entry in entries.flatten() {
                let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
                println!("    {}  ({} bytes)",
                    entry.file_name().to_str().unwrap_or("?"), size);
            }
        }
        Err(_) => println!("  shared/ is empty"),
    }
}
`,
  };
  return templates[lang];
}

export function getMetaTemplate(name: string, desc: string, tags: string[], lang: Lang): string {
  const allTags = [lang, ...tags].filter(Boolean).join(', ');
  return `name: ${name || 'my-node'}
description: ${desc || ''}
tags: ${allTags}
author:
# The field reads this to build your aura.
# Add comma-separated tags to help others find you via seek.
# private/ is never indexed. shared/ is always visible.
`;
}

export function getLockTemplate(name: string): string {
  return `{
  "node_id": "<generated-on-mount>",
  "name": "${name || 'my-node'}",
  "pid": null,
  "started": null,
  "field": "239.77.77.77:7777",
  "channel": null,
  "proto": "v0.4"
}
`;
}

export const README_CONTENT = `# AURA Node

This folder is your node in the AURA field.

## Folder structure

\`\`\`
./
├── .aura/
│   ├── identity.key    ← Ed25519 private key (auto-generated on mount)
│   ├── aura.pub        ← Ed25519 public key
│   ├── encryption.key  ← X25519 private key (for private aura)
│   └── encryption.pub  ← X25519 public key
├── aura.meta           ← who you are (plain text)
├── aura.lock           ← runtime state (auto-generated)
├── aura.py             ← your entry point
├── in/                 ← files that arrived for you
├── out/                ← files you are sending
├── shared/             ← visible to the whole field
└── private/            ← never leaves, never indexed
\`\`\`

## Getting started

\`\`\`bash
pip install aura-protocol
aura join .

# Seek the field from another terminal
aura seek . "your query here"

# Local HTTP API auto-starts at http://127.0.0.1:7778
\`\`\`

## Protocol

AURA v0.4 — UDP multicast, Ed25519 identity, X25519 encryption.
Source: https://github.com/aethyr-global/aura
`;

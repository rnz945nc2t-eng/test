#!/usr/bin/env python3
"""
aura v0.3 — the CLI

Your folder is your node. Files are everything.
No apps. The protocol does what apps pretend to do.

  aura new <folder> [lang]     scaffold a node folder
  aura mount <folder>          mount a folder into the field
  aura field                   enter the live field REPL
  aura seek <query>            find nodes that resonate
  aura ls [node]               list shared/ files of a node (or your own)
  aura in                      what arrived in your in/
  aura open [node]             run a node's entry point
  aura pull <node> <file>      copy a file from their shared/ to your in/
  aura talk <node>             open a live session with a node's entry point
  aura route <node> <file>     send a file to their in/ (shadow routing)
  aura scan [folder]           inspect a folder's aura without joining
  aura status                  your node's current state
"""

import sys, os, time, json, shutil, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aura_folder import FolderAura, ENTRY_NAMES, RUNNERS
from aura_field  import AuraField

# ── Terminal ──────────────────────────────────────────────────────────────
R    = "\033[0m"
BOLD = "\033[1m";  DIM  = "\033[2m"
PUR  = "\033[35m"; CYAN = "\033[36m"; GRN  = "\033[32m"
YEL  = "\033[33m"; WHT  = "\033[97m"; RED  = "\033[31m"
PINK = "\033[95m"; BLUE = "\033[34m"

def c(col, t): return f"{col}{t}{R}"
def bar(v, w=16):
    n = int(v * w)
    return c(PUR,"█"*n) + c(DIM,"░"*(w-n))
def ts(): return c(DIM, time.strftime("%H:%M:%S"))
def hr(char="─", width=48): return c(DIM, char * width)

BANNER = f"""
{PUR}  ╔══════════════════════════════════════════════╗
  ║  {WHT}A U R A{PUR}  ·  v0.3  ·  field protocol         ║
  ║  {DIM}folder = node · files = everything{PUR}           ║
  ╚══════════════════════════════════════════════╝{R}
"""

# ── Session ───────────────────────────────────────────────────────────────
SESSION = os.path.expanduser("~/.aura_v3.json")

def save_session(path, name):
    with open(SESSION,"w") as f: json.dump({"path":path,"name":name},f)

def load_session():
    if os.path.exists(SESSION):
        try:
            d = json.load(open(SESSION))
            return d["path"], d.get("name")
        except: pass
    return None, None

# ── Node scaffold templates ───────────────────────────────────────────────
TEMPLATES = {
    "py": ("aura.py", """\
#!/usr/bin/env python3
\"\"\"
This node's entry point.
Runs when someone opens this folder from the field.
Receives context via environment variables:
  AURA_NODE, AURA_VISITOR, AURA_QUERY, AURA_IN, AURA_OUT, AURA_SHARED
\"\"\"
import os, sys
from pathlib import Path

node    = Path(os.environ.get("AURA_NODE", "."))
visitor = os.environ.get("AURA_VISITOR", "unknown")
query   = os.environ.get("AURA_QUERY", "")
shared  = Path(os.environ.get("AURA_SHARED", node / "shared"))

name = node.name
print(f"  node: {name}")
if query:
    print(f"  visitor sought: {query}")
print()

# show what's in shared/
files = sorted(shared.glob("*")) if shared.exists() else []
if files:
    print("  shared:")
    for f in files:
        sz = f.stat().st_size
        print(f"    {f.name}  ({sz} bytes)")
else:
    print("  shared/ is empty — drop files there to share them")
"""),

    "sh": ("aura.sh", """\
#!/bin/bash
# Entry point — shell edition
echo "  node: $(basename $AURA_NODE)"
[ -n "$AURA_QUERY" ] && echo "  visitor sought: $AURA_QUERY"
echo
if [ -d "$AURA_SHARED" ] && [ "$(ls -A $AURA_SHARED 2>/dev/null)" ]; then
    echo "  shared:"
    ls -1 "$AURA_SHARED" | while read f; do echo "    $f"; done
else
    echo "  shared/ is empty"
fi
"""),

    "js": ("aura.js", """\
#!/usr/bin/env node
// Entry point — Node.js edition
const fs   = require('fs');
const path = require('path');
const node   = process.env.AURA_NODE   || '.';
const query  = process.env.AURA_QUERY  || '';
const shared = process.env.AURA_SHARED || path.join(node, 'shared');

console.log(`  node: ${path.basename(node)}`);
if (query) console.log(`  visitor sought: ${query}`);
console.log();

let files = [];
try { files = fs.readdirSync(shared); } catch(e) {}
if (files.length) {
    console.log('  shared:');
    files.forEach(f => {
        const st = fs.statSync(path.join(shared, f));
        console.log(`    ${f}  (${st.size} bytes)`);
    });
} else {
    console.log('  shared/ is empty');
}
"""),

    "rs": ("aura.rs", """\
// Entry point — Rust edition
// Compile: rustc aura.rs -o aura && chmod +x aura
// Then rename to just 'aura' (no extension)
use std::{env, fs, path::Path};
fn main() {
    let node   = env::var("AURA_NODE").unwrap_or(".".into());
    let query  = env::var("AURA_QUERY").unwrap_or_default();
    let shared = env::var("AURA_SHARED")
        .unwrap_or_else(|_| format!("{}/shared", node));
    println!("  node: {}", Path::new(&node).file_name()
        .and_then(|n| n.to_str()).unwrap_or("?"));
    if !query.is_empty() { println!("  visitor sought: {}", query); }
    println!();
    match fs::read_dir(&shared) {
        Ok(entries) => {
            println!("  shared:");
            for e in entries.flatten() {
                let meta = e.metadata().map(|m| m.len()).unwrap_or(0);
                println!("    {}  ({} bytes)", e.file_name().to_str().unwrap_or("?"), meta);
            }
        }
        Err(_) => println!("  shared/ is empty"),
    }
}
"""),
}

META_TEMPLATE = """\
name: {name}
description:
tags: {lang}, code
author:
# Add more tags separated by commas.
# The field reads this + your files to build your aura.
# private/ folder is never read. shared/ is always visible.
"""

# ── Commands ──────────────────────────────────────────────────────────────

def cmd_new(folder: str, lang: str = "py"):
    lang = lang.lower().lstrip(".")
    p    = os.path.abspath(folder)
    name = os.path.basename(p)

    if not os.path.exists(p):
        os.makedirs(p)
        print(f"  {c(GRN,'✓')} created  {p}")
    else:
        print(f"  {c(YEL,'◌')} exists   {p}")

    # entry point
    if lang in TEMPLATES:
        fname, code = TEMPLATES[lang]
        ep = os.path.join(p, fname)
        if not os.path.exists(ep):
            with open(ep,"w") as f: f.write(code)
            os.chmod(ep, 0o755)
            print(f"  {c(GRN,'✓')} entry    {fname}")
    else:
        print(f"  {c(YEL,'?')} lang '{lang}' not in templates — add your own aura.<ext> file")

    # meta
    mp = os.path.join(p, "aura.meta")
    if not os.path.exists(mp):
        with open(mp,"w") as f:
            f.write(META_TEMPLATE.format(name=name, lang=lang))
        print(f"  {c(GRN,'✓')} meta     aura.meta")

    # structure
    for d in ("in","out","shared","private"):
        dp = os.path.join(p, d)
        if not os.path.exists(dp):
            os.makedirs(dp)
    print(f"  {c(GRN,'✓')} dirs     in/  out/  shared/  private/")
    print()
    print(f"  {c(PUR,'→')} drop files into {c(WHT,'shared/')} to share them into the field")
    print(f"  {c(PUR,'→')} write files to  {c(WHT,'out/')} to shadow-route them to resonant peers")
    print(f"  {c(PUR,'→')} files arrive in {c(WHT,'in/')} when peers route to you")
    print(f"  {c(DIM,'→')} private/ is never read by the field")
    print()
    print(f"  {c(WHT,'next:')}  aura mount {folder}")
    print()


def cmd_scan(folder: str):
    print()
    try:
        fa = FolderAura(folder).scan()
    except FileNotFoundError as e:
        print(f"  {c(RED,'✗')} {e}\n"); return

    s = fa.summary()
    print(f"  {c(WHT+BOLD, s['name'])}  {c(DIM, s['path'])}")
    if s['description']:
        print(f"  {c(DIM, s['description'])}")
    print()
    entry = s['entry'] or c(DIM,"none — add aura.py / aura.sh / etc.")
    print(f"  entry   {c(CYAN, entry)}")
    print(f"  files   {s['file_count']}")
    st = s['structure']
    print(f"  in/     {st['in_count']} files  |  out/ {st['out_count']}  |  shared/ {st['shared_count']}")
    print(f"  private {c(GRN,'yes') if st['has_private'] else c(DIM,'no')}")
    print()
    print(f"  {c(PUR,'aura:')}")
    for tag, w in sorted(s['tags'].items(), key=lambda x:-x[1])[:12]:
        print(f"  {bar(w,14)}  {c(WHT,tag):<24} {c(DIM,f'{w:.2f}')}")
    print()


def cmd_mount(folder: str):
    folder = os.path.abspath(folder)
    if not os.path.exists(folder):
        print(f"  {c(RED,'✗')} not found: {folder}"); return
    fa   = FolderAura(folder).scan()
    name = fa.meta.get("name", os.path.basename(folder))
    save_session(folder, name)
    s    = fa.summary()
    print(f"\n  {c(GRN,'◉')} mounted  {c(WHT+BOLD,name)}")
    print(f"  {c(DIM,folder)}")
    print(f"  aura:   {', '.join(list(s['tags'].keys())[:6])}")
    print(f"  files:  {s['file_count']}  entry: {s['entry'] or 'none'}")
    print(f"\n  {c(DIM,'run:')}  aura field\n")


def cmd_status(field: AuraField):
    s = field.folder.summary()
    st = s['structure']
    print(f"\n  {c(WHT+BOLD, field.name)}  {c(DIM,'['+field.node_id+']')}")
    print(f"  {c(DIM, str(field.folder.path))}")
    print()
    print(f"  {c(PUR,'aura:')}")
    for tag, w in list(s['tags'].items())[:8]:
        print(f"    {bar(w,10)}  {tag}")
    print()
    inf = field.in_files()
    print(f"  {c(CYAN,'in/')}     {len(inf)} files waiting")
    for f in inf[:3]:
        print(f"    {c(WHT,f['name'])}  {c(DIM,str(f['size'])+'B')}")
    print(f"  {c(CYAN,'out/')}    {st['out_count']} outgoing")
    print(f"  {c(CYAN,'shared/')} {st['shared_count']} shared into field")
    print(f"  peers    {len(field.peers_list())}")
    print()


# ── Field REPL ────────────────────────────────────────────────────────────

def run_repl(field: AuraField):
    print(BANNER)
    s = field.folder.summary()
    print(f"  {c(GRN,'◉')} {c(WHT+BOLD,field.name)}  {c(DIM,'['+field.node_id+']')}")
    print(f"  {c(DIM,str(field.folder.path))}")
    print(f"  aura: {c(PUR,', '.join(list(s['tags'].keys())[:6]))}")
    print()
    print(f"  {c(DIM,'seek · ls · in · open · pull · route · talk · who · status · help · quit')}\n")

    # live events
    def ev_peer(pid, name, summary):
        tags = list(summary.get("tags",{}).keys())[:3]
        print(f"\r  {ts()}  {c(GRN,'◉')} {c(WHT,name)} joined  {c(DIM,' '.join(tags))}")
        print("  > ", end="", flush=True)

    def ev_seek(pid, name, query, score):
        if score > 0.12:
            print(f"\r  {ts()}  {c(YEL,'◎')} {c(WHT,name)} seeks '{query}'  {c(PUR,f'you: {score:.0%}')}")
            print("  > ", end="", flush=True)

    def ev_route(pid, name, fname, score):
        print(f"\r  {ts()}  {c(CYAN,'⬡')} {c(WHT,fname)} arrived in in/  {c(DIM,'from '+name)}")
        print("  > ", end="", flush=True)

    field.on_peer(ev_peer)
    field.on_seek(ev_seek)
    field.on_route(ev_route)

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw: continue

        parts = raw.split(None, 2)
        cmd   = parts[0].lower()
        a1    = parts[1] if len(parts) > 1 else ""
        a2    = parts[2] if len(parts) > 2 else ""

        # ── seek ──────────────────────────────────────────────────────
        if cmd in ("seek","s"):
            if not a1: print(f"  {c(DIM,'seek <query>')}"); continue
            query = a1 + (" " + a2 if a2 else "")
            print(f"\n  {c(YEL,'◎')} seeking '{query}'...\n")
            res = field.seek(query)
            time.sleep(1.0)
            res = field.seek(query)
            if not res:
                print(f"  {c(DIM,'no resonance')}")
            else:
                for r in res:
                    desc = r.get("description","")
                    tags = "  ".join(r["tags"][:5])
                    st   = r.get("structure",{})
                    print(f"  {bar(r['score'])}  {c(WHT+BOLD,r['name']):<16}  {c(DIM,'['+r['node_id']+']')}")
                    if desc: print(f"  {'':22}{c(DIM,desc)}")
                    print(f"  {'':22}{c(DIM,tags)}")
                    if st.get("has_shared"):
                        print(f"  {'':22}{c(CYAN,str(st.get('shared_count',0))+' files in shared/')}")
                    if r.get("entry"):
                        print(f"  {'':22}entry: {c(CYAN,r['entry'])}")
                    print()

        # ── ls ────────────────────────────────────────────────────────
        elif cmd == "ls":
            if not a1:
                files = field.shared_files()
                inf   = field.in_files()
                print(f"\n  {c(PUR,'shared/')}  ({len(files)} files)")
                for f in files:
                    print(f"  {c(WHT,f['name']):<32} {c(DIM,str(f['size'])+'B')}")
                print(f"\n  {c(CYAN,'in/')}  ({len(inf)} files)")
                for f in inf:
                    print(f"  {c(WHT,f['name']):<32} {c(DIM,str(f['size'])+'B')}")
                print()
            else:
                # find peer by name or id
                peer = _find_peer(field, a1)
                if not peer:
                    print(f"  {c(DIM,'node not found: '+a1)}"); continue
                files = field.shared_files(peer['node_id'])
                print(f"\n  {c(PUR,peer['name'])} shared/  ({len(files)} files)")
                for f in files:
                    print(f"  {c(WHT,f['name']):<32} {c(DIM,str(f['size'])+'B')}")
                print()

        # ── in ────────────────────────────────────────────────────────
        elif cmd == "in":
            files = field.in_files()
            print(f"\n  {c(CYAN,'in/')}  {len(files)} files\n")
            for f in files:
                mtime = time.strftime("%b %d %H:%M", time.localtime(f['modified']))
                print(f"  {c(WHT,f['name']):<32}  {c(DIM,str(f['size'])+'B  '+mtime)}")
            if not files:
                print(f"  {c(DIM,'empty — files arrive here when peers route to you')}")
            print()

        # ── open ──────────────────────────────────────────────────────
        elif cmd in ("open","run","visit","o"):
            if not a1:
                proc = field.folder.run_entry()
                _run_proc(proc, field.name)
            else:
                peer = _find_peer(field, a1)
                if not peer:
                    print(f"  {c(DIM,'node not found: '+a1)}"); continue
                path = peer.get("path") or field.peers.get(peer['node_id'],{}).get("summary",{}).get("path","")
                if not path or not os.path.exists(path):
                    print(f"  {c(YEL,'⚠')} remote nodes cannot be opened yet (local only)")
                    continue
                fa   = FolderAura(path).scan()
                proc = fa.run_entry(env_extra={
                    "AURA_VISITOR": field.node_id,
                    "AURA_QUERY":   "",
                })
                _run_proc(proc, peer['name'])

        # ── pull ──────────────────────────────────────────────────────
        elif cmd == "pull":
            if not a1 or not a2:
                print(f"  {c(DIM,'pull <node> <filename>')}"); continue
            peer = _find_peer(field, a1)
            if not peer:
                print(f"  {c(DIM,'node not found: '+a1)}"); continue
            dest = field.pull(peer['node_id'], a2)
            if dest:
                print(f"  {c(GRN,'✓')} pulled '{a2}' → in/{a2}")
            else:
                print(f"  {c(YEL,'✗')} file not found in {peer['name']}/shared/")

        # ── route (shadow mail) ───────────────────────────────────────
        elif cmd == "route":
            if not a1 or not a2:
                print(f"  {c(DIM,'route <node> <file>')}"); continue
            peer = _find_peer(field, a1)
            if not peer:
                print(f"  {c(DIM,'node not found: '+a1)}"); continue
            ok, msg = field.route_file(peer['node_id'], a2)
            if ok:
                print(f"  {c(GRN,'⬡')} routed '{os.path.basename(a2)}' → {peer['name']}/in/")
            else:
                print(f"  {c(RED,'✗')} {msg}")

        # ── talk ──────────────────────────────────────────────────────
        elif cmd == "talk":
            if not a1:
                print(f"  {c(DIM,'talk <node>')}"); continue
            peer = _find_peer(field, a1)
            if not peer:
                print(f"  {c(DIM,'node not found: '+a1)}"); continue
            session = str(int(time.time()))[-6:]
            print(f"\n  {c(CYAN,'talk')} → {c(WHT+BOLD,peer['name'])}  {c(DIM,'session:'+session)}")
            print(f"  {c(DIM,'ctrl+c or empty line to end')}\n")
            while True:
                try:
                    line = input(f"  {c(PUR,'you')} > ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line: break
                resp = field.talk(peer['node_id'], line, session)
                if resp:
                    print(f"  {c(CYAN,peer['name'])} > {resp}\n")
                else:
                    print(f"  {c(DIM,'(no response)')}")
            print()

        # ── who ───────────────────────────────────────────────────────
        elif cmd == "who":
            peers = field.peers_list()
            if not peers:
                print(f"\n  {c(DIM,'field is empty — waiting for heartbeats...')}\n"); continue
            print(f"\n  {c(PUR,str(len(peers))+' nodes in field:')}\n")
            for p in peers:
                st  = p.get("structure",{})
                age = int(time.time() - p.get("last_seen",0))
                print(f"  {c(GRN,'◉')}  {c(WHT+BOLD,p['name']):<20}  {c(DIM,p.get('entry') or 'no entry')}")
                if p['tags']:
                    print(f"     {c(DIM,'  '.join(p['tags'][:5]))}")
                extras = []
                if st.get("has_shared"): extras.append(f"shared:{st.get('shared_count',0)}")
                if st.get("has_in"):     extras.append("has in/")
                if extras: print(f"     {c(CYAN,'  '.join(extras))}")
            print()

        # ── status ────────────────────────────────────────────────────
        elif cmd in ("status","me","aura"):
            cmd_status(field)

        # ── scan ──────────────────────────────────────────────────────
        elif cmd == "scan":
            cmd_scan(a1 or str(field.folder.path))

        # ── refresh ───────────────────────────────────────────────────
        elif cmd == "refresh":
            field.folder = FolderAura(str(field.folder.path)).scan()
            s2 = field.folder.summary()
            print(f"  {c(GRN,'✓')} re-scanned — {len(s2['tags'])} tags")

        # ── help ──────────────────────────────────────────────────────
        elif cmd in ("help","h","?"):
            print(f"""
  {c(PUR,'commands')}

  {c(WHT,'seek')} <query>          find nodes by what they are
  {c(WHT,'ls')}                    list your shared/ and in/
  {c(WHT,'ls')} <node>             list a peer's shared/ files
  {c(WHT,'in')}                    see what arrived in your in/
  {c(WHT,'open')}                  run your own entry point
  {c(WHT,'open')} <node>           run a peer's entry point (local only)
  {c(WHT,'pull')} <node> <file>    copy from their shared/ to your in/
  {c(WHT,'route')} <node> <file>   shadow-route a file to their in/
  {c(WHT,'talk')} <node>           live session with a peer's entry point
  {c(WHT,'who')}                   nodes currently in the field
  {c(WHT,'status')}                your node — aura, in/, out/, shared/
  {c(WHT,'scan')} [path]           inspect a folder's aura
  {c(WHT,'refresh')}               re-scan your folder
  {c(WHT,'quit')}                  leave the field
""")

        elif cmd in ("quit","q","exit","bye"):
            break
        else:
            print(f"  {c(DIM,'unknown — type help')}")

    field.leave()


# ── helpers ───────────────────────────────────────────────────────────────

def _find_peer(field: AuraField, query: str) -> dict | None:
    peers = field.peers_list()
    # exact node_id
    for p in peers:
        if p['node_id'] == query:
            return p
    # name (case-insensitive substring)
    q = query.lower()
    for p in peers:
        if q in p['name'].lower():
            return p
    return None


def _run_proc(proc, name: str):
    if not proc:
        print(f"  {c(YEL,'⚠')} no entry point"); return
    print(f"\n  {c(GRN,'▶')} {name}\n  {hr()}")
    for line in proc.stdout:
        print(f"  {line}", end="")
    proc.wait()
    print(f"  {hr()}\n")


# ── main ──────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h","--help","help"):
        print(BANNER); print(__doc__); return

    cmd = args[0].lower()

    if cmd == "new":
        if len(args) < 2: print(f"  {c(RED,'usage:')} aura new <folder> [lang]"); return
        cmd_new(args[1], args[2] if len(args)>2 else "py")

    elif cmd == "scan":
        cmd_scan(args[1] if len(args)>1 else ".")

    elif cmd == "mount":
        if len(args) < 2: print(f"  {c(RED,'usage:')} aura mount <folder>"); return
        cmd_mount(args[1])

    else:
        # all other commands need a mounted node
        path, name = load_session()
        if not path:
            path = os.getcwd()
            print(f"  {c(YEL,'no node mounted')} — using {path}")
            print(f"  {c(DIM,'run: aura mount <folder> to set your node')}\n")

        field = AuraField(path, name)
        field.join()
        time.sleep(0.3)

        if cmd == "field":
            run_repl(field)

        elif cmd == "seek":
            q = " ".join(args[1:])
            if not q: print(f"  {c(RED,'usage:')} aura seek <query>"); field.leave(); return
            print(f"\n  {c(YEL,'◎')} seeking '{q}'...\n")
            field.seek(q); time.sleep(1.5)
            res = field.seek(q)
            if not res: print(f"  {c(DIM,'no resonance')}")
            else:
                for r in res:
                    print(f"  {bar(r['score'])}  {c(WHT+BOLD,r['name']):<16}  {', '.join(r['tags'][:4])}")
            print(); field.leave()

        elif cmd == "ls":
            arg = args[1] if len(args)>1 else None
            if not arg:
                files = field.shared_files()
                inf   = field.in_files()
                print(f"\n  {c(PUR,'shared/')}  {len(files)} files")
                for f in files: print(f"  {f['name']}")
                print(f"\n  {c(CYAN,'in/')}  {len(inf)} files")
                for f in inf:   print(f"  {f['name']}")
                print()
            field.leave()

        elif cmd == "in":
            files = field.in_files()
            print(f"\n  {c(CYAN,'in/')}  {len(files)} files\n")
            for f in files:
                print(f"  {c(WHT,f['name']):<32}  {c(DIM,str(f['size'])+'B')}")
            if not files: print(f"  {c(DIM,'empty')}")
            print(); field.leave()

        elif cmd == "status":
            cmd_status(field); field.leave()

        elif cmd == "who":
            time.sleep(2)
            peers = field.peers_list()
            if not peers: print(f"\n  {c(DIM,'field empty')}\n")
            else:
                print(f"\n  {c(PUR,str(len(peers))+' nodes:')}\n")
                for p in peers:
                    print(f"  {c(GRN,'◉')}  {c(WHT+BOLD,p['name']):<20}  {c(DIM,' '.join(p['tags'][:4]))}")
                print()
            field.leave()

        else:
            print(f"  {c(RED,'unknown:')} {cmd}  — run 'aura help'")
            field.leave()


if __name__ == "__main__":
    main()

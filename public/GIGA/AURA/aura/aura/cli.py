"""
aura.cli — Command-line interface for AURA

Usage:
  aura new   <path>             — scaffold a new node
  aura join  <path>             — join the field
  aura seek  <path> <query>     — seek from this node
  aura who   <path>             — list peers
  aura send  <path> <id> <file> — route a file to a peer
  aura pull  <path> <id> <file> — pull a file from a peer's shared/
  aura talk  <path> <id>        — open a talk session
  aura in    <path>             — list in/ files
  aura shared <path>            — list your shared/ files
  aura ledger <path>            — show intelligence balance
  aura relay                    — run a relay server
  aura api   <path>             — start local HTTP API
  aura init-config              — write default ~/.aura/config.toml
"""

from __future__ import annotations
import argparse
import sys
import os
import time
import json
import signal
import textwrap
from pathlib import Path
from typing import Optional

# ── helpers ───────────────────────────────────────────────────────────────────

def _col(text, code): return f"\033[{code}m{text}\033[0m"
def _green(t):  return _col(t, "32")
def _cyan(t):   return _col(t, "36")
def _yellow(t): return _col(t, "33")
def _red(t):    return _col(t, "31")
def _dim(t):    return _col(t, "2")
def _bold(t):   return _col(t, "1")

LOGO = """
  ▄████▄   ██████  ██▓  ██████   ██████
 ▒██▀ ▀█  ▒██    ▒ ▓██▒▒██    ▒ ▒██    ▒
 ▒▓█    ▄ ░ ▓██▄   ▒██▒░ ▓██▄   ░ ▓██▄
 ▒▓▓▄ ▄██▒  ▒   ██▒░██░  ▒   ██▒  ▒   ██▒
 ▒ ▓███▀ ░▒██████▒▒░██░▒██████▒▒▒██████▒▒
 ░ ░▒ ▒  ░▒ ▒▓▒ ▒ ░░▓  ▒ ▒▓▒ ▒ ░▒ ▒▓▒ ▒ ░
   ░  ▒   ░ ░▒  ░ ░ ▒ ░░ ░▒  ░ ░░ ░▒  ░ ░
 ░        ░  ░  ░   ▒ ░░  ░  ░  ░  ░  ░
 ░ ░            ░   ░        ░        ░
"""


def _header():
    from aura import __version__, __protocol__
    print(_cyan(LOGO))
    print(f"  {_bold('Autonomous Universal Resonance Architecture')}")
    print(f"  v{__version__}  protocol {__protocol__}  {_dim('https://github.com/aethyr-global/aura')}")
    print()


def _field(path: str):
    """Import lazily to keep CLI fast."""
    from aura.field import AuraField
    return AuraField(path)


def _node_path(args) -> str:
    path = getattr(args, "path", None) or "."
    return os.path.expanduser(path)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_new(args):
    from aura.folder import FolderAura
    path = Path(_node_path(args)).expanduser().resolve()
    if path.exists() and any(path.iterdir()):
        choice = input(f"  {path} exists. Continue? [y/N] ").strip().lower()
        if choice != "y":
            sys.exit(0)
    path.mkdir(parents=True, exist_ok=True)
    fa = FolderAura(str(path)).scan()
    fa.ensure_structure()

    name = getattr(args, "name", None) or input(f"  Node name [{path.name}]: ").strip() or path.name
    desc = getattr(args, "desc", None) or input("  Description: ").strip()
    tags = getattr(args, "tags", None) or input("  Tags (comma-separated): ").strip()
    lang = getattr(args, "lang", None) or input("  Language [py/sh/js/rs] (py): ").strip() or "py"

    # write aura.meta
    meta_lines = [
        f"name: {name}",
        f"description: {desc}",
        f"tags: {tags}",
        f"proto: v0.4",
        f"author: {os.environ.get('USER', 'anonymous')}",
    ]
    (path / "aura.meta").write_text("\n".join(meta_lines) + "\n")

    # write entry point
    entries = {
        "py": ("aura.py", _template_py(name, desc)),
        "sh": ("aura.sh", _template_sh(name, desc)),
        "js": ("aura.js", _template_js(name, desc)),
        "rs": ("aura.rs", _template_rs(name, desc)),
    }
    lang_key = lang.lower().lstrip(".")
    entry_name, entry_content = entries.get(lang_key, entries["py"])
    entry_path = path / entry_name
    entry_path.write_text(entry_content)
    if lang_key == "sh":
        entry_path.chmod(0o755)

    # write README
    (path / "README.md").write_text(_template_readme(name, desc, tags, entry_name))

    # write sample shared file
    (path / "shared" / "hello.txt").write_text(
        f"Hi, I'm {name}.\n{desc}\n\nFind me on the AURA field.\n"
    )

    print()
    print(f"  {_green('✓')} Node created at {_bold(str(path))}")
    print(f"  {_dim('id')}   {fa.identity.node_id}")
    print(f"  {_dim('ayr')}  {fa.identity.wallet_addr}")
    print()
    print(f"  Next:  {_cyan('aura join ' + str(path))}")
    print()


def cmd_join(args):
    from aura.field import AuraField
    from aura.api   import AuraAPI
    from aura.config import Config

    path    = _node_path(args)
    channel = getattr(args, "channel", None)
    name    = getattr(args, "name", None)
    no_api  = getattr(args, "no_api", False)

    field = AuraField(path, name=name, channel=channel)
    field.join()

    api_url = ""
    if not no_api and Config().get("api", "enabled", default=True):
        api = AuraAPI(field).start()
        api_url = api.url

    print()
    print(f"  {_green('●')} {_bold(field.name)} joined the field")
    print(f"  {_dim('id')}       {field.node_id}")
    print(f"  {_dim('wallet')}   {field.wallet}")
    print(f"  {_dim('field')}    {field.field_group}:{field.field_port}")
    if channel:
        print(f"  {_dim('channel')}  {channel}")
    if api_url:
        print(f"  {_dim('api')}      {api_url}")
    print()

    # peer join/leave callbacks
    def on_peer(pid, name, summary):
        tags = list((summary.get("tags") or {}).keys())[:4]
        print(f"  {_green('→')} {name}  {_dim(pid)}  {_dim(', '.join(tags))}")

    def on_leave(pid, name):
        print(f"  {_red('←')} {name} left  {_dim(pid)}")

    def on_route(pid, name, fname, score):
        print(f"  {_cyan('↓')} received {_bold(fname)} from {name}")

    field.on_peer(on_peer)
    field.on_leave(on_leave)
    field.on_route(on_route)

    def _shutdown(sig, frame):
        print(f"\n  leaving field...")
        field.leave()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(1)
    except Exception:
        field.leave()


def cmd_seek(args):
    import time as _time
    path  = _node_path(args)
    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    field = _field(path)
    field.join()
    _time.sleep(float(getattr(args, "wait", 2.0)))
    results = field.seek(query)
    _time.sleep(float(getattr(args, "wait", 2.0)))

    print()
    print(f"  seek: {_bold(query)}")
    print()
    if not results:
        print(f"  {_dim('no resonance')}")
    else:
        for r in results:
            score  = r.get("score", 0)
            bar    = "█" * int(score * 12) + _dim("░" * (12 - int(score * 12)))
            tags   = list((r.get("summary", {}).get("tags") or {}).keys())[:5]
            print(f"  {bar}  {_bold(r['name'])}  {_dim(r['node_id'])}")
            if tags:
                print(f"             {_dim(', '.join(tags))}")
        print()
    field.leave()


def cmd_who(args):
    import time as _time
    path  = _node_path(args)
    field = _field(path)
    field.join()
    _time.sleep(2.5)
    peers = field.who()
    print()
    if not peers:
        print(f"  {_dim('no peers found')}")
    else:
        for p in peers:
            tags  = list((p.get("summary", {}).get("tags") or {}).keys())[:6]
            print(f"  {_green('●')} {_bold(p['name'])}  {_dim(p['node_id'])}  {_dim(p.get('addr', ''))}")
            if tags:
                print(f"       {_dim(', '.join(tags))}")
    print()
    field.leave()


def cmd_send(args):
    path   = _node_path(args)
    target = args.target
    file   = args.file
    field  = _field(path)
    field.join()
    time.sleep(2)
    ok, msg = field.route_file(target, file)
    print()
    sym = _green("✓") if ok else _red("✗")
    print(f"  {sym} {msg}")
    print()
    field.leave()


def cmd_pull(args):
    path   = _node_path(args)
    target = args.target
    file   = args.file
    field  = _field(path)
    field.join()
    time.sleep(2)
    dest = field.pull(target, file)
    print()
    if dest:
        print(f"  {_green('✓')} saved to {dest}")
    else:
        print(f"  {_red('✗')} pull failed — check peer ID and filename")
    print()
    field.leave()


def cmd_talk(args):
    path   = _node_path(args)
    target = args.target
    field  = _field(path)
    field.join()
    time.sleep(2)
    print()
    print(f"  talking to {_bold(target)}")
    print(f"  {_dim('ctrl+c to quit')}")
    print()
    import uuid as _uuid
    session = str(_uuid.uuid4())[:6]
    try:
        while True:
            line = input(f"  {_cyan('you')} > ").strip()
            if not line:
                continue
            resp = field.talk(target, line, session)
            if resp:
                print(f"  {_green('them')} > {resp}")
            else:
                print(f"  {_dim('(no response)')}")
    except (KeyboardInterrupt, EOFError):
        pass
    field.leave()


def cmd_in(args):
    path  = _node_path(args)
    from aura.folder import FolderAura
    fa = FolderAura(path).scan()
    files = fa.in_files()
    print()
    if not files:
        print(f"  {_dim('in/ is empty')}")
    else:
        for f in files:
            size = f["size"]
            label = f"{size:,} B" if size < 1024 else f"{size//1024:,} KB"
            print(f"  {_green('↓')} {_bold(f['name'])}  {_dim(label)}")
    print()


def cmd_shared(args):
    path  = _node_path(args)
    from aura.folder import FolderAura
    fa = FolderAura(path).scan()
    files = fa.shared_files()
    print()
    if not files:
        print(f"  {_dim('shared/ is empty')}")
    else:
        for f in files:
            size = f["size"]
            label = f"{size:,} B" if size < 1024 else f"{size//1024:,} KB"
            print(f"  {_cyan('○')} {_bold(f['name'])}  {_dim(label)}")
    print()


def cmd_ledger(args):
    path  = _node_path(args)
    from aura.folder  import FolderAura
    from aura.ledger  import IntelligenceLedger
    fa = FolderAura(path).scan()
    lg = IntelligenceLedger(fa.aura_dir)
    s  = lg.summary()
    print()
    print(f"  {_bold('Intelligence Ledger')}")
    print(f"  {_dim('wallet')}         {fa.identity.wallet_addr}")
    print(f"  {_dim('balance')}        {_green(str(s['balance']))} AYR")
    print(f"  {_dim('total earned')}   {s['total_earned']} AYR")
    print(f"  {_dim('transactions')}   {s['transactions']}")
    if s["by_reason"]:
        print()
        print(f"  {_dim('breakdown:')}")
        for reason, pts in sorted(s["by_reason"].items(), key=lambda x: -x[1]):
            print(f"    {reason:<22} {pts} AYR")
    print()


def cmd_relay(args):
    from aura.relay import main as relay_main
    _header()
    relay_main()


def cmd_api(args):
    from aura.field import AuraField
    from aura.api   import AuraAPI
    path    = _node_path(args)
    port    = getattr(args, "port", 7778)
    field   = AuraField(path)
    field.join()
    api     = AuraAPI(field, port=port).start()
    print()
    print(f"  {_green('●')} API running at {_bold(api.url)}")
    print(f"  {_dim('ctrl+c to quit')}")
    print()
    signal.signal(signal.SIGINT,  lambda s, f: (field.leave(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (field.leave(), sys.exit(0)))
    while True:
        time.sleep(1)


def cmd_init_config(args):
    from aura.config import _CONFIG_DIR, _CONFIG_JSON
    _CONFIG_DIR.mkdir(exist_ok=True)
    default_cfg = {
        "field":    {"group": "239.77.77.77", "port": 7777, "ttl": 8, "relays": []},
        "node":     {"announce_interval": 15, "rescan_interval": 30, "peer_ttl": 90},
        "api":      {"host": "127.0.0.1", "port": 7778, "enabled": True},
        "relay":    {"port": 7779, "max_peers": 512},
        "transfer": {"tcp_port": 7780, "chunk_size": 65536, "timeout": 30},
    }
    _CONFIG_JSON.write_text(json.dumps(default_cfg, indent=2))
    print(f"  {_green('✓')} wrote {_CONFIG_JSON}")


# ── Templates ─────────────────────────────────────────────────────────────────

def _template_py(name, desc):
    return textwrap.dedent(f'''\
        #!/usr/bin/env python3
        """
        {name} — AURA node entry point
        {desc}
        """
        import os
        import sys

        AURA_QUERY   = os.environ.get("AURA_QUERY", "")
        AURA_VISITOR = os.environ.get("AURA_VISITOR", "anonymous")
        AURA_SESSION = os.environ.get("AURA_SESSION", "")
        AURA_IN      = os.environ.get("AURA_IN",  "in")
        AURA_OUT     = os.environ.get("AURA_OUT", "out")
        AURA_SHARED  = os.environ.get("AURA_SHARED", "shared")

        def respond(query: str, visitor: str) -> str:
            """Override this to make the node intelligent."""
            return f"{{visitor}} asked: {{query}}"

        if __name__ == "__main__":
            if AURA_QUERY:
                print(respond(AURA_QUERY, AURA_VISITOR), flush=True)
    ''')


def _template_sh(name, desc):
    return textwrap.dedent(f'''\
        #!/usr/bin/env bash
        # {name} — AURA node entry point
        # {desc}

        QUERY="${{AURA_QUERY:-}}"
        VISITOR="${{AURA_VISITOR:-anonymous}}"
        SESSION="${{AURA_SESSION:-}}"

        respond() {{
            echo "$VISITOR asked: $QUERY"
        }}

        if [ -n "$QUERY" ]; then
            respond
        fi
    ''')


def _template_js(name, desc):
    return textwrap.dedent(f'''\
        #!/usr/bin/env node
        // {name} — AURA node entry point
        // {desc}

        const query   = process.env.AURA_QUERY   || "";
        const visitor = process.env.AURA_VISITOR  || "anonymous";
        const session = process.env.AURA_SESSION  || "";

        function respond(query, visitor) {{
            return `${{visitor}} asked: ${{query}}`;
        }}

        if (query) {{
            process.stdout.write(respond(query, visitor) + "\\n");
        }}
    ''')


def _template_rs(name, desc):
    return textwrap.dedent(f'''\
        // {name} — AURA node entry point
        // {desc}
        use std::env;

        fn respond(query: &str, visitor: &str) -> String {{
            format!("{{}} asked: {{}}", visitor, query)
        }}

        fn main() {{
            let query   = env::var("AURA_QUERY").unwrap_or_default();
            let visitor = env::var("AURA_VISITOR").unwrap_or_else(|_| "anonymous".into());
            if !query.is_empty() {{
                println!("{{}}", respond(&query, &visitor));
            }}
        }}
    ''')


def _template_readme(name, desc, tags, entry):
    return textwrap.dedent(f'''\
        # {name}

        > {desc}

        **Tags:** {tags}

        ## Structure

        ```
        {name}/
        ├── aura.meta     ← identity metadata
        ├── {entry}       ← entry point (receives seeks & talk)
        ├── in/           ← incoming files from the field
        ├── out/          ← files to send (auto-routed)
        ├── shared/       ← files visible to peers
        └── private/      ← never indexed or shared
        ```

        ## Running

        ```bash
        aura join .
        ```

        ## AURA Protocol

        Built on [AURA v0.4](https://github.com/aethyr-global/aura).
        UDP multicast · Ed25519 identity · X25519 encryption · NOT Money
    ''')


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aura",
        description="AURA — Autonomous Universal Resonance Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    # new
    n = sub.add_parser("new", help="Scaffold a new node")
    n.add_argument("path", help="Node folder path")
    n.add_argument("--name"); n.add_argument("--desc")
    n.add_argument("--tags"); n.add_argument("--lang", default="py")

    # join
    j = sub.add_parser("join", help="Join the field")
    j.add_argument("path", nargs="?", default=".")
    j.add_argument("--channel", "-c")
    j.add_argument("--name", "-n")
    j.add_argument("--no-api", action="store_true")

    # seek
    s = sub.add_parser("seek", help="Seek the field")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("query", nargs="+")
    s.add_argument("--wait", type=float, default=2.0)

    # who
    w = sub.add_parser("who", help="List peers")
    w.add_argument("path", nargs="?", default=".")

    # send
    sd = sub.add_parser("send", help="Route a file to a peer")
    sd.add_argument("path", nargs="?", default=".")
    sd.add_argument("target"); sd.add_argument("file")

    # pull
    pl = sub.add_parser("pull", help="Pull a file from a peer's shared/")
    pl.add_argument("path", nargs="?", default=".")
    pl.add_argument("target"); pl.add_argument("file")

    # talk
    tk = sub.add_parser("talk", help="Talk to a peer's entry point")
    tk.add_argument("path", nargs="?", default=".")
    tk.add_argument("target")

    # in
    sub.add_parser("in", help="List in/ files").add_argument("path", nargs="?", default=".")

    # shared
    sub.add_parser("shared", help="List shared/ files").add_argument("path", nargs="?", default=".")

    # ledger
    sub.add_parser("ledger", help="Show intelligence balance").add_argument("path", nargs="?", default=".")

    # relay
    r = sub.add_parser("relay", help="Run a WAN relay server")
    r.add_argument("--host", default="0.0.0.0"); r.add_argument("--port", type=int, default=7779)
    r.add_argument("--max-peers", type=int, default=512)

    # api
    a = sub.add_parser("api", help="Start local HTTP API")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--port", type=int, default=7778)

    # init-config
    sub.add_parser("init-config", help="Write default ~/.aura/config.toml")

    return p


COMMANDS = {
    "new":         cmd_new,
    "join":        cmd_join,
    "seek":        cmd_seek,
    "who":         cmd_who,
    "send":        cmd_send,
    "pull":        cmd_pull,
    "talk":        cmd_talk,
    "in":          cmd_in,
    "shared":      cmd_shared,
    "ledger":      cmd_ledger,
    "relay":       cmd_relay,
    "api":         cmd_api,
    "init-config": cmd_init_config,
}


def main():
    parser = build_parser()
    args   = parser.parse_args()
    if not args.cmd:
        _header()
        parser.print_help()
        sys.exit(0)
    fn = COMMANDS.get(args.cmd)
    if not fn:
        parser.print_help()
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()

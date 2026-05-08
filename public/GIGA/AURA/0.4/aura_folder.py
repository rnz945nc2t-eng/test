"""
aura_folder.py — v0.3
Scans a folder and builds its semantic aura.
Understands in/ out/ shared/ private/ structure.
No apps. No schema. Just reads what's there.
"""

import os
import json
import time
import hashlib
import subprocess
from pathlib import Path
from collections import defaultdict

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization

# ── Entry point detection ─────────────────────────────────────────────────
# Any of these in the root folder = the "front door."
# Any language. AURA figures out the runner.

ENTRY_NAMES = [
    "aura.py","aura.sh","aura.js","aura.rs","aura.go",
    "aura.rb","aura.lua","aura.pl","aura.ex","aura.jl",
    "aura.hs","aura.c","aura.cpp","aura","run","start",
]

RUNNERS = {
    ".py":  ["python3"],
    ".sh":  ["bash"],
    ".js":  ["node"],
    ".rb":  ["ruby"],
    ".lua": ["lua"],
    ".pl":  ["perl"],
    ".jl":  ["julia"],
    ".ex":  ["elixir"],
}

# Folders that are NEVER indexed into the aura
PRIVATE_DIRS = {"private", ".private", "private_", "_private"}

# Folders whose contents are indexed but not routed
SHARED_DIRS  = {"shared", "public"}

# Extension → semantic meaning
EXT_MEANING = {
    ".py":    ["python","code","programming","script"],
    ".js":    ["javascript","code","web","script"],
    ".ts":    ["typescript","code","frontend"],
    ".rs":    ["rust","code","systems","fast"],
    ".go":    ["golang","code","systems","concurrent"],
    ".cpp":   ["c++","code","systems","graphics"],
    ".c":     ["c","code","systems","embedded"],
    ".sh":    ["shell","code","automation","sysadmin"],
    ".md":    ["writing","docs","text","notes"],
    ".txt":   ["writing","text","notes"],
    ".pdf":   ["document","writing","pdf"],
    ".png":   ["image","visual","design","pixel"],
    ".jpg":   ["image","photo","visual"],
    ".svg":   ["vector","design","visual","geometry"],
    ".mp3":   ["audio","music","sound"],
    ".wav":   ["audio","music","sound","raw"],
    ".flac":  ["audio","music","lossless","high-fidelity"],
    ".mp4":   ["video","motion","film"],
    ".blend": ["3d","blender","visual","render","mesh"],
    ".glb":   ["3d","model","scene"],
    ".csv":   ["data","spreadsheet","table","analysis"],
    ".json":  ["data","config","structured"],
    ".sql":   ["database","data","query"],
    ".ipynb": ["notebook","python","data","research","science"],
    ".r":     ["r","statistics","data","science"],
    ".jl":    ["julia","science","math","numerical"],
    ".stl":   ["3d","print","model","fabrication"],
    ".ino":   ["arduino","hardware","embedded","electronics"],
}


class FolderAura:
    """
    Reads a folder. Builds its semantic fingerprint.
    Understands the v0.3 folder structure.
    Never reads private/. Always reads shared/.
    """

    def __init__(self, path: str):
        self.path    = Path(path).expanduser().resolve()
        self.aura_dir = self.path / ".aura"
        self.tags:   dict[str, float] = {}
        self.files:  list[dict]       = []   # shared + root files
        self.meta:   dict             = {}
        self.entry:  Path | None      = None
        self.has_in      = False
        self.has_out     = False
        self.has_shared  = False
        self.has_private = False
        self.in_count    = 0
        self.out_count   = 0
        self.shared_count= 0

    # ── public ───────────────────────────────────────────────────────────

    def scan(self) -> "FolderAura":
        if not self.path.exists():
            raise FileNotFoundError(f"Node folder not found: {self.path}")
        self._ensure_identity()
        self._read_meta()
        self._find_entry()
        self._detect_structure()
        self._walk_root()
        self._walk_shared()
        self._normalize()
        return self

    def resonate(self, query: str) -> float:
        words = [w.lower().strip() for w in query.split() if len(w) > 1]
        if not words:
            return 0.0
        total = 0.0
        for w in words:
            if w in self.tags:
                total += self.tags[w]
            else:
                for tag, weight in self.tags.items():
                    if w in tag or tag in w:
                        total += weight * 0.55
                        break
        return min(1.0, total / max(1, len(words)))

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for f in sorted(self.files, key=lambda x: x["path"]):
            h.update(f["path"].encode())
            h.update(str(f.get("modified", 0)).encode())
        return h.hexdigest()[:12]

    def summary(self) -> dict:
        top = sorted(self.tags.items(), key=lambda x: -x[1])[:16]
        return {
            "name":         self.meta.get("name", self.path.name),
            "path":         str(self.path),
            "description":  self.meta.get("description", ""),
            "tags":         dict(top),
            "file_count":   len(self.files),
            "entry":        self.entry.name if self.entry else None,
            "fingerprint":  self.fingerprint(),
            "structure": {
                "has_in":      self.has_in,
                "has_out":     self.has_out,
                "has_shared":  self.has_shared,
                "has_private": self.has_private,
                "in_count":    self.in_count,
                "out_count":   self.out_count,
                "shared_count":self.shared_count,
            },
        }

    def run_entry(self, env_extra: dict = None) -> subprocess.Popen | None:
        if not self.entry:
            return None
        ext    = self.entry.suffix.lower()
        runner = RUNNERS.get(ext)
        if runner is None:
            if os.access(self.entry, os.X_OK):
                runner = []
            else:
                return None
        env = {
            **os.environ,
            "AURA_NODE":    str(self.path),
            "AURA_IN":      str(self.path / "in"),
            "AURA_OUT":     str(self.path / "out"),
            "AURA_SHARED":  str(self.path / "shared"),
            "AURA_FIELD":   "239.77.77.77:7777",
            **(env_extra or {}),
        }
        return subprocess.Popen(
            runner + [str(self.entry)],
            cwd=str(self.path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    # ── internal ─────────────────────────────────────────────────────────

    def _ensure_identity(self):
        """Ensure .aura/ directory and keys exist."""
        self.aura_dir.mkdir(exist_ok=True)
        key_path = self.aura_dir / "identity.key"
        pub_path = self.aura_dir / "aura.pub"
        x_key_path = self.aura_dir / "encryption.key"
        x_pub_path = self.aura_dir / "encryption.pub"

        if not key_path.exists():
            private_key = ed25519.Ed25519PrivateKey.generate()
            private_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption()
            )
            key_path.write_bytes(private_bytes)

            public_key = private_key.public_key()
            public_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH
            )
            pub_path.write_bytes(public_bytes)

        if not x_key_path.exists():
            x_priv = x25519.X25519PrivateKey.generate()
            x_priv_bytes = x_priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            x_key_path.write_bytes(x_priv_bytes)

            x_pub = x_priv.public_key()
            x_pub_bytes = x_pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            x_pub_path.write_bytes(x_pub_bytes)

    def get_private_key(self):
        key_path = self.aura_dir / "identity.key"
        return serialization.load_ssh_private_key(key_path.read_bytes(), None)

    def get_public_key_bytes(self):
        pub_path = self.aura_dir / "aura.pub"
        # We want raw bytes for the protocol
        key = serialization.load_ssh_public_key(pub_path.read_bytes())
        return key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

    def get_x_private_key(self):
        key_path = self.aura_dir / "encryption.key"
        return serialization.load_pem_private_key(key_path.read_bytes(), None)

    def get_x_public_key_bytes(self):
        pub_path = self.aura_dir / "encryption.pub"
        return pub_path.read_bytes()

    def _read_meta(self):
        meta_path = self.path / "aura.meta"
        if not meta_path.exists():
            return
        for line in meta_path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                self.meta[k.strip().lower()] = v.strip()
        # tags declared in meta carry max weight
        for tag in self.meta.get("tags","").split(","):
            tag = tag.strip().lower()
            if tag:
                self._set(tag, 1.0)
        for word in self.meta.get("description","").lower().split():
            if len(word) > 3:
                self._add(word, 0.3)

    def _find_entry(self):
        for name in ENTRY_NAMES:
            c = self.path / name
            if c.exists():
                self.entry = c
                return

    def _detect_structure(self):
        for item in self.path.iterdir():
            if not item.is_dir():
                continue
            n = item.name.lower()
            if n == "in":
                self.has_in = True
                self.in_count = sum(1 for _ in item.iterdir() if _.is_file())
            elif n == "out":
                self.has_out = True
                self.out_count = sum(1 for _ in item.iterdir() if _.is_file())
            elif n in SHARED_DIRS:
                self.has_shared = True
                self.shared_count = sum(1 for _ in item.iterdir() if _.is_file())
            elif n in PRIVATE_DIRS:
                self.has_private = True
            # index directory name as tag (except private)
            if n not in PRIVATE_DIRS and not n.startswith("."):
                for word in n.replace("_"," ").replace("-"," ").split():
                    if len(word) > 2:
                        self._add(word, 0.3)

    def _walk_root(self):
        for item in self.path.iterdir():
            if item.is_dir():
                continue
            if item.name.startswith("."):
                continue
            if item.name in ("aura.meta","aura.lock"):
                continue
            self._absorb_file(item, weight_scale=1.0)

    def _walk_shared(self):
        shared = self.path / "shared"
        if not shared.exists():
            return
        for item in shared.rglob("*"):
            if item.is_file() and not item.name.startswith("."):
                self._absorb_file(item, weight_scale=0.8)

    def _absorb_file(self, p: Path, weight_scale: float = 1.0):
        stat = p.stat()
        ext  = p.suffix.lower()

        self.files.append({
            "name":     p.name,
            "path":     str(p.relative_to(self.path)),
            "size":     stat.st_size,
            "ext":      ext,
            "modified": stat.st_mtime,
        })

        # filename → tags
        for word in p.stem.lower().replace("_"," ").replace("-"," ").split():
            if len(word) > 2:
                self._add(word, 0.25 * weight_scale)

        # extension → tags
        for tag in EXT_MEANING.get(ext, [ext.lstrip(".")] if ext else []):
            self._add(tag, 0.2 * weight_scale)

        # peek inside text / code files
        text_exts = {".py",".js",".ts",".md",".txt",".sh",".rs",
                     ".go",".cpp",".c",".r",".jl",".json",".lua"}
        if ext in text_exts and stat.st_size < 60_000:
            try:
                content = p.read_text(errors="ignore")[:4000]
                self._keywords(content, weight_scale)
            except Exception:
                pass

    def _keywords(self, text: str, scale: float):
        STOP = {
            "the","and","for","not","with","this","that","from","are","was",
            "has","have","been","will","its","can","but","you","def","import",
            "return","class","self","true","false","none","elif","else","pass",
            "print","open","file","path","str","int","list","dict","type","none",
        }
        freq: dict[str,int] = defaultdict(int)
        for w in text.lower().replace("\n"," ").split():
            w = "".join(c for c in w if c.isalpha())
            if len(w) > 4 and w not in STOP:
                freq[w] += 1
        for word, count in sorted(freq.items(), key=lambda x: -x[1])[:20]:
            self._add(word, min(0.35, count * 0.04) * scale)

    def _set(self, tag: str, v: float):
        self.tags[tag] = max(self.tags.get(tag, 0.0), v)

    def _add(self, tag: str, v: float):
        self.tags[tag] = min(1.0, self.tags.get(tag, 0.0) + v)

    def _normalize(self):
        if not self.tags:
            return
        mx = max(self.tags.values())
        if mx > 0:
            self.tags = {k: round(v / mx, 4) for k, v in self.tags.items()}

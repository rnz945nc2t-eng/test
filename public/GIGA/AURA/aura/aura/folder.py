"""
aura.folder — Folder scanner and semantic fingerprinter

A folder is a node. Its files build the aura.
Reads everything except private/. Indexes shared/ with full weight.
Produces a weighted tag map used for seek resonance scoring.
"""

from __future__ import annotations
import os
import hashlib
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .crypto import Identity

# ── Entry point detection ─────────────────────────────────────────────────────

ENTRY_NAMES = [
    "aura.py", "aura.sh", "aura.js", "aura.ts", "aura.rs",
    "aura.go", "aura.rb", "aura.lua", "aura.pl", "aura.ex",
    "aura.jl", "aura.hs", "aura.c",  "aura.cpp","aura",
    "run",     "start",   "main.py", "main.sh", "main.js",
]

RUNNERS: Dict[str, List[str]] = {
    ".py":  ["python3"],
    ".sh":  ["bash"],
    ".js":  ["node"],
    ".ts":  ["npx", "ts-node"],
    ".rb":  ["ruby"],
    ".lua": ["lua"],
    ".pl":  ["perl"],
    ".jl":  ["julia"],
    ".ex":  ["elixir"],
    ".hs":  ["runhaskell"],
}

PRIVATE_DIRS = {"private", ".private", "private_", "_private"}
SHARED_DIRS  = {"shared", "public"}
SKIP_DIRS    = {".git", ".aura", "node_modules", "__pycache__", ".venv", "venv"}

# ── Extension → semantic tags ─────────────────────────────────────────────────

EXT_TAGS: Dict[str, List[str]] = {
    ".py":    ["python", "code", "script"],
    ".js":    ["javascript", "code", "web"],
    ".ts":    ["typescript", "code", "frontend"],
    ".rs":    ["rust", "code", "systems"],
    ".go":    ["golang", "code", "systems"],
    ".cpp":   ["c++", "code", "systems"],
    ".c":     ["c", "code", "systems"],
    ".sh":    ["shell", "automation", "script"],
    ".rb":    ["ruby", "code", "script"],
    ".lua":   ["lua", "code", "scripting"],
    ".jl":    ["julia", "science", "math"],
    ".hs":    ["haskell", "functional", "code"],
    ".ex":    ["elixir", "code", "concurrent"],
    ".md":    ["writing", "docs", "markdown"],
    ".txt":   ["writing", "text", "notes"],
    ".rst":   ["writing", "docs"],
    ".pdf":   ["document", "writing", "pdf"],
    ".png":   ["image", "visual", "design"],
    ".jpg":   ["image", "photo", "visual"],
    ".jpeg":  ["image", "photo", "visual"],
    ".gif":   ["image", "animation"],
    ".svg":   ["vector", "design", "visual"],
    ".webp":  ["image", "visual"],
    ".mp3":   ["audio", "music", "sound"],
    ".wav":   ["audio", "sound", "raw"],
    ".flac":  ["audio", "music", "lossless"],
    ".ogg":   ["audio", "music"],
    ".mp4":   ["video", "film"],
    ".mov":   ["video", "film"],
    ".blend": ["3d", "blender", "render"],
    ".glb":   ["3d", "model", "scene"],
    ".stl":   ["3d", "print", "fabrication"],
    ".obj":   ["3d", "model"],
    ".csv":   ["data", "spreadsheet", "analysis"],
    ".json":  ["data", "config", "structured"],
    ".yaml":  ["data", "config"],
    ".toml":  ["data", "config"],
    ".sql":   ["database", "query"],
    ".ipynb": ["notebook", "python", "data", "science"],
    ".r":     ["r", "statistics", "data"],
    ".ino":   ["arduino", "hardware", "embedded"],
    ".sol":   ["solidity", "blockchain", "smart-contract"],
}

TEXT_EXTS = {
    ".py", ".js", ".ts", ".md", ".txt", ".sh", ".rs", ".go",
    ".cpp", ".c", ".rb", ".lua", ".json", ".yaml", ".toml",
    ".r", ".jl", ".ex", ".hs", ".sql", ".rst",
}

STOP_WORDS = {
    "the", "and", "for", "not", "with", "this", "that", "from", "are", "was",
    "has", "have", "been", "will", "its", "can", "but", "you", "def", "import",
    "return", "class", "self", "true", "false", "none", "elif", "else", "pass",
    "print", "open", "file", "path", "str", "int", "list", "dict", "type",
    "func", "var", "let", "const", "new", "null", "void", "public", "private",
    "static", "extern", "use", "mod", "impl", "struct", "enum", "trait",
}


class FolderAura:
    """
    Reads a folder. Builds its semantic aura.
    Understands the AURA folder structure.
    """

    def __init__(self, path: str | Path):
        self.path       = Path(path).expanduser().resolve()
        self.aura_dir   = self.path / ".aura"
        self.identity   = Identity(self.aura_dir)
        self.tags:      Dict[str, float] = {}
        self.files:     List[dict]       = []
        self.meta:      Dict[str, str]   = {}
        self.entry:     Optional[Path]   = None
        # structure
        self.has_in      = False
        self.has_out     = False
        self.has_shared  = False
        self.has_private = False
        self.in_count    = 0
        self.out_count   = 0
        self.shared_count= 0

    # ── public ───────────────────────────────────────────────────────────────

    def scan(self) -> "FolderAura":
        if not self.path.exists():
            raise FileNotFoundError(f"Node folder not found: {self.path}")
        self._read_meta()
        self._find_entry()
        self._detect_structure()
        self._walk_root()
        self._walk_shared()
        self._normalize()
        return self

    def resonate(self, query: str) -> float:
        """Score this folder's resonance with a query string. Returns 0.0–1.0."""
        words = [w.lower().strip(".,!?") for w in query.split() if len(w) > 1]
        if not words:
            return 0.0
        total = 0.0
        for w in words:
            if w in self.tags:
                total += self.tags[w]
            else:
                for tag, weight in self.tags.items():
                    if w in tag or tag in w:
                        total += weight * 0.5
                        break
        return min(1.0, total / max(1, len(words)))

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for f in sorted(self.files, key=lambda x: x["path"]):
            h.update(f["path"].encode())
            h.update(str(f.get("modified", 0)).encode())
        return h.hexdigest()[:12]

    def summary(self) -> dict:
        top = dict(sorted(self.tags.items(), key=lambda x: -x[1])[:20])
        return {
            "name":        self.meta.get("name", self.path.name),
            "path":        str(self.path),
            "description": self.meta.get("description", ""),
            "tags":        top,
            "file_count":  len(self.files),
            "entry":       self.entry.name if self.entry else None,
            "fingerprint": self.fingerprint(),
            "structure": {
                "has_in":       self.has_in,
                "has_out":      self.has_out,
                "has_shared":   self.has_shared,
                "has_private":  self.has_private,
                "in_count":     self.in_count,
                "out_count":    self.out_count,
                "shared_count": self.shared_count,
            },
        }

    def run_entry(self, env_extra: Optional[dict] = None) -> Optional[subprocess.Popen]:
        if not self.entry:
            return None
        ext    = self.entry.suffix.lower()
        runner = RUNNERS.get(ext, [])
        if not runner and not os.access(self.entry, os.X_OK):
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
            cwd=str(self.path), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )

    # ── internal ─────────────────────────────────────────────────────────────

    def _read_meta(self):
        meta_path = self.path / "aura.meta"
        if not meta_path.exists():
            return
        for line in meta_path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, _, v = line.partition(":")
                self.meta[k.strip().lower()] = v.strip()
        for tag in self.meta.get("tags", "").split(","):
            tag = tag.strip().lower()
            if tag:
                self._set(tag, 1.0)
        for word in self.meta.get("description", "").lower().split():
            word = word.strip(".,!?")
            if len(word) > 3 and word not in STOP_WORDS:
                self._add(word, 0.3)

    def _find_entry(self):
        for name in ENTRY_NAMES:
            cand = self.path / name
            if cand.exists():
                self.entry = cand
                return

    def _detect_structure(self):
        for item in self.path.iterdir():
            if not item.is_dir():
                continue
            n = item.name.lower()
            if n in SKIP_DIRS:
                continue
            if n == "in":
                self.has_in     = True
                self.in_count   = sum(1 for _ in item.iterdir() if _.is_file())
            elif n == "out":
                self.has_out    = True
                self.out_count  = sum(1 for _ in item.iterdir() if _.is_file())
            elif n in SHARED_DIRS:
                self.has_shared    = True
                self.shared_count  = sum(1 for _ in item.rglob("*") if _.is_file())
            elif n in PRIVATE_DIRS:
                self.has_private   = True
                continue  # never index private/
            if n not in PRIVATE_DIRS and not n.startswith("."):
                for word in n.replace("_", " ").replace("-", " ").split():
                    if len(word) > 2:
                        self._add(word, 0.25)

    def _walk_root(self):
        for item in self.path.iterdir():
            if item.is_dir():
                continue
            if item.name.startswith("."):
                continue
            if item.name in ("aura.meta", "aura.lock"):
                continue
            self._absorb(item, 1.0)

    def _walk_shared(self):
        shared = self.path / "shared"
        if shared.exists():
            for item in shared.rglob("*"):
                if item.is_file() and not item.name.startswith("."):
                    self._absorb(item, 0.85)

    def _absorb(self, p: Path, scale: float):
        try:
            stat = p.stat()
        except OSError:
            return
        ext = p.suffix.lower()
        self.files.append({
            "name":     p.name,
            "path":     str(p.relative_to(self.path)),
            "size":     stat.st_size,
            "ext":      ext,
            "modified": stat.st_mtime,
        })
        for word in p.stem.lower().replace("_", " ").replace("-", " ").split():
            if len(word) > 2 and word not in STOP_WORDS:
                self._add(word, 0.22 * scale)
        for tag in EXT_TAGS.get(ext, [ext.lstrip(".")][:1] if ext else []):
            self._add(tag, 0.18 * scale)
        if ext in TEXT_EXTS and stat.st_size < 80_000:
            try:
                self._keywords(p.read_text(errors="ignore")[:5000], scale)
            except Exception:
                pass

    def _keywords(self, text: str, scale: float):
        freq: Dict[str, int] = defaultdict(int)
        for w in text.lower().split():
            w = "".join(c for c in w if c.isalpha())
            if len(w) > 4 and w not in STOP_WORDS:
                freq[w] += 1
        for word, count in sorted(freq.items(), key=lambda x: -x[1])[:25]:
            self._add(word, min(0.32, count * 0.04) * scale)

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

    # ── convenience ──────────────────────────────────────────────────────────

    def ensure_structure(self):
        """Create in/ out/ shared/ private/ if missing."""
        for d in ("in", "out", "shared", "private"):
            (self.path / d).mkdir(exist_ok=True)

    def write_lock(self, node_id: str, name: str, field: str, channel: Optional[str], pid: int):
        import json as _json
        (self.path / "aura.lock").write_text(_json.dumps({
            "node_id": node_id, "name": name, "pid": pid,
            "started": time.time(), "field": field,
            "channel": channel, "proto": "v0.4",
        }, indent=2))

    def clear_lock(self):
        (self.path / "aura.lock").unlink(missing_ok=True)

    def in_files(self) -> List[dict]:
        d = self.path / "in"
        if not d.exists():
            return []
        return [
            {"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime}
            for f in sorted(d.iterdir(), key=lambda x: -x.stat().st_mtime)
            if f.is_file()
        ]

    def shared_files(self) -> List[dict]:
        d = self.path / "shared"
        if not d.exists():
            return []
        return [
            {"name": f.name, "size": f.stat().st_size, "path": str(f)}
            for f in sorted(d.rglob("*"))
            if f.is_file()
        ]

"""
aura.config — Configuration management

Config is loaded from (in priority order):
  1. Environment variables (AURA_*)
  2. ~/.aura/config.toml
  3. Defaults

Example ~/.aura/config.toml:
  [field]
  group   = "239.77.77.77"
  port    = 7777
  ttl     = 8
  relays  = ["relay.aethyr-global.com:7779"]

  [node]
  announce_interval = 15
  rescan_interval   = 30

  [api]
  host = "127.0.0.1"
  port = 7778
  enabled = true

  [relay]
  port    = 7779
  max_peers = 512
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib                  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib     # pip install tomli
    except ImportError:
        tomllib = None              # fallback: JSON only


_DEFAULTS: Dict[str, Any] = {
    "field": {
        "group":   "239.77.77.77",
        "port":    7777,
        "ttl":     8,
        "relays":  [],
    },
    "node": {
        "announce_interval": 15,
        "rescan_interval":   30,
        "peer_ttl":          90,        # drop peers not seen in N seconds
        "seek_timeout":      2.0,
    },
    "api": {
        "host":    "127.0.0.1",
        "port":    7778,
        "enabled": True,
    },
    "relay": {
        "port":      7779,
        "max_peers": 512,
        "log":       True,
    },
    "transfer": {
        "tcp_port":   7780,            # base port for TCP file transfer
        "chunk_size": 65536,           # 64 KB per chunk
        "timeout":    30,
    },
}

_CONFIG_DIR  = Path.home() / ".aura"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"
_CONFIG_JSON = _CONFIG_DIR / "config.json"   # fallback


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_file() -> dict:
    if _CONFIG_FILE.exists():
        if tomllib is not None:
            try:
                with open(_CONFIG_FILE, "rb") as f:
                    return tomllib.load(f)
            except Exception:
                pass
    if _CONFIG_JSON.exists():
        try:
            return json.loads(_CONFIG_JSON.read_text())
        except Exception:
            pass
    return {}


def _load_env() -> dict:
    result: dict = {}
    mappings = {
        "AURA_FIELD_GROUP":   ("field", "group"),
        "AURA_FIELD_PORT":    ("field", "port"),
        "AURA_FIELD_RELAYS":  ("field", "relays"),
        "AURA_API_PORT":      ("api",   "port"),
        "AURA_API_ENABLED":   ("api",   "enabled"),
        "AURA_RELAY_PORT":    ("relay", "port"),
        "AURA_TCP_PORT":      ("transfer", "tcp_port"),
    }
    for env_key, (section, key) in mappings.items():
        val = os.environ.get(env_key)
        if val is None:
            continue
        if section not in result:
            result[section] = {}
        # type coercion
        if key in ("port", "ttl", "max_peers", "tcp_port"):
            try:
                result[section][key] = int(val)
            except ValueError:
                pass
        elif key == "enabled":
            result[section][key] = val.lower() in ("1", "true", "yes")
        elif key == "relays":
            result[section][key] = [r.strip() for r in val.split(",") if r.strip()]
        else:
            result[section][key] = val
    return result


class Config:
    """
    Singleton-like configuration object.
    Access values like: Config().field.port
    """
    _instance: Optional["Config"] = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        merged = _DEFAULTS.copy()
        merged = _deep_merge(merged, _load_file())
        merged = _deep_merge(merged, _load_env())
        self._data = merged

    def reload(self):
        self._load()

    def get(self, *path: str, default: Any = None) -> Any:
        node = self._data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def __getattr__(self, name: str) -> "_Section":
        if name.startswith("_"):
            raise AttributeError(name)
        return _Section(self._data.get(name, {}))

    def save(self):
        """Write current config to ~/.aura/config.json (always works, no deps)."""
        _CONFIG_DIR.mkdir(exist_ok=True)
        _CONFIG_JSON.write_text(json.dumps(self._data, indent=2))

    @classmethod
    def reset(cls):
        cls._instance = None


class _Section:
    __slots__ = ("_data",)

    def __init__(self, data: dict):
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        return object.__getattribute__(self, "_data").get(name)

    def __repr__(self) -> str:
        return f"Section({object.__getattribute__(self, '_data')})"

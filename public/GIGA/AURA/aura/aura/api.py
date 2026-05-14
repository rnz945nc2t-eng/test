"""
aura.api — Local HTTP REST API

Exposes your AURA node over HTTP on 127.0.0.1:7778.
Useful for integrations, scripts, and local tooling.

Endpoints:
  GET  /status           — node status (name, node_id, wallet, balance)
  GET  /peers            — list of known peers
  POST /seek             — seek the field { "query": "..." }
  GET  /shared           — list your shared/ files
  GET  /in               — list your in/ files
  POST /route            — route a file { "target": "node_id", "file": "/path/to/file" }
  POST /pull             — pull a file   { "target": "node_id", "file": "name.ext" }
  GET  /ledger           — intelligence points summary
  GET  /health           — health check → { "ok": true }

All responses are JSON. The API is localhost-only by default.
"""

from __future__ import annotations
import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .field import AuraField

from .config import Config


def _json(obj) -> bytes:
    return json.dumps(obj, default=str, indent=2).encode()


class _Handler(BaseHTTPRequestHandler):
    field: "AuraField"

    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _ok(self, body: dict, status: int = 200):
        data = _json(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, msg: str, status: int = 400):
        self._ok({"error": msg}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        try:
            if path in ("/", "/health"):
                self._ok({"ok": True, "node_id": self.field.node_id})
            elif path == "/status":
                self._status()
            elif path == "/peers":
                self._ok({"peers": self.field.peers_list()})
            elif path == "/shared":
                self._ok({"files": self.field.shared_files()})
            elif path == "/in":
                self._ok({"files": self.field.in_files()})
            elif path == "/ledger":
                self._ok(self.field.ledger.summary())
            else:
                self._err("not found", 404)
        except Exception as e:
            self._err(str(e), 500)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()
        try:
            if path == "/seek":
                query = body.get("query", "")
                if not query:
                    return self._err("query required")
                results = self.field.seek(query)
                self._ok({"results": results, "count": len(results)})
            elif path == "/route":
                target = body.get("target", "")
                file   = body.get("file", "")
                if not target or not file:
                    return self._err("target and file required")
                ok, msg = self.field.route_file(target, file)
                self._ok({"ok": ok, "message": msg})
            elif path == "/pull":
                target = body.get("target", "")
                file   = body.get("file", "")
                if not target or not file:
                    return self._err("target and file required")
                dest = self.field.pull(target, file)
                if dest:
                    self._ok({"ok": True, "dest": dest})
                else:
                    self._err("pull failed — peer or file not found", 404)
            elif path == "/talk":
                target = body.get("target", "")
                line   = body.get("line", "")
                if not target or not line:
                    return self._err("target and line required")
                resp = self.field.talk(target, line)
                self._ok({"response": resp})
            else:
                self._err("not found", 404)
        except Exception as e:
            traceback.print_exc()
            self._err(str(e), 500)

    def _status(self):
        s = self.field.folder.summary()
        self._ok({
            "node_id":    self.field.node_id,
            "wallet":     self.field.wallet,
            "name":       self.field.name,
            "channel":    self.field.channel,
            "field":      f"{self.field.field_group}:{self.field.field_port}",
            "aura":       s["tags"],
            "file_count": s["file_count"],
            "structure":  s["structure"],
            "balance":    self.field.ledger.balance,
            "peers":      len(self.field.peers_list()),
            "uptime":     round(time.time() - _API_START, 1),
        })


_API_START = time.time()


class AuraAPI:
    """
    Local HTTP API server for an AURA node.
    Runs in a daemon thread — call start() after AuraField.join().
    """

    def __init__(self, field: "AuraField", host: str = "127.0.0.1", port: int = 7778):
        cfg       = Config()
        self.host = host or cfg.get("api", "host", default="127.0.0.1")
        self.port = port or cfg.get("api", "port", default=7778)
        self.field = field
        self._server: Optional[HTTPServer] = None

    def start(self) -> "AuraAPI":
        handler = type("Handler", (_Handler,), {"field": self.field})
        try:
            self._server = HTTPServer((self.host, self.port), handler)
            threading.Thread(
                target=self._server.serve_forever,
                daemon=True, name="aura.api",
            ).start()
        except OSError as e:
            import logging
            logging.getLogger("aura.api").warning(f"API failed to start: {e}")
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

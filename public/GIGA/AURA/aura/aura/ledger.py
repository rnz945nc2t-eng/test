"""
aura.ledger — Intelligence Ledger (NOT Money)

Intelligence points are earned by:
  - Responding to seeks with high resonance
  - Having peers pull files from your shared/
  - Receiving routed files (you are useful)
  - Hosting relay connections (you are infrastructure)

NOT Money is never transferred — it is earned in place.
The ledger is persisted to .aura/ledger.json.
"""

from __future__ import annotations
import json
import time
import threading
from pathlib import Path
from typing import List, Dict, Any


class Transaction:
    __slots__ = ("ts", "points", "reason", "peer_id")

    def __init__(self, points: float, reason: str, peer_id: str = ""):
        self.ts      = time.time()
        self.points  = round(points, 6)
        self.reason  = reason
        self.peer_id = peer_id

    def to_dict(self) -> dict:
        return {
            "ts":      self.ts,
            "points":  self.points,
            "reason":  self.reason,
            "peer_id": self.peer_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        t = cls.__new__(cls)
        t.ts      = d.get("ts", 0.0)
        t.points  = d.get("points", 0.0)
        t.reason  = d.get("reason", "")
        t.peer_id = d.get("peer_id", "")
        return t


class IntelligenceLedger:
    """
    Persistent, thread-safe intelligence point ledger.

    Earn rules (approximate):
      seek_resonance > 0.8  →  0.5 pts
      seek_resonance > 0.5  →  (score - 0.5) * 2.0 pts
      file pulled by peer   →  0.2 pts per pull
      file routed to you    →  0.1 pts received
      relay connection      →  0.05 pts per routed packet
    """

    MAX_HISTORY = 200

    def __init__(self, aura_dir: Path):
        self._path  = Path(aura_dir) / "ledger.json"
        self._lock  = threading.Lock()
        self._data  = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {"balance": 0.0, "total_earned": 0.0, "history": []}

    def _save(self):
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self._path)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def credit(self, points: float, reason: str, peer_id: str = "") -> None:
        if points <= 0:
            return
        with self._lock:
            self._data["balance"]      = round(self._data["balance"] + points, 6)
            self._data["total_earned"] = round(self._data.get("total_earned", 0) + points, 6)
            tx = Transaction(points, reason, peer_id)
            self._data.setdefault("history", []).append(tx.to_dict())
            if len(self._data["history"]) > self.MAX_HISTORY:
                self._data["history"] = self._data["history"][-self.MAX_HISTORY:]
            self._save()

    @property
    def balance(self) -> float:
        return self._data.get("balance", 0.0)

    @property
    def total_earned(self) -> float:
        return self._data.get("total_earned", 0.0)

    @property
    def history(self) -> List[dict]:
        return list(self._data.get("history", []))

    def summary(self) -> dict:
        hist = self.history
        by_reason: Dict[str, float] = {}
        for tx in hist:
            r = tx["reason"].split(":")[0]
            by_reason[r] = round(by_reason.get(r, 0) + tx["points"], 4)
        return {
            "balance":      self.balance,
            "total_earned": self.total_earned,
            "transactions": len(hist),
            "by_reason":    by_reason,
        }

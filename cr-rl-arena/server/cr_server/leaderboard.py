"""Persistent leaderboard: per-agent Elo rating and W/L/D record.

Stored as a single JSON file so it is trivial to inspect, back up, or serve.
Ratings persist across reconnects keyed by agent name.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field

from . import elo


@dataclass
class Record:
    name: str
    rating: float = elo.START_RATING
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws


class Leaderboard:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.records: dict[str, Record] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                raw = json.load(open(self.path))
                for r in raw.get("records", []):
                    self.records[r["name"]] = Record(**r)
            except (json.JSONDecodeError, TypeError, KeyError):
                pass  # start fresh on a corrupt file rather than crash the server

    def _save(self):
        data = {"records": [asdict(r) for r in self.records.values()]}
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)  # atomic

    def get(self, name: str) -> Record:
        if name not in self.records:
            self.records[name] = Record(name=name)
        return self.records[name]

    def report(self, a: str, b: str, score_a: float):
        """Record a result (score_a: 1 A-win, 0.5 draw, 0 B-win) and update Elo."""
        with self._lock:
            ra, rb = self.get(a), self.get(b)
            ra.rating, rb.rating, delta = elo.update(ra.rating, rb.rating, score_a)
            if score_a == 1.0:
                ra.wins += 1; rb.losses += 1
            elif score_a == 0.0:
                ra.losses += 1; rb.wins += 1
            else:
                ra.draws += 1; rb.draws += 1
            self._save()
            return delta

    def standings(self) -> list[dict]:
        with self._lock:
            rows = sorted(self.records.values(), key=lambda r: -r.rating)
            return [
                {"rank": i + 1, "name": r.name, "rating": round(r.rating, 1),
                 "wins": r.wins, "losses": r.losses, "draws": r.draws, "games": r.games}
                for i, r in enumerate(rows)
            ]

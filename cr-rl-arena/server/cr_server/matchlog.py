"""Match log and the public standings snapshot shown on the web page.

The leaderboard file holds each agent's current rating and W/L/D. The page also
needs things that file can't answer: who played whom recently, how a rating
moved over time, an agent's last few results. Those come from a match log —
one JSON line per finished match in ``<data>/matches.jsonl`` — which this module
appends to and folds into small per-agent summaries kept in memory.

Each log entry also names the replay file for that match, so a match id from the
page maps to a file on disk without ever building a path from user input.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque

HISTORY = 60        # rating points kept per agent for the trend chart
RECENT = 6          # an agent's last few matches, shown when its row is expanded
FEED = 30           # matches in the public results feed
MOVE_WINDOW = 30    # rank movement is measured against this many matches ago
UPSET_GAP = 60.0    # a win by the side rated this much lower counts as an upset


class _Agent:
    __slots__ = ("history", "results", "recent", "peak", "last_delta", "deck", "games",
                 "moves", "ignored")

    def __init__(self):
        self.history = deque(maxlen=HISTORY)
        self.results = deque(maxlen=5)
        self.recent = deque(maxlen=RECENT)
        self.peak = None
        self.last_delta = None
        self.deck = None
        self.games = 0
        self.moves = 0        # moves this agent tried to make, all matches
        self.ignored = 0      # ...of which this many did nothing


class MatchLog:
    def __init__(self, data_dir: str):
        self.replays_dir = os.path.join(data_dir, "replays")
        self.path = os.path.join(data_dir, "matches.jsonl")
        self.matches: list[dict] = []          # chronological
        self.by_id: dict[int, dict] = {}
        self.agents: dict[str, _Agent] = {}
        self._lock = threading.Lock()
        os.makedirs(self.replays_dir, exist_ok=True)
        self._load()

    # ---- loading -----------------------------------------------------------
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        int(e["id"]), e["p0"], e["p1"]
                    except (ValueError, KeyError, TypeError):
                        continue   # a torn last line must not take the server down
                    self._apply(e)
        else:
            self._backfill()

    def _backfill(self):
        """First start with this log: index replay files saved by older versions.

        Those files carry no rating information, so their entries have no delta
        and contribute to results but not to the rating charts.
        """
        try:
            names = sorted(n for n in os.listdir(self.replays_dir) if n.endswith(".json"))
        except OSError:
            names = []
        for n in names:
            try:
                with open(os.path.join(self.replays_dir, n)) as f:
                    r = json.load(f)
                at = int(n.split("_", 1)[0])
                e = {
                    "id": len(self.matches) + 1, "at": at, "p0": r["p0"], "p1": r["p1"],
                    "outcome": int(r["outcome"]), "crowns": list(r["crowns"]),
                    "ticks": int(r["ticks"]), "delta": None, "r0": None, "r1": None,
                    "upset": False, "forfeit": False,
                    "deck0": r.get("deck0"), "deck1": r.get("deck1"), "file": n,
                }
            except (OSError, ValueError, KeyError, TypeError):
                continue
            self._append(e)
            self._apply(e)

    # ---- writing -----------------------------------------------------------
    def next_id(self) -> int:
        return (self.matches[-1]["id"] + 1) if self.matches else 1

    def _append(self, e: dict):
        with open(self.path, "a") as f:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")

    def add(self, e: dict) -> dict:
        """Record a finished match (entry built by the server) and fold it in."""
        with self._lock:
            self._append(e)
            self._apply(e)
        return e

    def _apply(self, e: dict):
        self.matches.append(e)
        self.by_id[int(e["id"])] = e
        out, crowns, delta = e["outcome"], e["crowns"], e.get("delta")
        for seat, name in ((0, e["p0"]), (1, e["p1"])):
            a = self.agents.setdefault(name, _Agent())
            res = "D" if out == 3 else ("W" if out == seat + 1 else "L")
            mine = None if delta is None else (delta if seat == 0 else -delta)
            rating = e.get("r0" if seat == 0 else "r1")
            a.games += 1
            a.moves += (e.get("moves") or [0, 0])[seat]
            a.ignored += (e.get("ignored") or [0, 0])[seat]
            a.results.append(res)
            a.last_delta = mine
            if rating is not None:
                if not a.history and mine is not None:
                    a.history.append(round(rating - mine, 1))   # where it started
                a.history.append(rating)
                a.peak = rating if a.peak is None else max(a.peak, rating)
            deck = e.get("deck0" if seat == 0 else "deck1")
            if deck:
                a.deck = deck
            a.recent.appendleft({
                "id": e["id"], "opp": e["p1"] if seat == 0 else e["p0"], "res": res,
                "mine": crowns[seat], "theirs": crowns[1 - seat], "delta": mine,
            })

    # ---- reading -----------------------------------------------------------
    def replay_path(self, match_id: int) -> str | None:
        e = self.by_id.get(match_id)
        if not e or not e.get("file"):
            return None
        # `file` was written by this server, never taken from a request; keep it
        # inside the replays directory regardless.
        p = os.path.join(self.replays_dir, os.path.basename(e["file"]))
        return p if os.path.isfile(p) else None

    def _moves(self, standings: list[dict]) -> dict[str, int]:
        """Rank change per agent compared with MOVE_WINDOW matches ago."""
        then = {r["name"]: r["rating"] for r in standings}
        seen: set[str] = set()
        for e in reversed(self.matches[-MOVE_WINDOW:]):
            d = e.get("delta")
            if d is None:
                continue
            for name, rating, mine in ((e["p0"], e.get("r0"), d), (e["p1"], e.get("r1"), -d)):
                if rating is not None and name in then:
                    then[name] = rating - mine   # ends as the rating before its first match in the window
                    seen.add(name)
        if not seen:
            return {}
        old = sorted(then, key=lambda n: -then[n])
        old_rank = {n: i + 1 for i, n in enumerate(old)}
        return {r["name"]: old_rank[r["name"]] - r["rank"] for r in standings}

    def snapshot(self, standings: list[dict], online: set[str], live: int) -> dict:
        """Everything the standings page needs, as one JSON-ready dict."""
        with self._lock:
            moves = self._moves(standings)
            rows = []
            for r in standings:
                a = self.agents.get(r["name"]) or _Agent()
                games = r["games"]
                results = list(a.results)
                streak = 0
                for res in reversed(results):
                    if res != results[-1]:
                        break
                    streak += 1
                rows.append({
                    **r,
                    "move": moves.get(r["name"], 0),
                    "winPct": (r["wins"] / games) if games else 0.0,
                    "lastDelta": a.last_delta,
                    "form": results,
                    "streak": {"kind": results[-1] if results else None, "n": streak},
                    "history": list(a.history),
                    "peak": a.peak if a.peak is not None else r["rating"],
                    "deck": a.deck,
                    "recent": list(a.recent),
                    "moves": a.moves, "ignored": a.ignored,
                    "online": r["name"] in online,
                })
            feed = [{
                "id": e["id"], "at": e["at"], "p0": e["p0"], "p1": e["p1"],
                "outcome": e["outcome"], "crowns": e["crowns"], "ticks": e["ticks"],
                "delta": e.get("delta"), "upset": bool(e.get("upset")),
                "forfeit": bool(e.get("forfeit")), "replay": bool(e.get("file")),
            } for e in reversed(self.matches[-FEED:])]
            return {
                "rows": rows, "matches": feed,
                "stats": {"online": len(online), "live": live, "played": len(self.matches)},
                "now": int(time.time() * 1000),
            }

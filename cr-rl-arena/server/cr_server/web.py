"""HTTP side of the server: the standings page, its data, and match replays.

Served from the same port as the agent WebSocket (hosts like Railway expose one
port per service). A request that asks for a WebSocket upgrade is left alone and
becomes an agent connection; any other GET is answered here.

Routes
    /                     the standings page
    /replay?id=N          the replay viewer
    /api/standings        standings, recent results and live counts (JSON)
    /api/replay/N         frame-by-frame trace of match N (JSON, re-simulated)
    /healthz              liveness probe
"""
from __future__ import annotations

import asyncio
import gzip
import http
import json
import os
import re
from collections import OrderedDict

import cr_sim
from websockets.datastructures import Headers
from websockets.http11 import Response

from . import match

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PAGES = {"/": "index.html", "/replay": "replay.html"}
REPLAY_RE = re.compile(r"^/api/replay/(\d{1,12})$")
TRACE_CACHE = 24            # most-recently-watched traces kept (gzipped) in memory
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _response(status, body: bytes, ctype: str, *, gz=False, cache="no-store", already_gz=False):
    h = Headers()
    if already_gz:
        h["Content-Encoding"] = "gzip"
    elif gz and len(body) > 1024:
        body = gzip.compress(body, 6)
        h["Content-Encoding"] = "gzip"
    h["Content-Type"] = ctype
    h["Content-Length"] = str(len(body))
    h["Cache-Control"] = cache
    h["Vary"] = "Accept-Encoding"
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "no-referrer"
    if ctype.startswith("text/html"):
        h["Content-Security-Policy"] = CSP
    h["Connection"] = "close"
    st = http.HTTPStatus(status)
    return Response(st.value, st.phrase, h, body)


def _json(status, obj, **kw):
    return _response(status, json.dumps(obj, separators=(",", ":")).encode(),
                     "application/json; charset=utf-8", **kw)


class Web:
    def __init__(self, arena):
        self.arena = arena
        self._traces: OrderedDict[int, bytes] = OrderedDict()   # id -> gzipped JSON
        self._building: dict[int, asyncio.Future] = {}

    async def process_request(self, connection, request):
        """websockets hook: return None to proceed with a WebSocket handshake."""
        if "websocket" in request.headers.get("Upgrade", "").lower():
            return None
        gz = "gzip" in request.headers.get("Accept-Encoding", "").lower()
        path = request.path.split("?", 1)[0]
        try:
            if path in PAGES:
                with open(os.path.join(WEB_DIR, PAGES[path]), "rb") as f:
                    return _response(200, f.read(), "text/html; charset=utf-8", gz=gz, cache="no-cache")
            if path == "/api/standings":
                return _json(200, self.arena.standings_snapshot(), gz=gz)
            if path == "/healthz":
                return _response(200, b"ok\n", "text/plain; charset=utf-8")
            m = REPLAY_RE.match(path)
            if m:
                return await self._replay(int(m.group(1)), gz)
            return _json(404, {"error": "not found"})
        except Exception as e:  # a bad request must never take the server down
            print(f"[web error] {path}: {e!r}")
            return _json(500, {"error": "internal error"})

    async def _replay(self, match_id: int, gz: bool):
        body = self._traces.get(match_id)
        if body is None:
            entry = self.arena.log.by_id.get(match_id)
            path = self.arena.log.replay_path(match_id)
            if entry is None or path is None:
                return _json(404, {"error": "no replay for that match"})
            # one build per match even if several viewers ask at once
            fut = self._building.get(match_id)
            if fut is None:
                fut = asyncio.ensure_future(asyncio.to_thread(self._build, entry, path))
                self._building[match_id] = fut
            try:
                body = await fut
            finally:
                self._building.pop(match_id, None)
            self._traces[match_id] = body
            while len(self._traces) > TRACE_CACHE:
                self._traces.popitem(last=False)
        else:
            self._traces.move_to_end(match_id)
        # a finished match never changes, so let the browser keep it
        if gz:
            return _response(200, body, "application/json; charset=utf-8",
                             already_gz=True, cache="private, max-age=3600")
        return _response(200, gzip.decompress(body), "application/json; charset=utf-8",
                         cache="private, max-age=3600")

    @staticmethod
    def _build(entry: dict, path: str) -> bytes:
        with open(path) as f:
            rec = json.load(f)
        tr = match.trace(cr_sim, rec)
        tr["match"] = {k: entry.get(k) for k in
                       ("id", "at", "p0", "p1", "outcome", "crowns", "ticks", "delta", "forfeit", "upset")}
        tr["match"]["deck0"], tr["match"]["deck1"] = rec.get("deck0"), rec.get("deck1")
        return gzip.compress(json.dumps(tr, separators=(",", ":")).encode(), 6)

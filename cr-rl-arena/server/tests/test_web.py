"""The web side of the server: match log, replay traces and the HTTP routes."""
import asyncio
import json
import random
import urllib.error
import urllib.request

import cr_sim
import pytest
import websockets

from cr_server import match
from cr_server.matchlog import MatchLog

DECK = ["knight", "archers", "giant", "musketeer", "valkyrie", "minions", "wizard", "minipekka"]


class Bot:
    """A deterministic random agent, usable both in-process and over a socket."""

    def __init__(self, seed, name="bot"):
        self.r, self.deck, self.alive, self.name = random.Random(seed), DECK, True, name

    def choose(self, obs):
        legal = [i for i, ok in enumerate(obs["legal"]) if ok]
        if not legal or self.r.random() < 0.6:
            return None
        # every agent plays as the bottom player, so there is no seat to branch on
        return [self.r.choice(legal), self.r.uniform(2, 16), self.r.uniform(9, 14)]

    async def act(self, obs, timeout):
        return self.choose(obs), None


def _played(seed=7):
    res = asyncio.run(match.run_match(cr_sim, Bot(seed), Bot(seed + 1), seed=seed))
    return {**res, "deck0": DECK, "deck1": DECK, "sim_outcome": res["outcome"]}


def test_trace_reproduces_the_recorded_match():
    rec = _played()
    tr = match.trace(cr_sim, rec)
    m = tr["meta"]
    assert m["faithful"] and m["outcome"] == rec["outcome"]
    assert m["crowns"] == rec["crowns"] and m["ticks"] == rec["ticks"]
    assert tr["frames"][0][0] == 0 and tr["frames"][-1][0] == rec["ticks"]
    assert len(tr["frames"][0][3]) == 6                    # the six towers
    assert tr["events"], "a match with deploys must list them"
    for t, p, card, x, y in tr["events"]:
        assert p in (0, 1) and card in DECK and 0 <= x <= cr_sim.WIDTH


def test_both_seats_actually_play_in_a_server_match():
    rec = _played()
    seats = {p for _, p, _ in rec["actions"]}
    events = match.trace(cr_sim, rec)["events"]
    assert seats == {0, 1} and {e[1] for e in events} == {0, 1}
    # the viewer's events are board coordinates: seat 1's deploys are in the top half
    assert all(e[4] < 15 for e in events if e[1] == 0)
    assert all(e[4] > 17 for e in events if e[1] == 1)


def test_replays_recorded_before_the_seat_frame_still_play_back():
    rec = _played()
    old = dict(rec)
    del old["frame"]                                       # older files carry no frame marker...
    old["actions"] = [[t, p, [a[0], a[1], (32 - (int(a[2]) + 0.5)) if p == 1 else a[2]]]
                      for t, p, a in rec["actions"]]       # ...and hold board coordinates
    new_tr, old_tr = match.trace(cr_sim, rec), match.trace(cr_sim, old)
    assert old_tr["meta"]["faithful"] and old_tr["frames"] == new_tr["frames"]
    r = match.replay(cr_sim, old["seed"], old["actions"], DECK, DECK, frame="board")
    assert (r["outcome"], r["crowns"], r["ticks"]) == (rec["outcome"], rec["crowns"], rec["ticks"])


def test_trace_flags_a_replay_that_no_longer_matches():
    rec = _played()
    rec["crowns"] = [rec["crowns"][0] + 1, rec["crowns"][1]]   # as if recorded on another build
    assert match.trace(cr_sim, rec)["meta"]["faithful"] is False


def _entry(i, p0, p1, outcome, delta, r0, r1):
    return {"id": i, "at": 1000 + i, "p0": p0, "p1": p1, "outcome": outcome, "crowns": [3, 1],
            "ticks": 2000, "delta": delta, "r0": r0, "r1": r1, "upset": False, "forfeit": False,
            "deck0": DECK, "deck1": DECK, "moves": [10, 20], "ignored": [2, 4],
            "file": f"{i:08d}.json"}


def test_match_log_summaries_and_reload(tmp_path):
    log = MatchLog(str(tmp_path))
    log.add(_entry(1, "a", "b", 1, 16.0, 1216.0, 1184.0))
    log.add(_entry(2, "b", "a", 1, 17.5, 1201.5, 1198.5))
    log.add(_entry(3, "a", "c", 3, -0.1, 1198.4, 1200.1))
    standings = [
        {"rank": 1, "name": "b", "rating": 1201.5, "wins": 1, "losses": 1, "draws": 0, "games": 2},
        {"rank": 2, "name": "c", "rating": 1200.1, "wins": 0, "losses": 0, "draws": 1, "games": 1},
        {"rank": 3, "name": "a", "rating": 1198.4, "wins": 1, "losses": 1, "draws": 1, "games": 3},
    ]
    snap = log.snapshot(standings, {"a"}, 1)
    a = next(r for r in snap["rows"] if r["name"] == "a")
    assert a["form"] == ["W", "L", "D"] and a["online"] is True
    assert a["history"] == [1200.0, 1216.0, 1198.5, 1198.4] and a["peak"] == 1216.0
    assert a["lastDelta"] == -0.1 and a["deck"] == DECK
    assert (a["moves"], a["ignored"]) == (40, 8)           # seat 0 twice (10, 2), seat 1 once (20, 4)
    assert [m["id"] for m in a["recent"]] == [3, 2, 1] and a["recent"][1]["res"] == "L"
    assert [m["id"] for m in snap["matches"]] == [3, 2, 1]
    assert snap["stats"] == {"online": 1, "live": 1, "played": 3}
    json.dumps(snap)                                       # must be JSON-ready

    again = MatchLog(str(tmp_path))                        # survives a restart
    assert again.next_id() == 4
    assert again.snapshot(standings, set(), 0)["rows"] == [
        {**r, "online": False} for r in snap["rows"]]


def test_match_log_indexes_replays_from_older_versions(tmp_path):
    d = tmp_path / "replays"
    d.mkdir()
    (d / "1700000000000_x_vs_y.json").write_text(json.dumps(
        {"p0": "x", "p1": "y", "deck0": None, "deck1": None, "outcome": 2, "crowns": [0, 3],
         "ticks": 1500, "seed": 1, "actions": []}))
    (d / "junk.json").write_text("{not json")
    log = MatchLog(str(tmp_path))
    assert len(log.matches) == 1 and log.matches[0]["delta"] is None
    assert log.replay_path(1).endswith("1700000000000_x_vs_y.json")
    assert log.replay_path(2) is None
    assert (tmp_path / "matches.jsonl").exists()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def test_server_serves_page_data_and_replays(tmp_path, monkeypatch):
    """Two agents play real matches over the socket; the page data and a replay follow."""
    from cr_server import server, web

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    orig = match.run_match

    async def short(sim, a0, a1, **kw):                    # keep matches brief
        return await orig(sim, a0, a1, max_ticks=400, **kw)

    monkeypatch.setattr(match, "run_match", short)

    results = []

    async def agent(url, name, n):
        bot, done = Bot(hash(name) % 1000, name), 0
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"t": "join", "name": name, "deck": DECK}))
            async for raw in ws:
                m = json.loads(raw)
                if m["t"] == "obs":
                    assert "player" not in m["obs"]
                    o = m["obs"]
                    assert "last_action" in o
                    await ws.send(json.dumps({"t": "act", "tick": o["tick"], "action": bot.choose(o)}))
                elif m["t"] == "start":
                    assert set(m) == {"t", "opponent"}     # no seat, and no seed before the match
                elif m["t"] == "result":
                    assert m["result"] in ("win", "loss", "draw") and "you" not in m
                    results.append((name, m["result"], m["crowns"], m["match"]))
                    done += 1
                    if done >= n:
                        return

    async def main():
        arena = server.Arena()
        mm = asyncio.create_task(arena.matchmaker())
        async with websockets.serve(arena.handler, "127.0.0.1", 0,
                                    process_request=web.Web(arena).process_request) as srv:
            port = srv.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            get = lambda path: asyncio.to_thread(_get, base + path)   # noqa: E731

            st, ct, body = await get("/api/standings")
            assert st == 200 and json.loads(body)["rows"] == []      # no agents yet is fine

            await asyncio.wait_for(asyncio.gather(
                agent(f"ws://127.0.0.1:{port}", "alice", 3), agent(f"ws://127.0.0.1:{port}", "bob", 3)), 60)

            st, ct, body = await get("/api/standings")
            snap = json.loads(body)
            assert st == 200 and ct.startswith("application/json")
            assert {r["name"] for r in snap["rows"]} == {"alice", "bob"}
            # a further match may already have started and ended as the agents left
            assert snap["stats"]["played"] >= 3 and len(snap["matches"]) >= 3
            assert all(m["replay"] and m["delta"] is not None for m in snap["matches"])
            assert len(snap["rows"][0]["history"]) >= 4 and len(snap["rows"][0]["recent"]) >= 3

            mid = snap["matches"][0]["id"]
            st, ct, body = await get(f"/api/replay/{mid}")
            tr = json.loads(body)
            assert st == 200 and tr["meta"]["faithful"] and tr["match"]["id"] == mid
            assert tr["meta"]["ticks"] == snap["matches"][0]["ticks"]

            for path, want in (("/", "<title>Tournament standings"), ("/replay?id=1", "<title>Replay")):
                st, ct, body = await get(path)
                assert st == 200 and ct.startswith("text/html") and want in body.decode()
            assert (await get("/healthz"))[0] == 200
            for path in ("/api/replay/999", "/api/replay/abc", "/api/replay/1/../../x", "/nope", "/web/index.html"):
                assert (await get(path))[0] == 404, path
        mm.cancel()

    asyncio.run(main())
    # the two agents hear the same match from opposite sides
    by_match = {}
    for name, res, crowns, mid in results:
        by_match.setdefault(mid, {})[name] = (res, crowns)
    for mid, r in by_match.items():
        if len(r) == 2:
            (ra, ca), (rb, cb) = r["alice"], r["bob"]
            assert ca == cb[::-1]
            assert {ra, rb} in ({"win", "loss"}, {"draw"})
    assert (tmp_path / "matches.jsonl").exists()
    assert sorted(p.name for p in (tmp_path / "replays").iterdir())[:3] == [f"{i:08d}.json" for i in (1, 2, 3)]


# ---------------------------------------------------------------------------
# Turns: every tick, tick-tagged replies, skipped turns, silent agents
# ---------------------------------------------------------------------------

def test_every_tick_is_a_turn_and_ignored_moves_are_counted():
    class FarSide(Bot):                                    # only ever aims at the opponent's half
        def choose(self, obs):
            return [0, 6.0, 25.0] if obs["legal"][0] else None

    asked = []

    class Counting(Bot):
        async def act(self, obs, timeout):
            asked.append(obs["tick"])
            return self.choose(obs), None

    res = asyncio.run(match.run_match(cr_sim, FarSide(1), Counting(2), seed=3, max_ticks=600))
    assert asked == list(range(600))                       # asked on every single tick
    assert res["moves"][0] > 0 and res["ignored"][0] == res["moves"][0]   # every FarSide move did nothing
    assert res["moves"][1] > 0 and res["ignored"][1] < res["moves"][1]
    assert not any(p == 0 for _, p, _ in res["actions"]) or res["crowns"][0] == 0


def test_server_side_problems_reach_the_next_observation():
    seen = []

    class Flaky(Bot):
        async def act(self, obs, timeout):
            seen.append((obs["tick"], obs["last_action"]))
            t = obs["tick"]
            if t == 5:
                return None, "missed"
            if t == 8:
                return ["zero", 1, 2], None                # not a usable action
            return None, None

    res = asyncio.run(match.run_match(cr_sim, Flaky(1), Bot(2), seed=3, max_ticks=12))
    said = dict(seen)
    assert said[6] == "missed" and said[9] == "malformed" and said[7] == "none"
    assert res["moves"][0] == 1 and res["ignored"][0] == 1 # the malformed reply counts as an ignored move


def test_match_is_void_after_ten_missed_turns_in_a_row():
    class Silent(Bot):
        async def act(self, obs, timeout):
            return (None, "missed") if obs["tick"] >= 20 else (None, None)

    res = asyncio.run(match.run_match(cr_sim, Silent(1), Bot(2), seed=3))
    assert res["aborted"] == [0] and res["ticks"] == 20 + match.MAX_MISSED_TURNS - 1

    class Hiccup(Bot):                                     # misses 9, answers, misses 9 more: never 10 in a row
        async def act(self, obs, timeout):
            return (None, None) if obs["tick"] % 10 == 9 else (None, "missed")

    res = asyncio.run(match.run_match(cr_sim, Hiccup(1), Bot(2), seed=3, max_ticks=80))
    assert "aborted" not in res and res["ticks"] == 80


def _serve(tmp_path, monkeypatch, timeout, body):
    """Run `body(url, arena)` against a real server with a short move timeout."""
    from cr_server import server, web

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "MOVE_TIMEOUT", timeout)

    async def main():
        arena = server.Arena()
        mm = asyncio.create_task(arena.matchmaker())
        async with websockets.serve(arena.handler, "127.0.0.1", 0,
                                    process_request=web.Web(arena).process_request) as srv:
            port = srv.sockets[0].getsockname()[1]
            await asyncio.wait_for(body(f"ws://127.0.0.1:{port}", arena), 60)
        mm.cancel()

    asyncio.run(main())


async def _play_until(url, name, stop, reply):
    """Join and answer observations with `reply(obs) -> message dict | None` until `stop(msg)`."""
    seen = []
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"t": "join", "name": name, "deck": DECK}))
        try:
            async for raw in ws:
                m = json.loads(raw)
                seen.append(m)
                if m["t"] == "obs":
                    out = await reply(m["obs"])
                    if out is not None:
                        await ws.send(json.dumps(out))
                if stop(m):
                    break
        except websockets.ConnectionClosed:
            pass
    return seen


def test_a_late_reply_is_dropped_and_the_agent_stays_in_step(tmp_path, monkeypatch):
    """Answering one tick too late costs that one turn only: nothing shifts."""
    async def body(url, arena):
        async def slow_once(obs):
            if obs["tick"] == 30:
                await asyncio.sleep(0.5)                   # well past the 0.2 s allowance
            act = [0, 6.0, 10.0] if obs["legal"][0] and obs["tick"] % 40 == 0 else None
            return {"t": "act", "tick": obs["tick"], "action": act}

        async def normal(obs):
            return {"t": "act", "tick": obs["tick"], "action": None}

        stop = lambda m: m["t"] == "obs" and m["obs"]["tick"] >= 200   # noqa: E731
        a, b = await asyncio.gather(_play_until(url, "slow", stop, slow_once),
                                    _play_until(url, "ok", stop, normal))
        obs = {m["obs"]["tick"]: m["obs"] for m in a if m["t"] == "obs"}
        assert obs[31]["last_action"] == "missed"
        # afterwards every move is judged against the tick it was sent for
        assert all(obs[t]["last_action"] != "missed" for t in range(33, 200) if t in obs)
        played = [t for t in obs if obs[t]["last_action"] == "ok"]
        assert played and all((t - 1) % 40 == 0 for t in played)

    _serve(tmp_path, monkeypatch, 0.2, body)


def test_a_reply_without_its_tick_is_refused(tmp_path, monkeypatch):
    async def body(url, arena):
        async def untagged(obs):
            return {"t": "act", "action": None}

        async def normal(obs):
            return {"t": "act", "tick": obs["tick"], "action": None}

        stop = lambda m: m["t"] == "obs" and m["obs"]["tick"] >= 5     # noqa: E731
        a, _ = await asyncio.gather(_play_until(url, "untagged", stop, untagged),
                                    _play_until(url, "ok", stop, normal))
        said = [m["obs"]["last_action"] for m in a if m["t"] == "obs"]
        assert said[0] == "none" and set(said[1:]) == {"malformed"}

    _serve(tmp_path, monkeypatch, 1.0, body)


def test_a_silent_agent_is_removed_and_the_match_is_not_recorded(tmp_path, monkeypatch):
    async def body(url, arena):
        async def goes_quiet(obs):
            return {"t": "act", "tick": obs["tick"], "action": None} if obs["tick"] < 3 else None

        async def normal(obs):
            return {"t": "act", "tick": obs["tick"], "action": None}

        quiet, ok = await asyncio.gather(
            _play_until(url, "quiet", lambda m: m["t"] == "error", goes_quiet),
            _play_until(url, "ok", lambda m: m["t"] == "aborted", normal))
        assert quiet[-1]["t"] == "error" and "10 turns" in quiet[-1]["msg"]
        assert ok[-1] == {"t": "aborted", "reason": "opponent stopped responding"}
        assert not any(m["t"] == "result" for m in quiet + ok)
        snap = arena.standings_snapshot()
        assert snap["stats"]["played"] == 0 and snap["matches"] == []
        assert all(r["games"] == 0 for r in snap["rows"])            # no win, loss or rating change

    _serve(tmp_path, monkeypatch, 0.1, body)
    assert not list((tmp_path / "replays").iterdir())

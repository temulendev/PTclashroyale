"""Tournament server: continuous matches between agents, ranked by Elo.

Agents connect over WebSocket, join the queue, and are paired for
server-authoritative matches. The server owns the only real `cr_sim.Battle`;
agents just answer observations with actions. Results update a persistent Elo
leaderboard, and each match's (seed, action-log) is saved so it can be replayed.

The same port also serves a web page: the live standings at `/` and a replay
viewer for any saved match (see `web.py`).

Run:
    pip install cr-sim websockets        # cr-sim = the gym package
    python -m cr_server.server
Env:
    CR_ARENA_BIND        host:port         (default 0.0.0.0:8765)
    CR_ARENA_DATA        data dir          (default ./arena_data)
    CR_MOVE_TIMEOUT      seconds an agent has to answer each tick (default 2.0)

Protocol (JSON text frames)
  C->S  {"t":"join","name":str,"deck":[8 card names]}   (deck required; an
        illegal deck is refused with {"t":"error","msg":...} and the socket closed)
        {"t":"leaderboard"}                      (query then close)
  S->C  {"t":"joined","name","rating"}
        {"t":"start","opponent"}
        {"t":"obs","obs":{...}}                   (every tick; reply required)
  C->S  {"t":"act","tick":obs.tick,"action":[slot,x,y]|null}
  S->C  {"t":"result","result":"win"|"loss"|"draw","crowns":[mine,theirs],
         "rating","delta","match","seed"}
        {"t":"aborted","reason"}                  (match void: the opponent stopped answering)
        {"t":"leaderboard","standings":[...]}

Every agent plays as the bottom player: `obs` and `action` are in the agent's own
seat frame (see cr_sim), so an agent is never told, and never needs, its seat. The
seed is only sent with the result: before the match it would let an agent work out
the opponent's hand order.

Turns. An agent is asked for a move on every tick and has CR_MOVE_TIMEOUT seconds
to answer. Its reply must carry the `tick` it answers, so a reply that arrives late
is recognised and dropped instead of being taken for the next tick's move. No
answer in time means no move for that agent on that tick. An agent that lets
`match.MAX_MISSED_TURNS` turns in a row go by is disconnected, and that match is
closed without being recorded.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time

import cr_sim
import websockets

from . import match
from .matchlog import UPSET_GAP, MatchLog
from .leaderboard import Leaderboard
from .web import Web

BIND = os.environ.get("CR_ARENA_BIND", "0.0.0.0:8765")
DATA_DIR = os.environ.get("CR_ARENA_DATA", "./arena_data")
MOVE_TIMEOUT = float(os.environ.get("CR_MOVE_TIMEOUT", "2.0"))


class WsAgent:
    """Wraps a connected websocket as a match-runner agent."""

    def __init__(self, ws, name, deck):
        self.ws = ws
        self.name = name
        self.deck = deck
        self.alive = True

    async def send(self, obj):
        try:
            await self.ws.send(json.dumps(obj))
        except websockets.ConnectionClosed:
            self.alive = False

    async def act(self, obs, timeout):
        """Send the observation for this tick and wait for the reply to it.

        Returns (action, problem): problem is None for a usable reply, "missed"
        if none came in time, "malformed" if it could not be read. Replies tagged
        with any other tick are leftovers from a turn this agent already missed;
        they are dropped and the wait goes on, so an agent can never slip a step
        behind.
        """
        tick = obs["tick"]
        loop = asyncio.get_running_loop()
        try:
            await self.ws.send(json.dumps({"t": "obs", "obs": obs}))
            deadline = loop.time() + timeout
            while True:
                left = deadline - loop.time()
                if left <= 0:
                    return None, "missed"
                raw = await asyncio.wait_for(self.ws.recv(), left)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    return None, "malformed"
                if not isinstance(msg, dict) or msg.get("t") != "act":
                    return None, "malformed"
                at = msg.get("tick")
                if not isinstance(at, int) or isinstance(at, bool):
                    return None, "malformed"      # every reply must say which tick it answers
                if at != tick:
                    continue                      # a late answer to another tick
                return msg.get("action"), None
        except websockets.ConnectionClosed:
            self.alive = False
            return None, None
        except asyncio.TimeoutError:
            return None, "missed"

    async def drop(self, why):
        """Tell the agent why it is being removed, then close its connection."""
        await self.send({"t": "error", "msg": why})
        self.alive = False
        try:
            await self.ws.close()
        except Exception:
            pass


class Arena:
    def __init__(self):
        self.board = Leaderboard(os.path.join(DATA_DIR, "leaderboard.json"))
        self.idle: asyncio.Queue[WsAgent] = asyncio.Queue()
        self.replays_dir = os.path.join(DATA_DIR, "replays")
        os.makedirs(self.replays_dir, exist_ok=True)
        self.log = MatchLog(DATA_DIR)           # match history behind the web page
        self.online: dict[str, int] = {}        # name -> open connections under it
        self.live = 0                           # matches in progress
        self._deck_checker = cr_sim.Battle()  # only used to validate decks at join

    async def handler(self, ws):
        try:
            raw = await asyncio.wait_for(ws.recv(), 30)
            msg = json.loads(raw)
        except Exception:
            return
        if msg.get("t") == "leaderboard":
            await ws.send(json.dumps({"t": "leaderboard", "standings": self.board.standings()}))
            return
        if msg.get("t") != "join":
            await ws.send(json.dumps({"t": "error", "msg": "expected join or leaderboard"}))
            return

        name = str(msg.get("name") or f"anon-{random.randint(1000,9999)}")
        # A deck is required and is validated here, at join, so a missing or illegal
        # deck is refused to the agent that sent it instead of failing later inside
        # a match (which used to void the game for its opponent as well).
        deck = msg.get("deck")
        problem = self._deck_problem(deck)
        if problem:
            await ws.send(json.dumps({"t": "error", "msg": problem}))
            return
        agent = WsAgent(ws, name, deck)
        await agent.send({"t": "joined", "name": name,
                          "rating": round(self.board.get(name).rating, 1)})
        self.idle.put_nowait(agent)
        self.online[name] = self.online.get(name, 0) + 1
        try:
            await ws.wait_closed()
        finally:
            agent.alive = False
            left = self.online.get(name, 1) - 1
            if left > 0:
                self.online[name] = left
            else:
                self.online.pop(name, None)

    def standings_snapshot(self) -> dict:
        """Data for the web page: standings, recent results, live counts."""
        return self.log.snapshot(self.board.standings(), set(self.online), self.live)

    def _deck_problem(self, deck):
        """Why `deck` can't be played, or None if it is legal."""
        if deck is None:
            return "a deck is required: send 8 card names"
        if not isinstance(deck, list) or not all(isinstance(c, str) for c in deck):
            return "deck must be a list of 8 card names"
        try:
            self._deck_checker.check_deck(deck)  # same rules Battle.reset enforces
        except ValueError as e:
            return f"invalid deck: {e}"
        return None

    async def matchmaker(self):
        while True:
            a = await self._next_live()
            b = await self._next_live(exclude=a)
            asyncio.create_task(self._play(a, b))

    async def _next_live(self, exclude=None):
        while True:
            ag = await self.idle.get()
            if ag.alive and ag is not exclude:
                return ag

    async def _play(self, a: WsAgent, b: WsAgent):
        # Seats are drawn at random for every match: `a` is player 0 (bottom) from
        # here on. Queue order used to decide it, so with two agents connected the
        # same one was player 0 in every game.
        if random.random() < 0.5:
            a, b = b, a
        self.live += 1
        try:
            seed = random.getrandbits(63)
            await a.send({"t": "start", "opponent": b.name})
            await b.send({"t": "start", "opponent": a.name})

            res = await match.run_match(cr_sim, a, b, seed=seed, move_timeout=MOVE_TIMEOUT)
            if res.get("aborted") is not None:
                # One or both agents stopped answering. The match is void: no rating
                # change, no result, no replay. The silent agent is disconnected so
                # it cannot stall the next opponent too; the other goes back in the queue.
                gone = [(a, b)[i] for i in res["aborted"]]
                for ag in (a, b):
                    if ag in gone:
                        await ag.drop(f"removed: no reply to {match.MAX_MISSED_TURNS} turns in a row")
                    else:
                        await ag.send({"t": "aborted", "reason": "opponent stopped responding"})
                print(f"[match void] {a.name} vs {b.name}: "
                      f"{', '.join(g.name for g in gone)} stopped responding at tick {res['ticks']}")
                return
            out = res["outcome"]
            # forfeit: a disconnected agent loses to a connected one
            forfeit = False
            if not a.alive and b.alive:
                out, forfeit = 2, True
            elif not b.alive and a.alive:
                out, forfeit = 1, True

            score_a = 1.0 if out == 1 else 0.0 if out == 2 else 0.5
            before = (self.board.get(a.name).rating, self.board.get(b.name).rating)
            delta = self.board.report(a.name, b.name, score_a)
            mid = self._record(a, b, res, out, forfeit, delta, before)

            # each agent hears the result from its own side, never as a seat number
            c = res["crowns"]
            for ag, won, mine, d in ((a, 1, c, delta), (b, 2, c[::-1], -delta)):
                await ag.send({"t": "result",
                               "result": "win" if out == won else "loss" if out in (1, 2) else "draw",
                               "crowns": mine, "rating": round(self.board.get(ag.name).rating, 1),
                               "delta": round(d, 1), "match": mid, "seed": seed})
            print(f"[match] {a.name} vs {b.name} -> {['--','P0','P1','draw'][out]} "
                  f"{res['crowns']} in {res['ticks']} ticks")
        except Exception as e:  # never let one match kill the server
            print(f"[match error] {a.name} vs {b.name}: {e!r}")
        finally:
            self.live -= 1
            for x in (a, b):
                if x.alive:
                    self.idle.put_nowait(x)

    def _record(self, a, b, res, out, forfeit, delta, before):
        """Save the replay file and append the match to the log the web page reads.

        `outcome` is the result that counted for the ratings; `sim_outcome` is what
        the simulator itself produced. They differ only for a forfeit, and the
        replay viewer checks a re-run against `sim_outcome`.
        """
        mid = self.log.next_id()
        fname = f"{mid:08d}.json"          # never built from agent names
        at = int(time.time() * 1000)
        r0 = round(self.board.get(a.name).rating, 1)
        r1 = round(self.board.get(b.name).rating, 1)
        winner_before, loser_before = (before if out == 1 else before[::-1])
        saved = True
        try:
            with open(os.path.join(self.replays_dir, fname), "w") as f:
                json.dump({"id": mid, "at": at, "p0": a.name, "p1": b.name,
                           "deck0": a.deck, "deck1": b.deck,
                           **res, "outcome": out, "sim_outcome": res["outcome"],
                           "forfeit": forfeit}, f)
        except OSError:
            saved = False
        try:
            self.log.add({
                "id": mid, "at": at, "p0": a.name, "p1": b.name, "outcome": out,
                "crowns": res["crowns"], "ticks": res["ticks"],
                "delta": round(delta, 1), "r0": r0, "r1": r1,
                "upset": out in (1, 2) and not forfeit and winner_before < loser_before - UPSET_GAP,
                "forfeit": forfeit, "deck0": a.deck, "deck1": b.deck,
                "moves": res.get("moves"), "ignored": res.get("ignored"),
                "file": fname if saved else None,
            })
        except OSError:
            pass
        return mid


async def main():
    host, port = BIND.rsplit(":", 1)
    arena = Arena()
    asyncio.create_task(arena.matchmaker())
    print(f"cr-arena listening on ws://{host}:{port}  (data: {DATA_DIR}, move timeout {MOVE_TIMEOUT}s)")
    web = Web(arena)
    async with websockets.serve(arena.handler, host, int(port), ping_interval=20,
                                process_request=web.process_request):
        await asyncio.Future()  # run forever


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    run()

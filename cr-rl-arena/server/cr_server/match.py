"""Server-authoritative match runner.

The server owns the one true `cr_sim.Battle`. Agents never step their own sim
during a ranked match; they only receive observations and return actions. Because
the engine is deterministic, the full match is reproducible from
`(seed, actions)` — the returned log can be replayed or audited.

An "agent" here is any object with:
    .name : str
    .deck : list[str]                   (8 card names)
    async def act(obs: dict, timeout: float) -> (action, problem)
where `action` is (slot, x, y) or None (no move this tick), and `problem` is None
when the agent answered in time, "missed" when it did not, or "malformed" when
what it sent could not be read. Either problem means no move for that agent on
that tick; it never stops the other agent's move or the match.
"""
from __future__ import annotations

import asyncio
from numbers import Real

# An agent that lets this many turns in a row go by without answering has stopped
# playing. The match is closed and nothing about it is recorded.
MAX_MISSED_TURNS = 10


def _validate(action):
    if action is None:
        return None
    try:
        slot, x, y = action
        if not isinstance(slot, int) or isinstance(slot, bool) \
                or not isinstance(x, Real) or not isinstance(y, Real):
            return None
        return (int(slot), float(x), float(y))
    except (TypeError, ValueError):
        return None


async def run_match(sim, agent0, agent1, *, seed, move_timeout=2.0, max_ticks=None):
    """Play one match, asking both agents for a move on every tick.

    Each observation's `last_action` tells the agent what became of its previous
    move. The simulator fills it in for moves it received; when the server itself
    had to drop the reply, it says why instead: "missed" (no answer in time) or
    "malformed".

    Returns the match record, or `{"aborted": [seats]}` when one or both agents
    stopped answering (MAX_MISSED_TURNS in a row): that match is void.
    """
    b = sim.Battle()
    b.reset(seed, agent0.deck, agent1.deck)
    if max_ticks is None:
        max_ticks = sim.REGULATION_TICKS + sim.OVERTIME_TICKS + 2

    actions = []
    problem = [None, None]      # why the server dropped each agent's last reply, if it did
    missed = [0, 0]             # unanswered turns in a row
    moves = [0, 0]              # moves each agent tried to make
    ignored = [0, 0]            # ...of which this many did nothing
    out = 0
    t = 0
    while out == 0 and t < max_ticks:
        obs = [dict(b.observe(0)), dict(b.observe(1))]
        for i in (0, 1):
            if problem[i]:
                obs[i]["last_action"] = problem[i]
        replies = await asyncio.gather(
            agent0.act(obs[0], move_timeout),
            agent1.act(obs[1], move_timeout),
        )
        acts = [None, None]
        for i, (action, why) in enumerate(replies):
            problem[i] = why
            if why is None and action is not None:
                acts[i] = _validate(action)
                if acts[i] is None:
                    problem[i] = "malformed"
            missed[i] = missed[i] + 1 if why == "missed" else 0
        gone = [i for i in (0, 1) if missed[i] >= MAX_MISSED_TURNS]
        if gone:
            return {"aborted": gone, "ticks": t, "seed": seed}

        for i in (0, 1):
            if acts[i] is not None:
                actions.append([t, i, list(acts[i])])
        out = b.step(acts[0], acts[1])
        for i in (0, 1):
            if acts[i] is not None:
                moves[i] += 1
                ignored[i] += b.last_action(i) != "ok"
            elif problem[i] == "malformed":
                moves[i] += 1
                ignored[i] += 1
        t += 1

    return {
        "outcome": out,                 # referee's code: 0 running, 1 seat 0, 2 seat 1, 3 draw
        "crowns": list(b.crowns()),     # [seat 0, seat 1]
        "ticks": t,
        "seed": seed,
        "actions": actions,             # [[tick, seat, [slot,x,y]], ...] -> replayable
        "frame": "seat",                # each action is in its own seat's frame, as sent
        "moves": moves,                 # [seat 0, seat 1] moves attempted
        "ignored": ignored,             # [seat 0, seat 1] moves that did nothing
    }


def seat_actions(sim, actions, frame):
    """An action log in the seat frame `Battle.step` takes.

    Logs written since the seat frame was introduced are already in it
    (`frame == "seat"`). Older logs hold board coordinates, where the top seat's
    placements have high y; those are converted here, snapping to the tile first
    exactly as the simulator did when the match was played.
    """
    if frame == "seat":
        return actions
    out = []
    for t, p, a in actions:
        if p == 1:
            slot, x, y = a
            row = min(int(sim.HEIGHT) - 1, max(0, int(y // 1)))
            a = [slot, x, sim.HEIGHT - (row + 0.5)]
        out.append([t, p, a])
    return out


def replay(sim, seed, actions, deck0=None, deck1=None, frame="seat"):
    """Re-simulate a match from its (seed, actions) log and return the outcome.
    Used by the server to audit a result, and by anyone to verify a match.
    Pass the replay file's `frame` (older files have none: use `"board"`)."""
    b = sim.Battle()
    b.reset(seed, deck0 or "default", deck1 or "default")
    by_tick = {}
    for t, p, a in seat_actions(sim, actions, frame):
        by_tick.setdefault(t, [None, None])[p] = tuple(a)
    out, t, maxt = 0, 0, sim.REGULATION_TICKS + sim.OVERTIME_TICKS + 2
    while out == 0 and t < maxt:
        a0, a1 = by_tick.get(t, [None, None])
        out = b.step(a0, a1)
        t += 1
    return {"outcome": out, "crowns": list(b.crowns()), "ticks": t}


def trace(sim, rec, every=2):
    """Re-simulate a saved replay and return a frame-by-frame trace for the viewer.

    `rec` is a replay record (seed, actions, deck0, deck1, plus the recorded
    result). Every `every`-th tick becomes a frame of unit positions. The trace
    also lists the deploys that actually happened, and says whether this re-run
    reached the same result as the recorded match: a replay saved by an older
    simulator build may not, and the viewer should say so rather than show a
    different game as if it were the real one.
    """
    b = sim.Battle()
    b.reset(rec["seed"], rec.get("deck0") or "default", rec.get("deck1") or "default")
    cards = b.deployable_cards() + ["princess_tower", "king_tower"]
    idx = {n: i for i, n in enumerate(cards)}
    by_tick = {}
    for t, p, a in seat_actions(sim, rec["actions"], rec.get("frame")):
        by_tick.setdefault(t, [None, None])[p] = tuple(a)

    def frame(t):
        # the viewer is a spectator: it shows the real, unmirrored board
        ents = []
        for (owner, card, x, y, hp, mhp, flying, is_tower, deploying, eid, hw, hh) in b.spectator_entities():
            flags = (1 if flying else 0) | (2 if is_tower else 0) | (4 if deploying else 0)
            ents.append([eid, owner, idx.get(card, 0), round(x, 2), round(y, 2),
                         round(hp / mhp, 3) if mhp else 0.0, flags, round(hw, 2), round(hh, 2)])
        return [t, list(b.crowns()), [round(b.elixir(0), 1), round(b.elixir(1), 1)], ents]

    frames, events = [frame(0)], []
    # stop where the recorded match stopped (a match can be cut short by the server)
    out, t = 0, 0
    maxt = rec.get("ticks") or (sim.REGULATION_TICKS + sim.OVERTIME_TICKS + 2)
    while out == 0 and t < maxt:
        acts = by_tick.get(t)
        if acts:
            before = (b.elixir(0), b.elixir(1))
            names = [None, None]
            for p in (0, 1):
                a = acts[p]
                if a is None:
                    continue
                if a[0] == sim.ABILITY_SLOT:
                    names[p] = "ability"
                elif 0 <= a[0] < 4:
                    names[p] = b.hand(p)[a[0]]
            out = b.step(acts[0], acts[1])
            for p in (0, 1):
                # elixir only ever falls on a tick when something was actually played
                if names[p] and b.elixir(p) < before[p]:
                    x, y = acts[p][1], acts[p][2]
                    if p == 1:
                        y = sim.HEIGHT - y       # seat frame -> the board the viewer draws
                    events.append([t, p, names[p], round(x, 1), round(y, 1)])
        else:
            out = b.step(None, None)
        t += 1
        if t % every == 0 or out != 0:
            frames.append(frame(t))

    crowns = list(b.crowns())
    want = rec.get("sim_outcome", rec.get("outcome"))
    faithful = (out == want and crowns == list(rec.get("crowns", crowns))
                and t == rec.get("ticks", t))
    return {
        "meta": {
            "w": sim.WIDTH, "h": sim.HEIGHT, "river_y": sim.RIVER_Y, "river_half": sim.RIVER_HALF,
            "bridges": list(sim.BRIDGES), "bridge_half": sim.BRIDGE_HALF,
            "tps": sim.TICKS_PER_SECOND, "every": every,
            "regulation": sim.REGULATION_TICKS, "cards": cards,
            "outcome": out, "crowns": crowns, "ticks": t, "faithful": faithful,
        },
        "events": events,      # [tick, seat, card, x, y] for each deploy that happened (board coords)
        "frames": frames,      # [tick, crowns, elixir, [[id, owner, card, x, y, hp, flags, hw, hh], ...]]
    }


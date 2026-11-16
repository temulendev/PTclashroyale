# cr-arena-server

The tournament server for [`cr_sim`](../gym). Agents connect over WebSocket,
join a queue, and are continuously paired for **server-authoritative** matches.
The server owns the only real `cr_sim.Battle`; agents just answer observations
with actions. Results update a persistent **Elo** leaderboard, and every match's
`(seed, action-log)` is saved for replay/audit.

**Writing an agent?** See [CONNECTING.md](CONNECTING.md): how to connect, the
messages, the observation and action formats, turns and timing, and how playing on
the server differs from running the simulator locally.

## Run

```bash
pip install ./gym ./server      # server depends on the gym package (cr-sim)
cr-arena                        # or: python -m cr_server.server
```

Environment variables:

| var | default | meaning |
|---|---|---|
| `CR_ARENA_BIND` | `0.0.0.0:8765` | host:port to listen on |
| `CR_ARENA_DATA` | `./arena_data` | leaderboard, match log and replay storage |
| `CR_MOVE_TIMEOUT` | `2.0` | seconds an agent has to answer each tick (miss ⇒ no move that tick) |

## Protocol (JSON text frames over WebSocket)

```
C→S  {"t":"join","name":"myagent","deck":["knight",...8...]}
     {"t":"leaderboard"}                         # query standings, then close
S→C  {"t":"joined","name","rating"}
     {"t":"start","opponent"}
     {"t":"obs","obs":{...}}                      # sent every tick; reply required
C→S  {"t":"act","tick":N,"action":[slot,x,y] | null}   # N = obs.tick; slot 0-3
S→C  {"t":"result","result":"win"|"loss"|"draw","crowns":[mine,theirs],
      "rating","delta","match","seed"}
     {"t":"aborted","reason"}                     # match void: opponent stopped answering
     {"t":"error","msg"}                          # refused or removed; connection closes
```

- **Every agent plays as the bottom player.** `obs` and `action` are in the agent's
  own seat frame: its side is `y < 15`, its entities are owner `0`, crowns are
  `[mine, theirs]`. The simulator mirrors the board for whichever agent is really
  on top, so an agent is never told its seat and never needs it.
- The match **seed is sent only with the result.** Sent beforehand, it would let an
  agent reconstruct the opponent's hand order.

- **Every tick is a turn.** Each agent gets an observation on every tick and has
  `CR_MOVE_TIMEOUT` seconds to answer. No answer in time means no move for that
  agent on that tick; the other agent's move still counts.
- **Replies carry the tick they answer.** A late reply is recognised by its tick and
  dropped, so it is never taken for the next tick's move. A reply with no tick is
  refused.
- **Ten missed turns in a row** and the agent is disconnected. That match is closed
  and not recorded: no result, no rating change, no replay. The opponent gets
  `aborted` and is re-queued.
- A disconnected agent **forfeits** to a connected opponent; that match is recorded.
- **Ignored moves are reported.** `obs.last_action` says what became of the agent's
  previous move: `ok`, `none`, the simulator's reason it could not be carried out
  (`not_enough_elixir`, `not_your_side`, `bad_slot`, ...), or the server's
  (`malformed`, `missed`). The server counts each agent's ignored moves and the web
  page shows them.
- One bad agent can't stall or crash a match or the server.

The `obs` dict is `cr_sim.Battle.view(seat).observe()`: `elixir`, `hand`,
`hand_cost`, `next_card`, `legal` (per-slot affordability mask), `last_action`,
`crowns`, `entities` (full board), `tick`, `phase`. See [`examples/random_agent.py`](examples/random_agent.py)
for a complete client.

## Web page

The same port serves a web page, so opening the server's address in a browser
shows the standings. There is nothing extra to run or deploy.

| path | what it is |
|---|---|
| `/` | Live standings: top three, the full table, recent results. Refreshes every few seconds. Click an agent for its rating history, deck, ignored-move count and last matches. |
| `/replay` | Replay viewer. With no `id` it opens the newest match; `?id=N` opens match `N`. Beside the arena, score and playback controls it lists recent matches (search by agent, filter by upsets, king-tower wins or close games) and can play the next one automatically. Add `&t=75` to open a match paused 75 seconds in. |
| `/api/standings` | The page's data as JSON (standings, recent results, live counts). |
| `/api/replay/N` | Frame-by-frame trace of match `N`, re-simulated on request from the saved seed and actions. |
| `/healthz` | Liveness probe. |

Notes:

- **What is public.** Anyone who can reach the server can see every agent's name,
  rating, record and current deck, and can watch any saved match, including both
  players' elixir. Nothing is shown while a match is still being played.
- **Match log.** Besides `leaderboard.json` and the replay files, the server keeps
  `matches.jsonl` in `CR_ARENA_DATA`, one line per finished match. The page's
  results list, rating charts and rank movement come from it.
- **Replays and simulator versions.** A replay is re-run on the server's current
  simulator. If the result no longer matches what was recorded (the simulator
  changed since), the viewer says so instead of presenting a different game as the
  original.
- The pages load two fonts from Google Fonts; without internet access they fall
  back to system fonts.

## Reproducing / auditing a match

Each saved replay in `CR_ARENA_DATA/replays/` (named by match id, e.g.
`00000042.json`) holds the `seed` and `actions`.
Re-simulate it deterministically:

```python
import cr_sim, json
from cr_server.match import replay
r = json.load(open("arena_data/replays/<id>.json"))
print(replay(cr_sim, r["seed"], r["actions"], r["deck0"], r["deck1"]))  # same outcome/crowns
```

Replay files record each action as the agent sent it, in that agent's seat frame.
In a replay file `outcome` and `crowns` are the referee's: `1` seat-0 win, `2`
seat-1 win, `3` draw, and `[seat 0, seat 1]`.


## Design notes

- **Why Python, not Rust, for the server:** it imports the same `cr_sim` native
  extension the students use, so there is exactly one implementation of the game
  logic and no cross-language drift. Determinism holds because the engine itself
  is fixed-point.
- **Scaling:** matches are `asyncio` tasks and run concurrently. A full 3-minute
  match is 3,600 round-trips per agent, so how long it takes in real time depends
  almost entirely on how quickly the agents answer.

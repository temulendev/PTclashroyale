# Connecting an agent to the tournament server

This guide is for participants. It covers how your agent talks to the tournament
server, what it receives and sends, and how that differs from running the
simulator on your own machine.

In short: your agent opens a WebSocket, sends one `join` message with a name and
a deck, then answers every observation with an action until it disconnects. The
server runs the matches, keeps the ratings and saves a replay of every game.

## Quick start

```bash
pip install websockets
python server/examples/random_agent.py wss://<your-arena-host> my-team-name
```

[`examples/random_agent.py`](examples/random_agent.py) is a complete client in
about 60 lines. Copy it and replace `policy(obs)` with your own.

Open `https://<your-arena-host>` in a browser to see the standings and watch
replays of your matches.

Use `wss://` for a hosted server and `ws://` for one running locally
(`ws://localhost:8765`).

## The conversation

All messages are JSON text frames.

```
you    → {"t": "join", "name": "my-team", "deck": ["knight", ... 8 cards ...]}
server → {"t": "joined", "name": "my-team", "rating": 1200.0}

        ... wait in the queue until an opponent is free ...

server → {"t": "start", "opponent": "other-team"}
server → {"t": "obs", "obs": {"tick": 0, ...}}                 ┐ once per tick,
you    → {"t": "act", "tick": 0, "action": [slot, x, y]}       ┘ until the match ends
server → {"t": "result", "result": "win", "crowns": [3, 1],
          "rating": 1216.0, "delta": 16.0, "match": 42, "seed": 123}

        ... back in the queue automatically; the next "start" follows ...
```

| Message | Direction | Meaning |
|---|---|---|
| `join` | you → server | Must be your first message, within 30 seconds of connecting. |
| `joined` | server → you | You are in the queue. `rating` is your current rating. |
| `start` | server → you | A match is beginning, against `opponent`. |
| `obs` | server → you | The game state as you see it, sent on every tick. **You must reply with `act`.** |
| `act` | you → server | Your reply: the `tick` you are answering, and `[slot, x, y]` to play a card or `null` to do nothing. |
| `result` | server → you | The match is over: `result` is `win`, `loss` or `draw`, and `crowns` is `[yours, theirs]`. |
| `aborted` | server → you | The match was called off because your opponent stopped answering. It does not count. You are back in the queue. |
| `error` | server → you | You were refused or removed; `msg` says why. The connection then closes. |

You stay connected between matches and are re-queued after each one. To stop
playing, close the connection.

## You always play as the bottom player

This is the one rule to hold on to. In every match, whatever seat the server
gave you:

- **your side is the bottom half** of the board (`y` below 15),
- **your towers are at low `y`** and you attack toward high `y`,
- **anything you own has owner `0`**; the opponent's has owner `1`,
- **`crowns` is `[yours, theirs]`**.

The server flips the board for whichever agent is really on top, in both what it
sees and where its cards land. You are never told which seat you have, because it
makes no difference: the game is exactly mirror-symmetric, so a match from the top
seat looks and plays identically to one from the bottom.

Do not flip anything yourself.

## Joining

- **Name.** Your rating is stored under the name you send, so use the same name
  every time. Names are not password-protected: anyone can join under any name.
- **One connection per name.** Two connections with the same name are treated as
  two agents sharing one rating and can even be paired against each other.
- **Deck.** Required. It must be exactly 8 different playable card names with at
  most one champion. A missing or illegal deck is refused with an `error`
  explaining the problem (unknown card, duplicate, not a playable card, and so on).
- **Card names** are lowercase with underscores, for example `knight`,
  `minipekka`, `babydragon`, `barbarian_hut`. List them all with:

  ```python
  import cr_sim
  print(cr_sim.Battle().deployable_cards())
  ```

  and check a deck before you connect with `cr_sim.Battle().check_deck(deck)`,
  which raises `ValueError` with the same message the server would send.

## Turns

- **Every tick is a turn.** The server sends you an observation on every tick (20
  per second of game time) and waits for your reply.
- **Your reply must name the tick it answers:** copy `obs["tick"]` into `"tick"`.
  A reply without it is refused.
- **You have 2 seconds.** If your reply has not arrived by then, you make no move
  on that tick and the match goes on. Your opponent's move still counts.
- **A late reply is thrown away.** Because it is tagged with its tick, the server
  knows it is late and never mistakes it for your answer to a later tick. Just
  answer the newest observation.
- **Ten missed turns in a row and you are removed.** The server closes the match
  without recording it, tells you why in an `error` message and disconnects you.
  Your opponent gets `aborted` and goes back in the queue. Reconnect and `join`
  again when your agent is ready.
- **If you disconnect during a match you forfeit it.** That match does count.
- **Matches run as fast as both agents answer, not in real time.** A full
  three-minute match is 3,600 turns, so its length in real time is about 3,600
  times your round-trip time: a few seconds for fast agents on a good connection,
  several minutes if each reply takes 100 ms.

### Passing a turn

To do nothing on a tick, reply with a `null` action. Send it straight away:

```json
{"t": "act", "tick": 1240, "action": null}
```

**You must still reply on ticks where you have nothing to do.** Staying silent is
not passing: the server waits the full 2 seconds for you on every such tick, the
match crawls, and ten in a row gets you removed.

This matters most if your model was trained to decide less often than every tick.
Say it decides every 4 ticks. Run it on those ticks and pass on the others:

```python
DECIDE_EVERY = 4            # how often YOUR model was trained to act

async for raw in ws:
    msg = json.loads(raw)
    if msg["t"] == "obs":
        obs = msg["obs"]
        action = policy(obs) if obs["tick"] % DECIDE_EVERY == 0 else None
        await ws.send(json.dumps({"t": "act", "tick": obs["tick"], "action": action}))
```

The pass is cheap for you and keeps the match moving for your opponent.

## The observation

`obs` is what you are allowed to see:

```json
{
  "tick": 1240, "phase": "single",
  "elixir": 6.4, "crowns": [0, 1],
  "hand": ["valkyrie", "musketeer", "giant", "minipekka"],
  "hand_cost": [4, 4, 5, 4], "next_card": "knight",
  "legal": [true, true, true, true],
  "last_action": "ok",
  "entities": [[0, "king_tower", 9.0, 3.0, 4008, 4008, false, true, false, 1, 2.0, 2.0], ...],
  "done": false, "outcome": 0
}
```

| Field | Meaning |
|---|---|
| `tick` | Game time. 20 ticks per second. Regulation is 3600 ticks (3:00), overtime up to 2400 more. |
| `phase` | `single`, `double` (last minute of regulation: elixir regenerates twice as fast) or `overtime`. |
| `elixir` | Your elixir, 0 to 10. The opponent's is not shown. |
| `crowns` | `[yours, the opponent's]`. |
| `hand` | Your four cards, by slot 0–3. The opponent's hand is not shown. |
| `hand_cost` | Elixir cost of each card in `hand`. |
| `next_card` | The card that enters your hand after your next play. |
| `legal` | For each slot, whether you can afford that card right now. It says nothing about *where* the card may go. |
| `last_action` | What happened to the move you sent on the previous tick. See [Ignored moves](#ignored-moves). |
| `entities` | Every tower and unit on the board, both sides, yours first. See below. |
| `done`, `outcome` | `outcome` is `0` while the match is running. You will not normally see anything else; the final result comes in the `result` message. |

Each entity is a list:

```
[owner, card, x, y, hp, max_hp, flying, is_tower, deploying, id, half_w, half_h]
```

`owner` is `0` for yours and `1` for the opponent's. `deploying` is true while a unit is
still arriving and cannot act. `id` is stable for the unit's lifetime. `half_w`
and `half_h` are the half-size of a tower's box in tiles, and 0 for units.

### The board

- 18 tiles wide (`x` from 0 to 18) and 32 tall (`y` from 0 to 32).
- You own the bottom (`y` below 15); the opponent owns the top (`y` from 17).
  The river runs between, crossed by two bridges at `x` = 3.5 and 14.5.
- Your king tower is at (9, 3) and your princess towers at (3.5, 6.5) and
  (14.5, 6.5). The opponent's are at (9, 29), (3.5, 25.5) and (14.5, 25.5).
- Left and right are the same for both agents: your left lane (`x` = 3.5) leads to
  the opponent's tower at `x` = 3.5.
- The web page and replays show the real board, where one of the two agents is at
  the top. That view is for spectators; what you receive is always as above.

## The action

Reply to every `obs` with one of:

```json
{"t": "act", "tick": 1240, "action": [2, 5.5, 9.5]}
{"t": "act", "tick": 1240, "action": null}
```

- `tick` is the `tick` of the observation you are answering.
- `slot` is an integer 0–3, the position in `hand`. It must be a whole number:
  `2`, not `2.0`.
- `x`, `y` are the tile to deploy at. The position snaps to the centre of the tile
  it falls in.
- Troops and buildings must go on your own side (`y` below 15), plus the pocket
  that opens on the enemy side once you have destroyed that lane's princess tower
  (`y` below 27 in that lane). Spells can go anywhere.
- To use your champion's ability, send slot `100` (`cr_sim.ABILITY_SLOT`) with any
  `x`, `y`.

## Ignored moves

A move that cannot be carried out is ignored: no card is played and no elixir is
spent. It is not a penalty, and it is not silent. The next observation's
`last_action` tells you what happened:

| `last_action` | Meaning |
|---|---|
| `ok` | Your move was carried out. |
| `none` | You sent no move (a `null` action). |
| `not_enough_elixir` | You cannot afford that card yet. |
| `not_your_side` | A troop or building was aimed at a tile you may not deploy on. |
| `bad_slot` | The slot was not 0–3. |
| `nothing_to_mirror` | Mirror was played before any other card. |
| `ability_unavailable` | No champion on the field, or its ability is not ready or cannot be paid for. |
| `malformed` | The server could not read your reply: it was not valid JSON, had no `tick`, or the action was not `[integer, number, number]`. |
| `missed` | Your reply did not arrive within 2 seconds. |

Check it. An agent whose moves are all ignored looks connected and busy but never
plays a card. The standings page shows, for every agent, what share of its moves
were ignored; if yours is high, something in your action code is wrong.

The first seven values come from the simulator, so you get exactly the same
feedback when training locally. `malformed` and `missed` only happen on the server.

## Results and rating

- `result` is `win`, `loss` or `draw`, from your side.
- `match` is the match number; watch it at `/replay?id=<match>` on the web page.
- `seed` is the match's random seed, sent only once the match is over (it is in
  the replay file too, so a result can be re-simulated and checked).
- A king tower falling ends the match at once. Otherwise the side with more crowns
  at 3:00 wins; if level, overtime is sudden death; if still level at the end, the
  side whose weakest tower has more health wins, and an exact tie is a draw.
- Ratings are Elo, starting at 1200 with K = 32. `delta` is your change from this
  match.
- Every finished match appears on the web page with a replay.

## Training locally

The game is the same: the server runs the same `cr_sim` simulator you install, so
cards, physics and rules are identical. The observation is the same too: the
`obs` you receive is exactly what `battle.view(seat).observe()` returns locally,
including `last_action`, and actions mean the same thing. Both act on every tick.
What differs is how you drive it.

| | Local simulator | Tournament server |
|---|---|---|
| Who steps the game | You call `b.step(action0, action1)` for both seats | The server does; you only answer for yourself |
| Time per turn | Unlimited | 2 seconds |
| Opponent's hand and elixir | Readable through `b.hand(1)`, `b.elixir(1)` | Never sent |
| Seed and reset | You choose | The server chooses; you learn the seed afterwards |
| Observation format | Python dict; entities are tuples | JSON; entities are lists |

A deck is required in both. Locally you may pass the word `"default"` instead of a
list to get a built-in deck; the server needs your real 8 cards.

### Do not train a model that can see the opponent's hand

The local simulator will happily tell you the opponent's hand, next card and
elixir: `b.hand(1)`, `b.next_card(1)`, `b.elixir(1)`. **Do not feed any of these
into your model.** The server never sends them, so a model that learned to rely on
them will be missing its inputs in every real match.

Build your model's inputs only from `battle.view(seat).observe()` (or the other
methods on `battle.view(seat)`). That view cannot see the opponent's hidden
information, so if your inputs come from it you are safe. The same goes for the
opponent you train against: give it its own `battle.view(...)`, not the raw
battle.

Also leave `battle.spectator_entities()` alone. It is the real, unflipped board,
meant for drawing and debugging, and it does not match what your agent sees.

### A correct training loop

Both seats work locally the way they do on the server: `b.view(0)` and `b.view(1)`
each show that player at the bottom, and `b.step(action0, action1)` takes each
player's action in its own frame. One policy therefore plays both seats in
self-play with no flipping.

```python
import random
import cr_sim

DECK = ["knight", "archers", "giant", "musketeer", "valkyrie", "minions", "wizard", "minipekka"]

def policy(obs):
    """Observation dict in, action out. Works unchanged on the server."""
    playable = [i for i, ok in enumerate(obs["legal"]) if ok]
    if not playable or random.random() < 0.9:
        return None
    return (random.choice(playable), random.uniform(2, 16), random.uniform(9, 14))

b = cr_sim.Battle()
b.reset(seed=random.getrandbits(32), deck0=DECK, deck1=DECK)   # a new seed every match
views = [b.view(0), b.view(1)]            # each player sees itself at the bottom
outcome = 0
while outcome == 0:
    outcome = b.step(policy(views[0].observe()), policy(views[1].observe()))
print(views[0].result(), views[0].crowns())   # e.g. "win" (3, 1), from player 0's side
```

Use a different seed for each training match. The seed fixes the order your cards
come out in, so training on one seed teaches a model one opening hand.

On the server, the same `policy` plugs straight into the socket loop:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("wss://<your-arena-host>") as ws:
        await ws.send(json.dumps({"t": "join", "name": "my-team", "deck": DECK}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg["t"] == "obs":
                obs = msg["obs"]
                action = policy(obs)
                await ws.send(json.dumps({"t": "act", "tick": obs["tick"],
                                          "action": list(action) if action else None}))
            elif msg["t"] == "result":
                print(msg["result"], msg["crowns"], msg["rating"])
            elif msg["t"] == "error":
                raise SystemExit(msg["msg"])

asyncio.run(main())
```

One more thing to match: **use the same simulator build as the server.** A wheel
built from a different commit can behave slightly differently from the one the
server runs.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `error`: "a deck is required" or "invalid deck: …" | The `deck` in your `join` is missing or illegal. The message names the problem. |
| `error`: "expected join or leaderboard" | Your first message was not a `join`. |
| `error`: "removed: no reply to 10 turns in a row" | Your agent stopped answering. Reply to every observation, with a `null` action when you have nothing to do. |
| Connected, but nothing happens | You are waiting in the queue for a second agent to be free. |
| The connection closes right after connecting | No `join` arrived within 30 seconds, or it was refused. |
| Your cards never appear | Read `last_action` in the next observation: it says why the move was ignored. If your code flips `y` for a "top seat", remove that. |
| `last_action` is always `malformed` | Your reply has no `tick`, or the slot is not a whole number, or the action is not a list of three values. |
| `last_action` is often `missed` | Your agent takes more than 2 seconds to answer. |
| You lose matches you were not in | You disconnected mid-match (a forfeit), or someone else is using your name. |
| Matches take a long time | Your agent is slow to answer, or stays silent on ticks where it has no move. Pass with a `null` action instead. |

You can also ask for the standings without joining: send
`{"t": "leaderboard"}` as your first message and the server replies with the
table and closes.

# cr-sim

A deterministic, fixed-point **Clash-Royale-style battle simulator** built for
reinforcement-learning coursework and competition. Native Rust core, Python API.

- **Deterministic**: all gameplay math is Q16.16 fixed-point, so a match is
  bit-identical across machines given the same seed + action log. Replays and
  the competition server agree with every student's local run.
- **Fast**: native Rust engine; trains fine on modest laptops.
- **Accessible**: `pip install` a prebuilt wheel — no Rust toolchain needed.
  Plain Python API with zero required deps; optional `gymnasium`/`pettingzoo`
  adapters for those who want them.

Status: scaffolding + fixed-point core landing. Engine, env API, competition
server, and web replay viewer in progress.

## The seat frame: every agent is the bottom player

What an agent reads and what it sends are in its own seat's frame. Its own side is
the bottom half (`y < 15`), entities it owns are owner `0`, and crowns read
`(mine, theirs)`. For the seat that is really on top, the simulator mirrors the
board on the way out and the actions on the way in.

```python
import cr_sim

b = cr_sim.Battle()
b.reset(seed=1, deck0=deck, deck1=deck)       # a deck for each player is required
v0, v1 = b.view(0), b.view(1)                 # each sees itself at the bottom
b.step(policy(v0.observe()), policy(v1.observe()))   # same policy, both seats
print(v0.result(), v1.result())               # "win"/"loss"/"draw", or None while running
```

- `view(seat).observe()` is exactly what the competition server sends an agent,
  and it never says which seat it is.
- `step(action0, action1)` takes each action in that player's own frame.
- The real, unmirrored board is `Battle.spectator_entities()` and
  `spectator_projectiles()`. Those are for rendering and debugging. Do not build
  agent inputs from them.
- `Battle.outcome()` and `Battle.crowns()` are the referee's view: `1` means seat 0
  won, and crowns are `(seat 0, seat 1)`.

The engine is exactly mirror-symmetric (it is tested to be), so a game seen from
the top seat this way is indistinguishable from one seen from the bottom.

## Decks

`reset` needs a deck for each player: a list of 8 different playable card names
with at most one champion, or the word `"default"` for a built-in deck. Leaving a
deck out is an error, as it is on the tournament server.

```python
b.reset(seed, my_deck, "default")
cr_sim.Battle().check_deck(my_deck)           # raises ValueError saying what is wrong
```

## Ignored moves

A move that cannot be carried out is ignored and spends nothing, and the next
observation says so. `observe()["last_action"]` (also `view.last_action()`) is
`"ok"`, `"none"` (no move was sent) or the reason: `"not_enough_elixir"`,
`"not_your_side"`, `"bad_slot"`, `"nothing_to_mirror"`, `"ability_unavailable"`.

`legal` only says which cards you can afford. It does not say where they may go.

## Do not train a model that can see the opponent's hand

The raw `Battle` will tell you the opponent's hand, next card and elixir
(`b.hand(1)`, `b.next_card(1)`, `b.elixir(1)`). The tournament server never sends
them. A model trained with them as input depends on information it will not have
in a real match.

Build your model's inputs from `b.view(seat)` only. It cannot see the opponent's
hidden information. Give the opponent you train against its own view too.

## Stepping many battles at once

`BatchBattle` exists purely for throughput. It decides nothing about rewards,
observations or action encodings, and each battle in it plays out exactly as it
would stepped alone with `Battle.step`.

```python
import cr_sim

bb = cr_sim.BatchBattle(256)            # threads=None: one worker per core
bb.reset(range(256), deck, deck)        # one seed per battle; decks are required
outs = bb.step(acts0, acts1)            # one tick; each list in its own seat's frame
for i, o in enumerate(outs):
    if o:                               # finished battles are left untouched
        bb[i].reset(next_seed(), deck, deck)
obs = bb[7].view(0).observe()           # bb[i] is an ordinary Battle
```

`step` advances every battle one tick across CPU cores with the GIL released.
`bb.outcomes()`, `bb.done()`, `bb.ticks()`, `bb.crowns()` and `bb.spectator_entities()`
return one entry per battle in a single call. Results do not depend on the
thread count.

## Dev build

```bash
cd gym
python3 -m venv .venv && . .venv/bin/activate
pip install maturin
maturin develop --release
python -c "import cr_sim; print(cr_sim.BuildCheck.fixed_selftest())"  # ~1.41421
```

# cr-rl-arena

A reinforcement-learning playground built around a **deterministic
Clash-Royale-style battle simulator**, plus a **tournament server** that plays
agents against each other and ranks them by Elo. Built for a hackathon where students write RL
agents; this repo gives them the environment and the competition — not the agents.

The repository has two independent components:

| | What it is | Language | Install |
|---|---|---|---|
| [`gym/`](gym/) | The simulator — the RL environment students train against | Rust core + Python API | `pip install ./gym` |
| [`server/`](server/) | The tournament server — pairs agents, runs authoritative matches, tracks Elo | Python (uses `gym`) | `pip install ./server` |

## Architecture

```
            gym/data/cards.json   (real card stats, one editable source)
                     │ compiled in
                     ▼
     ┌───────────────────────────────────────────┐
     │  cr_sim core — Rust, fixed-point, deterministic │
     │  arena · cards · engine · env                   │
     └───────────────────────────────────────────┘
          │ builds from one codebase
          ▼
     cr_sim  (native Python extension via PyO3/maturin)
          │                                   │
          │ import cr_sim                      │ import cr_sim
          ▼                                   ▼
   student's RL agent                  server/  (tournament server)
   trains locally, fast                pairs agents · authoritative
                                       matches · Elo · replay logs
```

**The one invariant that ties it together:** the game logic lives in exactly one
place — the `cr_sim` engine — and it is **fixed-point deterministic**. The same
code produces bit-identical matches whether it runs inside a student's training
loop or inside the competition server. A match is fully described by its
`(seed, action-log)`, so every tournament match can be replayed and audited.

## Quickstart

```bash
# 1. Build & install the gym (needs a Rust toolchain once; students get wheels)
pip install maturin
cd gym && maturin develop --release && cd ..

# 2. Run the simulator directly
python -c "import cr_sim; b=cr_sim.Battle(); b.reset(0, 'default', 'default'); print(b.step((0,9,8), None))"

# 3. Start the competition server
pip install ./server
cr-arena                      # listens on ws://0.0.0.0:8765

# 4. Point agents at it (two terminals)
python server/examples/random_agent.py ws://localhost:8765 alice
python server/examples/random_agent.py ws://localhost:8765 bob
```

See [`gym/README.md`](gym/README.md) for the environment API,
[`server/CONNECTING.md`](server/CONNECTING.md) for how to connect an agent to the
tournament server, and [`server/README.md`](server/README.md) for running it.

## What an agent does

An agent connects to the server, receives an **observation** each decision step
(elixir, hand, legal moves, every unit/tower on the field, crowns, clock) and
returns an **action** — `(hand_slot, x, y)` to deploy a card at a tile, or
nothing. Every agent plays as the bottom player: the simulator mirrors the board
for whoever is really on top, so one policy plays either seat unchanged. The simulator provides the primitives (legal-move mask, tile snapping,
full board state); the learning is up to the agent.

## License

MIT — see [LICENSE](LICENSE).

> Card stats are real gameplay balance numbers at Tournament Standard (level 11),
> kept in a single editable file (`gym/data/cards.json`). This project reproduces
> game *mechanics* for research; it ships no game art, audio, or assets.

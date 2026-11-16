"""Run a match between two simple bots and dump a compact JSON replay trace.

Usage:
    python examples/record_trace.py [seed] [out.json]

The trace feeds the web viewer (viewer/index.html). Schema:
    {
      "meta": {arena w/h, river_y, bridges, tps, fps, cards:[names...]},
      "frames": [ {t, crowns:[a,b], elixir:[a,b],
                   ents:[[owner, cardIdx, x, y, hpFrac, flags], ...]} ... ]
    }
  flags bitfield: 1=flying, 2=tower, 4=deploying
"""
import json
import random
import sys

import cr_sim


def bot(b, player, rng):
    """Deploy a random affordable troop toward a lane when elixir is plentiful."""
    if b.elixir(player) < 4.5:
        return None
    legal = b.legal(player)
    idxs = [i for i, ok in enumerate(legal) if ok]
    if not idxs or rng.random() < 0.6:
        return None
    slot = rng.choice(idxs)
    lane = rng.choice([3.5, 14.5]) + rng.uniform(-1.0, 1.0)   # push a lane (bridge in front)
    # each seat places in its own frame, where its own side is always the bottom
    return (slot, lane, rng.uniform(9, 14))


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    out_path = sys.argv[2] if len(sys.argv) > 2 else "viewer/trace.json"

    b = cr_sim.Battle()
    b.reset(seed, "default", "default")   # the built-in deck for both players
    cards = b.deployable_cards() + ["princess_tower", "king_tower"]
    card_idx = {n: i for i, n in enumerate(cards)}

    rng0 = random.Random(seed * 2 + 1)
    rng1 = random.Random(seed * 2 + 2)

    fps_divisor = 2  # record every 2nd tick -> 10 fps
    frames = []
    out = 0
    t = 0
    maxt = cr_sim.REGULATION_TICKS + cr_sim.OVERTIME_TICKS + 5
    while out == 0 and t < maxt:
        out = b.step(bot(b, 0, rng0), bot(b, 1, rng1))
        t += 1
        if t % fps_divisor == 0:
            ents = []
            for (owner, card, x, y, hp, mhp, flying, is_tower, deploying, eid, hw, hh) in b.spectator_entities():
                flags = (1 if flying else 0) | (2 if is_tower else 0) | (4 if deploying else 0)
                ents.append([owner, card_idx.get(card, 0), round(x, 2), round(y, 2),
                             round(hp / mhp, 3) if mhp else 0.0, flags, eid, round(hw, 2)])
            frames.append({
                "t": t,
                "crowns": list(b.crowns()),
                "elixir": [round(b.elixir(0), 2), round(b.elixir(1), 2)],
                "ents": ents,
            })

    trace = {
        "meta": {
            "seed": seed,
            "w": cr_sim.WIDTH, "h": cr_sim.HEIGHT,
            "river_y": cr_sim.RIVER_Y, "river_half": cr_sim.RIVER_HALF,
            "bridges": cr_sim.BRIDGES, "bridge_half": cr_sim.BRIDGE_HALF, "level": 11,
            "tps": cr_sim.TICKS_PER_SECOND, "fps": cr_sim.TICKS_PER_SECOND // fps_divisor,
            "cards": cards,
            "outcome": out, "end_tick": t, "crowns": list(b.crowns()),
        },
        "frames": frames,
    }
    import os
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(trace, f, separators=(",", ":"))
    print(f"wrote {out_path}: {len(frames)} frames, outcome={out}, "
          f"crowns={b.crowns()}, size={os.path.getsize(out_path)//1024} KiB")


if __name__ == "__main__":
    main()

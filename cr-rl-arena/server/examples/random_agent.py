"""A minimal reference agent: connects, joins the queue, and plays random legal
moves forever. Shows the full client protocol students build their RL agent on.

    python examples/random_agent.py [ws://host:port] [name]
"""
import asyncio
import json
import random
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8765"
NAME = sys.argv[2] if len(sys.argv) > 2 else f"random-{random.randint(100, 999)}"


# A deck is required to join: 8 different playable cards, at most one champion.
DECK = ["knight", "archers", "giant", "musketeer", "valkyrie", "minions", "wizard", "minipekka"]


def policy(obs):
    """obs: {elixir, hand, hand_cost, next_card, legal, crowns, entities, ...}
    Return [slot, x, y] to deploy hand[slot] at tile (x,y), or None to wait.

    You always play as the bottom player: your own side is y < 15, your towers
    are at low y, and entities you own have owner 0. This is true in every match,
    so there is no seat to check."""
    legal = obs.get("legal", [])
    playable = [i for i, ok in enumerate(legal) if ok]
    if not playable or random.random() < 0.6:
        return None
    slot = random.choice(playable)
    return [slot, random.uniform(2.0, 16.0), random.uniform(9.0, 14.0)]


async def main():
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "join", "name": NAME, "deck": DECK}))
        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("t")
            if t == "obs":
                # answer every tick, and say which tick the answer is for
                obs = msg["obs"]
                await ws.send(json.dumps({"t": "act", "tick": obs["tick"], "action": policy(obs)}))
            elif t == "joined":
                print(f"joined as {msg['name']} (rating {msg['rating']})")
            elif t == "start":
                print(f"match vs {msg['opponent']}")
            elif t == "result":
                print(f"  {msg['result'].upper()} {msg['crowns']}  rating {msg['rating']} "
                      f"({msg['delta']:+})  replay: /replay?id={msg['match']}")
            elif t == "aborted":
                print(f"  match void: {msg['reason']}")
            elif t == "error":
                print("error:", msg.get("msg"))
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

import random
import cr_sim

# ============ card knowledge (guesses — we'll fix once we see the real deck) ============
SPELLS = {"fireball", "arrows", "zap", "the_log", "log", "poison", "rocket",
          "lightning", "earthquake", "giant_snowball", "snowball", "tornado",
          "freeze", "barbarian_barrel", "royal_delivery", "void"}
BUILDINGS = {"barbarian_hut", "goblin_hut", "furnace", "tombstone", "cannon",
             "tesla", "inferno_tower", "bomb_tower", "mortar", "x_bow",
             "elixir_collector", "goblin_cage"}

# ============ helpers ============
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def units(obs, owner):
    # all non-tower units for one side, as (name, x, y)
    out = []
    for e in obs["entities"]:
        if e[0] == owner and "tower" not in e[1]:
            out.append((e[1], e[2], e[3]))
    return out

def count_near(unit_list, x, y, r):
    count = 0
    for name, ux, uy in unit_list:
        if abs(ux - x) <= r and abs(uy - y) <= r:
            count += 1
    return count

def enemy_tower_hp(obs):
    left, right = 0, 0      # 0 means destroyed
    for e in obs["entities"]:
        if e[0] == 1 and e[1] == "princess_tower":
            if e[2] < 9:
                left = e[4]
            else:
                right = e[4]
    return left, right

def pick(obs, kind, cheapest=True):
    # kind: "troop", "spell", or "building"
    best = None
    for i in range(4):
        if not obs["legal"][i]:
            continue
        name = obs["hand"][i]
        if kind == "spell" and name not in SPELLS:
            continue
        if kind == "building" and name not in BUILDINGS:
            continue
        if kind == "troop" and (name in SPELLS or name in BUILDINGS):
            continue
        if best is None:
            best = i
        elif cheapest and obs["hand_cost"][i] < obs["hand_cost"][best]:
            best = i
        elif not cheapest and obs["hand_cost"][i] > obs["hand_cost"][best]:
            best = i
    return best

# ============ old bots (for comparison) ============
def do_nothing(obs):
    return None

def random_bot(obs):
    choices = [i for i in range(4) if obs["legal"][i]]
    if not choices:
        return None
    return (random.choice(choices), random.randint(0, 17), random.randint(0, 14))

def my_bot(obs):
    if obs["elixir"] < 8:
        return None
    s = pick(obs, "troop")
    if s is None:
        return None
    return (s, 3, 13)

def my_bot2(obs):
    threats = [u for u in units(obs, 1) if u[2] < 16]
    if threats:
        s = pick(obs, "troop")
        if s is None:
            return None
        name, tx, ty = threats[0]
        return (s, clamp(int(tx), 0, 17), clamp(int(ty), 0, 14))
    return my_bot(obs)

# ============ THE EVIL BOT (v1, kept for benchmarking) ============
class EvilBotV1:
    # a class so it can remember when it last played a card

    def __init__(self, cooldown=20):
        self.cooldown = cooldown
        self.last_play = -9999

    def __call__(self, obs):
        if obs["tick"] < self.last_play:      # new game started, reset memory
            self.last_play = -9999
        if obs["tick"] - self.last_play < self.cooldown:
            return None
        action = self.decide(obs)
        if action is not None:
            self.last_play = obs["tick"]
        return action

    def decide(self, obs):
        elixir = obs["elixir"]
        fast = obs["phase"] != "single"
        mine = units(obs, 0)
        theirs = units(obs, 1)

        # ---- 1. DEFEND: deal with the enemy closest to our towers ----
        target = None
        for u in theirs:
            if u[2] < 16 and (target is None or u[2] < target[2]):
                target = u
        if target is not None:
            name, tx, ty = target
            x = clamp(int(tx), 0, 17)
            y = clamp(int(ty), 0, 14)
            crowd = count_near(theirs, tx, ty, 3)
            defenders = count_near(mine, tx, ty, 4)
            if crowd >= 3:
                s = pick(obs, "spell")
                if s is not None:
                    return (s, x, y)
            if defenders < crowd:
                s = pick(obs, "building")
                if s is not None:
                    return (s, 9, 9)          # bait them to the middle
                s = pick(obs, "troop", cheapest=True)
                if s is not None:
                    return (s, x, y)

        # ---- 2. COUNTER-PUSH: back up our troops that crossed the river ----
        for name, ax, ay in mine:
            if ay >= 16 and elixir >= 5:
                lane_x = 3 if ax < 9 else 14
                if count_near(mine, lane_x, 13, 3) == 0:
                    s = pick(obs, "troop", cheapest=False)
                    if s is not None:
                        return (s, lane_x, 14)
                break

        # ---- 3. BIG PUSH on the weaker tower when elixir is nearly full ----
        threshold = 7 if fast else 9
        if elixir >= threshold:
            left, right = enemy_tower_hp(obs)
            lane_x = 3 if left <= right else 14
            s = pick(obs, "troop", cheapest=False)
            if s is not None:
                return (s, lane_x, 14)
            s = pick(obs, "building")
            if s is not None:
                return (s, 9, 9)
            s = pick(obs, "spell")            # don't let a spell clog the hand forever
            if s is not None and theirs:
                name, ex, ey = theirs[0]
                return (s, clamp(int(ex), 0, 17), clamp(int(ey), 0, 14))

        return None

# ============ THE EVIL BOT (v2: defensive, elixir-disciplined) ============
import json, os
_CARDS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "gym", "data", "cards.json")))["cards"]

def hits_air(name):
    c = _CARDS.get(name, {})
    return c.get("targets") in ("air", "both") and not c.get("target_buildings_only")

def power(name):
    # rough total hit points a card puts on the board
    c = _CARDS.get(name, {})
    return c.get("hp", 0) * c.get("count", 1)

def enemy_troops(obs):
    # (name, x, y, hp, flying) for every enemy non-tower unit
    return [(e[1], e[2], e[3], e[4], e[6]) for e in obs["entities"]
            if e[0] == 1 and "tower" not in e[1]]

class EvilBot:
    # Plays defense first: waits for the enemy to commit, answers with the cheapest
    # card that can actually deal with what is coming, and keeps an elixir reserve.

    def __init__(self, cooldown=10, reserve=3):
        self.cooldown = cooldown      # ticks between plays (20 ticks = 1 second)
        self.reserve = reserve        # elixir kept back when not under threat
        self.last_play = -9999

    def __call__(self, obs):
        if obs["tick"] < self.last_play:      # new game started, reset memory
            self.last_play = -9999
        if obs["tick"] - self.last_play < self.cooldown:
            return None
        action = self.decide(obs)
        if action is not None:
            self.last_play = obs["tick"]
        return action

    # ---- defense ----
    def defend(self, obs):
        enemies = enemy_troops(obs)
        incoming = [u for u in enemies if u[2] < (18 if u[4] else 15)]
        if not incoming:
            return None
        lead = min(incoming, key=lambda u: u[2])          # closest to our towers
        group = [u for u in enemies if abs(u[1] - lead[1]) <= 4 and abs(u[2] - lead[2]) <= 4]
        threat = sum(u[3] for u in group)
        if threat < 300:                                   # a lone scrap, towers can take it
            return None
        air = any(u[4] for u in group)
        mine = [(n, x, y) for n, x, y in units(obs, 0) if abs(x - lead[1]) <= 5 and abs(y - lead[2]) <= 5]
        covered = sum(_CARDS.get(n, {}).get("hp", 0) for n, _, _ in mine)
        if covered >= threat * 0.8:                        # already answered, save elixir
            return None

        need = (threat - covered) * 0.5
        options = []
        for i in range(4):
            if not obs["legal"][i]:
                continue
            name = obs["hand"][i]
            if name in SPELLS:
                continue
            if name in BUILDINGS:
                # a building only distracts: good against building-targeters, useless vs air
                if name == "barbarian_hut" and all(_CARDS.get(u[0], {}).get("target_buildings_only") for u in group):
                    options.append((i, obs["hand_cost"][i], 10**6, name))
                continue
            if air and not hits_air(name):
                continue
            options.append((i, obs["hand_cost"][i], power(name), name))
        if not options:
            return None
        enough = [o for o in options if o[2] >= need]
        best = min(enough, key=lambda o: (o[1], -o[2])) if enough else max(options, key=lambda o: o[2])
        i, _, _, name = best
        x = clamp(int(lead[1]), 1, 16)
        if name in BUILDINGS:
            return (i, 9, 9)
        # drop it a bit behind the enemy, close to our towers so they help
        y = clamp(int(lead[2]) - 3, 6, 12)
        return (i, x, y)

    # ---- offense ----
    def attack(self, obs, fast):
        elixir = obs["elixir"]
        if elixir < (8 if fast else 9.5):                  # only push from a full bar
            return None
        left, right = enemy_tower_hp(obs)
        lane_x = 3 if left <= right else 14
        s = pick(obs, "troop", cheapest=False)
        if s is None:
            return None
        return (s, lane_x, 11)                             # behind the bridge, not on it

    def decide(self, obs):
        fast = obs["phase"] != "single"
        action = self.defend(obs)
        if action is not None:
            return action
        # leave breathing room for a defense unless we are about to waste income at 10
        if obs["elixir"] - self.reserve < 0 and obs["elixir"] < 9.5:
            return None
        return self.attack(obs, fast)

# ============ testing ============
import sys
from replay import Recorder, serve

seen_cards = set()
problems = {}

def watched(bot):
    # wraps a bot to note the cards it sees and any of its moves the sim rejected
    def run(obs):
        seen_cards.update(obs["hand"])
        seen_cards.add(obs["next_card"])
        if obs["last_action"] not in ("ok", "none"):
            problems[obs["last_action"]] = problems.get(obs["last_action"], 0) + 1
        return bot(obs)
    return run

rec = Recorder()     # every match below is saved to gym/viewer/replays/

def test(bot0, bot1, name0, name1, games=30):
    counts = {"win": 0, "loss": 0, "draw": 0}
    for seed in range(games):
        counts[rec.play(watched(bot0), bot1, seed, name0, name1)] += 1
    print(f"{name0} vs {name1}:".ljust(16), counts)

test(EvilBot(), random_bot, "evil", "random")
test(EvilBot(), my_bot2,    "evil", "v2")
print("cards in default deck:", sorted(seen_cards))
print("evil's rejected moves:", problems)

if "--no-view" not in sys.argv:
    serve()          # open the replay viewer in the browser; Ctrl+C to stop

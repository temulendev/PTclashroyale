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

# ============ THE EVIL BOT ============
class EvilBot:
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

# ============ testing ============
seen_cards = set()
problems = {}

def play_game(bot0, bot1, seed):
    b = cr_sim.Battle()
    b.reset(seed, "default", "default")
    v0 = b.view(0)
    v1 = b.view(1)
    while v0.result() is None:
        o0 = v0.observe()
        seen_cards.update(o0["hand"])
        seen_cards.add(o0["next_card"])
        if o0["last_action"] not in ("ok", "none"):
            problems[o0["last_action"]] = problems.get(o0["last_action"], 0) + 1
        b.step(bot0(o0), bot1(v1.observe()))
    return v0.result()

def test(bot0, bot1, name, games=30):
    counts = {"win": 0, "loss": 0, "draw": 0}
    for seed in range(games):
        counts[play_game(bot0, bot1, seed)] += 1
    print(name, counts)

test(EvilBot(), random_bot, "evil vs random:")
test(EvilBot(), my_bot2,    "evil vs v2:    ")
print("cards in default deck:", sorted(seen_cards))
print("evil's rejected moves:", problems)

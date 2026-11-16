import cr_sim

# start a game, both players using the default deck
b = cr_sim.Battle()
b.reset(1, "default", "default")

# what player 0 sees
me = b.view(0)
obs = me.observe()

# print every piece of the observation
for key in obs:
    print(key, "->", obs[key])
    print()

# now let a whole game play out where nobody does anything
ticks = 0
while me.result() is None and ticks < 100000:
    b.step(None, None)
    ticks += 1

print("game ended after", ticks, "ticks")
print("result for me:", me.result())
print("crowns:", b.crowns())

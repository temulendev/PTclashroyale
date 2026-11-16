"""`BatchBattle` must be a pure speed-up: every battle in it has to follow
exactly the trajectory the same battle follows when stepped alone with
`Battle.step`, whatever the thread count.
"""
import random

import pytest

import cr_sim

N = 12


def _fingerprint(b):
    return (b.tick, b.outcome(), b.crowns(), round(b.elixir(0), 6), round(b.elixir(1), 6),
            tuple(b.spectator_entities()), tuple(b.hand(0)), tuple(b.hand(1)))


def _actions(rng, n):
    """Random deploys for each seat (None most of the time)."""
    def one(player):
        if rng.random() < 0.8:
            return None
        # each seat places in its own frame, where its side is always y < 15
        return (rng.randint(0, 3), rng.randint(0, 17) + 0.5, rng.randint(1, 13) + 0.5)
    return [one(0) for _ in range(n)], [one(1) for _ in range(n)]


@pytest.mark.parametrize("threads", [1, 2, None])
def test_batch_matches_independent_battles(threads):
    rng = random.Random(2)
    bb = cr_sim.BatchBattle(N, threads=threads)
    assert len(bb) == N and bb.threads >= 1
    seeds = [100 + i for i in range(N)]
    bb.reset(seeds, "default", "default")
    solo = []
    for s in seeds:
        b = cr_sim.Battle()
        b.reset(s, "default", "default")
        solo.append(b)
    for _ in range(1000):
        acts0, acts1 = _actions(rng, N)
        outs = bb.step(acts0, acts1)
        assert outs == [b.step(a0, a1) for b, a0, a1 in zip(solo, acts0, acts1)]
        assert outs == bb.outcomes()
    assert bb.ticks() == [b.tick for b in solo]
    assert bb.crowns() == [b.crowns() for b in solo]
    assert bb.spectator_entities() == [b.spectator_entities() for b in solo]
    for i in range(N):
        assert _fingerprint(bb[i]) == _fingerprint(solo[i])


def test_finished_battles_are_left_untouched():
    bb = cr_sim.BatchBattle(2, threads=2)
    bb.reset([3, 4], "default", "default")
    total = cr_sim.REGULATION_TICKS + cr_sim.OVERTIME_TICKS
    outs = [0, 0]
    for _ in range(total + 5):
        outs = bb.step()
    assert all(o in (1, 2, 3) for o in outs) and bb.done() == [True, True]
    ticks = bb.ticks()
    assert bb.step() == outs and bb.ticks() == ticks


def test_batch_elements_are_ordinary_battles():
    bb = cr_sim.BatchBattle(3, threads=1)
    bb.reset([1, 2, 3], "default", "default")
    assert isinstance(bb[0], cr_sim.Battle) and bb[-1] is bb.battles()[2]
    for _ in range(40):
        bb.step()
    bb[1].reset(9, "default", "default")  # per-battle reset leaves the others alone
    assert bb.ticks() == [40, 0, 40]
    assert len(bb[0].view(0).hand()) == 4  # the fog-of-war view works per battle
    assert bb.done() == [False, False, False]
    with pytest.raises(IndexError):
        bb[3]


def test_batch_validates_lengths():
    bb = cr_sim.BatchBattle(2, threads=1)
    with pytest.raises(ValueError):
        bb.reset([1], "default", "default")
    bb.reset([1, 2], "default", "default")
    with pytest.raises(ValueError):
        bb.step([None], None)

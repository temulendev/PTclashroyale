"""The core guarantee: a match is a pure function of (seed, action log).

Same seed + same actions => identical trajectory, tick for tick. This is what
lets a replay recorded on a student's laptop re-run bit-identically on the
competition server.
"""
import cr_sim


def _signature(seed, script):
    """Run a scripted match and return a hashable fingerprint of its trajectory."""
    b = cr_sim.Battle()
    b.reset(seed, "default", "default")
    sig = []
    out = 0
    t = 0
    while out == 0 and t < 1200:
        a0 = script.get((0, t))
        a1 = script.get((1, t))
        out = b.step(a0, a1)
        if t % 17 == 0:
            ents = b.spectator_entities()
            sig.append((t, b.crowns(), round(b.elixir(0), 4),
                        tuple((e[0], e[1], round(e[2], 3), round(e[3], 3), e[4]) for e in ents)))
        t += 1
    return out, t, tuple(sig)


def _script():
    # a fixed, reproducible set of deploys for both players
    return {
        (0, 10): (0, 5.0, 5.0),
        (0, 80): (1, 9.0, 4.0),
        (0, 160): (2, 13.0, 6.0),
        # both seats give positions in their own frame (own side is y < 15)
        (1, 40): (0, 6.0, 5.0),
        (1, 120): (1, 12.0, 4.0),
        (1, 200): (2, 9.0, 6.0),
    }


def test_same_seed_same_trajectory():
    s = _script()
    a = _signature(1234, s)
    b = _signature(1234, s)
    assert a == b, "identical seed+actions must produce identical trajectories"


def test_different_seed_differs():
    s = _script()
    a = _signature(1, s)
    b = _signature(2, s)
    # deck shuffle differs by seed, so trajectories should differ
    assert a != b


def test_terminates_and_well_formed():
    b = cr_sim.Battle()
    b.reset(7, "default", "default")
    assert len(b.spectator_entities()) == 6  # 2 kings + 4 princess towers
    assert len(b.hand(0)) == 4
    out, t = 0, 0
    while out == 0 and t < cr_sim.REGULATION_TICKS + cr_sim.OVERTIME_TICKS + 5:
        out = b.step(None, None)
        t += 1
    assert out in (1, 2, 3)
    assert b.done()

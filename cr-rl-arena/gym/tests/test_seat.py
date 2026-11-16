"""The seat frame: every agent plays as the bottom player, whichever seat it has.

Observations and actions for the seat that is really on top are mirrored by the
simulator, so one policy plays either seat unchanged and is never told which
seat it has. The unmirrored board is only available through `spectator_*`.
"""
import cr_sim

DECK = ["knight", "archers", "giant", "musketeer", "valkyrie", "minions", "wizard", "minipekka"]
H = cr_sim.HEIGHT


def _battle(seed=5):
    b = cr_sim.Battle()
    b.reset(seed, DECK, DECK)
    return b


def _wait_for_elixir(b, n=120):
    for _ in range(n):
        b.step(None, None)


def test_both_seats_see_the_same_board_at_kickoff():
    b = _battle()
    o0, o1 = b.view(0).observe(), b.view(1).observe()
    assert o0["entities"] == o1["entities"]
    assert o0.keys() == o1.keys()
    for k in ("tick", "elixir", "phase", "crowns", "done", "outcome"):
        assert o0[k] == o1[k]


def test_my_side_is_always_the_bottom_and_mine_is_owner_zero():
    b = _battle()
    for seat in (0, 1):
        ents = b.view(seat).entities()
        mine, theirs = ents[:3], ents[3:]
        assert all(e[0] == 0 and e[3] < H / 2 for e in mine)      # my towers: owner 0, low y
        assert all(e[0] == 1 and e[3] > H / 2 for e in theirs)
        assert b.view(seat).towers() == ents
    # the spectator board is NOT mirrored: seat 1's towers really are at the top
    top = [e for e in b.spectator_entities() if e[0] == 1]
    assert all(e[3] > H / 2 for e in top)


def test_the_observation_never_says_which_seat():
    b = _battle()
    for seat in (0, 1):
        o = b.view(seat).observe()
        assert "player" not in o and "seat" not in o
        assert o == b.observe(seat)                               # one observation, two spellings
        assert o["hand"] == b.hand(seat) and o["elixir"] == b.elixir(seat)


def test_same_action_lands_on_mirror_image_tiles_for_both_seats():
    """Including a point exactly on a tile boundary, which naive mirroring gets wrong."""
    for x, y in ((5.5, 9.5), (12.0, 14.0), (3.0, 2.0), (16.9, 7.25)):
        b = _battle()
        _wait_for_elixir(b)
        slot = 0
        assert b.legal(0)[slot] and b.legal(1)[slot]
        b.step((slot, x, y), (slot, x, y))
        own = []
        for seat in (0, 1):
            units = [e for e in b.view(seat).entities() if not e[7] and e[0] == 0]
            assert units, f"seat {seat}: nothing was deployed at {(x, y)}"
            # every unit this seat just placed is on its own (bottom) half
            assert all(u[3] < 15 for u in units)
            own.append(sorted((u[1], u[2], u[3]) for u in units))
        if b.hand(0) != b.hand(1):
            continue                                              # different cards: positions only comparable per card
        assert own[0] == own[1]
    # and on the real board the two deploys are mirror images of each other
    b = _battle()
    _wait_for_elixir(b)
    b.step((0, 6.0, 10.0), (0, 6.0, 10.0))
    ys = {seat: [e[3] for e in b.spectator_entities() if not e[7] and e[0] == seat] for seat in (0, 1)}
    assert ys[0] and ys[1] and max(ys[0]) < 15 and min(ys[1]) > 17


def test_placing_on_the_far_half_is_ignored_for_both_seats():
    b = _battle()
    _wait_for_elixir(b)
    before = (b.elixir(0), b.elixir(1))
    b.step((0, 6.0, 25.0), (0, 6.0, 25.0))                        # the opponent's half, in each seat's frame
    assert b.elixir(0) > before[0] - 0.5 and b.elixir(1) > before[1] - 0.5
    assert all(e[7] for e in b.spectator_entities())              # still only towers


def test_crowns_outcome_and_result_are_from_my_side():
    b = _battle(seed=3)
    out, t = 0, 0
    while out == 0:
        # only seat 1 plays, so seat 1 should come out ahead
        act = (t // 40 % 4, 3.5 + 11 * (t // 40 % 2), 13.5) if t % 40 == 0 else None
        out = b.step(None, act)
        t += 1
    v0, v1 = b.view(0), b.view(1)
    assert out == 2 and b.outcome() == 2                           # referee: seat 1 won
    assert (v0.result(), v1.result()) == ("loss", "win")
    assert (v0.outcome(), v1.outcome()) == (2, 1)
    assert v1.observe()["outcome"] == 1 and v0.observe()["outcome"] == 2
    c = b.crowns()
    assert v0.crowns() == c and v1.crowns() == c[::-1]
    assert v1.observe()["crowns"] == tuple(c[::-1]) and v1.crowns()[0] > v1.crowns()[1]


def test_result_is_none_while_running():
    b = _battle()
    assert b.view(0).result() is None and b.view(1).result() is None


def test_every_move_reports_what_happened_to_it():
    """An impossible move spends nothing, and the next observation says why."""
    b = _battle()
    v0, v1 = b.view(0), b.view(1)
    assert v0.observe()["last_action"] == "none"

    b.step((0, 6.0, 10.0), None)                                  # 5 elixir at kick-off buys nothing twice
    first = v0.last_action()
    assert first in ("ok", "not_enough_elixir") and v1.last_action() == "none"

    _wait_for_elixir(b)
    cases = [
        ((0, 6.0, 10.0), "ok"),
        ((0, 6.0, 25.0), "not_your_side"),                        # the opponent's half
        ((7, 6.0, 10.0), "bad_slot"),
        ((-1, 6.0, 10.0), "bad_slot"),                            # negative is a mistake, not "no move"
        (None, "none"),
        ((cr_sim.ABILITY_SLOT, 0.0, 0.0), "ability_unavailable"),  # no champion in this deck
    ]
    for action, want in cases:
        _wait_for_elixir(b, 300)                                  # enough for any card
        before = (b.elixir(0), b.elixir(1))
        b.step(action, action)
        for seat, v in ((0, v0), (1, v1)):                        # same answer from either seat
            assert v.last_action() == want == b.last_action(seat) == v.observe()["last_action"], (action, seat)
            spent = before[seat] - b.elixir(seat) > 0.5
            assert spent == (want == "ok"), (action, seat)

    # spend everything, then try again: cannot afford
    for _ in range(6):
        b.step((0, 6.0, 10.0), None)
    b.step((0, 6.0, 10.0), None)
    assert v0.last_action() == "not_enough_elixir"

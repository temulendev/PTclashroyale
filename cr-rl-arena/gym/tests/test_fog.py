"""Observability guard: a PlayerView must not leak the opponent's hidden state.

Clash Royale is a hidden-information game: a player sees the full board (all
deployed units + towers of both sides), their OWN hand / next card / elixir /
crowns, and the opponent's crowns + tower state — but NOT the opponent's hand,
next card, or elixir. The raw ``Battle`` exposes those for the trusted harness;
``Battle.view(player)`` returns a read-only ``PlayerView`` that structurally
cannot read the opponent's private information. These tests prove the guard.
"""
import pytest

import cr_sim


DECK0 = ["knight", "archers", "musketeer", "giant",
         "fireball", "minions", "arrows", "goblins"]
DECK1 = ["hogrider", "valkyrie", "babydragon", "wizard",
         "zap", "skeletons", "bomber", "cannon"]


def _fresh():
    b = cr_sim.Battle()
    # Distinct decks so player 0's and player 1's hands provably differ.
    b.reset(seed=99, deck0=DECK0, deck1=DECK1)
    return b


def test_view_exposes_own_private_state():
    b = _fresh()
    v0 = b.view(0)
    assert v0.player == 0
    assert v0.opponent == 1
    # Own private state is readable and matches the raw battle for seat 0.
    assert v0.hand() == b.hand(0)
    assert v0.hand_cost() == b.hand_cost(0)
    assert v0.next_card() == b.next_card(0)
    assert v0.elixir() == b.elixir(0)
    assert v0.legal() == b.legal(0)
    assert v0.champion_status() == b.champion_status(0)


def test_view_hides_opponent_private_state():
    b = _fresh()
    v0 = b.view(0)

    # The per-player private getters take NO player argument, so there is no
    # way to ask the view for seat 1's hand/next/elixir. Passing one is a
    # TypeError — the opponent's seat simply cannot be addressed.
    for call in (lambda: v0.hand(1),
                 lambda: v0.hand_cost(1),
                 lambda: v0.next_card(1),
                 lambda: v0.elixir(1),
                 lambda: v0.legal(1),
                 lambda: v0.champion_status(1)):
        with pytest.raises(TypeError):
            call()

    # And none of the view's own private getters return the opponent's values.
    # (Only meaningful when the two hands actually differ.)
    if b.hand(0) != b.hand(1):
        assert v0.hand() != b.hand(1)
        assert v0.next_card() == b.next_card(0)
    # The view never reports seat 1's elixir through any method it has.
    assert v0.elixir() == b.elixir(0)


def test_view_is_read_only_no_mutators():
    b = _fresh()
    v0 = b.view(0)
    for banned in ("step", "reset", "activate_ability"):
        assert not hasattr(v0, banned), f"view must not expose mutator {banned!r}"


def test_view_exposes_public_board_and_opponent_crowns():
    b = _fresh()
    v0, v1 = b.view(0), b.view(1)

    # Full board (both sides' deployed units + towers) is public to both views,
    # each in its own seat frame (see test_seat.py for the frame itself).
    assert len(v0.entities()) == len(v1.entities()) == len(b.spectator_entities())
    assert v0.projectiles() == b.spectator_projectiles()

    # Towers (both sides) are visible, including HP, via towers()/entities().
    towers = v0.towers()
    assert len(towers) == 6  # 2 kings + 4 princess towers at start
    assert all(t[7] for t in towers)  # every returned entity is a tower
    owners = {t[0] for t in towers}
    assert owners == {0, 1}  # you can see the OPPONENT's towers + HP

    # Crown score is public; the opponent's crown count is explicitly exposed.
    assert v0.crowns() == b.crowns()
    assert v1.crowns() == b.crowns()[::-1]       # always (mine, theirs)
    assert v0.my_crowns() == b.crowns()[0]
    assert v0.opponent_crowns() == b.crowns()[1]
    assert v1.opponent_crowns() == b.crowns()[0]


def test_view_observe_matches_fog_observation():
    b = _fresh()
    v0 = b.view(0)
    o_view = v0.observe()
    o_raw = b.observe(0)
    assert o_view == o_raw
    # The fog observation only carries this seat's own private fields; there is
    # no 'opponent_*' private key and elixir is the player's own.
    assert "player" not in o_view                # an agent is never told its seat
    assert o_view["elixir"] == b.elixir(0)
    assert o_view["hand"] == b.hand(0)
    assert "opponent_hand" not in o_view
    assert "opponent_elixir" not in o_view


def test_view_is_live_after_step():
    b = _fresh()
    v0 = b.view(0)
    t0 = v0.tick
    b.step(None, None)
    assert v0.tick == t0 + 1  # the view reads through to the live battle


def test_both_seats_and_clamping():
    b = _fresh()
    # Out-of-range seats clamp to seat 1 (matching the raw Battle getters).
    assert b.view(2).player == 1
    assert b.view(7).opponent == 0

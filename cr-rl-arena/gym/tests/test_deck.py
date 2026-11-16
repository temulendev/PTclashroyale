"""Deck legality: 8 different, playable cards, at most one champion."""
import pytest

import cr_sim

GOOD = ["knight", "archers", "giant", "musketeer", "valkyrie", "minions", "wizard", "minipekka"]


def _bad(deck, match):
    b = cr_sim.Battle()
    with pytest.raises(ValueError, match=match):
        b.check_deck(deck)
    with pytest.raises(ValueError, match=match):  # reset enforces the same rules
        b.reset(1, deck, GOOD)


def test_good_deck_is_accepted():
    b = cr_sim.Battle()
    assert b.check_deck(GOOD) is None
    b.reset(1, GOOD, GOOD)
    assert sorted(b.hand(0) + [b.next_card(0)]) != []


def test_wrong_size_rejected():
    _bad(GOOD[:7], "8 cards")


def test_unknown_card_rejected():
    _bad(GOOD[:7] + ["knigth"], "unknown card")


def test_duplicates_rejected():
    _bad(["knight"] * 8, "duplicate")
    _bad(GOOD[:7] + ["knight"], "duplicate")


@pytest.mark.parametrize("name", ["king_tower", "princess_tower", "golemite", "evo_knight"])
def test_non_cards_rejected(name):
    _bad(GOOD[:7] + [name], "not a playable card")


def test_a_deck_is_required_for_each_player():
    b = cr_sim.Battle()
    for args in ((1,), (1, GOOD), (1, None, GOOD)):
        with pytest.raises(ValueError, match="is required"):
            b.reset(*args)
    bb = cr_sim.BatchBattle(2, threads=1)
    with pytest.raises(ValueError, match="is required"):
        bb.reset([1, 2])


def test_default_keyword_gives_the_built_in_deck():
    b = cr_sim.Battle()
    b.reset(1, "default", "default")
    assert len(b.hand(0)) == 4 and len(b.hand(1)) == 4
    b.reset(1, GOOD, "default")                      # one of each is fine
    assert set(b.hand(0)) <= set(GOOD)
    with pytest.raises(ValueError, match="unknown deck"):
        b.reset(1, "defualt", GOOD)

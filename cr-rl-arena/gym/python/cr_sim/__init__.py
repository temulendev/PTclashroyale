"""cr_sim — deterministic Clash-Royale-style battle simulator for RL.

The heavy lifting is a native Rust core (`cr_sim._core`, built with maturin).
This package re-exports its public API and adds optional pure-Python helpers
(trace tools, adapters). The core has zero required third-party dependencies;
`gymnasium`/`numpy` are only needed for the optional adapters.

The seat frame
--------------
Every agent plays as the bottom player. What an agent reads (``view(p)`` and
its ``observe()``) and what it sends (``step``) are in its own seat's frame: its
towers are at low ``y``, its own side is ``y < 15``, entities it owns are owner
``0`` and crowns read ``(mine, theirs)``. For the seat that is really on top the
simulator mirrors the board and the actions, so one policy plays either seat
unchanged and is never told which seat it has::

    b = cr_sim.Battle()
    b.reset(seed, deck0, deck1)
    v0, v1 = b.view(0), b.view(1)
    b.step(policy(v0.observe()), policy(v1.observe()))   # same policy, both seats

This is exactly what the competition server sends and accepts. The unmirrored
board is only available as ``Battle.spectator_entities()`` /
``spectator_projectiles()``, for rendering and debugging, never as agent input.

Ignored moves
-------------
A move that cannot be carried out (a card you cannot afford, a troop on the
opponent's side, a slot that does not exist) is ignored and spends nothing. It is
not silent: the next observation's ``last_action`` is ``"ok"``, ``"none"`` (you
sent no move) or the reason it was ignored. ``legal`` only says which cards you
can afford, not where they may go.

Decks
-----
``reset`` needs a deck for each player: a list of 8 different card names, or the
word ``"default"`` for the built-in deck::

    b.reset(seed, my_deck, "default")

Do not train a model that can see the opponent's hand
-----------------------------------------------------
The raw ``Battle`` will tell you the opponent's hand, next card and elixir. The
competition server never sends them. A model trained with them as input learns
to depend on information it will not have in a real match. Build your model's
inputs from ``view(seat)`` only.

The raw ``Battle`` exposes per-player getters (``elixir(p)``, ``hand(p)``,
``next_card(p)``, ...) for *either* seat, which is convenient for the trusted
harness, debugging, and replay but lets a self-play agent peek at its opponent.
For competitive play, hand each agent a ``PlayerView`` instead::

    b = cr_sim.Battle()
    b.reset(seed, deck0, deck1)
    v0, v1 = b.view(0), b.view(1)          # one read-only window per agent
    action0 = agent0.act(v0)               # v0 can read its own hand/elixir and
    action1 = agent1.act(v1)               # the full board, but NOT v1's hand,
    b.step(action0, action1)               # next card, or elixir.

``PlayerView`` is a live, read-only window: it exposes the full board
(``entities``/``towers``/``projectiles``), its own ``hand``/``hand_cost``/
``next_card``/``elixir``/``crowns``/``champion_status``, the opponent's crown
count and tower state (public), and the fog-of-war ``observe()``/``legal()`` for
its seat. Its private getters take no player argument and there is no accessor
for the opponent's hand, next card, or elixir, so an agent *structurally* cannot
cheat. It has no mutators (``step``/``reset``/``activate_ability``).
"""
from __future__ import annotations

from ._core import (  # noqa: F401
    Battle,
    BatchBattle,
    PlayerView,
    BuildCheck,
    WIDTH,
    HEIGHT,
    TICKS_PER_SECOND,
    REGULATION_TICKS,
    OVERTIME_TICKS,
    RIVER_Y,
    RIVER_HALF,
    BRIDGE_HALF,
    BRIDGES,
    ABILITY_SLOT,
)

__all__ = [
    "Battle",
    "BatchBattle",
    "PlayerView",
    "WIDTH",
    "HEIGHT",
    "TICKS_PER_SECOND",
    "REGULATION_TICKS",
    "OVERTIME_TICKS",
    "RIVER_Y",
    "BRIDGES",
    "ABILITY_SLOT",
]
__version__ = "0.1.0"

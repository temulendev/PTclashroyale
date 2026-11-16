"""Elo rating math for the tournament server."""
from __future__ import annotations

K_FACTOR = 32.0
START_RATING = 1200.0


def expected(ra: float, rb: float) -> float:
    """Expected score for A against B (0..1)."""
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


def update(ra: float, rb: float, score_a: float, k: float = K_FACTOR):
    """Return (new_ra, new_rb, delta_a) after a game. score_a: 1 win, 0.5 draw, 0 loss."""
    ea = expected(ra, rb)
    delta = k * (score_a - ea)
    return ra + delta, rb - delta, delta

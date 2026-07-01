"""AC-4: the seeded RNG factory is deterministic."""

from __future__ import annotations

from tymi.core.rng import make_rng


def test_same_seed_same_draws() -> None:
    a = make_rng(42).random(5)
    b = make_rng(42).random(5)
    assert (a == b).all()


def test_different_seed_differs() -> None:
    a = make_rng(1).random(5)
    b = make_rng(2).random(5)
    assert (a != b).any()

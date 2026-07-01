"""Seeded RNG factory (AD-4, AD-11).

A single ``numpy.random.Generator`` is created here from the config seed and
passed explicitly (keyword-only ``rng``) to every stochastic component. No
module may use global ``random``/``np.random.*`` or time-based seeds.
"""

from __future__ import annotations

import numpy as np


def make_rng(seed: int | None) -> np.random.Generator:
    """Create the single Generator for a run.

    ``seed=None`` yields a nondeterministic generator; a concrete int makes the
    whole run reproducible (same seed -> same draws).
    """
    return np.random.default_rng(seed)

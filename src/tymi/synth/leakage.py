"""Leakage gate — exact-membership pre-export stage (Story 2.5, AD-7).

Every value of a declared Sensitive Column in the generated Dataset is checked
against the Profile's :class:`~tymi.domain.artifacts.LeakageGuard` — a keyed,
one-way hashed set of the source's real values. A collision (an emitted value
whose digest is in the set) is **regenerated** from the same sampler and
re-checked, so no real sensitive value survives to output. If a collision cannot
be resolved within the attempt budget the run **fails closed** with
:class:`~tymi.core.errors.LeakageError` — no branch reaches Export ungated.

The gate draws from the injected ``rng`` only when it must regenerate; with no
collisions it draws nothing and returns the input Dataset unchanged, so it is a
no-op for the common case and preserves determinism (AD-4/AD-11). It compares
hashes only — no raw source value is ever held (AD-6). Distinct from the
FR-24 similarity/outlier Privacy Filters, which are faithful-only quality filters.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from tymi.core.errors import LeakageError
from tymi.domain.artifacts import Dataset, LeakageGuard, leakage_digest

#: How many times the gate re-draws a colliding cell before failing closed. A
#: real collision against a synthetic sampler is astronomically rare, so a small
#: budget is ample; exhausting it means the column's value space cannot avoid the
#: real set (fail closed is the correct, safe outcome).
DEFAULT_MAX_ATTEMPTS = 100

#: Signature of the per-column regenerator the gate calls to replace colliding
#: cells: ``(column_name, count, rng) -> sequence of fresh candidate values``.
Resampler = Callable[[str, int, np.random.Generator], object]


def enforce_leakage_gate(
    dataset: Dataset,
    guard: LeakageGuard | None,
    *,
    rng: np.random.Generator,
    resample: Resampler,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Dataset:
    """Return a Dataset with every sensitive value guaranteed off the real set.

    ``guard`` ``None`` (no sensitive columns declared) makes this a no-op. For each
    guarded column present in the frame, colliding cells are regenerated via
    ``resample`` until the column is collision-free, or :class:`LeakageError` is
    raised after ``max_attempts``.
    """
    if guard is None:
        return dataset
    frame = dataset.frame
    updates: dict[str, pd.Series] = {}
    for name, digests in guard.columns.items():
        if name not in frame.columns:
            continue
        digest_set = set(digests)
        if not digest_set:
            continue
        column = frame[name].copy()
        colliding = _colliding_mask(column, digest_set, guard.salt)
        attempts = 0
        while bool(colliding.any()):
            if attempts >= max_attempts:
                raise LeakageError(
                    f"could not regenerate {int(colliding.sum())} value(s) in sensitive "
                    f"column {name!r} without colliding with a real source value after "
                    f"{max_attempts} attempts; the run fails closed (AD-7)."
                )
            positions = np.flatnonzero(colliding.to_numpy())
            candidates = np.asarray(resample(name, int(positions.size), rng), dtype=object)
            column.iloc[positions] = candidates
            attempts += 1
            colliding = _colliding_mask(column, digest_set, guard.salt)
        if attempts > 0:
            updates[name] = column

    if not updates:
        return dataset
    new_frame = frame.copy()
    for name, column in updates.items():
        new_frame[name] = column
    return Dataset(frame=new_frame, schema=dataset.schema)


def _colliding_mask(column: pd.Series, digest_set: set[str], salt: str) -> pd.Series:
    """Boolean mask of non-null cells whose hashed value is in the real set.

    Nulls never collide (only non-null source values are hashed into the guard), so
    a conditioned/no-null column keeps its invariant and null positions are left be.
    """

    def _hits(value: object) -> bool:
        return bool(pd.notna(value)) and leakage_digest(value, salt) in digest_set

    # ``astype(object)`` first: mapping a nullable ``Int64`` Series that holds a
    # ``pd.NA`` upcasts every element to float, so ``100`` would hash as ``"100.0"``
    # and miss the guard's ``"100"`` digest — a false negative in the gate's core
    # predicate. Object dtype preserves each scalar's real type (int/float/bool/
    # Timestamp) with ``pd.NA`` intact, keeping the hash symmetric with profile time.
    return column.astype(object).map(_hits).astype(bool)

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
from tymi.domain.artifacts import (
    _GATE_KEY,
    Dataset,
    GatedDataset,
    GateReport,
    LeakageGuard,
    leakage_digest,
)

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


def gate_dataset(
    dataset: Dataset,
    guard: LeakageGuard | None,
    *,
    rng: np.random.Generator,
    resample: Resampler,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> GatedDataset:
    """Run the leakage gate and **seal** the result into a :class:`GatedDataset` (AD-21).

    This is the provisioning-boundary producer: the only public way to obtain a
    ``GatedDataset``. It enforces the gate (regenerating any real-value collision, or failing
    closed with :class:`LeakageError`), then wraps the guaranteed-clean Dataset with the
    module-private key so no un-gated data can be forged past the ``load`` boundary. The
    per-table :func:`enforce_leakage_gate` stage embedded in ``generate_faithful`` is unchanged.
    """
    gated = enforce_leakage_gate(
        dataset, guard, rng=rng, resample=resample, max_attempts=max_attempts
    )
    # Seal an INDEPENDENT copy: the gate is a no-op-returns-same-object for guard=None / no
    # collision, so without a copy the caller's retained input frame would alias (and could
    # mutate) the sealed contents. Point-in-time seal (see GatedDataset docstring).
    sealed = Dataset(frame=gated.frame.copy(deep=True), schema=gated.schema)
    # Report only the columns the gate ACTUALLY inspected (present in the frame + non-empty
    # guard) — not every declared guard column.
    checked = (
        tuple(c for c, digests in guard.columns.items() if c in sealed.frame.columns and digests)
        if guard is not None
        else ()
    )
    return GatedDataset(sealed, GateReport(columns_checked=checked), key=_GATE_KEY)


def scan_and_gate(
    dataset: Dataset,
    guard: LeakageGuard | None,
    *,
    fixture_mask: np.ndarray | None = None,
    structural_columns: object = (),
    classify: Callable[..., dict[str, str]] | None = None,
) -> GatedDataset:
    """Scan-and-reject seal (AD-17): verify, never regenerate, then mint a :class:`GatedDataset`.

    Unlike :func:`gate_dataset`, this **never regenerates** — pinned fixtures must survive verbatim.
    It fails closed (:class:`LeakageError`) if:

    - a **fixture** cell in **any** guarded column collides with a real source value — fixtures are
      overlaid verbatim, so every guarded column of theirs is scanned, including structural
      key/shared columns; or
    - a **generated** cell in a guarded **non-structural** column collides — a safety re-scan (the
      embedded gate already cleaned these). ``structural_columns`` (PK/FK/shared) are skipped for
      *generated* rows only, because there they hold synthetic keys that would false-positive
      against the real-value digests; and
    - the ``classify`` PII classifier detects PII in the **fixture rows** of a column **not**
      covered by the guard — an un-guarded-PII bypass. The classifier is run at a match-rate low
      enough that a **single** PII fixture cell trips it (no minority-row bypass).

    ``fixture_mask`` (a boolean array over the frame) marks the pinned rows.
    """
    frame = dataset.frame
    structural = set(structural_columns)
    has_fixtures = fixture_mask is not None and bool(np.any(fixture_mask))
    if guard is not None:
        for name, digests in guard.columns.items():
            if name not in frame.columns:
                continue
            digest_set = set(digests)
            if not digest_set:
                continue
            # Fixture rows: scan EVERY guarded column (verbatim → could carry a real value).
            if has_fixtures:
                fixture_col = frame[name][fixture_mask]
                _reject_collisions(fixture_col, digest_set, guard.salt, name, "fixture")
            # Generated rows: scan only non-structural guarded cols (structural = synthetic keys).
            if name not in structural:
                generated = frame[name] if fixture_mask is None else frame[name][~fixture_mask]
                _reject_collisions(generated, digest_set, guard.salt, name, "generated")

    if classify is not None and has_fixtures:
        fixture_frame = frame[fixture_mask]
        n_fixtures = int(np.count_nonzero(fixture_mask))
        # min_match_rate = 1/n → any single PII cell among the fixture rows is detected.
        detected = classify(
            Dataset(frame=fixture_frame, schema=dataset.schema), min_match_rate=1.0 / n_fixtures
        )
        guarded = set(guard.columns) if guard is not None else set()
        smuggled = {col: kind for col, kind in detected.items() if col not in guarded}
        if smuggled:
            raise LeakageError(
                f"scan-and-reject: fixture rows carry un-guarded PII {smuggled}; a fixture may not "
                "introduce PII in a column the guard does not cover (AD-17). Fails closed."
            )

    sealed = Dataset(frame=frame.copy(deep=True), schema=dataset.schema)
    checked = (
        tuple(c for c, digests in guard.columns.items() if c in frame.columns and digests)
        if guard is not None
        else ()
    )
    return GatedDataset(sealed, GateReport(columns_checked=checked), key=_GATE_KEY)


def _reject_collisions(
    column: pd.Series, digest_set: set[str], salt: str, name: str, kind: str
) -> None:
    """Raise :class:`LeakageError` (fail closed) if any ``column`` cell is a real source value."""
    colliding = _colliding_mask(column, digest_set, salt)
    if bool(colliding.any()):
        raise LeakageError(
            f"scan-and-reject: {int(colliding.sum())} {kind} value(s) in guarded column "
            f"{name!r} collide with a real source value; the run fails closed (AD-17)."
        )


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

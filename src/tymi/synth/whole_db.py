"""Whole-DB faithful generation from a Spec (PDE-4/5/7, AD-13/AD-21).

Given a :class:`~tymi.config.spec.Spec`, generate every table faithfully and FK-consistently,
then hand each table across the provisioning boundary as a :class:`~tymi.domain.artifacts.
GatedDataset` (AD-21) — the guaranteed-clean, seal-typed value the ``load`` boundary accepts.

This is the first caller of :func:`~tymi.synth.relational.generate_related` (AD-13 first-wiring):
it already produces tables in FK-topological order with referential integrity and unique keys.
Each table is leakage-gated *during* generation (the gate is embedded in ``generate_faithful``);
here we re-run the gate via :func:`~tymi.synth.leakage.gate_dataset` — a no-op on already-clean
data — solely to **seal** the result through AD-21's sole ``GatedDataset`` producer.

Shared keys (AD-16) and pinned fixtures (AD-17) are *not* applied here; they overlay later in the
provisioning pipeline. This module is the clean whole-DB faithful baseline.
"""

from __future__ import annotations

from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import GenerationError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import GatedDataset, LeakageGuard, Profile, Schema
from tymi.synth.generator import _make_resampler
from tymi.synth.leakage import gate_dataset
from tymi.synth.relational import generate_related


def generate_from_spec(spec: Spec) -> dict[str, GatedDataset]:
    """Generate the whole DB from ``spec``, returning each table as a sealed ``GatedDataset``.

    Tables are produced in FK-topological order at the Spec's pinned per-table row counts and
    seed; the same Spec + seed yields byte-identical output (NFR-4). Every table is returned
    already leakage-gated (zero real sensitive values) and sealed for the ``load`` boundary.

    A whole-DB Spec must be FK-complete: every foreign key's referred table must also be in the
    Spec (subsetting is Phase 3). An out-of-spec FK parent fails closed with ``GenerationError``
    rather than silently emitting dangling references.
    """
    profiles = spec_profiles(spec)
    _require_fk_complete(profiles)
    row_counts = {name: ts.rows for name, ts in spec.tables.items()}
    datasets = generate_related(profiles, rows=row_counts, rng=make_rng(spec.seed))
    gated: dict[str, GatedDataset] = {}
    for name, dataset in datasets.items():
        profile = profiles[name]
        # Re-gate to SEAL only (AD-21 sole producer). We gate against a guard reduced to the
        # non-key sensitive columns: PK/FK columns are STRUCTURAL — generate_related overwrites
        # them with a synthetic surrogate key (arange) or with generated parent keys, carrying no
        # real value. Gating them would be a false positive (a synthetic key numerically matching
        # a real one) and the marginal regenerator is PK/FK-unaware, so it could break uniqueness
        # or referential integrity. On the remaining data columns the embedded per-table gate
        # already cleaned them, so this is a genuine no-op: no collision, no rng draw — the
        # single fresh make_rng(spec.seed) keeps output byte-identical. (Sensitive *keys* are
        # handled by shared-key generation in Epic 2, not the baseline.)
        gated[name] = gate_dataset(
            dataset,
            _seal_guard(profile.leakage_guard, profile.schema),
            rng=make_rng(spec.seed),
            resample=_make_resampler(profile, {}),
        )
    return gated


def _require_fk_complete(profiles: dict[str, Profile]) -> None:
    """Fail closed if any FK references a table absent from the Spec (self-FKs are in-spec)."""
    for table, profile in profiles.items():
        for fk in profile.schema.foreign_keys:
            parent = fk.referred_table
            if parent != table and parent not in profiles:
                raise GenerationError(
                    f"table {table!r} has a foreign key to {parent!r}, which is not in the spec; "
                    "whole-DB generation requires every FK parent to be present (subsetting is "
                    "Phase 3)."
                )


def _seal_guard(guard: LeakageGuard | None, schema: Schema) -> LeakageGuard | None:
    """The leakage guard restricted to non-key columns (see ``generate_from_spec``)."""
    if guard is None:
        return None
    key_columns = set(schema.primary_key)
    for fk in schema.foreign_keys:
        key_columns.update(fk.columns)
    reduced = {c: d for c, d in guard.columns.items() if c not in key_columns}
    return LeakageGuard(salt=guard.salt, algorithm=guard.algorithm, columns=reduced)

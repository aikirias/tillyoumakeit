"""Whole-DB faithful generation from a Spec (PDE-4/5/7, AD-13/AD-21).

Given a :class:`~tymi.config.spec.Spec`, generate every table faithfully and FK-consistently,
then hand each table across the provisioning boundary as a :class:`~tymi.domain.artifacts.
GatedDataset` (AD-21) — the guaranteed-clean, seal-typed value the ``load`` boundary accepts.

This is the first caller of :func:`~tymi.synth.relational.generate_related` (AD-13 first-wiring):
it already produces tables in FK-topological order with referential integrity and unique keys.
Each table is leakage-gated *during* generation (the gate is embedded in ``generate_faithful``);
here we re-run the gate via :func:`~tymi.synth.leakage.gate_dataset` — a no-op on already-clean
data — solely to **seal** the result through AD-21's sole ``GatedDataset`` producer.

Declared shared keys (AD-16) are overlaid here between generation and sealing. Pinned fixtures
(AD-17) overlay later in the provisioning pipeline (Story 3.1); the reserved keyspace block already
partitions the keyspace for them.
"""

from __future__ import annotations

from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import GenerationError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import GatedDataset, LeakageGuard, Profile, Schema
from tymi.synth.generator import _make_resampler
from tymi.synth.keys import apply_shared_keys, shared_specs
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
    datasets = generate_related(profiles, rows=row_counts, seed=spec.seed)
    # Shared-key emission (AD-16): declared shared columns become source/seed-independent
    # position-derived keys in the non-fixture keyspace, remapping referencing FKs. (Fixtures
    # overlay is Story 3.1; the reserved block already partitions the keyspace for them.)
    shared_by_table, reserved_by_table = shared_specs(spec)
    datasets = apply_shared_keys(
        datasets, shared_by_table=shared_by_table, reserved_by_table=reserved_by_table
    )
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
        # single fresh make_rng(spec.seed) keeps output byte-identical. Declared shared columns
        # are likewise excluded: apply_shared_keys just overwrote them with synthetic
        # position-derived keys, so gating them would be a false positive AND could regenerate
        # (and thereby break) the cross-team-stable key.
        gated[name] = gate_dataset(
            dataset,
            _seal_guard(profile.leakage_guard, profile.schema, shared_by_table.get(name, ())),
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


def _seal_guard(
    guard: LeakageGuard | None, schema: Schema, shared_columns: object = ()
) -> LeakageGuard | None:
    """The leakage guard restricted to non-key columns (see ``generate_from_spec``)."""
    if guard is None:
        return None
    key_columns = set(schema.primary_key)
    for fk in schema.foreign_keys:
        key_columns.update(fk.columns)
    key_columns.update(shared_columns)
    reduced = {c: d for c, d in guard.columns.items() if c not in key_columns}
    return LeakageGuard(salt=guard.salt, algorithm=guard.algorithm, columns=reduced)

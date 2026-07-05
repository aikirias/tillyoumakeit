"""Whole-DB faithful generation from a Spec (PDE-4/5/7, AD-13/AD-21).

Given a :class:`~tymi.config.spec.Spec`, generate every table faithfully and FK-consistently,
then hand each table across the provisioning boundary as a :class:`~tymi.domain.artifacts.
GatedDataset` (AD-21) — the guaranteed-clean, seal-typed value the ``load`` boundary accepts.

This is the first caller of :func:`~tymi.synth.relational.generate_related` (AD-13 first-wiring):
it already produces tables in FK-topological order with referential integrity and unique keys.
Each table is leakage-gated *during* generation (the gate is embedded in ``generate_faithful``).
The whole-DB pipeline then overlays declared shared keys (AD-16) and pinned fixtures (AD-17) and
**seals** each table via :func:`~tymi.synth.leakage.scan_and_gate` — a scan-and-reject seal that
never regenerates (fixtures are verbatim) and mints the AD-21 ``GatedDataset`` the ``load``
boundary accepts.
"""

from __future__ import annotations

from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import GenerationError
from tymi.domain.artifacts import GatedDataset, Profile, Schema
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.synth.cross_correlation import apply_cross_correlations
from tymi.synth.fixtures import overlay_fixtures
from tymi.synth.keys import apply_shared_keys, shared_specs
from tymi.synth.leakage import scan_and_gate
from tymi.synth.relational import generate_related


def generate_from_spec(spec: Spec) -> dict[str, GatedDataset]:
    """Generate the whole DB from ``spec``, returning each table as a sealed ``GatedDataset``.

    Tables are produced in FK-topological order at the Spec's pinned per-table row counts and
    seed; the same Spec + seed yields byte-identical output (NFR-4). Declared shared keys (AD-16)
    and pinned fixtures (AD-17) overlay before sealing, and every table is returned as a
    scan-and-reject–sealed ``GatedDataset`` (zero real sensitive values, no fixture PII bypass).

    A whole-DB Spec must be FK-complete: every foreign key's referred table must also be in the
    Spec (subsetting is Phase 3). An out-of-spec FK parent fails closed with ``GenerationError``
    rather than silently emitting dangling references.
    """
    profiles = spec_profiles(spec)
    _require_fk_complete(profiles)
    row_counts = {name: ts.rows for name, ts in spec.tables.items()}
    datasets = generate_related(profiles, rows=row_counts, seed=spec.seed)
    # Cross-table single-hop correlation (AD-25): induce declared child↔parent correlations by
    # rank reorder while FK values still equal the parent's generated keys (before shared-key
    # remapping). A no-op when nothing is declared.
    datasets = apply_cross_correlations(datasets, spec, seed=spec.seed)
    # Shared-key emission (AD-16): declared shared columns become source/seed-independent
    # position-derived keys in the non-fixture keyspace, remapping referencing FKs.
    shared_by_table, reserved_by_table = shared_specs(spec)
    datasets = apply_shared_keys(
        datasets, shared_by_table=shared_by_table, reserved_by_table=reserved_by_table
    )
    # Fixtures overlay (AD-17): pinned verbatim rows in the reserved keyspace, exempt from
    # regeneration but scanned below.
    fixtures_by_table = {name: list(ts.fixtures) for name, ts in spec.tables.items()}
    datasets, fixture_masks = overlay_fixtures(
        datasets, fixtures_by_table=fixtures_by_table, reserved_by_table=reserved_by_table
    )
    gated: dict[str, GatedDataset] = {}
    for name, dataset in datasets.items():
        profile = profiles[name]
        # Scan-and-reject seal (AD-17/AD-21 sole producer), NEVER regenerating — pinned fixtures
        # must survive verbatim. Fixture rows are scanned against the FULL guard (verbatim → could
        # carry a real value in any column, including a shared/key column); generated rows skip the
        # structural PK/FK/shared columns, which hold synthetic keys that would false-positive.
        gated[name] = scan_and_gate(
            dataset,
            profile.leakage_guard,
            fixture_mask=fixture_masks.get(name),
            structural_columns=_structural_columns(profile.schema, shared_by_table.get(name, ())),
            classify=classify_sensitive_columns,
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


def _structural_columns(schema: Schema, shared_columns: object = ()) -> set[str]:
    """PK + FK + shared columns — structural synthetic keys, skipped by the *generated*-row scan."""
    columns = set(schema.primary_key)
    for fk in schema.foreign_keys:
        columns.update(fk.columns)
    columns.update(shared_columns)
    return columns

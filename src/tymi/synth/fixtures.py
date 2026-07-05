"""Pinned fixtures: inject-verbatim, regenerate-never, scanned into the GatedDataset (AD-17).

A fixture is a specific row that must appear **verbatim** — a login/test account people need in a
dev environment. Fixtures are declared in the Spec, carry keys inside the reserved keyspace block
(``[0, reserved_key_block)``, AD-16), are overlaid **after** generation, and are **exempt from
regeneration**. But exempt-from-regeneration is not exempt-from-checking: the overlaid frame then
passes a **scan-and-reject** gate (:func:`~tymi.synth.leakage.scan_and_gate`) that fails closed on a
real value or un-guarded PII — so a fixture can never be a PII bypass (PDE-8/9/10).

Adding a fixture emits a **logged attestation** (AD-17): the operator is on record that these exact
rows were pinned. Synthetic fixtures are preferred; the scan is the safety net.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from tymi.core.errors import FixtureError
from tymi.domain.artifacts import Dataset

_log = logging.getLogger("tymi.provision.fixtures")


def overlay_fixtures(
    datasets: dict[str, Dataset],
    *,
    fixtures_by_table: dict[str, list[dict]],
    reserved_by_table: dict[str, int],
) -> tuple[dict[str, Dataset], dict[str, np.ndarray]]:
    """Append pinned fixture rows verbatim, returning ``(datasets, fixture_masks)``.

    ``fixture_masks[table]`` is a boolean array over the combined frame, ``True`` for fixture rows.
    Fixture keys must lie in the table's reserved block; fixture foreign keys must reference an
    existing (generated or fixture) parent key. Inputs are not mutated. Fails closed via
    :class:`FixtureError`.
    """
    result = {
        t: Dataset(frame=ds.frame.copy(deep=True), schema=ds.schema)
        for t, ds in datasets.items()
    }
    fixture_masks: dict[str, np.ndarray] = {}
    for table, fixtures in fixtures_by_table.items():
        if not fixtures:
            continue
        if table not in result:
            raise FixtureError(f"fixtures declared for table {table!r}, which was not generated")
        ds = result[table]
        reserved = reserved_by_table.get(table, 0)
        fixture_frame = _build_fixture_frame(fixtures, ds, table)
        _validate_fixture_keys_in_block(fixture_frame, ds, reserved, table)
        n_generated = len(ds.frame)
        combined = pd.concat([ds.frame, fixture_frame], ignore_index=True)
        result[table] = Dataset(frame=combined, schema=ds.schema)
        mask = np.zeros(len(combined), dtype=bool)
        mask[n_generated:] = True
        fixture_masks[table] = mask
        _attest(table, len(fixture_frame))

    _validate_fixture_pk_uniqueness(result, fixture_masks)
    _validate_fixture_fk_consistency(result, fixture_masks)
    return result, fixture_masks


def _validate_fixture_pk_uniqueness(
    datasets: dict[str, Dataset], fixture_masks: dict[str, np.ndarray]
) -> None:
    """A fixture key must not collide with a generated primary key (fail closed, PDE-10)."""
    for table in fixture_masks:
        ds = datasets[table]
        pk = ds.schema.primary_key
        if not pk:
            continue
        keys = _key_tuples(ds.frame, pk)
        if len(set(keys)) != len(keys):
            raise FixtureError(
                f"fixture key(s) in {table!r} collide with a generated primary key; pinned "
                "fixtures must occupy the disjoint reserved keyspace block (AD-16/PDE-10)."
            )


def _build_fixture_frame(fixtures: list[dict], ds: Dataset, table: str) -> pd.DataFrame:
    """A DataFrame of the fixture rows aligned to the table's schema/dtypes (missing cols → NA)."""
    columns = [c.name for c in ds.schema.columns]
    known = set(columns)
    for row in fixtures:
        unknown = set(row) - known
        if unknown:
            raise FixtureError(
                f"fixture for {table!r} has unknown column(s) {sorted(unknown)}; "
                f"columns must be a subset of {columns}."
            )
    rows = [{col: row.get(col, pd.NA) for col in columns} for row in fixtures]
    fixture_frame = pd.DataFrame(rows, columns=columns)
    # Align each fixture column to the generated frame's dtype so concat doesn't upcast the table.
    for col in columns:
        try:
            fixture_frame[col] = fixture_frame[col].astype(ds.frame[col].dtype)
        except (ValueError, TypeError) as exc:
            raise FixtureError(
                f"fixture value for {table}.{col} is not compatible with the column type: {exc}"
            ) from exc
    return fixture_frame


def _validate_fixture_keys_in_block(
    fixture_frame: pd.DataFrame, ds: Dataset, reserved: int, table: str
) -> None:
    """Every fixture primary-key value must be an integer inside the reserved block."""
    for pk in ds.schema.primary_key:
        if pk not in fixture_frame.columns:
            continue
        for value in fixture_frame[pk].tolist():
            if pd.isna(value) or not isinstance(value, (int, np.integer)):
                raise FixtureError(
                    f"fixture key {value!r} for {table}.{pk} must be an integer in the reserved "
                    f"block [0, {reserved}); the reserved keyspace is an integer block (AD-16)."
                )
            if not (0 <= value < reserved):
                raise FixtureError(
                    f"fixture key {value!r} for {table}.{pk} is outside the reserved block "
                    f"[0, {reserved}); pinned fixtures must occupy the reserved keyspace (AD-16)."
                )


def _validate_fixture_fk_consistency(
    datasets: dict[str, Dataset], fixture_masks: dict[str, np.ndarray]
) -> None:
    """Every fixture-row foreign key must reference an existing parent key (fail closed)."""
    for table, mask in fixture_masks.items():
        ds = datasets[table]
        fixture_rows = ds.frame[mask]
        for fk in ds.schema.foreign_keys:
            parent = datasets.get(fk.referred_table)
            if parent is None:
                continue  # out-of-spec parent already rejected upstream
            parent_keys = set(_key_tuples(parent.frame, fk.referred_columns))
            for key in _key_tuples(fixture_rows, fk.columns):
                if any(pd.isna(k) for k in key):
                    continue  # a nullable FK left unset is allowed
                if key not in parent_keys:
                    raise FixtureError(
                        f"fixture in {table!r} has foreign key {fk.columns} = {key} with no row "
                        f"in parent {fk.referred_table!r}."
                    )


def _key_tuples(frame: pd.DataFrame, columns: tuple[str, ...]) -> list[tuple]:
    return [tuple(row) for row in frame[list(columns)].itertuples(index=False, name=None)]


def _attest(table: str, count: int) -> None:
    """Emit the AD-17 logged attestation for pinning ``count`` fixture rows into ``table``."""
    _log.info("fixture attestation: pinned %d verbatim fixture row(s) into table %r", count, table)

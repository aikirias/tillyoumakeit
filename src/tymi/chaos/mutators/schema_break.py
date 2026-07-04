"""Schema and constraint breakage mutators (Story 3.4).

Unlike the cell-value faults (Stories 3.2/3.3), these break the **contract**: they
return a ``Dataset`` whose canonical ``Schema`` and/or frame no longer match the
original declaration — a dropped/renamed/added column, a changed logical type, a
PK/unique duplication, or an orphan FK. The returned artifact stays internally
consistent (Schema columns == frame columns); the *declared contract* is what breaks.

Each is registered under ``tymi.mutators`` (AD-3), toggled by chain membership, and
runs through the Story 3.1 engine. Check-constraint violations beyond PK/unique/FK are
deferred — the MVP ``Schema`` carries no check metadata.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from tymi.chaos.mutators._base import cell_count
from tymi.core.errors import ChaosError
from tymi.domain.artifacts import Column, Dataset, FaultManifest, LogicalType, Schema

_NUMERIC = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})


class SchemaBreakParams(BaseModel):
    """Which columns to break, and (for row-level faults) what fraction of rows."""

    model_config = ConfigDict(extra="forbid")

    columns: list[str] | None = None
    proportion: float = Field(default=0.1, ge=0.0, le=1.0)


class ExtraFieldParams(SchemaBreakParams):
    """Params for :class:`ExtraFieldMutator` — the name of the injected column."""

    field_name: str = Field(default="chaos_extra", min_length=1)


def _resolve(
    columns: list[str] | None, available: list[str], name: str, default: list[str]
) -> list[str]:
    if columns is None:
        return default
    for c in columns:
        if c not in available:
            raise ChaosError(f"{name} target column {c!r} is not in the dataset")
    return list(dict.fromkeys(columns))


class _SchemaBreakMutator:
    """Base: no-arg construction with a params model."""

    name: str = ""
    params_model: type[SchemaBreakParams] = SchemaBreakParams

    def __init__(self, params: SchemaBreakParams | None = None, **kwargs: object) -> None:
        self.params = params if params is not None else self.params_model(**kwargs)


class MissingFieldMutator(_SchemaBreakMutator):
    """Drop a column from the frame and the Schema."""

    structural = True

    name = "missing_field"

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        names = dataset.schema.names()
        targets = _resolve(self.params.columns, names, self.name, names[:1])
        drop = {c for c in targets if c in dataset.frame.columns}
        frame = dataset.frame.drop(columns=list(drop))
        schema = _drop_from_schema(dataset.schema, drop)
        entries = [
            {"mutator": self.name, "fault_type": "missing_field", "column": c} for c in targets
        ]
        return Dataset(frame=frame, schema=schema), FaultManifest(entries=entries)


class ExtraFieldMutator(_SchemaBreakMutator):
    """Add an undeclared column to the frame and the Schema."""

    structural = True

    name = "extra_field"
    params_model = ExtraFieldParams

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        field = self.params.field_name
        if field in dataset.frame.columns or field in dataset.schema.names():
            raise ChaosError(f"extra_field column {field!r} already exists in the dataset")
        frame = dataset.frame.copy()
        frame[field] = "chaos"
        schema = replace(
            dataset.schema,
            columns=(*dataset.schema.columns, Column(field, LogicalType.STRING)),
        )
        entries = [{"mutator": self.name, "fault_type": "extra_field", "column": field}]
        return Dataset(frame=frame, schema=schema), FaultManifest(entries=entries)


class RenamedColumnMutator(_SchemaBreakMutator):
    """Rename a column in the frame and the Schema."""

    structural = True

    name = "renamed_column"

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        names = dataset.schema.names()
        targets = _resolve(self.params.columns, names, self.name, names[:1])
        mapping = {c: f"{c}__renamed" for c in targets}
        frame = dataset.frame.rename(columns=mapping)
        schema = _rename_in_schema(dataset.schema, mapping)
        entries = [
            {"mutator": self.name, "fault_type": "renamed_column", "column": old, "new_name": new}
            for old, new in mapping.items()
        ]
        return Dataset(frame=frame, schema=schema), FaultManifest(entries=entries)


class ChangedTypeMutator(_SchemaBreakMutator):
    """Change a column's declared logical type (the frame data now mismatches it)."""

    structural = True

    name = "changed_type"

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        names = dataset.schema.names()
        targets = _resolve(self.params.columns, names, self.name, names[:1])
        target_set = set(targets)
        entries = []
        new_columns = []
        for col in dataset.schema.columns:
            if col.name in target_set:
                new_type = _other_type(col.logical_type)
                entries.append(
                    {
                        "mutator": self.name,
                        "fault_type": "changed_type",
                        "column": col.name,
                        "from": col.logical_type.value,
                        "to": new_type.value,
                    }
                )
                new_columns.append(replace(col, logical_type=new_type))
            else:
                new_columns.append(col)
        schema = replace(dataset.schema, columns=tuple(new_columns))
        return Dataset(frame=dataset.frame.copy(), schema=schema), FaultManifest(entries=entries)


class DuplicateKeysMutator(_SchemaBreakMutator):
    """Duplicate a PK / unique **key** so its uniqueness is violated.

    The key is treated as a unit: a composite PK ``(a, b)`` copies the *whole tuple*
    from one surviving row into the chosen rows, so the composite key genuinely repeats
    (duplicating columns independently would not). Works positionally, so a non-default
    or non-unique frame index cannot break the row bookkeeping.
    """

    name = "duplicate_keys"

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        schema = dataset.schema
        if self.params.columns is not None:
            groups = [tuple(_resolve(self.params.columns, schema.names(), self.name, []))]
        else:
            groups = _key_groups(schema) or [tuple(schema.names()[:1])]
        frame = dataset.frame.copy()
        n = len(frame)
        entries: list[dict[str, object]] = []
        for group in groups:
            cols = [c for c in group if c in frame.columns]
            if not cols or n < 2:
                continue
            valid = np.flatnonzero(frame[cols].notna().all(axis=1).to_numpy())
            if valid.size < 2:
                continue
            source = int(valid[0])
            source_values = {c: frame.iloc[source][c] for c in cols}
            candidates = valid[valid != source]
            k = min(cell_count(self.params.proportion, candidates.size), candidates.size)
            if k == 0:
                continue
            chosen = np.sort(rng.choice(candidates, size=k, replace=False))
            for c in cols:
                frame.iloc[chosen, frame.columns.get_loc(c)] = source_values[c]
            for pos in chosen:
                for c in cols:
                    entries.append(
                        {
                            "mutator": self.name,
                            "fault_type": "duplicate_key",
                            "row": int(pos),
                            "column": c,
                            "value": str(source_values[c]),
                        }
                    )
        return Dataset(frame=frame, schema=schema), FaultManifest(entries=entries)


class OrphanFkMutator(_SchemaBreakMutator):
    """Overwrite FK values with a sentinel that references no real parent."""

    name = "orphan_fk"

    def apply(self, dataset: Dataset, *, rng: np.random.Generator) -> tuple[Dataset, FaultManifest]:
        fk_cols = [c for fk in dataset.schema.foreign_keys for c in fk.columns]
        default = list(dict.fromkeys(fk_cols)) or dataset.schema.names()[:1]
        targets = _resolve(self.params.columns, dataset.schema.names(), self.name, default)
        frame = dataset.frame.copy()
        types = {c.name: c.logical_type for c in dataset.schema.columns}
        entries: list[dict[str, object]] = []
        for name in targets:
            non_null_pos = np.flatnonzero(frame[name].notna().to_numpy())
            k = cell_count(self.params.proportion, non_null_pos.size)
            if k == 0:
                continue
            orphan = _orphan_value(frame[name], types.get(name))
            rows = np.sort(rng.choice(non_null_pos, size=k, replace=False))
            col_idx = frame.columns.get_loc(name)
            frame[name] = frame[name].astype(object)
            frame.iloc[rows, col_idx] = [orphan] * k
            for row in rows:
                entries.append(
                    {
                        "mutator": self.name,
                        "fault_type": "orphan_fk",
                        "row": int(row),
                        "column": name,
                        "value": str(orphan),
                    }
                )
        return Dataset(frame=frame, schema=dataset.schema), FaultManifest(entries=entries)


# --- helpers ----------------------------------------------------------------


def _other_type(logical_type: LogicalType) -> LogicalType:
    return LogicalType.STRING if logical_type in _NUMERIC else LogicalType.INTEGER


def _key_groups(schema: Schema) -> list[tuple[str, ...]]:
    """Uniqueness key groups: the PK tuple + each unique constraint (kept as units)."""
    groups: list[tuple[str, ...]] = []
    if schema.primary_key:
        groups.append(tuple(schema.primary_key))
    for unique in schema.unique_constraints:
        groups.append(tuple(unique))
    return groups


def _orphan_value(column: object, logical_type: LogicalType | None) -> object:
    import pandas as pd

    if logical_type in _NUMERIC:
        numeric = pd.to_numeric(column, errors="coerce").dropna()
        top = float(numeric.max()) if not numeric.empty else 0.0
        return int(top) + 1_000_000_001 if logical_type == LogicalType.INTEGER else top + 1e9
    # a string sentinel proven ABSENT from the column (so it references no real value).
    existing = set(pd.Series(column).dropna().astype(str))
    value, suffix = "__ORPHAN__", 0
    while value in existing:
        suffix += 1
        value = f"__ORPHAN__{suffix}"
    return value


def _drop_from_schema(schema: Schema, dropped: set[str]) -> Schema:
    return replace(
        schema,
        columns=tuple(c for c in schema.columns if c.name not in dropped),
        primary_key=tuple(k for k in schema.primary_key if k not in dropped),
        foreign_keys=tuple(
            fk for fk in schema.foreign_keys if not (set(fk.columns) & dropped)
        ),
        unique_constraints=tuple(
            u for u in schema.unique_constraints if not (set(u) & dropped)
        ),
        # drop any index that references a gone column (no dangling reference)
        indexes=tuple(ix for ix in schema.indexes if not (set(ix.columns) & dropped)),
    )


def _rename_in_schema(schema: Schema, mapping: dict[str, str]) -> Schema:
    def rn(name: str) -> str:
        return mapping.get(name, name)

    return replace(
        schema,
        columns=tuple(replace(c, name=rn(c.name)) for c in schema.columns),
        primary_key=tuple(rn(k) for k in schema.primary_key),
        foreign_keys=tuple(
            replace(fk, columns=tuple(rn(c) for c in fk.columns)) for fk in schema.foreign_keys
        ),
        unique_constraints=tuple(tuple(rn(c) for c in u) for u in schema.unique_constraints),
        indexes=tuple(
            replace(ix, columns=tuple(rn(c) for c in ix.columns)) for ix in schema.indexes
        ),
    )

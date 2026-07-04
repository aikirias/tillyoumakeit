"""Shared base for cell-level fault mutators (Stories 3.3+).

A ``CellFaultMutator`` corrupts a configurable proportion of cells in the columns it
targets: it resolves targets, picks ``round(proportion·non_null)`` distinct non-null
cells per column, casts the column to ``object`` (an illegal value no longer fits the
declared dtype — that is the fault), injects the subclass's fault values, and records
one ``FaultManifest`` entry per cell. Subclasses supply the applicable logical types,
a ``fault_type`` label, and ``_fault_values``.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from tymi.core.errors import ChaosError
from tymi.domain.artifacts import Column, Dataset, FaultManifest, LogicalType

_MAX_MANIFEST_VALUE = 80


class CellFaultParams(BaseModel):
    """Base params: which columns to target, and what fraction of cells to corrupt."""

    model_config = ConfigDict(extra="forbid")

    columns: list[str] | None = None
    proportion: float = Field(default=0.05, ge=0.0, le=1.0)


class CellFaultMutator:
    """Base for a fault that replaces a proportion of cells with an illegal value."""

    name: str = ""
    fault_type: str = ""
    applicable: frozenset[LogicalType] = frozenset()
    params_model: type[CellFaultParams] = CellFaultParams

    def __init__(self, params: CellFaultParams | None = None, **kwargs: object) -> None:
        self.params = params if params is not None else self.params_model(**kwargs)

    def apply(
        self, dataset: Dataset, *, rng: np.random.Generator
    ) -> tuple[Dataset, FaultManifest]:
        meta = {c.name: c for c in dataset.schema.columns}
        frame = dataset.frame.copy()
        targets = self._targets(meta, set(frame.columns))
        entries: list[dict[str, object]] = []
        for name in targets:
            positions = np.flatnonzero(frame[name].notna().to_numpy())
            k = cell_count(self.params.proportion, positions.size)
            if k == 0:
                continue
            rows = np.sort(rng.choice(positions, size=k, replace=False))
            values = self._fault_values(len(rows), rng)
            col_idx = frame.columns.get_loc(name)
            frame[name] = frame[name].astype(object)
            frame.iloc[rows, col_idx] = values
            for row, value in zip(rows, values, strict=True):
                entries.append(
                    {
                        "mutator": self.name,
                        "row": int(row),
                        "column": name,
                        "fault_type": self.fault_type,
                        "value": repr(value)[:_MAX_MANIFEST_VALUE],
                    }
                )
        return Dataset(frame=frame, schema=dataset.schema), FaultManifest(entries=entries)

    def _targets(self, meta: dict[str, Column], frame_columns: set[str]) -> list[str]:
        if self.params.columns is None:
            return self._default_targets(meta, frame_columns)
        targets: list[str] = []
        for name in dict.fromkeys(self.params.columns):  # dedupe, preserve order
            if name not in meta:
                raise ChaosError(f"{self.name} target column {name!r} is not in the dataset schema")
            if name not in frame_columns:
                raise ChaosError(
                    f"{self.name} target column {name!r} is not present in the dataset frame"
                )
            if meta[name].logical_type not in self.applicable:
                raise ChaosError(
                    f"{self.name} cannot target column {name!r}: it is "
                    f"{meta[name].logical_type}, not one of "
                    f"{sorted(t.value for t in self.applicable)}"
                )
            targets.append(name)
        return targets

    def _default_targets(self, meta: dict[str, Column], frame_columns: set[str]) -> list[str]:
        return [
            name
            for name, col in meta.items()
            if col.logical_type in self.applicable and name in frame_columns
        ]

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        raise NotImplementedError


def cell_count(proportion: float, available: int) -> int:
    """Cells to corrupt: ``round(proportion·available)``, but **at least 1** when a
    positive proportion is requested on a non-empty column — so a small column never
    silently no-ops (on a tiny column this may exceed the ±2 pp margin, unavoidably)."""
    k = round(proportion * available)
    if k == 0 and proportion > 0.0 and available > 0:
        return 1
    return k


def choose_tokens(tokens: tuple[str, ...], k: int, rng: np.random.Generator) -> list[object]:
    """Pick ``k`` fault tokens from ``tokens`` via ``rng`` (deterministic)."""
    idx = rng.integers(0, len(tokens), size=k)
    return [tokens[int(i)] for i in idx]

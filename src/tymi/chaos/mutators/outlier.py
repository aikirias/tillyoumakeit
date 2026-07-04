"""Out-of-distribution fault mutator (Story 3.2).

``OutlierMutator`` replaces a configurable proportion of cells in numeric/datetime
columns with values **outside the column's observed range** (``max + magnitude·span``
or ``min − magnitude·span``), producing genuine range-jumps/outliers to stress-test a
pipeline. "Out of distribution" is relative to the frame the chaos branch mutates (a
generated Dataset), so no Profile is needed.

Registered under ``tymi.mutators`` (AD-3); parameterised by a Pydantic ``OutlierParams``
(AD-5). ``OutlierMutator()`` uses defaults (entry-point discovery, Story 3.1); a caller
or the Chaos Policy (Story 3.5) passes explicit params to the same constructor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from tymi.core.errors import ChaosError
from tymi.domain.artifacts import Dataset, FaultManifest, LogicalType

_NUMERIC = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})
_TARGETABLE = _NUMERIC | {LogicalType.DATETIME}
_INT64_MAX = int(np.iinfo("int64").max)
_INT64_MIN = int(np.iinfo("int64").min)


class OutlierParams(BaseModel):
    """Validated parameters for :class:`OutlierMutator`."""

    model_config = ConfigDict(extra="forbid")

    #: Columns to target; ``None`` targets every numeric/datetime column.
    columns: list[str] | None = None
    #: Fraction of rows to corrupt per target column.
    proportion: float = Field(default=0.05, ge=0.0, le=1.0)
    #: How far beyond the observed range to jump, in multiples of the column's span.
    magnitude: float = Field(default=3.0, gt=0.0)


class OutlierMutator:
    """Inject out-of-range values into numeric/datetime columns."""

    name = "outlier"

    def __init__(self, params: OutlierParams | None = None, **kwargs: object) -> None:
        self.params = params if params is not None else OutlierParams(**kwargs)

    def apply(
        self, dataset: Dataset, *, rng: np.random.Generator
    ) -> tuple[Dataset, FaultManifest]:
        types = {c.name: c.logical_type for c in dataset.schema.columns}
        frame = dataset.frame.copy()
        targets = self._targets(types, set(frame.columns))
        entries: list[dict[str, object]] = []
        for name in targets:
            col_type = types[name]
            # Corrupt only real (non-null) cells: an outlier replaces an observed
            # value, and nulls are a separate fault family (illegal nulls, Story 3.3).
            non_null_pos = np.flatnonzero(frame[name].notna().to_numpy())
            k = round(self.params.proportion * non_null_pos.size)
            if k == 0:
                continue
            rows = np.sort(rng.choice(non_null_pos, size=k, replace=False))
            values = self._outlier_values(frame[name], col_type, k, rng)
            frame.iloc[rows, frame.columns.get_loc(name)] = values
            fault = "datetime_outlier" if col_type == LogicalType.DATETIME else "numeric_outlier"
            for row, value in zip(rows, values, strict=True):
                entries.append(
                    {
                        "mutator": self.name,
                        "row": int(row),
                        "column": name,
                        "fault_type": fault,
                        "value": str(value),
                    }
                )
        return Dataset(frame=frame, schema=dataset.schema), FaultManifest(entries=entries)

    def _targets(self, types: dict[str, LogicalType], frame_columns: set[str]) -> list[str]:
        if self.params.columns is None:
            return [
                name
                for name, t in types.items()
                if t in _TARGETABLE and name in frame_columns
            ]
        targets: list[str] = []
        for name in dict.fromkeys(self.params.columns):  # dedupe, preserve order
            if name not in types:
                raise ChaosError(f"outlier target column {name!r} is not in the dataset schema")
            if name not in frame_columns:
                raise ChaosError(
                    f"outlier target column {name!r} is not present in the dataset frame"
                )
            if types[name] not in _TARGETABLE:
                raise ChaosError(
                    f"outlier cannot target column {name!r}: it is {types[name]}, "
                    "not numeric or datetime"
                )
            targets.append(name)
        return targets

    def _outlier_values(
        self, column: pd.Series, col_type: LogicalType, k: int, rng: np.random.Generator
    ) -> np.ndarray | list[object]:
        directions = rng.choice(np.array([-1, 1]), size=k)
        magnitude = self.params.magnitude
        if col_type == LogicalType.DATETIME:
            times = pd.to_datetime(column, errors="coerce").dropna()
            lo, hi = times.min(), times.max()
            span = (hi - lo) or pd.Timedelta(days=1)
            return [hi + magnitude * span if d > 0 else lo - magnitude * span for d in directions]
        numeric = pd.to_numeric(column, errors="coerce").dropna()
        lo, hi = float(numeric.min()), float(numeric.max())
        span = hi - lo
        if span == 0:
            span = abs(hi) or 1.0
        if col_type == LogicalType.INTEGER:
            ints = [self._integer_outlier(lo, hi, span, d) for d in directions]
            return np.array(ints, dtype="int64")
        return np.array(
            [hi + magnitude * span if d > 0 else lo - magnitude * span for d in directions],
            dtype=float,
        )

    def _integer_outlier(self, lo: float, hi: float, span: float, direction: int) -> int:
        """An int strictly outside ``[lo, hi]``, clipped to the int64 range.

        Rounding ``hi + magnitude·span`` can land back on ``hi`` for a small magnitude,
        and a huge value would overflow ``int64`` — so force at least one step past the
        bound and clip, guaranteeing an out-of-range, representable integer.
        """
        magnitude = self.params.magnitude
        if direction > 0:
            raw = hi + magnitude * span
            value = int(np.ceil(raw)) if np.isfinite(raw) else _INT64_MAX
            return min(max(value, int(np.floor(hi)) + 1), _INT64_MAX)
        raw = lo - magnitude * span
        value = int(np.floor(raw)) if np.isfinite(raw) else _INT64_MIN
        return max(min(value, int(np.ceil(lo)) - 1), _INT64_MIN)

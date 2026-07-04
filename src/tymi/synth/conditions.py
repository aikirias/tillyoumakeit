"""Generation conditions (Story 2.4).

A *condition* restricts one column's generated values so a targeted dataset can be
produced (``region=LATAM``, ``age in [18,25]``). Three shapes are supported:

* :class:`Equals` — ``col=value`` (the column becomes a constant),
* :class:`Between` — ``col in [lo,hi]`` (inclusive numeric/datetime range),
* :class:`Members` — ``col in {a,b,c}`` (membership set).

Enforcement is by **restriction** (the conditioned column's sampler is narrowed),
not rejection sampling: this guarantees 100% satisfaction and termination while
leaving every non-conditioned column's marginal untouched (see ``marginals.py``).

This module only *parses, models and validates* conditions; the sampling lives in
``tymi.synth.marginals``. All values are carried as strings until the marginal
layer coerces them against the column's logical type. ``[...]`` denotes a range and
``{...}`` a set, so ``age in [18,25]`` reads as the range the AC specifies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import LogicalType, Profile

_NUMERIC_TYPES = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})
_RANGE_TYPES = _NUMERIC_TYPES | {LogicalType.DATETIME}


@dataclass(frozen=True)
class Equals:
    """``column = value`` — the column is filled with the constant ``value``."""

    column: str
    value: str


@dataclass(frozen=True)
class Between:
    """``lo <= column <= hi`` — inclusive range (numeric or datetime)."""

    column: str
    low: str
    high: str


@dataclass(frozen=True)
class Members:
    """``column in {values...}`` — the column draws only from ``values``."""

    column: str
    values: tuple[str, ...]


Condition = Equals | Between | Members

# ``col in [a,b]`` (range) or ``col in {a,b,c}`` (set). ``col=value`` (equality).
_IN_RE = re.compile(
    r"^\s*(?P<col>\w+)\s+in\s+(?P<open>[\[{])(?P<body>.*)(?P<close>[\]}])\s*$", re.I
)
_EQ_RE = re.compile(r"^\s*(?P<col>\w+)\s*=\s*(?P<value>.*?)\s*$", re.I)


def _unquote(token: str) -> str:
    """Strip surrounding single/double quotes and outer whitespace from a token."""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _split_values(body: str) -> list[str]:
    """Split a comma-separated condition body into unquoted, non-empty tokens."""
    return [_unquote(part) for part in body.split(",") if part.strip()]


def parse_condition(text: str) -> Condition:
    """Parse a single ``--where`` expression into a :class:`Condition`.

    Raises :class:`GenerationError` on an unparsable expression, an empty
    membership set, or a range that is not exactly two bounds.
    """
    match = _IN_RE.match(text)
    if match:
        col = match["col"]
        bracketed = match["open"] == "["
        values = _split_values(match["body"])
        if not values:
            raise GenerationError(f"empty value list in condition: {text!r}")
        if bracketed:
            if match["close"] != "]":
                raise GenerationError(f"mismatched brackets in condition: {text!r}")
            if len(values) != 2:
                raise GenerationError(
                    f"range condition needs exactly two bounds [lo,hi]: {text!r}"
                )
            return Between(column=col, low=values[0], high=values[1])
        if match["close"] != "}":
            raise GenerationError(f"mismatched brackets in condition: {text!r}")
        return Members(column=col, values=tuple(values))

    match = _EQ_RE.match(text)
    if match and match["value"] != "":
        return Equals(column=match["col"], value=_unquote(match["value"]))

    raise GenerationError(
        f"could not parse condition {text!r}; expected 'col=value', "
        "'col in [lo,hi]' or 'col in {a,b,c}'"
    )


def parse_conditions(expressions: list[str]) -> dict[str, Condition]:
    """Parse ``--where`` expressions, keyed by column; a duplicate column errors."""
    conditions: dict[str, Condition] = {}
    for text in expressions:
        condition = parse_condition(text)
        if condition.column in conditions:
            raise GenerationError(
                f"more than one condition given for column {condition.column!r}"
            )
        conditions[condition.column] = condition
    return conditions


def validate_conditions(conditions: dict[str, Condition], profile: Profile) -> None:
    """Check every condition targets an existing column of a compatible type.

    Raises :class:`GenerationError` for an unknown column or a range condition on a
    column that is neither numeric nor datetime.
    """
    types = {c.name: c.logical_type for c in profile.schema.columns}
    if not types:  # schema-less profile: fall back to the profiled column list
        types = {c.name: c.logical_type for c in profile.columns}
    for column, condition in conditions.items():
        if column not in types:
            raise GenerationError(
                f"condition targets unknown column {column!r}; "
                f"available columns: {sorted(types)}"
            )
        if isinstance(condition, Between) and types[column] not in _RANGE_TYPES:
            raise GenerationError(
                f"range condition on non-numeric/non-datetime column {column!r} "
                f"(logical type {types[column].value!r})"
            )


def satisfies(frame, conditions: dict[str, Condition]) -> bool:
    """True iff every row of ``frame`` satisfies every condition (test helper).

    Numeric columns are compared numerically (so ``5`` matches a generated ``5.0``)
    and range bounds are order-normalized to mirror the sampler.
    """
    import pandas as pd

    for column, condition in conditions.items():
        series = frame[column]
        if series.isna().any():
            return False
        numeric = pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(
            series.dtype
        )
        if isinstance(condition, Equals):
            if not _value_matches(series, condition.value, numeric).all():
                return False
        elif isinstance(condition, Members):
            per_value = [_value_matches(series, v, numeric) for v in condition.values]
            allowed = per_value[0]
            for mask in per_value[1:]:
                allowed = allowed | mask
            if not allowed.all():
                return False
        elif isinstance(condition, Between):
            if pd.api.types.is_datetime64_any_dtype(series):
                lo, hi = pd.Timestamp(condition.low), pd.Timestamp(condition.high)
            else:
                lo, hi = float(condition.low), float(condition.high)
                series = pd.to_numeric(series)
            if lo > hi:  # order-normalize like the sampler
                lo, hi = hi, lo
            if not ((series >= lo) & (series <= hi)).all():
                return False
    return True


def _value_matches(series, value: str, numeric: bool):
    """Elementwise equality of ``series`` to ``value`` (numeric- or string-aware)."""
    import pandas as pd

    if numeric:
        try:
            return pd.to_numeric(series) == float(value)
        except (TypeError, ValueError):
            return series.astype(str) == str(value)
    return series.astype(str) == str(value)

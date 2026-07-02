"""Persist and load a Profile (Story 1.8).

A Profile is saved as human-inspectable YAML carrying its ``schema_version`` so
it can be moved to another environment and consumed **offline** — no source
connection needed — by downstream faithful generation (Epic 2).

Serialization reuses the JSON projection (``profile_to_json``) to reduce the
Profile to plain ``dict``/``list``/``str``/number types before ``yaml.safe_dump``:
``SafeDumper`` cannot represent ``tuple`` or ``StrEnum``, so that projection is
the normalization step. Loading rebuilds the frozen dataclasses with explicit,
typed builders (not reflection) and coerces YAML-loaded numbers back to their
declared ``float``/``int`` so ``load_profile(save_profile(p)) == p``.

AD-6: persistence is representation-only — the file holds exactly the in-memory
aggregates, never raw row values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tymi.core.errors import ProfileError, ProfileVersionError
from tymi.domain.artifacts import (
    CategoryFrequency,
    Column,
    ColumnProfile,
    CorrelationMatrix,
    Correlations,
    DatetimeStats,
    ForeignKey,
    Index,
    LogicalType,
    NumericStats,
    Profile,
    Schema,
    TextStats,
    profile_to_json,
)

#: The Profile schema major version this build can load.
PROFILE_SCHEMA_MAJOR = 1


def save_profile(profile: Profile, path: str | Path) -> None:
    """Write ``profile`` to ``path`` as YAML (UTF-8), carrying its schema_version."""
    plain = json.loads(profile_to_json(profile))  # tuples->lists, StrEnum->str
    text = yaml.safe_dump(plain, sort_keys=False, allow_unicode=True)
    Path(path).write_text(text, encoding="utf-8")


def load_profile(path: str | Path) -> Profile:
    """Load a saved Profile, gating on ``schema_version`` major.

    Raises ``ProfileVersionError`` when the major is unsupported/malformed and
    ``ProfileError`` on any other unreadable/malformed file.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileError(f"Could not read profile file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"Could not parse profile YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError("Profile root must be a mapping.")

    declared = str(data.get("schema_version", "1.0.0"))
    if _major(declared) != PROFILE_SCHEMA_MAJOR:
        raise ProfileVersionError(
            f"Unsupported profile schema_version {declared!r}; "
            f"this build supports major {PROFILE_SCHEMA_MAJOR}."
        )
    try:
        return _profile_from_dict(data, declared)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        # AttributeError covers hand-edited files where a section is the wrong
        # shape (e.g. `schema:` a list, `columns:` a scalar → `.get`/`.items`
        # on the wrong type). Every malformed artifact must surface as ProfileError.
        raise ProfileError(f"Malformed profile artifact: {exc}") from exc


def _major(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (ValueError, TypeError) as exc:
        raise ProfileVersionError(f"Invalid schema_version: {version!r}") from exc


# --- typed reconstruction -------------------------------------------------


def _profile_from_dict(data: dict[str, Any], schema_version: str) -> Profile:
    return Profile(
        schema_version=schema_version,
        schema=_schema_from_dict(data.get("schema") or {}),
        row_count=int(data.get("row_count", 0)),
        columns=tuple(_column_profile_from_dict(c) for c in data.get("columns") or []),
        correlations=_correlations_from_dict(data.get("correlations")),
    )


def _schema_from_dict(d: dict[str, Any]) -> Schema:
    return Schema(
        columns=tuple(_column_from_dict(c) for c in d.get("columns") or []),
        primary_key=tuple(d.get("primary_key") or []),
        foreign_keys=tuple(_fk_from_dict(f) for f in d.get("foreign_keys") or []),
        unique_constraints=tuple(tuple(u) for u in d.get("unique_constraints") or []),
        indexes=tuple(_index_from_dict(i) for i in d.get("indexes") or []),
    )


def _column_from_dict(d: dict[str, Any]) -> Column:
    return Column(
        name=d["name"],
        logical_type=LogicalType(d["logical_type"]),
        nullable=bool(d.get("nullable", True)),
        primary_key=bool(d.get("primary_key", False)),
    )


def _fk_from_dict(d: dict[str, Any]) -> ForeignKey:
    return ForeignKey(
        columns=tuple(d["columns"]),
        referred_table=d["referred_table"],
        referred_columns=tuple(d["referred_columns"]),
    )


def _index_from_dict(d: dict[str, Any]) -> Index:
    return Index(
        name=d.get("name"),
        columns=tuple(d["columns"]),
        unique=bool(d.get("unique", False)),
    )


def _column_profile_from_dict(d: dict[str, Any]) -> ColumnProfile:
    categories = d.get("categories")
    return ColumnProfile(
        name=d["name"],
        logical_type=LogicalType(d["logical_type"]),
        count=int(d["count"]),
        null_count=int(d["null_count"]),
        distinct_count=int(d["distinct_count"]),
        numeric=_numeric_from_dict(d.get("numeric")),
        categories=(
            tuple(CategoryFrequency(value=c["value"], count=int(c["count"])) for c in categories)
            if categories is not None
            else None
        ),
        datetime=_datetime_from_dict(d.get("datetime")),
        text=_text_from_dict(d.get("text")),
    )


def _numeric_from_dict(d: dict[str, Any] | None) -> NumericStats | None:
    if d is None:
        return None
    return NumericStats(
        min=float(d["min"]),
        max=float(d["max"]),
        mean=float(d["mean"]),
        std=float(d["std"]),
        quantiles={str(k): float(v) for k, v in d["quantiles"].items()},
        histogram_bins=tuple(float(x) for x in d["histogram_bins"]),
        histogram_counts=tuple(int(x) for x in d["histogram_counts"]),
    )


def _datetime_from_dict(d: dict[str, Any] | None) -> DatetimeStats | None:
    if d is None:
        return None
    return DatetimeStats(
        min=d.get("min"),
        max=d.get("max"),
        day_of_week_frequency=_int_freq(d.get("day_of_week_frequency")),
        month_frequency=_int_freq(d.get("month_frequency")),
    )


def _int_freq(d: dict[str, Any] | None) -> dict[str, int]:
    return {str(k): int(v) for k, v in (d or {}).items()}


def _text_from_dict(d: dict[str, Any] | None) -> TextStats | None:
    if d is None:
        return None
    return TextStats(
        min_length=int(d["min_length"]),
        max_length=int(d["max_length"]),
        mean_length=float(d["mean_length"]),
    )


def _correlations_from_dict(d: dict[str, Any] | None) -> Correlations | None:
    if d is None:
        return None
    return Correlations(
        numeric=_matrix_from_dict(d.get("numeric")),
        categorical=_matrix_from_dict(d.get("categorical")),
    )


def _matrix_from_dict(d: dict[str, Any] | None) -> CorrelationMatrix | None:
    if d is None:
        return None
    return CorrelationMatrix(
        method=d["method"],
        columns=tuple(d["columns"]),
        matrix=tuple(
            tuple(None if v is None else float(v) for v in row) for row in d["matrix"]
        ),
    )

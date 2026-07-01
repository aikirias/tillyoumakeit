"""Canonical pipeline artifacts (AD-10).

A ``Dataset`` is a pandas DataFrame plus a canonical ``Schema`` (per-column
logical type + engine-agnostic dtype) that every stage preserves; exporters and
``EngineAdapter.load`` map from the Schema, never from raw pandas dtypes.

These are intentionally minimal skeletons for the scaffold story; later stories
flesh out their fields.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum

import pandas as pd


class LogicalType(StrEnum):
    """Engine-agnostic column type."""

    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    STRING = "string"
    DATETIME = "datetime"
    CATEGORICAL = "categorical"


@dataclass(frozen=True)
class Column:
    name: str
    logical_type: LogicalType
    nullable: bool = True
    primary_key: bool = False


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]


@dataclass(frozen=True)
class Index:
    name: str | None
    columns: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True)
class Schema:
    """Ordered, engine-agnostic description of a table's structure."""

    columns: tuple[Column, ...] = ()
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    unique_constraints: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[Index, ...] = ()

    def names(self) -> list[str]:
        return [c.name for c in self.columns]


def schema_to_json(schema: Schema) -> str:
    """Serialize a Schema to deterministic JSON (StrEnum values render as strings)."""
    return json.dumps(asdict(schema), indent=2, default=str)


@dataclass
class Dataset:
    """A DataFrame paired with its canonical Schema (AD-10)."""

    frame: pd.DataFrame
    schema: Schema


@dataclass
class Profile:
    """Statistical signature of one or more source tables (skeleton).

    AD-6: stores only aggregates + schema + PII tags, never raw values.
    """

    schema_version: str = "1.0.0"
    schema: Schema = field(default_factory=Schema)


@dataclass
class FidelityReport:
    """Source-vs-generated similarity/correlation report (skeleton)."""

    per_column: dict[str, float] = field(default_factory=dict)
    global_correlation: float | None = None


@dataclass
class FaultManifest:
    """Auditable record of injected faults (skeleton)."""

    entries: list[dict[str, object]] = field(default_factory=list)

"""Canonical pipeline artifacts (AD-10).

A ``Dataset`` is a pandas DataFrame plus a canonical ``Schema`` (per-column
logical type + engine-agnostic dtype) that every stage preserves; exporters and
``EngineAdapter.load`` map from the Schema, never from raw pandas dtypes.

These are intentionally minimal skeletons for the scaffold story; later stories
flesh out their fields.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum

import pandas as pd

#: Digest size (bytes) for the leakage guard's keyed hashes. 16 bytes (128-bit)
#: makes accidental collisions between distinct source values negligible.
_LEAKAGE_DIGEST_SIZE = 16


def leakage_digest(value: object, salt: str) -> str:
    """Keyed one-way digest of ``value`` for the leakage guard (AD-6/AD-7).

    A per-Profile ``salt`` keys a BLAKE2b hash so the Profile stores membership of
    the source's real sensitive values **without** the raw value and without being
    vulnerable to generic precomputed rainbow tables. The value is stringified the
    same way the profiler stringifies category labels, so a source value and an
    equal generated value hash identically. Stdlib only, so this stays in
    ``domain`` (no adapter import).
    """
    key = salt.encode("utf-8")[:64]  # BLAKE2b key is at most 64 bytes
    return hashlib.blake2b(
        str(value).encode("utf-8"), key=key, digest_size=_LEAKAGE_DIGEST_SIZE
    ).hexdigest()


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


def profile_to_json(profile: Profile) -> str:
    """Serialize a Profile to deterministic JSON."""
    return json.dumps(asdict(profile), indent=2, default=str)


@dataclass
class Dataset:
    """A DataFrame paired with its canonical Schema (AD-10)."""

    frame: pd.DataFrame
    schema: Schema


#: Gate-only sentinel (PRD-1 AD-21). The sole holder is ``tymi.synth.leakage``; it is the
#: token that lets the leakage gate mint a ``GatedDataset``. Not exported.
_GATE_KEY = object()


@dataclass(frozen=True)
class GateReport:
    """What the leakage gate inspected while producing a :class:`GatedDataset`.

    ``columns_checked`` is the set of sensitive columns actually gated (present in the frame
    with a non-empty guard) — the columns the gate really inspected, not merely declared.
    """

    columns_checked: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False, init=False, repr=False)
class GatedDataset:
    """A point-in-time seal of a :class:`Dataset` proven free of real sensitive values by the
    leakage gate (AD-21).

    The provisioning ``load`` boundary accepts a ``GatedDataset`` and refuses a raw
    ``Dataset`` (:func:`require_gated`), so un-gated data reaching a destination is a *type*
    error, not a matter of discipline. The barrier stops **accidental** construction —
    including ``dataclasses.replace`` (the gate key is validated at ``__init__`` and never
    stored, so a field-copying protocol can't resurrect it). It is not a defense against a
    determined forger reaching into internals. The seal wraps an **independent copy** taken at
    gate time; identity is by object (``eq=False``), and ``repr`` never dumps cell values
    (this type carries sensitive columns).
    """

    dataset: Dataset
    report: GateReport

    def __init__(self, dataset: Dataset, report: GateReport, *, key: object) -> None:
        if key is not _GATE_KEY:
            raise TypeError(
                "GatedDataset can only be produced by the leakage gate (AD-21); "
                "do not construct it directly."
            )
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "report", report)

    def __repr__(self) -> str:  # never dump cell values — sensitive columns live here
        frame = self.dataset.frame
        return (
            f"GatedDataset(rows={len(frame)}, columns={list(frame.columns)}, "
            f"checked={self.report.columns_checked})"
        )

    @property
    def schema(self) -> Schema:
        """The canonical Schema of the gated data (preserved through the gate, AD-10)."""
        return self.dataset.schema

    @property
    def frame(self) -> pd.DataFrame:
        return self.dataset.frame


def require_gated(value: object) -> GatedDataset:
    """The load boundary (AD-21): return ``value`` if it is a ``GatedDataset``, else fail closed.

    A raw ``Dataset`` (or anything un-gated) raises ``TypeError`` — no un-gated data reaches a
    destination.
    """
    if not isinstance(value, GatedDataset):
        raise TypeError(
            f"a GatedDataset is required at the load boundary (AD-21), got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True)
class NumericStats:
    min: float
    max: float
    mean: float
    std: float
    quantiles: dict[str, float]
    histogram_bins: tuple[float, ...]
    histogram_counts: tuple[int, ...]


@dataclass(frozen=True)
class CategoryFrequency:
    value: str
    count: int


@dataclass(frozen=True)
class DatetimeStats:
    min: str | None
    max: str | None
    day_of_week_frequency: dict[str, int]
    month_frequency: dict[str, int]


@dataclass(frozen=True)
class TextStats:
    min_length: int
    max_length: int
    mean_length: float


@dataclass(frozen=True)
class ColumnProfile:
    """Per-column aggregates. Exactly one of the ``*_stats`` fields is set."""

    name: str
    logical_type: LogicalType
    count: int
    null_count: int
    distinct_count: int
    numeric: NumericStats | None = None
    categories: tuple[CategoryFrequency, ...] | None = None
    datetime: DatetimeStats | None = None
    text: TextStats | None = None


@dataclass(frozen=True)
class CorrelationMatrix:
    """A symmetric pairwise-association matrix over a set of columns.

    ``matrix[i][j]`` is the coefficient between ``columns[i]`` and ``columns[j]``;
    an undefined coefficient (constant column, zero overlap) is ``None`` so it
    serializes to JSON ``null`` rather than a bare ``NaN``.
    """

    method: str
    columns: tuple[str, ...]
    matrix: tuple[tuple[float | None, ...], ...]


@dataclass(frozen=True)
class Correlations:
    """Cross-column correlations detected during profiling (AD-6: coefficients only)."""

    numeric: CorrelationMatrix | None = None
    categorical: CorrelationMatrix | None = None


@dataclass(frozen=True)
class LeakageGuard:
    """Hashed membership set of the source's real values for sensitive columns.

    AD-7: the leakage gate checks every emitted sensitive value against this set
    and regenerates on collision. AD-6 is preserved — only keyed one-way digests
    (see :func:`leakage_digest`) are stored, never a raw value. ``columns`` maps a
    sensitive column name to the sorted distinct digests of its real values; the
    ``salt`` is a per-Profile nonce reused by the gate to hash generated values.
    """

    salt: str
    algorithm: str = "blake2b"
    columns: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass
class Profile:
    """Statistical signature of a source table.

    AD-6: stores only aggregates + schema + PII tags + hashed leakage guard, never
    raw row values.
    """

    schema_version: str = "1.0.0"
    schema: Schema = field(default_factory=Schema)
    row_count: int = 0
    columns: tuple[ColumnProfile, ...] = ()
    correlations: Correlations | None = None
    leakage_guard: LeakageGuard | None = None


@dataclass
class FidelityReport:
    """Source-vs-generated similarity/correlation report (Story 2.7).

    ``per_column`` maps a column to its KSComplement/TVComplement score in ``[0, 1]``;
    ``global_correlation`` is the CorrelationSimilarity (``None`` when < 2 numeric
    columns). ``passed`` is ``True`` only if every score and the global metric are
    ``>= tolerance``; ``failures`` lists the columns (or ``"__correlation__"``) below
    it. ``skipped`` names columns with no comparable distribution (e.g. free text).
    """

    per_column: dict[str, float] = field(default_factory=dict)
    global_correlation: float | None = None
    tolerance: float = 0.9
    passed: bool = True
    failures: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def fidelity_report_to_json(report: FidelityReport) -> str:
    """Serialize a FidelityReport to deterministic JSON (exportable, AC-3)."""
    return json.dumps(asdict(report), indent=2, sort_keys=True, default=str)


@dataclass
class QualityPrivacyReport:
    """Composite quality + privacy report (Story 4.3).

    ``quality_score`` is a single ``[0, 1]`` composite of the Story 2.7 fidelity metrics
    (the embedded ``fidelity`` carries the per-column drill-down). ``membership_risk`` is
    the share of generated sensitive values that exactly reproduce a real source value
    (via the hashed ``LeakageGuard``, AD-6). ``attribute_inference_risk`` is the strongest
    per-sensitive-column inference signal (correlation / mode probability) — a
    conservative proxy. Each privacy metric is ``None`` when not applicable (no sensitive
    columns). ``passed`` is ``True`` only if the quality score is ``>= quality_tolerance``
    and each applicable privacy metric is within its threshold; ``failures`` names the
    gates that tripped.
    """

    quality_score: float | None = None
    membership_risk: float | None = None
    attribute_inference_risk: float | None = None
    quality_tolerance: float = 0.9
    membership_threshold: float = 0.0
    attribute_threshold: float = 1.0
    passed: bool = True
    failures: tuple[str, ...] = ()
    fidelity: FidelityReport | None = None


def quality_privacy_report_to_json(report: QualityPrivacyReport) -> str:
    """Serialize a QualityPrivacyReport to deterministic JSON (exportable, AC-5)."""
    return json.dumps(asdict(report), indent=2, sort_keys=True, default=str)


@dataclass
class FaultManifest:
    """Auditable record of injected faults (Story 3.1+).

    Each entry describes one corruption a Mutator made — conventionally
    ``{"mutator", "row", "column", "fault_type", ...}`` — so a downstream Evaluate
    (chaos run_mode, AD-12) can validate the bidirectional fault contract (Story 3.6).
    """

    entries: list[dict[str, object]] = field(default_factory=list)


def merge_fault_manifests(manifests: Iterable[FaultManifest]) -> FaultManifest:
    """Concatenate manifests into one, preserving order (the chaos chain's order).

    Each entry is shallow-copied so editing a merged entry (e.g. a downstream audit,
    Story 3.6) cannot reach back and corrupt the producing Mutator's own manifest.
    """
    merged: list[dict[str, object]] = []
    for manifest in manifests:
        merged.extend(dict(entry) for entry in manifest.entries)
    return FaultManifest(entries=merged)


def fault_manifest_to_json(manifest: FaultManifest) -> str:
    """Serialize a FaultManifest to deterministic JSON."""
    return json.dumps(asdict(manifest), indent=2, default=str)


@dataclass
class ManifestAudit:
    """Result of the bidirectional Fault Manifest audit (Story 3.6).

    ``valid`` is ``True`` only when every listed fault materialized in the output AND
    every output change is listed. ``listed_not_present`` describes manifest entries not
    reflected in the output; ``present_not_listed`` describes output changes with no
    manifest entry. ``checked`` counts the faults compared.
    """

    valid: bool = True
    listed_not_present: tuple[str, ...] = ()
    present_not_listed: tuple[str, ...] = ()
    checked: int = 0


def manifest_audit_to_json(audit: ManifestAudit) -> str:
    """Serialize a ManifestAudit to deterministic JSON (exportable)."""
    return json.dumps(asdict(audit), indent=2, sort_keys=True, default=str)

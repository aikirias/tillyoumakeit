"""The whole-DB Spec — a versioned artifact bundling the pinned per-table Profiles (AD-14).

A ``Spec`` is the single, editable, versioned input to whole-DB provisioning (PRD 1). It
bundles each table's **pinned Profile** (its FK graph, stats, and sensitive marks live in the
Profile) plus per-table fixture and shared-key placeholders, a seed, and a tolerance. Because
the Profiles are embedded (not a live-source reference), regeneration reads the Spec offline —
the precondition for the cross-team consistency unit (AD-15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tymi.core.errors import ConfigError, ConfigVersionError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Profile
from tymi.profiling.profile_io import profile_from_dict, profile_to_dict
from tymi.profiling.profiler import profile_dataset

#: The Spec schema major version this build understands.
SPEC_SCHEMA_MAJOR = 1

_FORBID = ConfigDict(extra="forbid")


class TableSpec(BaseModel):
    """One table's entry in a :class:`Spec`: its pinned Profile + editable marks."""

    model_config = _FORBID

    #: The pinned Profile as a plain dict (round-trips via profile_to_dict/profile_from_dict).
    profile: dict[str, Any]
    #: Columns whose real values must never leak (mirrors the Profile's leakage guard).
    sensitive_columns: list[str] = Field(default_factory=list)
    #: Columns emitted with source-independent shared keys (AD-16) — filled in Story 2.2.
    shared_keys: list[str] = Field(default_factory=list)
    #: Pinned verbatim fixture rows (AD-17) — filled in Story 3.1.
    fixtures: list[dict[str, Any]] = Field(default_factory=list)


class Spec(BaseModel):
    """A versioned whole-DB generation spec (AD-14)."""

    model_config = _FORBID

    schema_version: str = "1.0.0"
    seed: int = 0
    tolerance: float = Field(default=0.9, ge=0.0, le=1.0)
    tables: dict[str, TableSpec] = Field(default_factory=dict)


def bootstrap_spec(
    profiles: dict[str, Profile], *, seed: int = 0, tolerance: float = 0.9
) -> Spec:
    """Build a first-cut Spec from already-pinned per-table Profiles (PDE-2).

    Sensitive columns are read from each Profile's leakage guard; fixtures and shared keys
    start empty (filled by later stories). The Profiles are embedded as-is (their salts and
    stats are pinned), so the Spec is self-contained (AC-2 / AD-15).
    """
    tables = {
        name: TableSpec(
            profile=profile_to_dict(prof),
            sensitive_columns=list(prof.leakage_guard.columns) if prof.leakage_guard else [],
        )
        for name, prof in profiles.items()
    }
    return Spec(seed=seed, tolerance=tolerance, tables=tables)


def bootstrap_from_source(
    adapter: Any,
    tables: list[str],
    *,
    rows: int = 1000,
    seed: int = 0,
    tolerance: float = 0.9,
    sensitive_columns: dict[str, list[str]] | None = None,
    classify_pii: bool = False,
    salt: str | None = None,
) -> Spec:
    """Introspect + sample + profile each declared table, then bundle a Spec (PDE-1/2).

    ``tables`` is explicit — the ``EngineAdapter`` port exposes no ``list_tables`` (PRD 1
    scopes that out). The ``adapter`` is injectable so this runs without a live DB in tests.

    With ``salt=None`` the leakage-guard salt is derived deterministically from ``seed`` (one
    salt for the whole Spec), so re-bootstrapping the same source with the same seed yields an
    identical Spec — the AD-15 offline-reproducibility contract. (The salt lives inside the
    shared Spec anyway, so deriving it from the seed is no secrecy regression.) Pass an explicit
    ``salt`` to override.
    """
    marks = sensitive_columns or {}
    resolved_salt = salt if salt is not None else f"tymi-spec-seed-{seed}"
    profiles: dict[str, Profile] = {}
    for table in tables:
        dataset = adapter.sample(table, rows=rows, rng=make_rng(seed))
        profiles[table] = profile_dataset(
            dataset,
            sensitive_columns=marks.get(table, ()),
            classify_pii=classify_pii,
            salt=resolved_salt,
        )
    return bootstrap_spec(profiles, seed=seed, tolerance=tolerance)


def spec_profiles(spec: Spec) -> dict[str, Profile]:
    """Reconstruct the pinned per-table Profiles from the Spec (offline; AD-15)."""
    return {name: profile_from_dict(ts.profile) for name, ts in spec.tables.items()}


def save_spec(spec: Spec, path: str | Path) -> None:
    """Write the Spec to ``path`` as one YAML carrying its ``schema_version``."""
    text = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not write spec file {path}: {exc}") from exc


def load_spec(path: str | Path) -> Spec:
    """Load a Spec, gating on ``schema_version`` major and validating (``extra='forbid'``)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read spec file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Spec root must be a mapping.")
    if _major(str(data.get("schema_version", "1.0.0"))) != SPEC_SCHEMA_MAJOR:
        raise ConfigVersionError(
            f"Unsupported spec schema_version {data.get('schema_version')!r}; "
            f"this build supports major {SPEC_SCHEMA_MAJOR}."
        )
    try:
        return Spec.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid spec: {exc}") from exc


def _major(version: str) -> int:
    try:
        return int(version.split(".")[0])
    except (ValueError, AttributeError, IndexError) as exc:
        raise ConfigVersionError(f"Malformed schema_version {version!r}.") from exc

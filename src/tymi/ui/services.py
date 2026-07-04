"""UI controller logic (Story 5.1+).

Pure functions the Streamlit view (``app.py``) calls. Kept free of any ``streamlit``
import so they are unit-testable without a browser and so the view stays a thin shell.
Every function takes/returns plain artifacts (the shared :class:`Config`, dataclasses),
and the engine registry is injectable so tests use a fake adapter with no live database.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tymi.config.models import Config, ConnectionConfig, SourceConfig
from tymi.core.errors import EngineConnectionError, TymiError
from tymi.core.plugins import load_engines
from tymi.core.rng import make_rng
from tymi.domain.artifacts import ColumnProfile, Dataset, Profile, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.synth.conditions import parse_conditions
from tymi.synth.generator import generate_faithful

#: Engines selectable in the connection form (the four AD-2 adapters).
ENGINES = ("mssql", "postgres", "mysql", "starrocks")


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of a connection test — never carries a raw credential."""

    ok: bool
    message: str


def default_config() -> Config:
    """A fresh Config for a new UI session (the shared, mutable-by-copy artifact)."""
    return Config()


def set_connection(
    config: Config,
    *,
    engine: str,
    host: str,
    port: int | None = None,
    database: str | None = None,
    user_env: str = "TYMI_DB_USER",
    password_env: str = "TYMI_DB_PASSWORD",
) -> Config:
    """Return a copy of ``config`` with its source engine + connection set.

    Only the *names* of the env vars holding credentials are stored (NFR-6). Pydantic
    validates the connection (e.g. port range), raising ``pydantic.ValidationError`` (a
    ``ValueError``) on bad input.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; expected one of {ENGINES}")
    # Normalise here (single source of truth for both the UI form and direct callers): a
    # blank host is a meaningless connection and must not save as a silent success; blank
    # optional fields collapse to None / the documented env-var defaults.
    host = host.strip()
    if not host:
        raise ValueError("host must not be empty")
    connection = ConnectionConfig(
        host=host,
        port=port,
        database=(database or "").strip() or None,
        user_env=(user_env or "").strip() or "TYMI_DB_USER",
        password_env=(password_env or "").strip() or "TYMI_DB_PASSWORD",
    )
    source = config.source.model_copy(update={"engine": engine, "connection": connection})
    return config.model_copy(update={"source": source})


def connection_summary(config: Config) -> dict[str, object] | None:
    """Display-safe view of the configured connection — env-var *names*, never secrets."""
    source = config.source
    conn = source.connection
    if source.engine is None or conn is None:
        return None
    return {
        "engine": source.engine,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "user_env": conn.user_env,
        "password_env": conn.password_env,
    }


def test_connection(
    config: Config, *, engines: dict[str, type] | None = None
) -> ConnectionResult:
    """Build the configured engine adapter in-process and test it.

    ``engines`` overrides the entry-point registry (tests inject a fake adapter). The
    returned message never contains a credential — only the connection error text, which
    the adapters are contracted to keep secret-free (NFR-6).
    """
    source = config.source
    if source.engine is None or source.connection is None:
        return ConnectionResult(False, "No connection configured yet.")
    registry = engines if engines is not None else load_engines()
    adapter_cls = registry.get(source.engine)
    if adapter_cls is None:
        return ConnectionResult(
            False, f"Unknown engine {source.engine!r}. Available: {sorted(registry)}"
        )
    try:
        adapter_cls(source.connection).test_connection()
    except EngineConnectionError as exc:
        return ConnectionResult(False, f"Connection failed: {exc}")
    except TymiError as exc:  # any typed adapter/config error, surfaced cleanly (scrubbed upstream)
        return ConnectionResult(False, str(exc))
    except Exception:  # noqa: BLE001 - a misbehaving 3rd-party adapter: don't echo a raw
        # driver traceback (it can carry a DSN/password) — return a generic message (NFR-6).
        return ConnectionResult(False, "Connection test failed with an unexpected adapter error.")
    return ConnectionResult(True, f"Connection to {source.engine!r} OK.")


# --- profile & schema explorer (Story 5.2) ----------------------------------


@dataclass(frozen=True)
class ColumnChart:
    """Display-ready distribution view for one column, built from the Profile aggregates."""

    name: str
    logical_type: str
    kind: str  # "histogram" | "categories" | "datetime" | "text" | "empty"
    data: pd.DataFrame | None
    summary: dict[str, object]
    #: A second chart frame (datetime: month frequency alongside ``data``'s day-of-week).
    extra: pd.DataFrame | None = None


def run_profile(
    config: Config,
    table: str,
    *,
    rows: int = 1000,
    seed: int = 0,
    extra_sensitive: tuple[str, ...] = (),
    classify_pii: bool = False,
    engines: dict[str, type] | None = None,
) -> Profile:
    """Sample ``table`` and profile it — the identical artifact ``tymi profile`` builds.

    Mirrors the CLI ``profile`` command: same sample + same ``profile_dataset`` call
    (sensitive columns merged from the Config and the extra list, order-preserving), so
    the UI never produces a divergent Profile (AD-8).
    """
    source = config.source
    if source.engine is None or source.connection is None:
        raise ValueError("No connection configured.")
    if not table.strip():
        raise ValueError("Table name is required.")
    if seed < 0:
        raise ValueError("seed must be >= 0.")
    registry = engines if engines is not None else load_engines()
    adapter_cls = registry.get(source.engine)
    if adapter_cls is None:
        raise ValueError(f"Unknown engine {source.engine!r}. Available: {sorted(registry)}")
    adapter = adapter_cls(source.connection)
    dataset = adapter.sample(table.strip(), rows=rows, rng=make_rng(seed))
    sensitive = list(dict.fromkeys([*extra_sensitive, *source.sensitive_columns]))
    return profile_dataset(
        dataset,
        sensitive_columns=sensitive,
        not_sensitive_columns=source.not_sensitive_columns,
        classify_pii=classify_pii,
    )


def schema_table(schema: Schema) -> pd.DataFrame:
    """The Schema as a display table: column name, logical type, nullability, PK flag."""
    return pd.DataFrame(
        [
            {
                "column": c.name,
                "type": c.logical_type.value,
                "nullable": c.nullable,
                "primary_key": c.primary_key,
            }
            for c in schema.columns
        ],
        # Explicit columns so an empty Schema yields an empty frame WITH headers rather
        # than a column-less frame that KeyErrors on df["column"].
        columns=["column", "type", "nullable", "primary_key"],
    )


def column_chart(cp: ColumnProfile) -> ColumnChart:
    """Build one column's distribution view from its stored aggregates (AD-6, no raw rows)."""
    lt = cp.logical_type.value
    summary: dict[str, object] = {
        "count": cp.count,
        "null_count": cp.null_count,
        "distinct_count": cp.distinct_count,
    }
    if cp.numeric is not None:
        n = cp.numeric
        counts = list(n.histogram_counts)
        edges = list(n.histogram_bins)
        if counts and len(edges) == len(counts) + 1:
            labels = [f"{edges[i]:.4g}–{edges[i + 1]:.4g}" for i in range(len(counts))]
            # Fall back to bin indices if value labels collide (narrow bins on a large
            # magnitude round to identical strings), else the bars merge and mislead.
            if len(set(labels)) != len(labels):
                labels = [f"bin {i}" for i in range(len(counts))]
        else:
            labels = [f"bin {i}" for i in range(len(counts))]
        data = pd.DataFrame({"bin": labels, "count": counts}).set_index("bin")
        summary.update({"min": n.min, "max": n.max, "mean": n.mean, "std": n.std})
        return ColumnChart(cp.name, lt, "histogram", data if counts else None, summary)
    if cp.categories is not None:
        data = pd.DataFrame(
            {"value": [c.value for c in cp.categories], "count": [c.count for c in cp.categories]}
        ).set_index("value")
        return ColumnChart(cp.name, lt, "categories", data if len(data) else None, summary)
    if cp.datetime is not None:
        d = cp.datetime
        dow = d.day_of_week_frequency or {}
        month = d.month_frequency or {}
        data = (
            pd.DataFrame({"day": list(dow), "count": list(dow.values())}).set_index("day")
            if dow
            else None
        )
        extra = (
            pd.DataFrame({"month": list(month), "count": list(month.values())}).set_index("month")
            if month
            else None
        )
        summary.update({"min": d.min, "max": d.max})
        return ColumnChart(cp.name, lt, "datetime", data, summary, extra=extra)
    if cp.text is not None:
        t = cp.text
        summary.update(
            {"min_length": t.min_length, "max_length": t.max_length, "mean_length": t.mean_length}
        )
        return ColumnChart(cp.name, lt, "text", None, summary)
    return ColumnChart(cp.name, lt, "empty", None, summary)


def profile_charts(profile: Profile) -> list[ColumnChart]:
    """Distribution view for every profiled column, in Schema order."""
    return [column_chart(cp) for cp in profile.columns]


# --- faithful generation config + preview (Story 5.3) -----------------------


@dataclass(frozen=True)
class ComparisonChart:
    """Per-column source-vs-generated distribution comparison for the preview."""

    name: str
    logical_type: str
    data: pd.DataFrame  # index = bin/category, columns = ["source", "generated"]


def set_generation(
    config: Config,
    *,
    rows: int,
    seed: int,
    tolerance: float,
    conditions: tuple[str, ...] = (),
) -> Config:
    """Write the generation choices back to the shared Config (AD-8).

    Re-validates the whole Config (``model_copy(update=...)`` skips field validators), so a
    bad ``rows``/``tolerance`` raises here instead of silently persisting a Config that
    fails its own schema — consistent with ``run_generation_preview``'s guards.
    """
    cleaned = [c.strip() for c in conditions if c.strip()]  # drop blank condition lines
    updated = config.model_copy(
        update={
            "generation": config.generation.model_copy(
                update={"rows": rows, "tolerance": tolerance, "conditions": cleaned}
            ),
            "seed": seed,
        }
    )
    return Config.model_validate(updated.model_dump())


def run_generation_preview(
    profile: Profile,
    *,
    rows: int = 1000,
    seed: int = 0,
    conditions: tuple[str, ...] = (),
) -> Dataset:
    """Generate a faithful preview — the same path as the CLI ``generate`` (AD-8)."""
    if rows <= 0:
        raise ValueError("rows must be > 0.")
    if seed < 0:
        raise ValueError("seed must be >= 0.")
    parsed = parse_conditions(list(conditions))
    return generate_faithful(profile, rows=rows, rng=make_rng(seed), conditions=parsed)


def generation_comparison(profile: Profile, generated: Dataset) -> list[ComparisonChart]:
    """Per-column source (Profile aggregates) vs generated (sample) distribution frames."""
    frame = generated.frame
    charts: list[ComparisonChart] = []
    for cp in profile.columns:
        if cp.name not in frame.columns:
            continue
        lt = cp.logical_type.value
        if cp.numeric is not None and len(cp.numeric.histogram_bins) >= 2:
            edges = np.asarray(cp.numeric.histogram_bins, dtype=float)
            src = np.asarray(cp.numeric.histogram_counts, dtype=float)
            values = pd.to_numeric(frame[cp.name], errors="coerce").to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            gen_counts, _ = np.histogram(values, bins=edges)
            labels = [f"bin {i}" for i in range(len(src))]
            # Normalize the generated series over the TOTAL generated count (not the in-bin
            # survivors): values outside the source bin range are dropped by np.histogram,
            # so this makes them show as missing mass (bars summing to < 1) instead of being
            # hidden by a renormalize-to-1 that misreads as "generator produced nothing".
            total = float(len(values))
            gen_frac = list(gen_counts / total) if total > 0 else [0.0] * len(gen_counts)
            data = pd.DataFrame(
                {"source": _normalize(src), "generated": gen_frac}, index=labels
            )
            charts.append(ComparisonChart(cp.name, lt, data))
        elif cp.categories is not None:
            src_freq = {c.value: float(c.count) for c in cp.categories}
            gen_freq = {
                # dropna first so a generated null doesn't become a spurious "nan" category.
                str(k): float(v)
                for k, v in frame[cp.name].dropna().astype(str).value_counts().items()
            }
            cats = list(dict.fromkeys([*src_freq, *gen_freq]))
            data = pd.DataFrame(
                {
                    "source": _normalize([src_freq.get(c, 0.0) for c in cats]),
                    "generated": _normalize([gen_freq.get(c, 0.0) for c in cats]),
                },
                index=cats,
            )
            charts.append(ComparisonChart(cp.name, lt, data))
    return charts


def _normalize(counts) -> list[float]:
    """Counts → a probability vector (sums to 1), or all-zeros when the total is 0."""
    arr = np.asarray(list(counts), dtype=float)
    total = arr.sum()
    return list(arr / total) if total > 0 else list(arr)


__all__ = [
    "ENGINES",
    "ConnectionResult",
    "ColumnChart",
    "ComparisonChart",
    "Config",
    "SourceConfig",
    "default_config",
    "set_connection",
    "connection_summary",
    "test_connection",
    "run_profile",
    "schema_table",
    "column_chart",
    "profile_charts",
    "set_generation",
    "run_generation_preview",
    "generation_comparison",
]

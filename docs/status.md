# Implementation Status

A living map of what exists in the code versus what is designed. Update this
page whenever a story changes status.

Legend: ✅ done · 🚧 in progress · ⬜ not started

## Epic 1 — Foundation & Source Profiling ✅

| Story | Scope | Status |
| --- | --- | --- |
| 1.1 | Project scaffold + hexagonal skeleton (uv package, core/ports/domain, config, RNG, plugin registry, CLI shell, CI, import-linter) | ✅ |
| 1.2 | `EngineAdapter` port + **MSSQL** connectivity (`tymi test-connection`), env-var credentials, entry-point registration, testcontainers integration test | ✅ |
| 1.3 | **PostgreSQL, MySQL, StarRocks** adapters via plugins (shared `SqlAlchemyEngineAdapter` base); PG + MySQL integration tests pass against real containers | ✅ |
| 1.4 | **Schema introspection** (`tymi schema`) — columns/types/PK/FK/indexes via SQLAlchemy reflection (all engines); verified on real PG + MySQL | ✅ |
| 1.5 | **Streaming, seed-reproducible sampling** (`tymi sample`) — per-dialect random SQL; PG/MySQL reproducibility verified on real containers. MSSQL (`NEWID()`) and StarRocks (distributed `RAND`) are random but **not** seed-reproducible (flagged via `reproducible_sample` + a CLI notice). Schema-qualified table names supported. | ✅ |
| 1.6 | **Per-column statistical profiler** (`tymi profile`) — numeric/categorical/datetime/text stats, no raw free-text values (AD-6); the first real Profile. Verified on real PG + MySQL | ✅ |
| 1.7 | **Correlation detection** — pairwise numeric correlation (Spearman) + first-order categorical dependencies (Cramér's V, in-house chi²) attached to the Profile; serializes to valid JSON (undefined → `null`, no raw values, AD-6). Verified on real PG + MySQL | ✅ |
| 1.8 | **Persistent, versioned Profile** (`tymi profile -o profile.yaml` / `--load`) — YAML save/load round-trip with `schema_version` gating; a loaded Profile is consumed fully **offline** (no source connection). Verified on real PG + MySQL | ✅ |

## Epic 2 — Faithful Synthetic Data ⬜

Marginal distributions, correlations (in-house Gaussian copula), referential
integrity, conditional generation, leakage gate, multi-destination export,
fidelity report.

## Epic 3 — Data Chaos Monkey ⬜

Pluggable mutator engine, out-of-distribution / format-type / schema-constraint
faults, chaos policy, fault manifest.

## Epic 4 — Privacy & Evaluation ⬜

PII auto-classification, privacy filters, quality & privacy report.

## Epic 5 — Web UI (Streamlit) ⬜

Wizard exposing the full connect → profile → configure → preview → export flow.

## What works today

- `tymi --help` and the CLI command surface (most subcommands are stubs).
- `tymi test-connection --engine <mssql|postgres|mysql|starrocks> --config <file>` —
  real connectivity check for all four engines, with credentials read from
  environment variables. (PostgreSQL and MySQL are verified end-to-end against
  real containers; MSSQL in CI with the ODBC driver; StarRocks opt-in.)
- Config loading/validation (Pydantic v2 + YAML, `schema_version` gating).
- The plugin registry (`tymi.engines`, `tymi.mutators`).
- `tymi schema` / `tymi sample` — schema introspection and seed-reproducible
  sampling (PG/MySQL) for all four engines.
- `tymi profile <table>` — the full source Profile: per-column stats
  (numeric/categorical/datetime/text), cross-column correlations (Spearman +
  Cramér's V), no raw values (AD-6). `-o profile.yaml` saves a versioned Profile;
  `--load profile.yaml` reads it back **offline** (no source connection).

Everything under "Generate / Chaos / Export" is designed (see the PRD and
architecture spine) but not yet implemented — Epic 2 consumes the Profile next.

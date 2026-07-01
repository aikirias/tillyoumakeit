# Implementation Status

A living map of what exists in the code versus what is designed. Update this
page whenever a story changes status.

Legend: ✅ done · 🚧 in progress · ⬜ not started

## Epic 1 — Foundation & Source Profiling

| Story | Scope | Status |
| --- | --- | --- |
| 1.1 | Project scaffold + hexagonal skeleton (uv package, core/ports/domain, config, RNG, plugin registry, CLI shell, CI, import-linter) | ✅ |
| 1.2 | `EngineAdapter` port + **MSSQL** connectivity (`tymi test-connection`), env-var credentials, entry-point registration, testcontainers integration test | ✅ |
| 1.3 | **PostgreSQL, MySQL, StarRocks** adapters via plugins (shared `SqlAlchemyEngineAdapter` base); PG + MySQL integration tests pass against real containers | ✅ |
| 1.4 | **Schema introspection** (`tymi schema`) — columns/types/PK/FK/indexes via SQLAlchemy reflection (all engines); verified on real PG + MySQL | ✅ |
| 1.5 | **Streaming, seed-reproducible sampling** (`tymi sample`) — per-dialect random SQL; PG/MySQL reproducibility verified on real containers (MSSQL random, non-reproducible) | ✅ |
| 1.6 | Per-column statistical profiler | ⬜ |
| 1.7 | Correlation detection | ⬜ |
| 1.8 | Persistent, versioned Profile | ⬜ |

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

Everything under "Profile / Generate / Chaos / Export" is designed (see the PRD
and architecture spine) but not yet implemented.

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

## Epic 2 — Faithful Synthetic Data 🚧

| Story | Scope | Status |
| --- | --- | --- |
| 2.1 | **Marginal distribution synthesis** (`tymi generate --profile … --rows … --seed …`) — per-column reproduction from the Profile: numeric inverse-transform from the histogram, categorical from stored frequencies, datetime across range, length-faithful synthetic text; nulls reproduced; canonical Schema preserved (AD-10); deterministic (AD-4/AD-11); no raw values (AD-6). Verified on real PG + MySQL | ✅ |
| 2.2 | **Correlation preservation (in-house Gaussian copula)** — numeric cross-column correlations from the Profile (Spearman) preserved via an in-house Gaussian copula (numpy + `scipy.special.ndtr`); marginals unchanged; deterministic; categorical cross-dependency deferred to a follow-up. Verified on real PG + MySQL | ✅ |
| 2.3 | **Referential integrity + realistic synthetic values** — `generate_related` produces related tables in topological order (parents before children, cycle detection), with unique PKs and every FK pointing at a real parent value (incl. junction/self-referential tables); text columns that look like email/name/phone/id get realistic **Faker** values (single-table `tymi generate` too). Verified on real PG + MySQL | ✅ |
| 2.4 | **Conditional (seeded) generation** (`tymi generate --where`) — condition a column by equality (`region=LATAM`), inclusive range (`age in [18,25]`) or membership set (`region in {LATAM,EMEA}`); 100% of rows satisfy every condition (no nulls) while non-conditioned columns keep their marginal + copula correlation. Range conditions draw from the histogram truncated to the range (not uniform). Deterministic; typed errors for invalid conditions | ✅ |
| 2.5 | **Leakage gate over declared sensitive columns** — columns marked sensitive in the Config (or `tymi profile --sensitive`) are hashed (keyed BLAKE2b + per-Profile salt) into a `LeakageGuard` on the Profile with their raw values suppressed (AD-6); `generate_faithful` runs the gate as its terminal core stage — every generated sensitive value is checked against the hashed set and regenerated on collision, failing closed with `LeakageError` if unresolvable. Sensitive `STRING` columns synthesize via Faker/length-text; other sensitive types emit typed null (rich PII synthesis → Epic 4). Deterministic (AD-4/AD-11) | ✅ |
| 2.6 | Multi-destination export | ⬜ |
| 2.7 | Fidelity Report | ⬜ |

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
- `tymi generate --profile profile.yaml --rows N --seed S` — **faithful synthesis**:
  loads a saved Profile **offline** and emits N synthetic rows whose per-column
  distributions match the Profile **and** whose numeric cross-column correlations
  are preserved via an in-house Gaussian copula, as CSV. Deterministic per seed;
  canonical Schema preserved (AD-10); no SDV/Copulas (AD-9). Text columns that look
  like email/name/phone/id get realistic **Faker** values (Story 2.3). Categorical
  cross-dependency preservation is a documented follow-up. `--where` conditions a
  column — `region=LATAM`, `age in [18,25]` (inclusive range) or `region in
  {LATAM,EMEA}` (set) — so 100% of rows satisfy it while the other columns keep
  their distribution (Story 2.4). Columns declared **sensitive** (config
  `source.sensitive_columns` or `--sensitive` at profile time) are hashed into a
  leakage guard with their raw values suppressed; a **leakage gate** then runs as a
  core stage of generation and guarantees no real sensitive value reaches the output,
  regenerating on collision and failing closed otherwise (Story 2.5).
- `generate_related(profiles, rows, rng)` (library) — **multi-table referential
  integrity**: related tables generated parents-before-children with unique PKs and
  valid FKs (incl. junction/self-referential tables). Verified on real PG + MySQL.
  Wiring a multi-table surface into the CLI/pipeline orchestrator lands with the
  export/pipeline stories.

Chaos, privacy filters, evaluation and export are designed (see the PRD and
architecture spine) but not yet implemented — Story 2.6 (multi-destination
export) is next.

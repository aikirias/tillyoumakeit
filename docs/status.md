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

## Epic 2 — Faithful Synthetic Data ✅

| Story | Scope | Status |
| --- | --- | --- |
| 2.1 | **Marginal distribution synthesis** (`tymi generate --profile … --rows … --seed …`) — per-column reproduction from the Profile: numeric inverse-transform from the histogram, categorical from stored frequencies, datetime across range, length-faithful synthetic text; nulls reproduced; canonical Schema preserved (AD-10); deterministic (AD-4/AD-11); no raw values (AD-6). Verified on real PG + MySQL | ✅ |
| 2.2 | **Correlation preservation (in-house Gaussian copula)** — numeric cross-column correlations from the Profile (Spearman) preserved via an in-house Gaussian copula (numpy + `scipy.special.ndtr`); marginals unchanged; deterministic; categorical cross-dependency deferred to a follow-up. Verified on real PG + MySQL | ✅ |
| 2.3 | **Referential integrity + realistic synthetic values** — `generate_related` produces related tables in topological order (parents before children, cycle detection), with unique PKs and every FK pointing at a real parent value (incl. junction/self-referential tables); text columns that look like email/name/phone/id get realistic **Faker** values (single-table `tymi generate` too). Verified on real PG + MySQL | ✅ |
| 2.4 | **Conditional (seeded) generation** (`tymi generate --where`) — condition a column by equality (`region=LATAM`), inclusive range (`age in [18,25]`) or membership set (`region in {LATAM,EMEA}`); 100% of rows satisfy every condition (no nulls) while non-conditioned columns keep their marginal + copula correlation. Range conditions draw from the histogram truncated to the range (not uniform). Deterministic; typed errors for invalid conditions | ✅ |
| 2.5 | **Leakage gate over declared sensitive columns** — columns marked sensitive in the Config (or `tymi profile --sensitive`) are hashed (keyed BLAKE2b + per-Profile salt) into a `LeakageGuard` on the Profile with their raw values suppressed (AD-6); `generate_faithful` runs the gate as its terminal core stage — every generated sensitive value is checked against the hashed set and regenerated on collision, failing closed with `LeakageError` if unresolvable. Sensitive `STRING` columns synthesize via Faker/length-text; other sensitive types emit typed null (rich PII synthesis → Epic 4). Deterministic (AD-4/AD-11) | ✅ |
| 2.6 | **Multi-destination export** — `tymi generate --to csv\|json\|parquet` writes a deterministic (byte-identical, NFR-4), re-importable file mapped from the canonical Schema (AR-10, not raw pandas dtypes); `--to sql --engine/--config/--table` loads the rows directly into any standard-SQL engine via `EngineAdapter.load` (Schema-driven DDL + insert, idempotent). Verified on real PG + MySQL; StarRocks auto-create is a documented exception (needs distribution DDL). Typed errors, no traceback | ✅ |
| 2.7 | **Fidelity Report** (`tymi report --fidelity`) — per-column **KSComplement** (numeric/datetime, two-sample KS vs a Profile-reconstructed reference) + **TVComplement** (categorical/boolean vs stored frequencies) + a global **CorrelationSimilarity**; scores in `[0,1]`, `--tolerance` gates a CI build (exit 1 on failure) and lists the failing columns; JSON, exportable via `--out`. Metrics computed **in-house** (scipy+numpy) — the SDMetrics package pulls `copulas` (BUSL-1.1), excluded by AD-9. Deterministic; AD-6 (Profile aggregates only) | ✅ |

## Epic 3 — Data Chaos Monkey ✅

| Story | Scope | Status |
| --- | --- | --- |
| 3.1 | **Pluggable Mutator engine** — `chaos/engine.py`: `resolve_mutators` discovers Mutators from the `tymi.mutators` entry-point group by name + order (AD-3, unknown → `ChaosError`); `apply_chaos` runs the chain threading the shared `rng` (AD-4/AD-11) and the mutated Dataset, and merges each Mutator's `FaultManifest`. Off-contract mutator returns / uninstantiable registry entries raise `ChaosError`; the caller's frame is copied (an in-place Mutator can't corrupt it; re-runs idempotent). A new Mutator runs with zero core changes. No fault mutators / no CLI yet | ✅ |
| 3.2 | **Out-of-distribution fault mutators** — `OutlierMutator` (registered under `tymi.mutators`) injects out-of-range values (`max + magnitude·span` / `min − magnitude·span`) into a configurable proportion of numeric/datetime cells; targeting by column or type (default all numeric/datetime), non-numeric target → `ChaosError`; integers stay strictly out-of-range + int64-clipped (no overflow), nulls preserved, exact `round(proportion·n)` per column (±2 pp margin). Each injection recorded in the `FaultManifest`. Deterministic; validated Pydantic params (AD-5); runs via the 3.1 engine with zero core change | ✅ |
| 3.3 | **Format & type violation mutators** — five independently-toggleable fault plugins under `tymi.mutators` on a shared `CellFaultMutator` base: `text_in_numeric`, `invalid_date` (unparsable + out-of-range), `broken_encoding` (corrupt-but-serializable), `oversized_string` (capped 10 MB), `illegal_null` (nulls in non-nullable columns). Each corrupts a proportion of applicable cells (≥1 on small columns), records a bounded manifest entry, preserves the canonical Schema (frame dtype degrades to `object` — that is the fault); targeting by column/type, deterministic, validated params | ✅ |
| 3.4 | **Schema & constraint breakage mutators** — six structural fault plugins under `tymi.mutators` that mutate the canonical Schema + frame: `missing_field`, `extra_field`, `renamed_column`, `changed_type`, `duplicate_keys` (violates PK/unique, composite-aware), `orphan_fk` (references no real parent). Schema stays internally consistent (columns == frame) — the *contract* is what breaks; deterministic, validated params, targeting by column. Check-constraint violations deferred (no check metadata in the MVP Schema) | ✅ |
| 3.5 | **Configurable Chaos Policy** (`tymi chaos --profile P --config C`) — a declarative `ChaosConfig` (`mode` mixed/fully_chaotic, `rate`, ordered `mutators` chain with per-mutator params) resolved from the `tymi.mutators` entry points; **mixed** mode corrupts a `rate` fraction of rows (±2 pp, robust to null-bearing targets) and leaves the rest faithful; **fully_chaotic** corrupts the whole table and, over a table with FKs, requires `--confirm` (breaks referential integrity by design). Emits chaotic CSV + optional fault manifest; deterministic | ✅ |
| 3.6 | **Fault Manifest (bidirectional audit)** — `audit_manifest(baseline, chaotic, manifest)` verifies both directions (every listed fault materialized; every output change vs the faithful baseline is listed), for cell **and** structural faults; `evaluate(dataset, run_mode=…)` dispatches faithful→FidelityReport / chaos→ManifestAudit (AD-12, no fidelity in chaos mode); `tymi chaos --audit` exits 1 if the manifest isn't a faithful record. Deterministic; JSON-exportable | ✅ |

## Epic 4 — Privacy & Evaluation ✅

| Story | Scope | Status |
| --- | --- | --- |
| 4.1 | **PII / Sensitive-Column auto-classification** — `tymi profile --classify-pii` auto-detects Sensitive Columns from the sample (in-house rules: value validators for email/SSN/IBAN/credit-card[Luhn]/IP/phone + column-name hints, restricted to non-numeric columns so a false positive can't null a numeric column); the detected set unions with `source.sensitive_columns` minus `source.not_sensitive_columns` (explicit mark always wins) and feeds the Story 2.5 `LeakageGuard` + suppression + gate — no raw values stored (AD-6). NER (Presidio/spaCy) deferred for weight; free-text PII is a documented follow-up | ✅ |
| 4.2 | **Privacy Filters (similarity + outlier)** — two `PrivacyFilter`s over faithful output: `SimilarityFilter` drops any row within `threshold` of a real `reference` row (a mixed-type, null-aware, z-scored distance — both-null matches so a memorized copy sharing a null can't slip the gate) and `OutlierFilter` drops tail extremes via a robust median/MAD modified z-score (catches clustered memorized extremes that mean/std self-masks). Both take the real `reference` explicitly (AD-6: the Profile stores no raw values → connected-only), preserve the canonical Schema (AD-10), and are drop-only → deterministic (AD-4/AD-11). Fail-loud: disjoint columns raise (no silent no-op), `threshold <= 0` rejected; pairwise distance computed in row-blocks to bound memory. `PrivacyConfig` toggles + thresholds. Pipeline wiring + residual-risk report → 4.3 | ✅ |
| 4.3 | **Quality & Privacy Report** — `tymi report --quality-privacy` emits a composite Quality Score (mean of the Story 2.7 KS/TV/correlation fidelity metrics) plus two in-house privacy metrics (AD-9: no SDMetrics): a **membership-disclosure** rate — the worst sensitive column's share of generated values that exactly reproduce a real source value, checked against the hashed `LeakageGuard` (keyed digests only, AD-6; a gated faithful run scores ~0) — and an **attribute-inference** proxy on the released data (max Spearman ρ / best single-predictor conditional-mode accuracy, with support guards). Deterministic JSON export (`--out`) and three configurable CI gates (`--tolerance` / `--membership-threshold` / `--attribute-threshold`) that fail the build on exit 1 | ✅ |

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
  regenerating on collision and failing closed otherwise (Story 2.5). `--to
  csv|json|parquet --out FILE` writes a deterministic, re-importable file (mapped
  from the canonical Schema, AR-10), and `--to sql --engine E --config C --table T`
  loads the rows directly into any standard-SQL engine (Story 2.6).
- `tymi report --fidelity --profile profile.yaml` — a **fidelity report** scoring the
  generated data against the Profile: per-column KSComplement/TVComplement + a global
  correlation metric, all in-house (scipy+numpy; no SDMetrics/copulas BUSL, AD-9).
  `--tolerance` gates a CI build (exit 1 on failure), `--out` exports the JSON, and
  `--data file.parquet` evaluates an externally-produced dataset (Story 2.7).
- `generate_related(profiles, rows, rng)` (library) — **multi-table referential
  integrity**: related tables generated parents-before-children with unique PKs and
  valid FKs (incl. junction/self-referential tables). Verified on real PG + MySQL.
  Wiring a multi-table surface into the CLI/pipeline orchestrator lands with the
  export/pipeline stories.

Epics 1–4 are complete (source profiling, faithful synthetic data, the data chaos
monkey — pluggable mutators, all fault families, chaos policy, and the bidirectional
fault-manifest audit — and privacy & evaluation: PII auto-classification, the
similarity/outlier privacy filters, and the composite quality & privacy report). The
Streamlit UI (Epic 5) is designed (see the PRD and architecture spine) but unbuilt —
Epic 5 is next. The cross-stage pipeline orchestrator (`core/pipeline.py`), the
generate→privacy-filter wiring, and the multi-table chaos surface remain honestly
deferred to the pipeline/UI work.

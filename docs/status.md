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

## Epic 5 — Web UI (Streamlit) ✅

Wizard exposing the full connect → profile → configure → preview → export flow.

| Story | Scope | Status |
| --- | --- | --- |
| 5.1 | **App shell + connection management** — `tymi ui` launches an in-process Streamlit wizard (driving adapter beside the CLI, no REST — AD-8); a sidebar walks Connection → Profile → Generate → Chaos → Reports. The Connection page builds/tests an engine adapter in-process and writes the connection into the one shared Pydantic `Config` (the same artifact the CLI loads). Credentials are never entered or shown — only the *names* of the env vars holding them (NFR-6). Logic lives in a pure `services.py` (engine registry injectable); the view is a thin `app.py` driven in tests by `streamlit.testing.v1.AppTest` | ✅ |
| 5.2 | **Profile & schema explorer** — the Profile page samples + profiles a table in-process (`run_profile`, byte-identical to the CLI `profile` wiring, AD-8) and stores the `Profile` in session; it renders the normalized Schema table (name/type/nullable/PK) and per-column distribution charts built only from the Profile's stored aggregates (AD-6): numeric → histogram, categorical → frequencies, datetime → day-of-week + month, text → length summary. No-connection guidance; failure surfaces without echoing raw driver errors (NFR-6) and clears any stale profile | ✅ |
| 5.3 | **Faithful generation config + preview** — the Generate page configures rows/seed/tolerance/conditions (pre-filled from the Config) and previews a real faithful sample via the same `generate_faithful` + `parse_conditions` path as the CLI (AD-8, deterministic AD-4); it renders the sample and a per-column source-vs-generated distribution comparison (source from Profile aggregates, generated re-binned over the same bins; out-of-range mass shown honestly). Choices are re-validated and written back to `Config.generation`/`Config.seed` (new `conditions` field, YAML round-trips). No-profile guidance; numeric+categorical comparison only (disclosed) | ✅ |
| 5.4 | **Chaos policy config + preview** — the Chaos page configures mode/rate/mutators (+ FK confirmation) and previews via the same `generate_faithful` → `apply_policy` path as the CLI `chaos` (single threaded rng, deterministic); the corrupted cells are highlighted from the Fault Manifest (pure `fault_style_frame`). `fully_chaotic` over a table with foreign keys is refused until the confirmation box is ticked (mirrors CLI `--confirm`). The policy is re-validated and written back to `Config.chaos` (YAML round-trips); stable widget keys so a re-preview honors changed selections | ✅ |
| 5.5 | **Reports view + export** — the Reports page shows the faithful reports (Fidelity + Quality & Privacy, the exact CLI artifacts) or the chaos Fault Manifest, with a "Report for" toggle when both runs are in session; it exports the dataset to csv/json/parquet (byte-identical to the CLI exporter, NFR-4) via a download button, or loads it into the configured engine (`adapter.load`, the CLI `--to sql` path, AD-2). Nothing-generated guidance | ✅ |

---

## PRD 1 — Obfuscated Prod-Like Dev Environments (Phase 1) ✅

Post-MVP capability: provision a **whole**, FK-consistent, fully-obfuscated database into a non-prod
environment from one command, with **cross-team consistency**, **pinned fixtures**, and a
**fail-closed guardrail**. See [Provisioning](provisioning.md) for the concepts. Architecture spine
`architecture/architecture-tymi-pde1-phase1-2026-07-04/` (`AD-13..21` over the MVP's `AD-1..12`);
per-story records in `_bmad-output/implementation-artifacts/pde1-*.md`. Phase 1 validates the
cross-team-consistency wedge on the in-memory engine; Phase 2 (out-of-core) and Phase 3 (cross-table
correlation / subsetting / delta refresh) are deferred.

### Epic 1 — Whole-DB Spec & faithful generation ✅

| Story | Scope | Status |
| --- | --- | --- |
| 1.1 | **`GatedDataset` load boundary** (AD-21) — a seal type mintable only by the leakage/scan gate; the provisioning `load` accepts a `GatedDataset` and refuses a raw `Dataset` (`require_gated`), so un-gated data at a destination is a *type* error. Resists `dataclasses.replace` forging; sensitive-safe `repr`. | ✅ |
| 1.2 | **Whole-DB `Spec` model + auto-bootstrap** (AD-14, `config/spec.py`) — a versioned artifact bundling each table's **pinned Profile** (embedded, offline) + row count + seed + tolerance; `bootstrap_from_source` introspects+samples+profiles every declared table; YAML round-trips; seed-reproducible bootstrap salt. | ✅ |
| 1.3 | **Whole-DB faithful generation** (`generate_from_spec`, AD-13, `synth/whole_db.py`) — first-wires `generate_related` to produce every table in FK-topological order, each sealed as a `GatedDataset`; same Spec+seed → byte-identical; out-of-spec FK parent fails closed. | ✅ |

### Epic 2 — Cross-team consistency (the wedge) ✅

| Story | Scope | Status |
| --- | --- | --- |
| 2.1 | **Per-table RNG substreams** (AD-20, `synth/substreams.py`) — each table draws from a deterministic substream `(seed, table_name)` (hashlib entropy, process-independent), replacing `generate_related`'s single shared RNG; a table's rows and FK edges are byte-identical regardless of an unrelated table's row count or the generation order. | ✅ |
| 2.2 | **Position-derived shared keys + reserved fixture keyspace** (AD-16, `synth/keys.py`, closes OQ-5) — columns declared `shared` are emitted `reserved_key_block + position` (source- and seed-independent), so two teams with the same pinned row counts get identical join keys; referencing FKs remapped for integrity; fixtures occupy a disjoint reserved block, validated fail-closed; a shared key must be unique and non-composite. | ✅ |
| 2.3 | **Consistency unit + fingerprint** (AD-15, `config/consistency.py`) — a stable hash over `(Spec + pinned Profiles + seed + pinned deps)`; identical units → identical fingerprint **and** byte-identical output; a changed Spec/Profile/seed/dep changes it; regeneration reuses the bundled Profiles offline, never re-profiling the source. | ✅ |

### Epic 3 — Fixtures & safe self-service provisioning ✅

| Story | Scope | Status |
| --- | --- | --- |
| 3.1 | **Pinned fixtures + scan-and-reject** (AD-17, `synth/fixtures.py` + `leakage.scan_and_gate`) — login/test accounts injected **verbatim** in the reserved keyspace, FK-consistent, exempt from regeneration but scanned: fixture rows checked against the full real-value guard **and** a PII classifier (any single PII cell trips it); a real value or un-guarded PII fails closed; adding a fixture logs an attestation; generated rows never collide with fixture keys. | ✅ |
| 3.2 | **Non-prod destination guardrail** (AD-18, `provision/guardrail.py`, closes OQ-2) — `assert_nonprod_destination` fails closed unless the Spec's destination affirms `environment: nonprod` **and** neither host nor database matches a case-insensitive prod deny-list glob; empty deny-list still requires the affirmation. The `destination` block is excluded from the consistency fingerprint. | ✅ |
| 3.3 | **One-command `tymi provision --spec`** (AD-19, `provision/pipeline.py`) — the thin composition-adapter pipeline the CLI and any CI/DAG call identically: guardrail → generate → `require_gated` → idempotent clean-replace load → **provisioning report** (rows, fixtures, gated columns, fidelity, consistency-unit fingerprint). The CLI cross-checks the real `--config` connection against the affirmed destination. | ✅ |

## PRD 1 — Phase 2: Out-of-core streaming ✅

Provision a database from a few MB to hundreds of TB with peak memory bounded to one row-chunk.
Spine `architecture-tymi-pde-phase2-2026-07-05/` (AD-22..24), no new dependencies. Rides the Phase-1
seam (per-table substreams + position-derived keys). See [Provisioning](provisioning.md).

| Story | Scope | Status |
| --- | --- | --- |
| P2.1 | **Chunk-aware substreams + chunked generation** (AD-22, `synth/substreams.py` + `synth/streaming.py`) — `table_substream(seed, table, chunk)`; `generate_table_chunks` yields a table as bounded-memory blocks with global-position surrogate PK / shared keys; byte-identical for a given `(seed, table, chunk_rows)`; leakage gate per block. New `Spec.chunk_rows` (pinned, in the fingerprint). | ✅ |
| P2.2 | **Position-addressable FK resolution** (AD-23) — a child block resolves each single-column FK by drawing parent **positions** and mapping them via a `ParentKeyRule` (`base+pos`), so the parent is never materialised; a composite/natural-key FK target fails closed. | ✅ |
| P2.3 | **Streaming load + `stream_from_spec`** (AD-24) — streams the whole DB as sealed `GatedDataset` chunks in FK order; `EngineAdapter.load_stream` replaces on the first chunk, appends the rest (idempotent). Fixtures fail closed on the streaming path (use in-memory). | ✅ |
| P2.4 | **Out-of-core `provision --stream`** — `provision(stream=True)` streams chunk-by-chunk (`require_gated` per chunk at the write boundary); the report aggregates rows across chunks; the fingerprint folds in the generation `mode` (in-memory vs streaming emit different byte layouts). | ✅ |

## PRD 1 — Phase 3: Depth & controls ✅

Spine `architecture-tymi-pde-phase3-2026-07-05/` (AD-25..27), in-memory, no new dependencies.

| Story | Scope | Status |
| --- | --- | --- |
| P3.1 | **Cross-table single-hop correlation** (AD-25, `synth/cross_correlation.py`) — a declared `CrossCorrelation(child.col ↔ parent.col, ρ)` is induced by a Gaussian-copula rank **reorder** (Spearman ≈ ρ vs the referenced parent value) that preserves the child marginal; both columns numeric; single-hop/self/key declarations fail closed; each table's correlations draw from an independent substream. | ✅ |
| P3.2 | **Referentially-consistent subsetting** (AD-26, `synth/subset.py`) — keep a deterministic fraction of a root table; a **downward** closure keeps descendants connected to kept roots and an **upward** closure keeps the dimensions they reference (no re-expansion). Keys are not renumbered, so a subset joins to a full sibling dataset; cyclic/composite/no-PK graphs fail closed. | ✅ |
| P3.3 | **Incremental / delta refresh** (AD-27, `synth/delta.py`) — `delta_refresh(previous, new)` diffs two Specs and regenerates only dirty tables (direct change, key-affecting parent one hop, or a dirty cross-correlation parent); a clean table is byte-identical to the previous run, so the caller reloads only what changed. Reports regenerated / reused / dropped + the new fingerprint. | ✅ |

---

## What works today

- `tymi --help` and the full CLI command surface (no stubs remain).
- `tymi ui` — the Streamlit wizard for the whole flow (connect → profile → generate →
  chaos → reports/export), in-process over the same shared Config the CLI uses (Epic 5).
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
- `generate_related(profiles, rows, seed)` (library) — **multi-table referential
  integrity**: related tables generated parents-before-children with unique PKs and
  valid FKs (incl. junction/self-referential tables), each from its own per-table RNG
  substream. Verified on real PG + MySQL.
- `tymi provision --spec dev-env.spec.yaml --engine E --config runner.yaml` — **whole-DB
  obfuscated provisioning** (PRD 1): bootstrap a versioned `Spec` from a source, then
  provision the whole FK-consistent, fully-gated database into a **non-prod** destination
  in one command (runnable in CI/DAG). Cross-team-consistent shared keys, pinned login
  fixtures (scan-and-reject), a fail-closed non-prod guardrail, and a provisioning report
  with the consistency-unit fingerprint. See [Provisioning](provisioning.md).

All five MVP epics are complete: source profiling, faithful synthetic data, the data chaos
monkey (pluggable mutators, all fault families, chaos policy, and the bidirectional
fault-manifest audit), privacy & evaluation (PII auto-classification, the
similarity/outlier privacy filters, and the composite quality & privacy report), and the
Streamlit UI (`tymi ui` — connect → profile → generate → chaos → reports/export over the
one shared Config).

**PRD 1 — all three phases** (post-MVP) are complete: whole-DB obfuscated dev-environment
provisioning. **Phase 1** — the `Spec` model + auto-bootstrap, whole-DB faithful generation,
per-table RNG substreams, source-independent shared keys, the consistency-unit fingerprint, pinned
fixtures with scan-and-reject, the non-prod guardrail, and `tymi provision`. **Phase 2** —
out-of-core streaming (`--stream`): chunked generation, position-addressable FK resolution, and a
streaming load, so a DB of any size provisions with bounded memory. **Phase 3** — cross-table
single-hop correlation, referentially-consistent subsetting, and incremental delta refresh. See
[Provisioning](provisioning.md).

Honestly deferred: the cross-stage pipeline orchestrator (`core/pipeline.py`), the
generate→privacy-filter wiring, wiring `tymi generate` to read `Config.generation`, and the
multi-table chaos surface. Within PRD 1: cross-table correlation *over streaming*, multi-hop /
source-profiled correlation, subsetting over streaming, and whole-DB transactional atomicity.

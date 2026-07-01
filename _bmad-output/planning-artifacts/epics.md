---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-tymi-2026-07-01/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-tymi-2026-07-01/solution-design.md
---

# TYMI - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for TYMI ("Fake It Till You Make It"), decomposing the requirements from the PRD and the Architecture spine into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: Connect to Sources — configurable connection string + secure credentials for MSSQL, StarRocks, PostgreSQL, MySQL.
FR-2: Schema Introspection — columns, types, nullability, PK/FK, unique/check constraints, indexes; normalized to a common model.
FR-3: Streaming Sampling — sample N rows or X% without loading the full table; seed-reproducible.
FR-4: Per-Column Profile — numeric/categorical/date/string profiles; no re-identifiable raw values.
FR-5: Correlation Detection — pairwise numeric correlation + first-order categorical dependencies.
FR-6: Persistent, Versioned Profile — save/load Profile with schema version; regenerate offline.
FR-7: Marginal Distribution Reproduction — generate N rows matching per-column distributions within Tolerance; seed-reproducible.
FR-8: Correlation Preservation — preserve correlations within Tolerance.
FR-9: Referential Integrity & Realistic Values — PK/FK/unique respected (parents before children); synthetic realistic formatted values, no source copies.
FR-10: Conditional Generation (Seeded) — condition generation on column values/ranges, preserving the rest of the signature.
FR-11: Pluggable Mutator Engine — registrable Mutators, configurable order, each records what it corrupted.
FR-12: Out-of-Distribution Faults — outliers/low-probability values, configurable proportion + targeting.
FR-13: Format and Type Violations — text-in-numeric, invalid dates, broken encoding, oversized strings, illegal nulls.
FR-14: Schema and Constraint Breakage — missing/extra fields, renamed columns, changed types, dup PK/unique, orphan FK, check violations.
FR-15: Configurable Chaos Policy — global rate, targeting, output mode (Mixed / Fully Chaotic); Fully-Chaotic-with-FKs needs explicit confirmation.
FR-16: Fault Manifest — per row/column injected fault type; seed-reproducible, exportable; bidirectional contract with output.
FR-17: Multi-Destination Export (any engine) — files (CSV/Parquet/JSON), SQL INSERT, direct load into any of the 4 engines; byte-identical for deterministic exporters.
FR-18: Fidelity Report — source-vs-generated per-column similarity + global correlation; CI-integrable.
FR-19: Declarative Config — one versionable YAML file, shared source of truth CLI↔UI.
FR-20: CLI — profile/generate/chaos/report/export; exit codes for CI.
FR-21: Python Library — same capabilities as CLI, programmatic.
FR-22: Web UI — connect, profile, configure generation/chaos, preview (chaotic rows highlighted), reports, export; reads/writes the Config.
FR-23: PII / Sensitive-Column Auto-Classification — NER+rules detect & tag Sensitive Columns; user override via Config.
FR-24: Privacy Filters — similarity filter + outlier filter over faithful output; configurable, seed-reproducible.
FR-25: Quality & Privacy Report — composite Quality Score + membership/attribute inference Privacy Metrics; extends the Fidelity Report.

### NonFunctional Requirements

NFR-1: Privacy — no real sensitive value in output; enforced by exact membership check (not sampling); Profiles store no re-identifiable raw values.
NFR-2: Performance — sampling/streaming profiling; tables ≥10M rows without exhausting memory (configurable limit).
NFR-3: Fidelity — distribution divergence within a configurable Tolerance (default target: ≥90% columns pass).
NFR-4: Reproducibility — same config + same Seed ⇒ byte-identical output on deterministic exporters.
NFR-5: Extensibility — new Source engine or new Mutator via plugin without touching core.
NFR-6: Security — credentials never persisted in plaintext; env vars / secret managers.
NFR-7: Observability — structured logs + run artifacts (Fidelity Report + Fault Manifest) for CI traceability.

### Additional Requirements

*From the Architecture spine (AD = Architecture Decision). No external starter template — greenfield custom hexagonal scaffold (impacts Epic 1, Story 1).*

- AR-1 (AD-1): Hexagonal skeleton — pure `tymi.core` depending only on `tymi.ports`; all I/O in adapters; uv-managed package.
- AR-2 (AD-2): EngineAdapter is bidirectional (introspect/sample + load) with capability flags; source/destination are runtime roles.
- AR-3 (AD-3, NFR-5): Plugin discovery via `importlib.metadata` entry points (groups `tymi.engines`, `tymi.mutators`).
- AR-4 (AD-4, AD-11, NFR-4): Single `numpy.random.Generator` seeded from config, passed as keyword-only `rng` to every stochastic Port method.
- AR-5 (AD-5): Pydantic-v2 + YAML Config with semver `schema_version`; per-plugin param schema validated at load.
- AR-6 (AD-6): Profile persists only aggregates + schema + PII tags; never raw values.
- AR-7 (AD-7, NFR-1): Leakage Gate is a core pre-export stage on BOTH generate branches (exact membership check).
- AR-8 (AD-8): Single pipeline orchestrator in core (Connect→Profile→Generate→PrivacyFilters/LeakageGate→Evaluate→Export); CLI/UI are thin driving adapters.
- AR-9 (AD-9): Permissive-license-only dependencies; SDV and Copulas excluded (BUSL-1.1); correlation via in-house Gaussian copula on numpy/scipy.
- AR-10 (AD-10): Canonical Dataset `Schema` (logical type + engine-agnostic dtype) preserved by every stage; Exporters/load map from it.
- AR-11 (AD-12): Evaluate consumes `(Dataset, run_mode)` with a defined per-branch contract.
- AR-12: Web UI = Streamlit (pure Python, in-process); REST API/FastAPI deferred.
- AR-13: Testing — pytest; unit (pure core); integration via testcontainers (MSSQL/PostgreSQL/MySQL); statistical-validation tests (SDMetrics thresholds) in CI.

### UX Design Requirements

*No dedicated UX spine yet. Web UI stories derive from FR-22 + the Streamlit decision (AR-12). A `bmad-ux` run can add a detailed wizard spec later.*

### FR Coverage Map

FR-1: Epic 1 — connect to any of the 4 engines
FR-2: Epic 1 — schema introspection
FR-3: Epic 1 — streaming sampling
FR-4: Epic 1 — per-column profile
FR-5: Epic 1 — correlation detection
FR-6: Epic 1 — persistent versioned profile
FR-7: Epic 2 — marginal distribution reproduction
FR-8: Epic 2 — correlation preservation
FR-9: Epic 2 — referential integrity + realistic values
FR-10: Epic 2 — conditional/seeded generation
FR-11: Epic 3 — pluggable mutator engine
FR-12: Epic 3 — out-of-distribution faults
FR-13: Epic 3 — format/type violations
FR-14: Epic 3 — schema/constraint breakage
FR-15: Epic 3 — configurable chaos policy
FR-16: Epic 3 — fault manifest
FR-17: Epic 2 — multi-destination export (reused by Epic 3)
FR-18: Epic 2 — fidelity report
FR-19: Epic 1 — declarative config (established, extended per epic)
FR-20: Epic 1 — CLI (established, extended per epic)
FR-21: Epic 1 — Python library (established, extended per epic)
FR-22: Epic 5 — web UI (Streamlit)
FR-23: Epic 4 — PII auto-classification
FR-24: Epic 4 — privacy filters
FR-25: Epic 4 — quality & privacy report

## Epic List

### Epic 1: Foundation & Source Profiling
Establish the hexagonal project skeleton (uv package, core/ports/adapters, plugin registry, seeded RNG, canonical Dataset schema, YAML config, CI + testcontainers) and deliver the ability to connect to any of the 4 engines, introspect schema, sample data, and build a reusable, privacy-safe Profile — usable from the CLI and library. **User outcome:** "I can point TYMI at any of my databases and produce a reusable Profile plus inspect its schema and a data sample."
**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-6; establishes FR-19, FR-20, FR-21. Foundation for AR-1..AR-13.

### Epic 2: Faithful Synthetic Data
From a Profile, generate synthetic data that reproduces distributions and correlations (in-house Gaussian copula) with referential integrity, realistic synthetic values, and conditional/seeded control; export to files / SQL / any engine; produce a Fidelity Report. Includes a basic leakage gate over config-declared sensitive columns. **User outcome:** "I can produce a statistically faithful, exportable synthetic dataset and see a fidelity report proving it matches — with no real values leaked."
**FRs covered:** FR-7, FR-8, FR-9, FR-10, FR-17, FR-18.

### Epic 3: Data Chaos Monkey
A pluggable Mutator engine producing the three fault families (out-of-distribution, format/type, schema/constraint) driven by a declarative Chaos Policy, with a seed-reproducible Fault Manifest; reuses Epic 2 export. **User outcome:** "I can produce controlled, auditable corrupted datasets to test whether my pipeline catches bad data."
**FRs covered:** FR-11, FR-12, FR-13, FR-14, FR-15, FR-16.

### Epic 4: Privacy & Evaluation
Auto-classify PII / Sensitive Columns (NER+rules), apply Privacy Filters (similarity + outlier) over faithful output, harden the leakage gate, and produce a Quality & Privacy Report with measurable privacy metrics. **User outcome:** "I can trust and measure privacy — sensitive columns are detected automatically, output is filtered, and I get a quality + privacy score."
**FRs covered:** FR-23, FR-24, FR-25 (deepens NFR-1 / AD-7).

### Epic 5: Web UI (Streamlit)
A pure-Python Streamlit wizard exposing the full flow (connect → profile → configure generation → configure chaos → preview with chaotic rows highlighted → export) for both capabilities, reading/writing the same Declarative Config. **User outcome:** "I can run the entire faithful/chaos workflow from the browser without the CLI."
**FRs covered:** FR-22.

---

## Epic 1: Foundation & Source Profiling

Establish the hexagonal skeleton and deliver: connect to any of the 4 engines, introspect, sample, and build a reusable, privacy-safe Profile from CLI and library.

### Story 1.1: Project scaffold and hexagonal skeleton

As a developer,
I want a uv-managed package with the hexagonal skeleton, config loader, a CLI shell, and CI,
So that every later story has a consistent, testable base to build on.

**Acceptance Criteria:**

**Given** a clean checkout
**When** I run `uv sync` and `uv run tymi --help`
**Then** the package installs and the Typer CLI prints its (stubbed) subcommands
**And** `tymi.core` imports only `tymi.ports` (enforced by an import-lint test)
**And** CI runs lint + tests on every push
**And** a `Config` model (Pydantic v2) loads a YAML file carrying a semver `schema_version`, rejecting an unknown major.

### Story 1.2: EngineAdapter port and MSSQL connectivity

As a user,
I want to connect to MSSQL with a configurable connection string and secure credentials,
So that TYMI can reach my database without me hardcoding secrets.

**Acceptance Criteria:**

**Given** valid MSSQL credentials provided via env/secret
**When** I run `tymi test-connection --engine mssql`
**Then** it reports success against a testcontainer
**And** the `EngineAdapter` port exposes `introspect`, `sample`, `load`, and capability flags
**And** invalid credentials/unreachable host produce an actionable error without printing secrets (NFR-6).

### Story 1.3: PostgreSQL, MySQL, and StarRocks adapters via plugins

As a user,
I want the same connectivity for PostgreSQL, MySQL, and StarRocks,
So that all four engines are usable as source or destination.

**Acceptance Criteria:**

**Given** each engine's credentials
**When** I run `tymi test-connection` for each
**Then** each adapter passes the same connection test against its testcontainer
**And** StarRocks connects over the MySQL wire protocol
**And** all four adapters are discovered via `tymi.engines` entry points, with the core importing none of them directly (AR-3).

### Story 1.4: Schema introspection

As a user,
I want to extract a table's schema (columns, types, nullability, PK/FK, unique/check, indexes),
So that generation and chaos can respect the real structure.

**Acceptance Criteria:**

**Given** a connected source and a table name
**When** I run `tymi schema <table>`
**Then** a serializable (JSON) schema is produced, normalized to a common model across engines
**And** FK relationships between tables are captured
**And** engine-specific quirks are hidden behind the common model.

### Story 1.5: Streaming, seed-reproducible sampling

As a user,
I want to sample N rows or X% of a table without loading it fully,
So that I can profile large tables safely.

**Acceptance Criteria:**

**Given** a table of ≥10M rows in a testcontainer
**When** I run `tymi sample <table> --rows N --seed S`
**Then** a sample is returned without exceeding a configurable memory limit (NFR-2)
**And** the same seed yields the same sample (the RNG is created from the seed and passed explicitly, AR-4).

### Story 1.6: Per-column statistical profiler

As a user,
I want each column profiled by type (numeric/categorical/date/string),
So that I capture the statistical shape without storing raw values.

**Acceptance Criteria:**

**Given** a sample
**When** I run `tymi profile <table>`
**Then** numeric columns get histogram/quantiles/mean/std/min/max/cardinality, categoricals get frequencies, dates get range + basic seasonality, strings get length/pattern stats
**And** the Profile stores no re-identifiable raw values (AR-6); free-text keeps only pattern/length stats.

### Story 1.7: Correlation detection

As a user,
I want cross-column correlations detected,
So that faithful generation can later preserve them.

**Acceptance Criteria:**

**Given** a profiled table
**When** profiling completes
**Then** the Profile includes a pairwise numeric correlation matrix and first-order categorical dependencies
**And** the representation is serializable within the Profile artifact.

### Story 1.8: Persistent, versioned Profile

As a user,
I want to save and load a Profile file,
So that I can regenerate data later without reconnecting to the source.

**Acceptance Criteria:**

**Given** a completed profile
**When** I run `tymi profile <table> -o profile.yaml` and later load it
**Then** the Profile round-trips with its `schema_version`
**And** downstream generation can consume it fully offline (no source connection).

---

## Epic 2: Faithful Synthetic Data

From a Profile, generate faithful synthetic data with integrity and realistic values, export it anywhere, and prove fidelity — with no real values leaked.

### Story 2.1: Marginal distribution synthesis

As a user,
I want to generate N rows whose per-column distributions match the Profile,
So that the synthetic data is statistically faithful column-by-column.

**Acceptance Criteria:**

**Given** a Profile and `tymi generate --profile profile.yaml --rows N --seed S`
**Then** each column's distribution matches the Profile within the default Tolerance
**And** the pipeline orchestrator produces a Dataset carrying a canonical Schema (AR-10)
**And** the same seed yields the same output (AR-4).

### Story 2.2: Correlation preservation (in-house Gaussian copula)

As a user,
I want generated columns to keep their correlations,
So that relationships between fields survive, not just individual columns.

**Acceptance Criteria:**

**Given** a Profile with correlations
**When** I generate data
**Then** the global correlation divergence from the source stays within Tolerance
**And** correlation is produced by an in-house Gaussian copula on numpy/scipy (no SDV/Copulas, AR-9).

### Story 2.3: Referential integrity and realistic synthetic values

As a user,
I want related tables generated consistently with realistic-looking values,
So that the dataset is usable end-to-end without leaking real values.

**Acceptance Criteria:**

**Given** related tables with PK/FK/unique constraints
**When** I generate them
**Then** parents are generated before children and every FK points to a valid PK; no unique constraint is violated
**And** formatted columns (email/name/phone/id) get synthetic realistic values via Faker
**And** no output value equals a real sensitive source value.

### Story 2.4: Conditional (seeded) generation

As a user,
I want to condition generation on specific column values/ranges,
So that I can produce targeted test datasets.

**Acceptance Criteria:**

**Given** a condition like `region='LATAM'` or `age in [18,25]`
**When** I generate with that condition
**Then** 100% of rows satisfy the condition
**And** non-conditioned columns keep their distribution within Tolerance.

### Story 2.5: Leakage gate over declared sensitive columns

As a user,
I want a pre-export gate that blocks any real sensitive value from leaking,
So that faithful output is provably safe.

**Acceptance Criteria:**

**Given** columns marked sensitive in the Config
**When** the pipeline reaches the pre-export stage
**Then** every value in a sensitive column is checked against a hashed set of real source values and regenerated on collision (AR-7)
**And** the run fails closed if any collision cannot be resolved
**And** the gate runs as a core stage, independent of the CLI/UI.

### Story 2.6: Multi-destination export

As a user,
I want to export generated data to files, SQL, or any engine,
So that I can load it wherever I need it.

**Acceptance Criteria:**

**Given** a generated Dataset
**When** I export with `--to csv|parquet|json|sql` or `--load --engine <any>`
**Then** files are re-importable and direct load works against each of the 4 engines (source and destination independent)
**And** deterministic exporters produce byte-identical output for the same config+seed (NFR-4)
**And** exporters map from the canonical Schema, not raw pandas dtypes (AR-10).

### Story 2.7: Fidelity Report

As a user,
I want a report comparing source vs generated,
So that I can trust the synthetic data before using it.

**Acceptance Criteria:**

**Given** a source Profile and a generated Dataset
**When** I run `tymi report --fidelity`
**Then** the report shows per-column similarity (SDMetrics KSComplement/TVComplement) and a global correlation metric
**And** it is exportable and can fail a CI build on a configurable threshold.

---

## Epic 3: Data Chaos Monkey

Produce controlled, auditable corrupted datasets to test pipeline robustness.

### Story 3.1: Pluggable Mutator engine

As a developer,
I want a Mutator port and pipeline stage with entry-point discovery,
So that new fault types can be added without touching the core.

**Acceptance Criteria:**

**Given** a Mutator registered under `tymi.mutators`
**When** the chaos stage runs
**Then** registered Mutators execute in configurable order and each records what it corrupted
**And** each stochastic Mutator method receives the shared `rng` keyword (AR-4/AR-11)
**And** a new Mutator runs with zero core changes.

### Story 3.2: Out-of-distribution fault mutators

As a user,
I want to inject outliers and low-probability values,
So that I can test how my pipeline handles extreme data.

**Acceptance Criteria:**

**Given** a chaos run targeting given columns
**When** I set an out-of-distribution proportion
**Then** the output contains that proportion of outliers/range-jumps within the acceptance margin
**And** targeting by column/type is honored.

### Story 3.3: Format and type violation mutators

As a user,
I want to inject malformed formats and wrong types,
So that I can test my parsers and validators.

**Acceptance Criteria:**

**Given** a chaos policy enabling format/type faults
**When** I generate chaotic data
**Then** I can independently toggle text-in-numeric, invalid/out-of-range dates, broken encoding, oversized strings, and illegal nulls
**And** each enabled fault appears in the output.

### Story 3.4: Schema and constraint breakage mutators

As a user,
I want to break schema and constraints on purpose,
So that I can test my data contracts.

**Acceptance Criteria:**

**Given** a chaos policy enabling schema faults
**When** I generate chaotic data
**Then** I can produce missing/extra fields, renamed columns, changed types, duplicate PK/unique, orphan FKs, and check-constraint violations
**And** each breakage declared in the policy materializes in the output.

### Story 3.5: Configurable Chaos Policy

As a user,
I want to declare corruption rate, targeting, and output mode,
So that I control exactly how chaotic the dataset is.

**Acceptance Criteria:**

**Given** a declarative Chaos Policy in the Config
**When** I run `tymi chaos --profile profile.yaml`
**Then** in Mixed mode the fraction of corrupted rows matches the configured rate within ±2 pp (default)
**And** Fully-Chaotic mode over tables with FKs requires explicit confirmation (breaks referential integrity by design).

### Story 3.6: Fault Manifest

As a user,
I want an auditable manifest of every injected fault,
So that I can validate whether my pipeline detected them.

**Acceptance Criteria:**

**Given** a completed chaos run
**When** I inspect the manifest
**Then** every fault in the output is listed with row/column/fault-type, and every listed fault is present (bidirectional contract)
**And** the same config+seed produces the same manifest
**And** Evaluate is invoked in `chaos` run_mode (validates the manifest, no fidelity report) per AR-11.

---

## Epic 4: Privacy & Evaluation

Detect and measure privacy: auto-classify PII, filter faithful output, and produce a measurable quality + privacy report.

### Story 4.1: PII / Sensitive-Column auto-classification

As a user,
I want sensitive columns detected automatically,
So that I don't have to hand-mark every PII column.

**Acceptance Criteria:**

**Given** a source with known PII
**When** profiling runs with classification enabled (Presidio NER + rules)
**Then** expected Sensitive Columns are detected above a configurable recall threshold and tagged in the Profile
**And** I can override the classification (mark/unmark) via the Config
**And** the leakage gate (Story 2.5) then applies to auto-classified columns too.

### Story 4.2: Privacy Filters

As a user,
I want similarity and outlier filters on faithful output,
So that no synthetic row is suspiciously close to a real record.

**Acceptance Criteria:**

**Given** faithful output with the similarity filter active
**When** I generate data
**Then** no output row is closer than the configured threshold to a real sampled record
**And** the outlier filter removes memorized outliers
**And** filters are configurable (threshold, on/off) and seed-reproducible.

### Story 4.3: Quality & Privacy Report

As a user,
I want a composite quality score plus privacy metrics,
So that I can quantify both fidelity and leakage risk.

**Acceptance Criteria:**

**Given** a generated Dataset and the source Profile
**When** I run `tymi report --quality-privacy`
**Then** the report emits a composite Quality Score plus at least one membership and one attribute inference Privacy Metric (SDMetrics)
**And** it is exportable and can fail a CI build on configurable thresholds.

---

## Epic 5: Web UI (Streamlit)

Run the whole faithful/chaos workflow from the browser, reading/writing the same Config.

### Story 5.1: Streamlit app shell and connection management

As a user,
I want a browser app where I configure and test connections,
So that I can start without the CLI.

**Acceptance Criteria:**

**Given** the app running via `tymi ui`
**When** I add and test a connection
**Then** the connection is validated and stored in the Config (credentials not shown in plaintext)
**And** the app calls the core library in-process (no separate API).

### Story 5.2: Profile and schema explorer

As a user,
I want to browse tables, schema, and detected distributions,
So that I understand my data before generating.

**Acceptance Criteria:**

**Given** a connection
**When** I profile a table in the UI
**Then** I see the schema and per-column distribution charts
**And** the resulting Profile is the same artifact the CLI produces.

### Story 5.3: Faithful generation configuration and preview

As a user,
I want to configure faithful generation and preview a sample,
So that I can tune it visually before exporting.

**Acceptance Criteria:**

**Given** a Profile
**When** I set rows/seed/tolerance/conditions and click Preview
**Then** a synthetic sample renders and a side-by-side source-vs-generated distribution comparison is shown
**And** my choices are written back to the shared Config.

### Story 5.4: Chaos policy configuration and preview

As a user,
I want to configure a Chaos Policy and preview corrupted rows,
So that I can see exactly what will be injected.

**Acceptance Criteria:**

**Given** a Profile
**When** I set rate/targeting/mode and click Preview
**Then** a sample renders with chaotic rows/cells highlighted
**And** Fully-Chaotic-with-FKs requires an explicit confirmation in the UI
**And** the policy is written to the shared Config.

### Story 5.5: Reports view and export

As a user,
I want to view reports and export results from the UI,
So that I can finish the whole flow in the browser.

**Acceptance Criteria:**

**Given** a generated (faithful or chaotic) Dataset
**When** I open the reports panel
**Then** I see the Fidelity Report / Quality & Privacy Report (faithful) or the Fault Manifest (chaos)
**And** I can export to files or load into any of the 4 engines.

---
title: Fake It Till You Make It (TYMI)
status: final
created: 2026-07-01
updated: 2026-07-01
---

# PRD: Fake It Till You Make It (TYMI)

*Working title — confirm.*

## 0. Document Purpose

This PRD is written for the PM (John), the owners of downstream BMAD workflows (UX/Sally, Architecture/Winston, Epics & Stories), and technical stakeholders. It is structured with vocabulary anchored in the **Glossary** (§3), features grouped with nested, globally- and stably-numbered FRs, cross-cutting NFRs in their own section, and assumptions tagged inline (`[ASSUMPTION]`) and indexed in §9. The technical *how* (concrete libraries, algorithms) does not live here — it belongs to the Architecture document. A prior Spanish draft served as input and has been superseded by this canonical PRD.

## 1. Vision

Data teams need realistic datasets for development, testing, demos, and benchmarking, but using real production data carries privacy, compliance, and security risk. Fixture-style tools with random data produce plausible but **statistically unreal** values: they lose distributions, correlations, and edge cases — exactly what makes systems fail in production.

**TYMI** generates synthetic data that **faithfully replicates the statistical signature** of real tables (distributions, correlations, and referential integrity) without exposing a single real value, and — with equal weight — ships a **Data Chaos Monkey** that produces deliberately broken data (out-of-distribution, with invalid formats/types, and schema/constraint violations) in a **controlled, reproducible, and auditable** way.

With this, a team can replace production data in non-production environments with statistically equivalent datasets, and at the same time systematically test how its pipeline behaves under the chaos that today only shows up in production incidents. It ships as a Python tool usable from **CLI, library, and web UI**, suitable for local use and CI.

## 2. Target User

### 2.1 Jobs To Be Done

- **When** I need data for dev/test/demo, **I want** a dataset statistically equivalent to the real one **so that** I can work with fidelity without touching sensitive data or requesting production access.
- **When** I prepare a non-production environment, **I want** to guarantee that no real sensitive value leaks **so that** I meet privacy/compliance requirements without friction.
- **When** I validate the robustness of a pipeline or data contract, **I want** to inject realistic, controlled data faults **so that** I discover where it breaks *before* production does.
- **When** a robustness test passes or fails, **I want** to know exactly which data was corrupted and how **so that** I can trust that my validations catch what they should.
- **When** I integrate this into CI, **I want** generation to be seed-reproducible and declarative **so that** results are deterministic and versionable.

### 2.2 Non-Users (v1)

- Teams that need **anonymization/pseudonymization of a real dataset while preserving rows** (TYMI *synthesizes*, it does not transform existing records one-to-one).
- Cases requiring **certifiable formal differential privacy guarantees** in v1 (good practices are aimed for, not a formal mathematical proof). `[ASSUMPTION: formal differential privacy is out of scope for v1]`
- Users looking for a managed/multi-tenant cloud SaaS platform (v1 is local-first).

### 2.3 Key User Journeys

- **UJ-1. Dana replaces a production database with a faithful synthetic one.**
  Dana, a data engineer, needs to populate staging without copying production PII. From the CLI she points TYMI at the source MSSQL table, runs profiling (which samples without loading the full table), and generates 1M synthetic rows into a staging destination. She opens the **Fidelity Report** and sees that 94% of columns pass the similarity test and that key correlations are preserved. She closes it knowing staging is statistically equivalent to prod and that no real value traveled. Realizes FR-1–FR-9, FR-17–FR-18, FR-23–FR-25.
  - **Edge case:** a very-high-cardinality column (IDs) is flagged as "not faithfully modelable" and TYMI proposes treating it as a synthetic identifier instead of trying to replicate its distribution.

- **UJ-2. Marco tests his pipeline's robustness with the Chaos Monkey.**
  Marco, a dev on an ingestion pipeline, wants to know whether his validations catch bad data. From the web UI he loads an existing Profile, defines a Chaos Policy (10% corrupted rows, targeting date columns and the `orders` FK), and picks "mixed" mode. He previews a sample, sees the broken rows highlighted, exports to CSV, and runs his pipeline. His pipeline rejects 8% of rows; he opens TYMI's **Fault Manifest** and confirms the undetected 2% were out-of-range dates his validator let through — a real bug found before production. Realizes FR-11–FR-16, FR-17, FR-22.
  - **Edge case:** if he requests 100% chaotic on a table with FKs, TYMI warns that referential integrity will be broken by design and asks for explicit confirmation.

- **UJ-3. Sofía integrates TYMI into CI.**
  Sofía, in her CI pipeline, references a versioned Declarative Config file (Profile + rules + Chaos Policy) and a fixed Seed. Each run regenerates the same faithful dataset + the same set of faults, deterministically, and publishes the Fidelity Report and the Fault Manifest as build artifacts. Realizes FR-16, FR-18, FR-19, FR-20.

## 3. Glossary

- **Source Table** — A real table (in a Source) from which schema is read and data is sampled. Its values are never copied to the output.
- **Source** — Origin database or engine. In v1, at equal priority: MSSQL, StarRocks, PostgreSQL, MySQL. Any Source can also act as a destination.
- **Profile** — A serializable artifact capturing the statistical signature of one or more Source Tables (per-column distributions, correlations, schema metadata). It contains no identifiable raw values. Reusable without reconnecting to the Source.
- **Faithful Generator** — Component that produces Synthetic Data reproducing a Profile's distributions and correlations within a Tolerance, respecting the schema and Referential Integrity.
- **Synthetic Data** — Rows generated by TYMI. Never copies of real rows.
- **Data Chaos Monkey** — Component that produces Chaotic Data by applying Mutators according to a Chaos Policy.
- **Chaotic Data** — Deliberately invalid data: out-of-distribution, with invalid format/type, or violating the schema/constraints.
- **Mutator** — A pluggable unit that applies a specific fault type to rows/columns. Every Mutator records what it corrupted.
- **Chaos Policy** — Declarative configuration defining corruption rate, targeting (by column/type/fault), and output mode (Mixed or Fully Chaotic).
- **Fault Manifest** — Auditable, seed-reproducible record of which row/column was corrupted and with what fault type.
- **Fidelity Report** — Source-vs-generated comparison with per-column similarity and global correlation metrics.
- **Tolerance** — Configurable threshold of acceptable divergence between the Source distribution and the generated one.
- **Referential Integrity** — PK/FK/unique consistency across related tables in the Synthetic Data.
- **Seed** — Value that makes all generation deterministic (same config + same Seed ⇒ same output).
- **Declarative Config** — A single versionable file (profile + generation rules + Chaos Policy), the shared source of truth between CLI and UI.
- **Sensitive Column** — A column classified as carrying PII/sensitive data; it receives a specific synthesis strategy and is tagged in the Profile.
- **PII Classification** — Process (NER + rules) that detects and tags Sensitive Columns.
- **Privacy Filter** — Post-generation filter over the faithful output: *similarity filter* (drops synthetics too close to a real record) and *outlier filter* (removes memorized outliers).
- **Quality Score** — Composite quality score (correlation stability + per-column distribution) reported over the Synthetic Data.
- **Privacy Metric** — Quantitative measure of potential leakage (protection against membership and attribute inference).
- **Conditional Generation** — Faithful generation conditioned on values/ranges of specific columns, preserving the rest of the Profile's signature.

## 4. Features

### 4.1 Source Connectivity and Introspection

**Description:** TYMI connects to a Source with user-provided credentials, introspects the schema of one or more Source Tables, and samples their data by streaming (without loading the full table). It is the foundation feeding profiling and chaos. The 4 engines (MSSQL, StarRocks, PostgreSQL, MySQL) have **equal priority** and are interchangeable: any can act as source and any as destination, independently (e.g. profile from MSSQL and load into PostgreSQL). Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-1: Connect to Sources

A user can connect to a Source (MSSQL, StarRocks, PostgreSQL, MySQL) via a configurable connection string and securely provided credentials. Realizes UJ-1.

**Consequences (testable):**

- With valid credentials, `test-connection` returns success for each of the 4 engines against a test container.
- Invalid credentials / unreachable host produce an actionable error (engine, cause) without dumping secrets to logs.
- Credentials are never persisted in plaintext in any artifact (profile, config, logs).

#### FR-2: Schema Introspection

A user can extract a Source Table's schema: columns, types, nullability, PK, FK, unique/check constraints, and indexes (where the engine exposes them). Realizes UJ-1.

**Consequences (testable):**

- Output is serializable (JSON) and includes FK relationships across tables.
- Cross-engine differences are normalized to a common schema model.

#### FR-3: Streaming Sampling

A user can sample N rows or X% of a Source Table without loading it fully into memory. Realizes UJ-1.

**Consequences (testable):**

- On a table of ≥10M rows, sampling completes without exceeding a configurable memory limit.
- Sampling is seed-reproducible.

### 4.2 Statistical Profiling

**Description:** From a sample, TYMI builds a per-column Profile according to column type and detects cross-column correlations, persisting it as a reusable artifact that **stores no identifiable raw values**. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-4: Per-Column Profile

The system profiles each column by type: numeric (histogram/quantiles, mean, std, min/max, cardinality), categorical (per-category frequencies), date/time (range, basic seasonality), string (lengths, inferred patterns, cardinality). Realizes UJ-1.

**Consequences (testable):**

- Each supported type produces its profile without error on reference datasets.
- The Profile contains no raw values that would allow record re-identification (aggregates/histograms only). `[ASSUMPTION: for low-cardinality categoricals, storing category labels is acceptable; for free-text strings, only patterns/statistics]`

#### FR-5: Correlation Detection

The system detects and models correlations/dependencies between columns of the same table (at least correlation between numerics and first-order conditional dependencies between categoricals). Realizes UJ-1.

**Consequences (testable):**

- The Profile includes a representation of the detected correlations.

#### FR-6: Persistent, Versioned Profile

A user can save and load a Profile as a file and regenerate data from it without reconnecting to the Source. Realizes UJ-3.

**Consequences (testable):**

- A saved Profile includes its schema version and can be consumed offline.

### 4.3 Faithful Generation

**Description:** The Faithful Generator produces Synthetic Data that reproduces the Profile's marginal distributions and correlations within a Tolerance, respects the schema and Referential Integrity, and uses realistic formatted values that are **synthesized** (never copied from the source). Realizes UJ-1.

**Functional Requirements:**

#### FR-7: Marginal Distribution Reproduction

A user can generate N rows whose per-column distributions reproduce those of the Profile within a configurable Tolerance. N is independent of the source size. Realizes UJ-1.

**Consequences (testable):**

- For a reference dataset, ≥90% of columns pass the similarity test within the default Tolerance.
- Same config + same Seed ⇒ same output.

#### FR-8: Correlation Preservation

The Synthetic Data preserves the Profile's correlations within a configurable Tolerance. Realizes UJ-1.

**Consequences (testable):**

- Global correlation divergence from the source stays within Tolerance on reference datasets.

#### FR-9: Referential Integrity and Realistic Values

The system generates related tables respecting PK/FK/unique (parents before children, FKs pointing to valid PKs) and produces synthetic realistic formatted values (emails, names, phones, IDs) without copying source values. Realizes UJ-1.

**Consequences (testable):**

- No generated FK is orphaned; no unique constraint is violated in the faithful output.
- No output value matches a real sensitive source value (verifiable by an exact membership check against the source sensitive-value set, not sampling).

#### FR-10: Conditional Generation (Seeded)

A user can condition faithful generation on values or ranges of specific columns (e.g. generate only rows with `region='LATAM'` or `age` in [18,25]), preserving the rest of the Profile's statistical signature. Realizes UJ-1.

**Consequences (testable):**

- Generated rows satisfy the specified condition in 100% of cases.
- Non-conditioned columns keep their distribution within Tolerance.

**Feature-specific NFRs:**

- The faithful output must be exportable to the same destinations as the rest of the system (see FR-17).

### 4.4 Data Chaos Monkey

**Description:** The Data Chaos Monkey applies Mutators according to a Chaos Policy to produce Chaotic Data in three families: out-of-distribution, format/type violations, and schema/constraint breakage. Everything is seed-reproducible and every run emits a Fault Manifest. Realizes UJ-2, UJ-3.

**Functional Requirements:**

#### FR-11: Pluggable Mutator Engine

The system applies a pipeline of registrable Mutators, with configurable ordering, where each Mutator records what it corrupted. Adding a new fault type is done by adding a Mutator without modifying the core. Realizes UJ-2.

**Consequences (testable):**

- A new Mutator registers and runs with no core changes.
- Every applied mutation is recorded for the Fault Manifest.

#### FR-12: Out-of-Distribution Faults

A user can inject outliers and low-probability values (range jumps) with configurable proportion and targeting by column/type. Realizes UJ-2.

**Consequences (testable):**

- The proportion of out-of-distribution values in the output matches the configured one within a margin.

#### FR-13: Format and Type Violations

A user can inject data with invalid format/type: text where a number is expected, invalid or out-of-range dates, broken encoding, oversized strings, nulls where not allowed. Realizes UJ-2.

**Consequences (testable):**

- Each format/type violation type can be toggled independently and appears in the output.

#### FR-14: Schema and Constraint Breakage

A user can inject schema/constraint violations: missing fields, extra fields, renamed columns, changed types, duplicate PK/unique, orphaned FKs, and check-constraint violations. Realizes UJ-2.

**Consequences (testable):**

- Each breakage declared in the Policy materializes in the output.

#### FR-15: Configurable Chaos Policy

A user can define a declarative Chaos Policy: global corruption rate, targeting by column/type/fault, and output mode (Mixed with valid data, or Fully Chaotic). Realizes UJ-2.

**Consequences (testable):**

- In Mixed mode, the fraction of corrupted rows matches the configured rate within a margin.
- Fully Chaotic mode over tables with FKs requires explicit confirmation (breaks Referential Integrity by design).

#### FR-16: Fault Manifest

Every chaos run produces a Fault Manifest listing, per row/column, the injected fault type; it is seed-reproducible and exportable. Realizes UJ-2, UJ-3.

**Consequences (testable):**

- Every fault present in the output is listed in the Manifest, and vice versa (contract verifiable in tests).
- Same config + same Seed ⇒ same Manifest.

### 4.5 Output, Reporting, and Interfaces

**Description:** TYMI exports to multiple destinations, produces the Fidelity Report, is configured declaratively, and exposes the same capabilities via CLI, Python library, and web UI (full parity through the Declarative Config). Realizes UJ-1, UJ-2, UJ-3.

**Functional Requirements:**

#### FR-17: Multi-Destination Export (any engine)

A user can export the generated data (faithful and/or chaotic) to files (CSV/Parquet/JSON), SQL `INSERT` statements, and/or **direct load into any of the 4 engines** (MSSQL, StarRocks, PostgreSQL, MySQL) as destination, independently of the source engine. Realizes UJ-1, UJ-2.

**Consequences (testable):**

- Each output format is re-importable/parseable by standard tools.
- Direct load works against each of the 4 engines on a test container, with source and destination independently selectable.
- For deterministic exporters, same config + same Seed ⇒ byte-identical output.

#### FR-18: Fidelity Report

The system produces a Fidelity Report comparing source-vs-generated distributions (per-column similarity and global correlation), exportable and CI-integrable. Realizes UJ-1, UJ-3.

**Consequences (testable):**

- The report reports a per-column similarity metric and a global correlation metric.

#### FR-19: Declarative Config

A user can define the whole flow (profile + generation rules + Chaos Policy) in a versionable declarative file, which is the shared source of truth between CLI and UI. Realizes UJ-3.

**Consequences (testable):**

- The same file produces equivalent results whether launched from CLI or UI.

#### FR-20: CLI

The system exposes a CLI to profile, generate (faithful), apply chaos, report, and export, usable in scripts and CI. Realizes UJ-3.

**Consequences (testable):**

- Each core operation has a subcommand; exit codes distinguish success from failure for CI.

#### FR-21: Python Library

The system exposes a Python API/library with the same capabilities as the CLI. Realizes UJ-3.

**Consequences (testable):**

- Every CLI-available operation is invocable programmatically.

#### FR-22: Web UI

The system offers a web UI to configure connections, launch profiling, adjust generation rules and Chaos Policy, preview samples (with chaotic rows highlighted), view reports, and export. It reads/writes the same Declarative Config. Realizes UJ-2.

**Consequences (testable):**

- The UI can complete the end-to-end flow (connect → profile → configure → preview → export) without the CLI.
- Changes made in the UI are reflected in the Declarative Config file.

**Notes:** Screen detail and wizard flow are delegated to the UX spec (Sally / `bmad-ux`).

### 4.6 Privacy and Evaluation

**Description:** TYMI classifies sensitive columns before synthesizing, applies privacy filters over the faithful output to prevent a synthetic from resembling a real record too closely, and produces a report with a composite Quality Score and measurable Privacy Metrics. It turns the "zero leakage" guardrail (NFR-1 / SM-2) from a binary claim into something verifiable and quantified. Inspired by Gretel's Safe Synthetics capabilities, in its lightweight/CPU variant. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-23: PII / Sensitive-Column Auto-Classification

The system automatically detects Sensitive Columns (via NER + configurable rules) and tags them in the Profile, allowing a per-column synthesis strategy. Realizes UJ-1.

**Consequences (testable):**

- On a reference dataset with known PII, PII Classification detects the expected Sensitive Columns above a configurable recall threshold.
- The user can override the classification (mark/unmark columns) via the Declarative Config.

#### FR-24: Privacy Filters

The system applies Privacy Filters over the Faithful Generator's output: a *similarity filter* that drops synthetic rows too close to a real record, and an *outlier filter* that removes memorized outliers. Realizes UJ-1.

**Consequences (testable):**

- With the similarity filter active, no output row is closer than the configured threshold to a real record from the sample.
- Filters are configurable (threshold, on/off) and seed-reproducible.

#### FR-25: Quality & Privacy Report

The system produces a report combining a composite Quality Score (correlation stability + per-column distribution) and Privacy Metrics (protection against membership and attribute inference). Extends the Fidelity Report (FR-18). Realizes UJ-1, UJ-3.

**Consequences (testable):**

- The report emits an aggregate quality score and at least one membership and one attribute Privacy Metric.
- The report is exportable and CI-integrable (with thresholds that can fail the build).

## 5. Non-Goals (Explicit)

- Not a **1-to-1 anonymization** tool for real datasets; it synthesizes, it does not transform existing records while preserving rows.
- Does not provide **certifiable formal differential-privacy guarantees** in v1.
- Not a **multi-tenant cloud SaaS platform**; v1 is local-first, with no mandatory cloud dependency.
- Does not aim to **replicate business semantics** beyond the statistical (e.g. it does not infer implicit business rules not expressed in constraints). `[ASSUMPTION]`
- Not a generator of **time-series data with advanced predictive modeling** in v1 (basic seasonality yes; forecasting no). `[ASSUMPTION]`

## 6. MVP Scope

### 6.1 In Scope

- Connectivity + introspection + sampling for the **4 engines at equal priority** (MSSQL, StarRocks, PostgreSQL, MySQL), with **interchangeable source and destination** (any engine → any engine).
- Per-column profiling + correlations + persistent Profile.
- Full **Faithful Generator**: distributions, correlations, referential integrity, synthetic realistic values, seed-reproducible.
- Full **Data Chaos Monkey**: the three fault families, declarative Policy, Mixed/Fully-Chaotic modes, Fault Manifest.
- Export (CSV/Parquet/JSON, SQL INSERT, load to destination DB), Fidelity Report.
- **Conditional/seeded generation** (condition synthesis on given values/ranges).
- **PII auto-classification**, **Privacy Filters** (similarity + outlier), and **Quality & Privacy Report** (Quality Score + privacy metrics).
- **CLI + library + web UI** with parity via the Declarative Config.

*Both capabilities (Faithful Generator and Data Chaos Monkey) carry equal weight in the MVP — confirmed by the user.*

### 6.2 Out of Scope for MVP

- Engines beyond the 4 prioritized (Oracle, BigQuery, Snowflake, etc.) → v2.
- Formal differential privacy → v2+. `[NOTE FOR PM]` emotionally load-bearing for regulated cases; revisit if the timeline allows pulling it forward.
- Advanced multivariate modeling (high-order copulas, order >1 dependencies) beyond what is needed to pass the default Tolerance → v2.
- **Cross-table correlation** (statistical correlations between related tables, beyond referential integrity) → v2 (Gretel-inspired roadmap).
- Pluggable ML/DL synthesis backend (GAN/LLM) and rare-class rebalancing → v2+ (not prioritized).
- Distributed orchestration / cluster-scale generation of billions of rows → v2.
- Authentication / access control in the web UI: v1 runs **without auth** (local use, confirmed). RBAC/multi-user → v2.

## 7. Success Metrics

*Each SM cross-references the FR(s) it validates. Counter-metrics counterbalance specific primary/secondary metrics.*

**Primary**

- **SM-1**: Statistical fidelity — ≥90% of a reference dataset's columns pass the similarity test within the default Tolerance. Validates FR-7, FR-8.
- **SM-2**: Zero leakage — 0 real sensitive source values appear in the faithful output (verified by an automated exact membership check in CI, not sampling); with Privacy Filters active, no synthetic row falls below the similarity threshold to a real record. Validates FR-9, FR-24.
- **SM-3**: Chaos fidelity — 100% of the faults present in the output are correctly listed in the Manifest (verifiable contract). Validates FR-16.

**Secondary**

- **SM-4**: Reproducibility — same config + same Seed ⇒ identical output on deterministic exporters, in 100% of CI runs. Validates FR-17, FR-7.
- **SM-5**: Flow adoption — a new user completes the end-to-end flow (connect → profile → generate → export) from CLI or UI without external assistance. `[ASSUMPTION: qualitative target for early validation]`
- **SM-6**: Measurable privacy — the Quality & Privacy Report reports membership- and attribute-inference protection above a configurable threshold on reference datasets. Validates FR-25.
- **SM-7**: Chaos injection accuracy — the configured corruption rate and targeting are reflected in the output within the defined acceptance margin. Validates FR-12, FR-13, FR-14, FR-15.
- **SM-8**: PII detection recall — PII Classification detects known Sensitive Columns above the configured recall threshold on reference datasets. Validates FR-23.

**Counter-metrics (do not optimize)**

- **SM-C1**: Do not over-fit fidelity to the point of memorizing the source — "fidelity" must not rise at the cost of shrinking the minimum distance between generated and real sensitive values. Counterbalances SM-1 (protects SM-2).
- **SM-C2**: Do not inflate the user's pipeline detection rate by making chaos trivially detectable — Chaotic Data must include subtle/realistic faults, not just gross ones. Counterbalances SM-3.

## 8. Open Questions

1. Which similarity test and which default Tolerance are adopted per column type? (technical decision → Architecture)
2. What level of multivariate correlation is "enough" for the MVP (first-order only vs. copulas)?
3. Scope of date seasonality in v1?
4. Declarative config = YAML (confirmed). Pending: the file's versioning scheme.
5. Acceptance margin for the chaos corruption rate/targeting (FR-12–FR-15) — default value and per-fault overrides. Deferred to Architecture, alongside the similarity test and default Tolerance.

*Resolved:* the 4 engines are equal priority with interchangeable source/destination (was OQ-1); the v1 UI runs without auth on localhost (was OQ-5); config format = YAML (was OQ-6).

## 9. Assumptions Index

- §2.2 — Formal differential privacy is out of scope for v1.
- §4.2 / FR-4 — For low-cardinality categoricals, labels may be stored; for free-text strings, only patterns/statistics.
- §5 — Implicit business rules not expressed in constraints are not inferred.
- §5 — No time-series forecasting in v1 (basic seasonality yes).
- §7 / SM-5 — The adoption metric is a qualitative target for early validation.

*Confirmed (no longer assumptions):* 4 engines equal priority with interchangeable source/destination; v1 UI without auth on localhost; declarative config = YAML.

---

## 10. Cross-Cutting NFRs

- **NFR-1 (Privacy):** No real sensitive source value is emitted in the output; Profiles store no re-identifiable raw values. This is a hard requirement, not aspirational. Enforced by an exact membership check of every emitted value against the source sensitive-value set (not statistical sampling), so absence is proven rather than estimated.
- **NFR-2 (Performance):** Sampling/streaming-based profiling; handles tables ≥10M rows without exhausting memory (configurable limit).
- **NFR-3 (Fidelity):** Distribution divergence within a configurable Tolerance (default target: SM-1).
- **NFR-4 (Reproducibility):** Same config + same Seed ⇒ same output (deterministic exporters), byte-for-byte.
- **NFR-5 (Extensibility):** A new Source engine or a new Mutator is added via interfaces/plugins without touching the core.
- **NFR-6 (Security):** Credentials never persisted in plaintext; support for environment variables / secret managers.
- **NFR-7 (Observability):** Structured logs + run artifacts (Fidelity Report + Fault Manifest) for CI traceability.

## 11. Constraints and Guardrails

**Privacy / Data**

- The system must be able to demonstrate (via an automated check) that the faithful output contains no real sensitive source values (guardrail for NFR-1 / SM-2).
- Shareable artifacts (Profile, config) must contain no PII or credentials.

**Security**

- Credentials outside the code and outside versionable artifacts (NFR-6).
- Read-only connections to Sources recommended by default. `[ASSUMPTION]`

**Cost / Operations**

- Local-first: no mandatory cloud cost; must run on a developer's machine (portability NFR).

## 12. Developer-Product Surface

- **Runtime target:** Python 3.11+; runnable on Linux/macOS/Windows. `[ASSUMPTION: 3.11+ as floor]`
- **Public surfaces:** CLI (subcommand + exit-code contract), Python library (importable public API), and the Declarative Config schema. All three are versionable contracts.
- **Versioning/deprecation policy:** SemVer for the library and the config schema; breaking changes to the declarative schema must be detectable via the version embedded in the file. `[ASSUMPTION]`
- **Dependency policy and statistical/synthesis library selection:** defined in Architecture (permissive-license only: numpy/scipy/pandas + Faker + an in-house Gaussian copula; **SDV/Copulas excluded — BUSL-1.1**). Web UI is Streamlit (pure Python); a REST API / FastAPI is deferred. See the architecture spine.

## 13. Downstream Handoffs

- **UX (Sally / `bmad-ux`):** specify the UI wizard (Connect → Profile → Configure generation → Configure chaos → Preview → Export), the source-vs-generated distribution comparison view, and the Chaos Policy panel with chaotic-row highlighting.
- **Architecture (Winston / `bmad-architecture`):** `SourceConnector` interface + 4 drivers (interchangeable source and destination); Profile artifact model; statistical/synthesis library selection; pluggable Mutator engine design; PII classifier (NER + rules); Privacy Filters (similarity/outlier); computation of Privacy Metrics (membership/attribute inference) and composite Quality Score; conditional/seeded generation; Declarative Config schema; seed-based reproducibility strategy; testing strategy (unit + integration with containers + statistical validation in CI).
- **Epics & Stories (`bmad-create-epics-and-stories`):** derive epics from §4 (one per feature cluster), advancing 4.3 (Faithful Generation) and 4.4 (Chaos Monkey) in parallel on top of the 4.1/4.2 foundations.

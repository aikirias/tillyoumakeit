---
title: TYMI — Obfuscated Prod-Like Dev Environments (PRD 1)
status: final
created: 2026-07-04
updated: 2026-07-04
---

# TYMI — Obfuscated Prod-Like Dev Environments (PRD 1)

> Post-MVP PRD. Builds on the shipped MVP (Epics 1–5). New capability lands as new
> adapters/ports under the hexagonal core (AD-1/AD-3); the 12 ADs and NFRs of the MVP PRD
> (`prd-tymi-2026-07-01`) still hold — especially AD-4/AD-11 (determinism), AD-6/AD-7
> (zero real values, leakage gate), AD-9 (permissive deps), AD-10 (canonical Schema).
> FR IDs use the `PDE-` namespace (Prod Dev Env) to avoid collision with the MVP's
> FR-1…FR-25. Technical mechanism/rewrite notes live in `addendum.md`.

## Problem

Non-production environments are simultaneously:

- **Unrealistic** — the data does not match production distributions or behavior, so bugs
  don't reproduce and work is done on data that lies.
- **Incomplete** — some tables don't even exist in lower environments, so teams can't
  build or test against the real schema.
- **Unsafe (the sharp one)** — to get usable data, analysts and developers copy *real
  production data down* into lower environments, leaking PII downward.
- **Inconsistent** — each team's non-prod uses different entity IDs (e.g. `customer_id`),
  so cross-project work burns time reconciling them by hand.

## Vision

One command to provision a **whole-database, prod-like, fully-obfuscated dev environment**
from a source database: statistically **faithful** and **FK-consistent across all
tables**, with **zero real values**, **reproducible from a shared versioned spec** so every
team generates **identical synthetic entities** (cross-team IDs align for free), including a
**controlled set of pinned fixture accounts** so people can actually log in and test.

_One-liner: a single versioned spec → a whole-database dev environment that is realistic,
carries not one real value, and is identical for every team._

**Thesis (the bet this PRD makes):** the differentiated value is **not** whole-DB faithful
generation (SDV/Tonic already do that) — it is **cross-team consistency from a shared,
versioned spec with zero real values**. Phase 1 exists to validate that bet cheaply before
funding the expensive scale/fidelity work.

## Goals & Success Metrics

**G1 — North star: self-service provisioning in minutes (falsifiable).** Anyone who needs
it (data eng, dev, or analyst — role-agnostic) provisions prod-like data into non-prod
themselves, with **no mandatory gatekeeping handoff**, and without touching production
data. Made falsifiable against a fixed **reference database** benchmark (defined in the
addendum; a small/medium schema):
- **G1a** median end-to-end provisioning time for the reference DB on a single runner
  **≤ 10 minutes** (baseline: today's process = hours-to-days).
- **G1b** self-service ratio **≥ 80%** of provisions run with no gatekeeping handoff
  (baselined at rollout, measured quarterly).
- **G1c** "prepare/copy data for non-prod" ticket volume **→ ~0 within two quarters**.

**G2 — Safety (a hard constraint expressed as a metric).** Zero real values / PII reach
non-prod: 0 "copy prod down" incidents per quarter; **100% leakage-gate pass** (inherits
SM-2), **including a scan of pinned fixtures**.

**G3 — Realism.** Dev data reproduces production behavior: fidelity within tolerance
(inherits SM-1: ≥90% of columns pass); qualitatively, a named prod bug reproduces on the
dev data.

**G4 — Cross-team consistency (the differentiated bet).** The same spec yields identical
synthetic entities everywhere: byte-identical output across runs of the same
*consistency unit* (see PDE-11); **0 manual ID-reconciliation tasks** on a cross-team
project that adopts a shared spec.

**Counter-metrics (guardrails so G1 isn't won by breaking something else):**
- **CM1 (observable, not a restatement)** — **100% of provisions run the full leakage
  gate + fixture PII scan**; no "fast path" skips safety. A provision that skipped a
  safety check is a G1-gaming failure, tracked explicitly.
- **CM2** — self-service must not enable a footgun: a **production destination** or an
  **un-obfuscated run fails closed** (see PDE-14 / NFR-E).
- **CM3** — no memorizing/over-fitting the source (inherits SM-C1).

## Phasing / Roadmap

The scope is sequenced so the **differentiated bet (G4 cross-team consistency) is validated
cheaply first**, before funding the parts the market already proves buildable or that
require an engine rewrite.

- **Phase 1 — Validate the wedge (small scale, current in-memory engine).** Whole-DB,
  FK-consistent faithful generation at *small/medium* scale, the leakage gate, pinned
  fixtures, cross-team consistency, and safe self-service provisioning. Target: two teams,
  a few tables, one shared spec — prove that "shared spec → aligned entities → cross-team
  joins that hold" delivers real value. **PDE-1..5, PDE-7..15.**
- **Phase 2 — Scale (engine rewrite).** Out-of-core / chunked, table-parallel generation
  spanning megabytes → hundreds of terabytes at a bounded memory footprint; the leakage
  reference-set and the loader re-architected for streaming; distributed escape hatch.
  **NFR-A / NFR-B / NFR-C-at-scale.** This is a *rewrite of the generation engine*, not an
  extension (see addendum).
- **Phase 3 — Depth & controls.** Cross-table statistical correlation (**PDE-6**),
  referentially-consistent subsetting (**PDE-16**), incremental/delta refresh
  (**PDE-17**). Each is effectively its own project (see Open Questions).

## Users & Journeys

**One role, role-agnostic: the self-service provisioner.** Whoever needs prod-like
non-prod data — a data engineer, a developer, or an analyst. The role is defined by the
job, not the title; a data engineer can also be the self-service user. The point is to
remove the mandatory gatekeeping *handoff*, not to exclude anyone. Governance lives in the
versioned spec (reviewed like code), not in a gatekeeper person.

**UJ-1 — Provision a realistic, safe non-prod database (golden path).**
A practitioner picks up work that needs a realistic non-prod database — their current
non-prod has missing tables and fake data that won't reproduce the bug. Instead of a
Data-Eng ticket (days) or copying prod down by hand (unsafe), they trigger a CI job / DAG
that runs `tymi provision --spec <spec>` on a central runner (which holds the accesses, so
they never see prod credentials). In minutes a **whole-database, obfuscated** copy lands in
their non-prod: every table present, FK-consistent, prod-like distributions, **zero real
values**, with the pinned **fixture accounts** present so they can log in. Because it comes
from the **shared spec**, their `customer_id`s match a teammate's on the same cross-team
project — no reconciliation. They reproduce the bug on realistic data and ship the fix.

**Moment of truth / guardrail (CM2):** provisioning must refuse a production destination
and always obfuscate — a prod destination or an un-obfuscated run fails closed, never a
checkbox.

## Functional Requirements

Each FR is tagged with the phase that delivers it. `PDE-` namespace; builds on MVP
FR-1…FR-25.

### A. Whole-DB introspection & Spec-as-code

- **PDE-1 [P1] — Whole-DB introspection.** Introspect a full schema/database — all tables
  or a declared subset/allow-list — producing the complete table set and the FK dependency
  graph. (Generalizes MVP FR-2.)
- **PDE-2 [P1] — Spec auto-bootstrap.** From introspection, generate a first-cut **spec**:
  per-table profiles, auto-classified sensitive columns (MVP FR-23), fixture placeholders,
  seed, tolerances — human-editable.
- **PDE-3 [P1] — Spec is the source of truth.** The spec is a single versioned artifact
  (`schema_version`, semver) that fully governs a provisioning run; it is the shared,
  reviewable-as-code contract (extends MVP FR-19).

### B. Whole-DB faithful generation

- **PDE-4 [P1] — Graph-ordered generation with referential integrity.** Generate every
  table in FK-dependency (topological) order — parents before children across the whole
  graph — so every FK resolves to a generated PK and no unique constraint is violated.
  (Generalizes MVP FR-9.)
- **PDE-5 [P1] — Per-table fidelity.** Each table's column distributions match the source
  within the configured tolerance (inherits MVP FR-7/FR-8). Tolerance is explicit in the
  spec (see OQ-3).
- **PDE-6 [P3] — Cross-table statistical correlation.** Preserve statistical correlations
  between columns of *related* tables (beyond referential integrity) within tolerance.
  Effectively its own project (SDV-class); bounded to single-hop parent→child conditioning
  in the first cut (see addendum + OQ-3).
- **PDE-7 [P1] — Zero real values across the whole DB.** The leakage gate runs over the
  entire generated database; no real sensitive value survives to any table (inherits AD-7
  / MVP FR-24, applied DB-wide). *At scale, the reference-set membership structure is
  re-architected — see NFR-A and the addendum.*

### C. Pinned fixtures

- **PDE-8 [P1] — Declarative fixture allow-list.** The spec carries a controlled allow-list
  of exact rows (e.g. login/test accounts) injected **verbatim** into the generated output.
- **PDE-9 [P1] — Fixtures are FK-consistent, exempt from *regeneration* but not from the
  *check*.** Fixture rows are referentially valid (their keys exist; child rows referencing
  them are generated consistently) and are exempt from **obfuscation/regeneration** — but
  they are **still scanned by the leakage gate / PII check**, so a real PII value smuggled
  in as a "fixture" is flagged and fails closed (closes the fixtures-as-PII-bypass hole).
  Adding a fixture requires a **logged attestation**; synthetic fixtures are preferred.
- **PDE-10 [P1] — No key collision with fixtures.** Generated rows never collide with
  fixture PK/unique keys.

### D. Cross-team consistency

- **PDE-11 [P1] — The consistency unit is explicit.** Byte-identical output requires a
  fully pinned **consistency unit = (spec + pinned source-Profile snapshot + seed + pinned
  dependency versions)**. Two teams that share the *consistency unit* get identical output;
  a different source snapshot or dependency set is a *different* unit (this is the fix for
  the "same spec, different source" hole).
- **PDE-12 [P1] — Stable, source-independent entity keys.** Shared entity keys (e.g.
  `customer_id`) are generated **position-derived — independent of both the source and the
  seed** (a deterministic `key(table, row_position)`), so datasets from different teams
  **join consistently even when their source snapshots differ or drift**, given the spec's
  pinned per-table row counts — the keys align; the per-entity attributes are faithful to
  each team's own source. Cross-team *relationship* stability additionally requires
  per-table RNG substreams (architecture AD-20). (Resolved by architecture AD-16/AD-20.)

### E. Safe self-service provisioning

- **PDE-13 [P1] — One-command whole-DB provisioning.** A single `tymi provision --spec
  <spec>` orchestrates introspect(or cached Profile)→generate→load of the whole DB into a
  destination, idempotently, runnable unattended in a CI job / Airflow DAG. Orchestration
  stays external.
- **PDE-14 [P1] — Guardrails, fail closed.** Refuse a destination flagged/detected as
  production; always obfuscate (never pass real data through); any guardrail breach fails
  closed (CM2). *Prod-destination detection mechanism = OQ-2.*
- **PDE-15 [P1] — Provisioning report.** Emit a report of the run — tables provisioned, row
  counts, fidelity summary, leakage-gate result (incl. the fixture scan), fixtures present,
  and the consistency-unit fingerprint — so the requester can trust what landed.

### F. Scale & refresh controls (Phase 3)

- **PDE-16 [P3] — Referentially-consistent subsetting.** Provision a configurable *subset*
  — a sampling fraction and/or a **connected subset** (selecting seed rows pulls their
  FK-related rows across tables so the subset stays FK-valid) — not a naive per-table
  `LIMIT`. Interacts with determinism + bounded memory (OQ-4).
- **PDE-17 [P3] — Incremental / delta refresh.** Refresh an existing provisioned
  environment by applying only what changed since the last run instead of a full rebuild —
  preserving FK integrity, pinned fixtures, and determinism. Highest-complexity item;
  depends on the Phase-2 seed-split landing first (OQ-1).

## Non-Functional Requirements & Constraints

**Inherited from the MVP (still binding):** byte-identical determinism (NFR-4); zero real
values / leakage gate (NFR-1, AD-6/AD-7); no plaintext secrets (NFR-6); extensibility via
plugins without touching the core (NFR-5, AD-1/AD-3); structured logs + run artifacts
(NFR-7); permissive-license-only dependencies (AD-9); canonical Schema across stages
(AD-10).

**New / sharpened:**

- **NFR-A [Phase 2] Scale is an engine rewrite, not a property to assert.** Operating from
  **megabytes to hundreds of terabytes** at a **bounded, configurable memory footprint**
  requires replacing the MVP's materialize-whole-table-in-RAM model
  (`synth/relational.py`, `synth/leakage.py`) with an **out-of-core / chunked, table-
  parallel** engine, and re-architecting the leakage **reference-set** (today an in-memory
  Python `set` of every distinct source digest — O(source cardinality), ~100 GB at scale)
  into a disk/mmap-backed or Bloom/cuckoo membership structure. Superseding AD-10's
  "Dataset = one DataFrame" per-run is expected. **This is explicitly a Phase-2 rewrite.**
- **NFR-B [Phase 2] Performance as throughput, scaled to resources.** A small/medium DB
  provisions in minutes on one runner (G1a); large DBs scale ~linearly with allocated
  resources at a bounded footprint; there is no fixed absolute time cap.
- **NFR-C Determinism under chunking + parallelism.** Output byte-identical regardless of
  chunk size or worker count — the seeded RNG is split deterministically per table/chunk
  (`SeedSequence.spawn`). **This alone is insufficient:** the copula's linear-algebra
  (`eigh`/`cholesky`/matmul) has BLAS-vendor- and thread-count-dependent floating-point
  reduction order, so the run environment must also **pin BLAS threading**, not just
  dependency versions. Byte-identity is *redefined* across the Phase-2 rewrite, not
  preserved against today's MVP output.
- **NFR-D Credential isolation.** The self-service requester never sees production
  credentials; secrets live on the runner; **source access is read-only** (extends NFR-6).
- **NFR-E Non-production destination (hard constraint).** The provisioning destination
  cannot be a production system; a prod destination or an un-obfuscated run **fails
  closed** (CM2). Detection mechanism = OQ-2.
- **NFR-F Idempotent provisioning.** Re-running `provision` is safe — no partial/corrupt
  state (transactional or clean-replace load).

_Mechanism detail (out-of-core execution, deterministic seed-splitting + BLAS pinning,
leakage-set membership structure, distributed escape hatch, cross-table-correlation and
delta-refresh approaches, the reference-DB benchmark) is in `addendum.md`._

## Out of Scope

- **Pipeline / stream chaos & edge-case hunting** — the second use case; its own PRD
  (PRD 2), not this one.
- **Keyed pseudonymization / traceability to real IDs (Option B)** — rejected; this PRD is
  irreversible synthesis only (zero real values), consistency via shared spec (Option A).
- **Cross-job orchestration / scheduling** — lives in an external scheduler (CI/CD /
  Airflow); the library ships only the `provision` primitive + a thin in-process pipeline.
- **Distributed / multi-node generation engine** — the extreme-tail escape hatch; the
  Phase-2 chunked design *allows* it later, but not a Phase-1/2 deliverable.
- **Formal differential privacy** — a separate future item; the zero-real-value guarantee
  here rests on the leakage gate, not a DP budget.
- **New engines beyond the four supported** (Oracle/BigQuery/Snowflake, …) — each is an
  independent `EngineAdapter` (AD-2/AD-3), added on demand, not gated by this PRD.
- **Non-relational sources** (document/event stores) — the FK-graph model assumes
  relational databases.
- **Hosted SaaS / RBAC / multi-tenant** — local-first, like the MVP.

## Open Questions

- **OQ-1 (PDE-17 phasing).** Delta refresh depends on the Phase-2 seed-split; confirmed
  Phase 3. Any Phase-1 stopgap needed (e.g. full-rebuild-only) — or is full rebuild
  sufficient until Phase 3?
- **OQ-2 (prod-destination detection, NFR-E/PDE-14).** How does the tool *know* a
  destination is production — an explicit deny-list, a required "this is non-prod"
  affirmation, environment tagging, or a connection allow-list? Fail-closed default.
- **OQ-3 (fidelity tolerance & cross-table depth, PDE-5/PDE-6).** The numeric tolerance for
  per-table fidelity, and — for Phase 3 — which cross-table correlation types must be
  preserved (single-hop parent→child vs full multi-hop joined) and at what tolerance.
- **OQ-4 (subsetting semantics, PDE-16).** Connected-subset scope — seed-row selection
  strategy and how far the FK closure is walked (direct vs full transitive closure), and
  how it stays deterministic under bounded memory.
- **OQ-5 (source-independent keys vs fidelity, PDE-12).** Generating entity keys purely
  from the seed guarantees cross-team join alignment but decouples the key from any
  source-derived structure. Confirm this is acceptable (keys are opaque tokens), and define
  how key *ranges/cardinality* are chosen so they don't clash with fixtures (PDE-10).

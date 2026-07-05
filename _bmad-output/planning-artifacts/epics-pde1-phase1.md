---
stepsCompleted: [step-01, step-02, step-03, step-04]
inputDocuments:
  - prds/prd-tymi-obfuscated-dev-env-2026-07-04/prd.md
  - prds/prd-tymi-obfuscated-dev-env-2026-07-04/addendum.md
  - architecture/architecture-tymi-pde1-phase1-2026-07-04/ARCHITECTURE-SPINE.md
  - architecture/architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md
---

# TYMI PRD-1 Phase-1 (Obfuscated Prod-Like Dev Environments) - Epic Breakdown

## Overview

Epic and story breakdown for **Phase 1 only** of PRD 1 — validate the cross-team-consistency
wedge on the current in-memory engine, small/medium scale. Out-of-core scale (Phase 2) and
cross-table correlation / subsetting / delta refresh (Phase 3) are out of scope here.
Builds on the shipped MVP (Epics 1–5); new capability lands as new adapters/ports under the
hexagonal core. All FR IDs use the `PDE-` namespace; ADs are from the Phase-1 spine
(AD-13…AD-21) over the inherited MVP spine (AD-1…AD-12).

## Requirements Inventory

### Functional Requirements (Phase 1)

- **PDE-1** — Whole-DB introspection (all tables or a declared subset) → table set + FK graph.
- **PDE-2** — Spec auto-bootstrap (per-table Profiles + sensitive marks + fixtures + seed + tolerances).
- **PDE-3** — Spec is the versioned source of truth (`schema_version`), reviewed as code.
- **PDE-4** — Graph-ordered whole-DB generation with referential integrity (first-wires `generate_related`).
- **PDE-5** — Per-table fidelity within the spec's tolerance.
- **PDE-7** — Zero real values across the whole DB (leakage gate DB-wide).
- **PDE-8** — Declarative fixture allow-list injected verbatim.
- **PDE-9** — Fixtures FK-consistent, exempt from regeneration but scanned (fail closed on real PII).
- **PDE-10** — Generated rows never collide with fixture keys (reserved keyspace).
- **PDE-11** — The consistency unit is explicit (Spec + pinned Profile artifacts + seed + pinned deps).
- **PDE-12** — Stable, position-derived (source- and seed-independent) shared entity keys.
- **PDE-13** — One-command whole-DB provisioning (`tymi provision --spec`), CI/DAG-runnable.
- **PDE-14** — Destination guardrails, fail closed (non-prod affirmation + prod deny-list).
- **PDE-15** — Provisioning report (tables, rows, fidelity, gate result, fixtures, consistency fingerprint).

### NonFunctional Requirements (Phase 1)

- **NFR-C** — Determinism under the same consistency unit; cross-machine reproducibility (pinned deps).
- **NFR-D** — Credential isolation (source read-only; secrets on the runner, never in the Spec).
- **NFR-E** — Non-production destination is a hard constraint; fail closed.
- **NFR-F** — Idempotent provisioning (clean-replace or transactional load; no partial state).
- **Inherited (binding):** NFR-1 zero real values, NFR-4 byte-identical determinism, NFR-5 plugin
  extensibility, NFR-6 no plaintext secrets, NFR-7 structured logs/artifacts, AD-9 permissive deps.

### Additional Requirements (from Architecture — AD-13…AD-21)

- **AD-13** multi-table gen first-wires `generate_related` (no parallel generator).
- **AD-14** Spec = versioned whole-DB superset of Config (bundles pinned Profile artifacts).
- **AD-15** identity = consistency unit; Spec pins Profile *artifacts*, regenerate offline, fingerprint.
- **AD-16** shared keys position-derived (source/seed-independent); disjoint reserved fixture keyspace, validated. **(closes OQ-5)**
- **AD-17** fixtures inject-verbatim / regenerate-never / scan-and-reject into the GatedDataset (new gate mode + PIIClassifier).
- **AD-18** provision fails closed unless the Spec affirms a non-prod destination (+ deny-list). **(closes OQ-2)**
- **AD-19** provision is a driving/composition adapter (`tymi.provision`), not core; CLI + DAG call it identically.
- **AD-20** per-table RNG substreams `(seed, table)` → relationships independent of other tables' row counts.
- **AD-21** typed `GatedDataset` load boundary — un-gated data at a destination is a type error.
- **Open decisions a story must close:** OQ-2 (prod-destination detection mechanism), OQ-5 (reserved fixture keyspace convention).

## Epic List

### Epic 1: Obfuscated whole-DB generation from a Spec

Produce a whole-database, realistic, zero-real-value obfuscated dataset from a versioned
Spec: bootstrap the Spec, generate all tables in FK-topological order (first-wiring
`generate_related`), run the leakage gate DB-wide, and emit a `GatedDataset`.
**FRs covered:** PDE-1, PDE-2, PDE-3, PDE-4, PDE-5, PDE-7. **ADs:** AD-13, AD-14, AD-21.

### Epic 2: Cross-team consistency (the wedge)

Identical synthetic entities across teams: position-derived (source- and seed-independent)
shared keys, per-table RNG substreams for stable relationships, and the consistency unit
with a fingerprint. Validates the differentiated bet. Closes OQ-5.
**FRs covered:** PDE-11, PDE-12. **ADs:** AD-15, AD-16, AD-20.

### Epic 3: Fixtures & safe self-service provisioning

Log-in fixtures and safe, minutes-fast self-service provisioning: fixtures injected +
scanned, the `tymi provision --spec` command (a composition adapter runnable in CI/DAG),
fail-closed non-prod destination guardrails, and a provisioning report. Closes OQ-2.
**FRs covered:** PDE-8, PDE-9, PDE-10, PDE-13, PDE-14, PDE-15. **ADs:** AD-17, AD-18, AD-19.

## Stories

### Epic 1: Obfuscated whole-DB generation from a Spec

#### Story 1.1: The GatedDataset load boundary

As a maintainer,
I want a `GatedDataset` type that can only be built by passing a `Dataset` through the leakage gate,
so that un-gated data can never reach a destination (it becomes a type error, not a discipline).

**Acceptance Criteria:**

**Given** a `Dataset`, **When** it is run through the leakage gate, **Then** the only way to
obtain a `GatedDataset` is that gate call — there is no public constructor from a raw `Dataset`.
**And** the leakage gate returns a `GatedDataset`; a raw `Dataset` passed where a `GatedDataset`
is required is a type error (AD-21).
**And** the `GatedDataset` preserves the canonical Schema (AD-10) and carries the gate result.

#### Story 1.2: Whole-DB Spec model and auto-bootstrap

As a self-service provisioner,
I want to introspect a whole database and get a first-cut versioned Spec I can edit,
so that I can describe an obfuscated dev environment without hand-writing it (PDE-1, PDE-2, PDE-3).

**Acceptance Criteria:**

**Given** a source connection, **When** I bootstrap a Spec over a schema (all tables or a
declared subset), **Then** a versioned `Spec` (`schema_version`) is produced with the FK graph,
per-table Profiles, auto-classified sensitive columns, fixture placeholders, seed, and tolerances (AD-14).
**And** the Spec bundles the pinned Profile artifacts (not a live source reference).
**And** the Spec loads/validates via Pydantic (`extra="forbid"`) and round-trips through YAML.

#### Story 1.3: Whole-DB faithful generation from the Spec

As a self-service provisioner,
I want to generate a whole obfuscated database from a Spec,
so that I get a realistic, FK-consistent dataset with zero real values (PDE-4, PDE-5, PDE-7).

**Acceptance Criteria:**

**Given** a Spec, **When** I generate, **Then** every table is produced in FK-topological order
via `generate_related` (first-wiring it), referential integrity holds, and per-table fidelity is
within the Spec's tolerance (AD-13, PDE-4/5).
**And** the DB-wide leakage gate runs (embedded per-table) and the result is a `GatedDataset` with
zero real sensitive values (PDE-7).
**And** the same Spec + seed yields byte-identical output (inherits NFR-4).

### Epic 2: Cross-team consistency (the wedge)

#### Story 2.1: Per-table RNG substreams

As a maintainer,
I want each table generated from a deterministic per-table RNG substream,
so that a table's output is independent of other tables' row counts or order (AD-20).

**Acceptance Criteria:**

**Given** a Spec, **When** tables are generated, **Then** each table draws from a substream derived
from `(seed, table_name)`, not a single shared generator (AD-20).
**And** a table's output (rows and FK edges) is byte-identical regardless of another table's row
count or the generation order.
**And** determinism per the consistency unit still holds end-to-end.

#### Story 2.2: Position-derived shared keys and reserved fixture keyspace

As a self-service provisioner,
I want declared shared keys generated identically across teams and clear of fixture keys,
so that datasets from different teams join consistently (PDE-12, closes OQ-5).

**Acceptance Criteria:**

**Given** a Spec declaring `shared` key columns and a reserved fixture keyspace block, **When** I
generate, **Then** shared keys are emitted by `key(table, row_position)` — independent of source and
seed — so two teams with the same pinned row counts get identical keys (AD-16, PDE-12).
**And** generated keys never enter the reserved fixture block; disjointness is validated and a clash
fails closed (PDE-10).
**And** OQ-5's reserved-keyspace convention is fixed and documented.

#### Story 2.3: Consistency unit and fingerprint

As a self-service provisioner,
I want a provable "same environment" identity across teams,
so that I can trust two datasets are the same synthetic reality (PDE-11).

**Acceptance Criteria:**

**Given** a Spec bundling pinned Profile artifacts, **When** I regenerate, **Then** generation reuses
the bundled Profiles offline and never re-profiles the source (AD-15).
**And** the run emits a consistency-unit fingerprint = a hash over (Spec + pinned Profiles + seed +
pinned deps); identical units produce byte-identical output and identical fingerprints (PDE-11).

### Epic 3: Fixtures & safe self-service provisioning

#### Story 3.1: Pinned fixtures with scan-and-reject

As a self-service provisioner,
I want to pin exact login/test accounts that appear verbatim but are still checked for real PII,
so that people can log in without opening a PII bypass (PDE-8, PDE-9, PDE-10).

**Acceptance Criteria:**

**Given** a Spec fixture allow-list (in the reserved keyspace), **When** I generate, **Then** fixtures
are overlaid verbatim, FK-consistent, and exempt from regeneration (PDE-8/9).
**And** the overlaid frame passes a scan-and-reject gate mode (leakage guard + PIIClassifier) that
fails closed on a real value / PII, with no regeneration, before minting the `GatedDataset` (AD-17).
**And** adding a fixture records a logged attestation; generated rows never collide with fixture keys (PDE-10).

#### Story 3.2: Non-production destination guardrail

As a self-service provisioner,
I want provisioning to refuse a production destination and always obfuscate,
so that I cannot accidentally write to prod or ship un-obfuscated data (PDE-14, closes OQ-2).

**Acceptance Criteria:**

**Given** a Spec destination block, **When** I provision, **Then** the destination must carry an
explicit `environment: nonprod` affirmation and not match the configured prod deny-list; a missing
affirmation or a deny-list match aborts before any write (AD-18, fail-closed default).
**And** there is no code path that loads a non-`GatedDataset` into a destination (AD-21).
**And** OQ-2's detection mechanism (affirmation + deny-list format) is fixed and documented.

#### Story 3.3: One-command `tymi provision --spec` with report

As a self-service provisioner,
I want a single command that provisions a whole obfuscated DB into a non-prod destination,
so that I can do it myself in minutes, runnable in CI/DAG (PDE-13, PDE-15).

**Acceptance Criteria:**

**Given** a Spec, **When** I run `tymi provision --spec <spec>`, **Then** a composition-adapter
pipeline runs load-Spec → generate (gate per-table) → substreams → shared keys → fixtures overlay +
scan → `GatedDataset` → guardrail → `EngineAdapter.load` → report, callable identically by a CI job /
DAG (AD-19, PDE-13).
**And** provisioning is idempotent (clean-replace/transactional; no partial state) (NFR-F).
**And** the run emits a provisioning report: tables, row counts, fidelity, gate result, fixtures
present, and the consistency-unit fingerprint (PDE-15).


## Validation Summary

- **FR coverage:** all 14 Phase-1 FRs (PDE-1..5, PDE-7..15) covered by ≥1 story; ACs address each.
- **AD coverage:** AD-13..21 each realized by a story; OQ-2 closed in Story 3.2, OQ-5 in Story 2.2.
- **Dependencies:** epics are independent in their domain (E1 standalone; E2 builds on E1; E3 on
  E1+E2); no epic requires a future epic. Within each epic, stories only depend on prior stories
  (1.1→1.2→1.3, 2.1→2.2→2.3, 3.1→3.2→3.3).
- **Epic split rationale:** the three epics share `synth`/`config`/`provision` files, but the split
  is deliberate — Epic 2 (cross-team consistency) is isolated as the risk boundary the Phase-1
  thesis exists to validate cheaply; Epics 1 and 3 are distinct user outcomes (generation vs safe
  provisioning). Consolidation considered and rejected with rationale.
- **Brownfield:** extends the shipped repo; no starter-setup story needed. New data is generated,
  not app tables. Each story creates only what it needs.
- **Per project convention (CLAUDE.md):** each story runs the full 3-layer `bmad-code-review` gate
  before `done`; build/test inside the devcontainer.

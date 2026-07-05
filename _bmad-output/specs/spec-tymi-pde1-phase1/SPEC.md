---
id: SPEC-tymi-pde1-phase1
companions:
  - ../../planning-artifacts/architecture/architecture-tymi-pde1-phase1-2026-07-04/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/epics-pde1-phase1.md
  - ../../planning-artifacts/prds/prd-tymi-obfuscated-dev-env-2026-07-04/prd.md
  - ../../planning-artifacts/prds/prd-tymi-obfuscated-dev-env-2026-07-04/addendum.md
  - ../../planning-artifacts/architecture/architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete contract
> for what to build, test, and validate in Phase 1. The architecture spine holds the ADs and
> diagrams; the epics file holds the stories and acceptance criteria; the PRD holds the full
> requirements and rationale. Stable IDs: `PDE-*` (FRs), `AD-*` (architecture decisions),
> `CAP-*` (capabilities below), and story `N.M`.

# TYMI — Obfuscated Prod-Like Dev Environments (Phase 1)

## Why

Non-production environments are unrealistic (data doesn't match prod, so bugs don't
reproduce), incomplete (some tables don't exist below prod), unsafe (to get usable data,
people copy real production data — PII — down into lower environments), and inconsistent
(each team's non-prod uses different entity IDs, so cross-team work burns time reconciling
them). This is a **pain to solve** for whoever needs prod-like non-prod data — data engineer,
developer, or analyst. Phase 1 exists to validate one bet cheaply, on the current in-memory
engine: the differentiated value is not whole-DB faithful generation (SDV/Tonic already do
that) but **cross-team consistency from one shared, versioned spec with zero real values**.
The design partner is an internal rollout; the tool is open-source for everyone.

## Capabilities

- **CAP-1 — Bootstrap a versioned whole-DB Spec**
  - **intent:** a user introspects a whole database (all tables or a declared subset) and gets
    a first-cut, editable, versioned Spec that bundles the pinned per-table Profiles, sensitive
    marks, fixture placeholders, seed, and tolerances. (PDE-1/2/3, Story 1.2, AD-14)
  - **success:** `tymi spec bootstrap` yields a Pydantic-validated Spec (`schema_version`,
    `extra="forbid"`) that round-trips through YAML and carries the FK dependency graph.

- **CAP-2 — Generate a whole obfuscated database from a Spec**
  - **intent:** generate every table FK-consistent in topological order, at per-table fidelity,
    with the leakage gate applied DB-wide, producing a `GatedDataset` that carries no real
    value. (PDE-4/5/7, Story 1.1/1.3, AD-13/AD-21)
  - **success:** referential integrity holds across the whole DB; the DB-wide leakage gate
    passes (zero real sensitive values); the same Spec+seed yields a byte-identical
    `GatedDataset`; a raw `Dataset` cannot reach a destination (type error).

- **CAP-3 — Cross-team consistency (the wedge)**
  - **intent:** two teams that share a consistency unit get identical synthetic entities, keys,
    and relationships, so their datasets join without reconciliation. (PDE-11/12,
    Story 2.1/2.2/2.3, AD-15/AD-16/AD-20)
  - **success:** the same consistency unit (Spec + pinned Profile artifacts + seed + pinned
    deps) → byte-identical output and an identical fingerprint; shared keys are
    position-derived (source- and seed-independent) so cross-team joins on them match; a
    sibling table's row count never changes another table's output (per-table RNG substreams).

- **CAP-4 — Pinned fixtures without a PII bypass**
  - **intent:** pin exact login/test accounts that appear verbatim so people can log in, while
    still checking them for real PII. (PDE-8/9/10, Story 3.1, AD-17)
  - **success:** fixtures are present verbatim, FK-consistent, and exempt from regeneration, but
    the overlaid frame passes a scan-and-reject gate (leakage guard + PIIClassifier) that fails
    closed on a real value/PII; generated rows never collide with fixture keys.

- **CAP-5 — Safe self-service provisioning**
  - **intent:** one `tymi provision --spec` command, runnable unattended in a CI job / Airflow
    DAG, provisions the whole obfuscated DB into a non-prod destination and reports what landed.
    (PDE-13/14/15, Story 3.2/3.3, AD-18/AD-19)
  - **success:** a non-prod destination is provisioned in minutes with no gatekeeping handoff; a
    production destination, a missing non-prod affirmation, or a non-`GatedDataset` input fails
    closed; provisioning is idempotent; the report carries the consistency-unit fingerprint.

## Constraints

- **Hexagonal boundary (AD-1/AD-19):** `tymi.core`/`ports`/`domain` import no adapters; the
  provisioning pipeline is a **driving/composition adapter** (`tymi.provision`), invoked
  identically by the CLI and an external scheduler — orchestration never lives in the core.
- **Zero real values, enforced by type (AD-6/AD-7/AD-21):** the leakage gate runs DB-wide; only
  a `GatedDataset` (constructible solely via the gate + fixture scan) may reach a destination.
- **Determinism (AD-4/AD-11/AD-20):** all randomness from the injected `rng`; per-table RNG
  substreams `(seed, table)` so a table's output is independent of other tables; byte-identical
  under the same consistency unit; cross-machine reproducibility needs pinned dependencies.
- **The Spec is the versioned source of truth (AD-5/AD-14/AD-15):** one artifact that bundles
  the pinned Profile **artifacts** (regenerate offline, never re-profile a drifting source).
- **Shared keys are position-derived, source- and seed-independent (AD-16):** disjoint from a
  declared reserved fixture keyspace; disjointness validated, fail-closed on overlap.
- **Permissive-license dependencies only (AD-9):** no SDV/Copulas (BUSL); every new dep verified.
- **Canonical Schema across stages (AD-10).**
- **In-memory engine, small/medium scale only:** Phase 1 does not rewrite the engine.

## Non-goals

- **Out-of-core / hundreds-of-terabytes scale** — Phase 2 (an engine rewrite).
- **Cross-table statistical correlation, referentially-consistent subsetting, incremental/delta
  refresh** — Phase 3.
- **Keyed pseudonymization / traceability to real IDs** — irreversible synthesis only.
- **Pipeline / stream chaos & edge-case hunting** — a separate PRD (PRD 2).
- **Distributed / multi-node generation; formal differential privacy; hosted SaaS / RBAC /
  multi-tenant; non-relational sources.**

## Success signal

Two teams provision their non-prod databases from one shared Spec and their datasets **join on
`customer_id` with matching entities and relationships** — with **not one real value** in
either — each provisioned **self-service in minutes**, with no Data-Engineering ticket and no
copy of production pulled down.

## Open Questions

- **OQ-2 (destination detection, AD-18):** the exact non-prod-destination mechanism (affirmation
  + prod deny-list format) is drafted; a story (3.2) confirms it for the target environment.
- **OQ-5 (fixture keyspace, AD-16):** the reserved fixture-keyspace convention is drafted; a
  story (2.2) fixes and documents it.

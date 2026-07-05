---
title: TYMI — Deeper Chaos Monkey / Content Chaos (PRD 2)
status: draft
created: 2026-07-04
updated: 2026-07-04
note: Fast-path first cut, hardened by the reviewer gate (rubric + adversarial). [ASSUMPTION]/OQ mark calls pending the forcing function.
---

# TYMI — Deeper Chaos Monkey / Content Chaos (PRD 2)

> Post-MVP PRD 2 (PRD 1 dev-env, **PRD 2 content-chaos**, PRD 3 streaming). Builds on the
> shipped MVP chaos monkey (FR-11..16: Mutator engine, Chaos Policy, Fault Manifest,
> mutators). New work is **narrow and deep**: the genuinely-new fault behavior + the
> detection audit, end-to-end against a real fixture. **Against batch/DB only** (streams =
> PRD 3). FR IDs use `CC-`.

## What already ships vs what's new (honesty first)

The reviewer gate found ~half of a naive "content chaos" scope already exists in the MVP.
This PRD scopes **only the genuinely-new**:

| Already shipped (reuse, don't re-spec) | Genuinely new (this PRD) |
| --- | --- |
| uniform nullification (`illegal_null` = MCAR) | **conditioned** nullification (MAR/MNAR) |
| `missing_field` / `extra_field` / `renamed_column` / `changed_type` | column **reorder** + type/nullability drift as a **versioned delta** |
| `outlier` OOD, `duplicate_keys`, `orphan_fk` | **dropped records** (CC-1), **sequence gaps** (CC-3) |
| Chaos Policy + Fault Manifest (positional-row keyed) | **manifest/audit/policy support for cardinality faults** + the **detection audit** |

## Problem

Pipelines that pass on clean test data **break in production on unpredictable real data** —
the #1 cited data-engineering pain: a column that was always an integer suddenly allows NULL;
records arrive dropped, late, or partial; a child row is orphaned when its parent goes
missing. No tool **generates** realistic content chaos: infra-chaos tools (Gremlin, Toxiproxy)
corrupt the network, not the data; Great Expectations *validates* bad data but doesn't
*generate* it. TYMI's chaos monkey injects faults today — the gap is the two families with the
most demand and the least coverage, **plus the missing feedback loop**: did the pipeline or
its data-QA alert actually *catch* the fault?

## Vision

Inject realistic, reproducible, auditable **content chaos** — conditioned missing-data
(including **referential gaps that orphan children across joins**) and schema drift — into a
whole-DB dataset, and **audit whether the consumer caught it**. The differentiator is the
**detection audit**, not the mutators.

**Thesis:** content chaos is TYMI's sharpest white space, but the *value* is the detection
loop (does your pipeline/alert survive?), not another mutator. Build **narrow and deep**: one
genuinely-new family + the detection audit, proven end-to-end against a reference fixture —
not a broad shelf of re-skinned mutators. **Multi-table by design** (a dropped record only
breaks a real pipeline when it orphans a child across a join), reusing PRD 1's whole-DB model
and the shipped `OrphanFkMutator` / `_drop_from_schema`.

## Goals & Success Metrics

**G1 — The detection audit shows a real miss (falsifiable, Phase 1).** Against a **declared
reference fixture** — a small multi-table dataset + a toy pipeline + a data-QA alert suite,
built as part of this PRD (CC-9) — injecting a genuinely-new fault produces a detection audit
that reports **≥ 1 injected fault the pipeline/alert missed**. (No dependency on a later
phase; the fixture is defined here, not assumed.)
**G2 — Conditioned missingness is verifiably not uniform (falsifiable).** For a MAR/MNAR run,
the realized missing-rate **differs across the conditioning column's strata** by more than a
margin (i.e. MAR/MNAR ≠ MCAR), with a stated statistical check — so "mechanism honored" is
testable, not vocabulary.
**G3 — Reproducible & auditable.** Same config+seed → identical output and identical Fault
Manifest, **including deletions** (which today's positional manifest cannot express — CC-8).

**Counter-metrics:** **CM1** chaos must include *subtle* faults (inherits SM-C2). **CM2** the
faithful baseline stays faithful in mixed mode.

## Phasing / Roadmap

The detection audit (the value) is **Phase 1**, not deferred.

- **Phase 1 — Referential missing-data + manifest/audit for cardinality + the detection
  audit + a reference fixture.** `CC-1, CC-3, CC-8, CC-9, CC-10, CC-11`.
- **Phase 2 — Conditioned nullification (MAR/MNAR) + partial records.** `CC-2, CC-4`.
- **Phase 3 — Schema-drift depth (reorder + versioned type/nullability delta).** `CC-5, CC-7`.

## Users & Journeys

**One role: the pipeline hardener** (data/pipeline or QA engineer). **UJ-1:** points
content-chaos at a whole-DB faithful dataset (from PRD 1/MVP), runs it against their pipeline
and alerts, and the **detection audit** tells them exactly which injected missing-data /
drift faults their pipeline or alerts failed to catch — reproducibly.

## Functional Requirements

### A. Referential missing-data (Phase 1)

- **CC-1 — Dropped records (referential).** Remove a configurable fraction of whole rows,
  **including rows whose deletion orphans a child across a join** (reuses the shipped
  `OrphanFkMutator` / `_drop_from_schema` and PRD 1's whole-DB FK model). This is the fault
  that actually breaks multi-table pipelines.
- **CC-3 — Sequence gaps.** Introduce gaps in a monotonic column (missing IDs / skipped
  timestamps) so gap-detection is exercised.

### B. Manifest, audit, policy for cardinality faults (Phase 1) — *not "zero core change"*

- **CC-8 — Cardinality-aware manifest + policy.** Extend the Fault Manifest and Chaos Policy
  so a **row deletion/insertion is representable and auditable** (today's manifest is
  positional-row-keyed and the audit marks row-count changes "unauditable" — this is a **core
  change to `chaos_audit.py` + the manifest schema + mixed-mode policy**, not just a plugin).
- **CC-9 — Reference fixture.** A small multi-table dataset + a toy pipeline + a data-QA alert
  suite, shipped as a test fixture, so G1 is measurable in CI.
- **CC-10 — Batch/DB delivery.** Emit chaotic output through the existing exporters + PRD 1
  destinations. No streams (PRD 3).

### C. The detection audit (Phase 1 — the differentiator)

- **CC-11 — Detection audit ("did it catch it?").** Given the Fault Manifest and a consumer's
  result (pipeline output and/or fired data-QA alerts), report which injected faults were
  **detected vs missed** — a bidirectional detection contract extending the Story 3.6 manifest
  audit. The consumer reports detections in a **declared results format** (defined here, see
  OQ-3), so the audit is buildable, not hand-wavy.

### D. Conditioned nullification & partial records (Phase 2)

- **CC-2 — Conditioned nullification (MAR/MNAR).** Null cells under a **rule-based**
  conditioning: MAR (missingness rate depends on another column), MNAR (depends on the cell's
  own value). Extends the shipped uniform `illegal_null` (MCAR) — only the *conditioning* is
  new. Verified by G2's stratum test.
- **CC-4 — Partial records.** Null a declared subset of columns per affected row (incomplete
  rows), distinct from CC-2's cell pattern.

### E. Schema-drift depth (Phase 3)

- **CC-5 — Column reorder.** The one column-level drift the MVP doesn't have (rename/drop/add
  already ship).
- **CC-7 — Versioned drift delta.** Express type/nullability drift as an explicit, recorded
  delta from the canonical Schema (AD-10) so a contract test can diff it.

## Non-Functional Requirements & Constraints

Inherited (binding): determinism (NFR-4), reproducible Fault Manifest (SM-3/4) — **extended to
represent deletions** (CC-8), pluggable mutators (NFR-5, AD-3) **except the manifest/audit/
policy core changes CC-8 requires**, permissive deps (AD-9), canonical Schema (AD-10),
injected rng (AD-4/AD-11), chaos run_mode (AD-12). No new runtime dependency (numpy/pandas).

## Out of Scope

- **Streams / queues + API/OpenAPI-contract chaos** — PRD 3.
- **Faithful generation** — PRD 1 / MVP (content chaos consumes faithful output or a sample).
- **Re-implementing shipped mutators** (`illegal_null`, `missing_field`, `changed_type`, …) —
  reused, not re-specified (see the honesty table).
- **Learned/generative missingness models** — rule-based conditioning only.

## Open Questions

- **OQ-1 (forcing function).** The concrete pull — a specific pipeline/team whose alerts must
  be hardened — sets which family and fixture ship first.
- **OQ-2 (conditioning rules).** The exact MAR/MNAR conditioning language in the policy (a
  threshold/expression on another column vs the cell's own value).
- **OQ-3 (detection-audit results format).** How a consumer reports what it detected (a results
  file? an alert log? exit codes?) so CC-11 can compare against the manifest.

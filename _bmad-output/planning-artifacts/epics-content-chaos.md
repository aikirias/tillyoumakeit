---
stepsCompleted: ['step-01', 'step-02', 'step-03']
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-tymi-content-chaos-2026-07-04/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-tymi-content-chaos-2026-07-05/ARCHITECTURE-SPINE.md
---

# PRD 2 — Content Chaos epics & stories (Deeper Chaos Monkey)

Deeper chaos-monkey content faults over the shipped MVP chaos engine + PRD 1 whole-DB model.
Architecture: `architecture-tymi-content-chaos-2026-07-05/` (AD-28..34 over inherited AD-1..27).
**No new dependencies** (AD-9 — numpy/pandas/PyYAML already in stack). Batch/DB only (streams =
PRD 3). Each story runs the full 3-layer `bmad-code-review` gate before `done`; build/test in the
devcontainer; code/artifacts in English.

**The differentiator (Phase 1) is the detection audit** — "did the pipeline/alerts catch the
fault?" — proven end-to-end against a self-contained synthetic reference fixture (G1).

## Requirements inventory

**FRs (from the PRD):** CC-1 dropped records (referential) · CC-2 conditioned nullification
(MAR/MNAR) · CC-3 sequence gaps · CC-4 partial records · CC-5 column reorder · CC-7 versioned drift
delta · CC-8 cardinality-aware manifest + policy · CC-9 reference fixture · CC-10 batch/DB delivery ·
CC-11 detection audit. *(The PRD has no CC-6.)*

**Goals:** G1 detection audit shows a real miss (Phase 1, falsifiable) · G2 conditioned missingness
verifiably ≠ uniform (per-stratum) · G3 reproducible + auditable **including deletions**.
**Counter-metrics:** CM1 chaos includes subtle faults · CM2 faithful baseline stays faithful in
mixed mode.

**Binding invariants (spine):** AD-28 row identity = a frozen baseline label carried as the frame
index (never re-derived from the mutated frame; source = declared PK else AD-16 surrogate; **fail
closed** on an unkeyable table; `duplicate_keys` → audit-excuse region) · canonical `row_key`
encoding = JSON array of PK values in schema order, ints/floats normalized · G3 determinism =
FK-topological order + manifest sorted by `(table, row_key, fault_type)` before serialization ·
AD-29 orphaned children **left dangling** + `orphaned_child` fault, inserts minted from a reserved
baseline-disjoint keyspace · AD-30 detection audit imports no data-QA tool · AD-31 records realized
per-stratum null-rate (G2's home) · AD-33 reference fixture outside `tymi.*` · hexagonal +
import-linter (core/ports/domain never import adapters; adapter→adapter allowed).

### FR coverage map

| FR / Goal | Story | AD |
| --- | --- | --- |
| CC-8 (manifest half), G3 | CC1.1 | AD-28 |
| CC-8 (audit), G3 | CC1.2 | AD-28 |
| CC-1 | CC1.3 | AD-28, AD-29 |
| CC-3 | CC1.4 | AD-28, AD-29 |
| CC-8 (policy half), CM2 | CC1.5 | AD-34 |
| CC-9, G1 (fixture) | CC1.6 | AD-33 |
| CC-11, CC-10, G1 (proof) | CC1.7 | AD-30 |
| CC-2, G2 | CC2.1 | AD-31 |
| CC-4 | CC2.2 | AD-31 |
| CC-7 | CC3.1 | AD-32 |
| CC-5 | CC3.2 | AD-32 |

> **CC-10 (batch/DB delivery)** introduces no new mechanism — chaotic whole-DB output is emitted
> through the existing exporters + PRD 1 destinations. It is carried as a delivery AC on CC1.3 /
> CC1.5, not a standalone story.

---

## Epic CC1 — Phase 1: Referential missing-data + cardinality manifest + the detection audit

The genuinely-new fault family (whole-row deletion that orphans children) **plus** the core change
that makes it auditable **plus** the detection audit that is the product differentiator, proven on a
reference fixture (G1). Sequenced so the keyed manifest (foundational) lands before anything records
against it.

### Story CC1.1: Keyed Fault Manifest foundation

As a chaos author, I want every fault recorded against a stable `(table, row_key)` identity instead
of a frame position, so that a deletion/insertion is representable and a run stays auditable after a
row moves (CC-8 manifest half, AD-28, G3).

**AC.** `EXTEND domain/artifacts.py`: a `FaultManifest` entry carries `table` and `row_key` (frame
position `row` retired from the contract); a `manifest_version` marks the new shape. `row_key` is the
**canonical encoding** — a JSON array of the table's PK values in schema-declared column order, with
ints/floats normalized (`1.0`→`1`) — produced by one shared helper used by producer, audit, and (later)
the results file. The new `fault_type` vocabulary is registered: `dropped_record`, `inserted_record`,
`orphaned_child`, `sequence_gap`, `conditioned_null`, `schema_reorder`. A serialization helper sorts
entries by `(table, row_key, fault_type)` so the bytes are stable regardless of emission order (G3).
No fault behavior yet — this is the data model + encoding + helpers other stories build on. Pure-core
+ unit tests; determinism asserted.

### Story CC1.2: Key-aligned manifest audit (cardinality auditable)

As an auditor, I want the manifest audit to align baseline↔chaotic rows by their frozen `row_key`
label instead of by position, so that deletions and insertions become auditable rather than
`(unauditable)` (CC-8 audit, AD-28).

**AC.** `EXTEND eval/chaos_audit.py`: cell faults diff by `(table, row_key)`, so a surviving row stays
auditable after a sibling is dropped. `deletions = baseline_labels − surviving_labels` and
`insertions = new_labels` are checked as first-class faults (no more "row count changed …
(unauditable)"). When `duplicate_keys` makes a live PK non-unique the duplicated rows form an
**audit-excuse region** (mirroring the existing row-count guard) rather than silently collapsing —
identity is the frozen baseline label, not the live PK. The Story-3.6 bidirectional contract still
holds for cell/structural faults. Depends on CC1.1.

### Story CC1.3: Relational-chaos stage + dropped records (referential)

As a pipeline hardener, I want to delete whole rows from a whole-DB dataset — including parent rows
that orphan children across a join — so that I exercise the fault that actually breaks multi-table
pipelines (CC-1, AD-28/AD-29, CC-10 delivery).

**AC.** `NEW chaos/relational.py`: a stage over the whole-DB `dict[table → Dataset]` + FK graph
(`Schema.foreign_keys`). At stage entry each table's rows are stamped with the frozen `row_key`
carried as the **frame index** (source: declared PK, else the AD-16 surrogate; a table with neither
**fails closed**). A configurable fraction of rows is deleted (driven by the injected `rng`,
AD-4/AD-11); the referencing children of a deleted parent are **left dangling** (not cascade-deleted)
and each recorded as an `orphaned_child` fault; the deleted parent is a `dropped_record`. Tables are
visited in **FK-topological order**; same seed+config → same rows dropped and byte-identical manifest
(G3). Chaotic output is delivered through the existing exporters + PRD 1 destinations (CC-10). Depends
on CC1.1.

### Story CC1.4: Sequence gaps

As a pipeline hardener, I want gaps introduced into a monotonic column (missing IDs / skipped
timestamps), so that gap-detection logic is exercised (CC-3, AD-28/AD-29).

**AC.** In `chaos/relational.py`: given a declared monotonic column, remove a configurable set of
values so the sequence has holes, recorded as `sequence_gap` faults keyed by `(table, row_key)`.
Deterministic for a given seed. Distinct from `dropped_record` (a gap need not delete the whole row —
it targets the sequence column) and honored under the audit (CC1.2). Depends on CC1.3.

### Story CC1.5: Cardinality-aware Chaos Policy (mixed mode)

As a chaos author, I want cardinality faults governed by the Chaos Policy the same way per-row faults
are, so that mixed mode corrupts only its `rate` share and the faithful remainder stays faithful
(CC-8 policy half, AD-34, CM2).

**AC.** `EXTEND chaos/policy.py`: in **mixed** mode a `rate` fraction of rows is eligible for
deletion / cardinality faults and the rest are emitted **byte-identical** to the faithful baseline
(CM2); in **fully_chaotic** mode over an FK graph the RI break is by design and keeps the inherited
explicit-confirmation guard. The realized dropped/faulted fraction is auditable against `rate` via the
manifest (AD-28). Deterministic. Depends on CC1.3.

### Story CC1.6: Synthetic reference fixture (the forcing function)

As the product, I want a self-contained synthetic demo — a multi-table dataset, a toy pipeline, and a
data-QA alert suite — so that the detection audit is measurable in CI with no dependency on a real
team (CC-9, AD-33, G1).

**AC.** `NEW examples/reference_fixture/` (wired into `tests/fixtures/reference/` for CI): a
`customers`/`orders`-shaped whole-DB **Spec** (PRD 1), a **toy pipeline** of a few deterministic
transforms/joins, a **data-QA alert suite** (non-null keys, FK integrity, row-count band, monotonic
sequence), and a **declared results file** stub the alerts emit. It consumes **only** the public
library surface (Spec / provision / chaos / eval) and is imported by **no** `tymi.*` module (guarded).
Runs in CI. Depends on CC1.3 (so a real fault can flow through it).

### Story CC1.7: Detection audit ("did it catch it?")

As a pipeline hardener, I want to diff my pipeline's declared detections against the Fault Manifest,
so that I learn exactly which injected faults my pipeline/alerts **missed** — the product
differentiator (CC-11, AD-30, G1).

**AC.** `NEW eval/detection_audit.py` (chaos run_mode, AD-12): consumes `(FaultManifest, results_file)`
where the results file (JSON **or** YAML) lists what the consumer flagged, each entry keyed to the
manifest fault vocabulary (`fault_type` / `table` / `row_key` / `column`) via the CC1.1 encoding.
Emits three disjoint, exhaustive sets — **detected** (∩), **missed** (`manifest − results`),
**false_alarm** (`results − manifest`). Ships the schema + a mapping helper only; imports **no**
data-QA tool. An end-to-end run over the CC1.6 fixture demonstrates **G1** (≥ 1 injected fault the
alert suite misses). Depends on CC1.1 + CC1.6.

---

## Epic CC2 — Phase 2: Conditioned missingness (MAR/MNAR + partial records)

Rule-based conditioned nullification over the keyed manifest, reusing the shipped condition DSL.

### Story CC2.1: Conditioned nullification (MAR/MNAR)

As a pipeline hardener, I want to null cells under a rule (missingness that depends on another column,
or on the cell's own value), so that I test non-uniform missing-data mechanisms — provably not MCAR
(CC-2, AD-31, G2).

**AC.** `NEW chaos/mutators/missing_data.py`: a `Mutator` that reuses `synth/conditions.py`
(`Equals`/`Between`/`Members`) by importing it directly (adapter→adapter, allowed). A rule pairs a
parsed `Condition` with a per-stratum `null_rate`: **MAR** conditions on **another** column, **MNAR**
on the affected column's **own** value; cells outside the condition keep the run base rate. Per-cell
null faults recorded as `conditioned_null` by `(table, row_key, column)`. The mutator records the
**realized per-stratum null-rate** in the manifest, so G2's check (realized rate differs across the
conditioning column's strata by more than a margin) is computable from the manifest alone. Determinism
(AD-4/AD-11). Depends on Epic CC1 (keyed manifest).

### Story CC2.2: Partial records

As a pipeline hardener, I want to null a declared subset of columns for affected rows (incomplete
rows), so that I test partial-record handling distinct from the CC-2 cell pattern (CC-4, AD-31).

**AC.** In `chaos/mutators/missing_data.py`: for a selected fraction of rows, null a declared column
subset (leaving the rest of the row intact), recorded per cell by `(table, row_key, column)`. Distinct
from CC2.1's conditioned single-cell pattern (this nulls a fixed column set per affected row).
Deterministic. Depends on CC2.1.

---

## Epic CC3 — Phase 3: Schema-drift depth (versioned delta + reorder)

Express schema drift as an explicit, diffable delta off the canonical Schema; add the one column-level
drift the MVP lacks.

### Story CC3.1: Versioned drift delta (`SchemaDelta`)

As a contract owner, I want type/nullability/order drift expressed as an explicit recorded delta from
the canonical Schema, so that a contract test can diff `old → new` declaratively (CC-7, AD-32).

**AC.** `EXTEND domain/artifacts.py`: a `SchemaDelta` artifact captures ops (add / drop / rename /
retype / nullability-change / reorder columns) off the AD-10 `Schema`, recorded in the manifest's
structural channel. A `SchemaDelta` applies its ops in a **fixed intra-delta order — rename → retype →
nullability → reorder (last)** — so two implementations can't produce a different final schema. Serializes
deterministically; diffable. Foundational for CC3.2. Pure-core + unit tests.

### Story CC3.2: Column reorder

As a pipeline hardener, I want to permute a table's column order without changing the column set, so
that I test the column-order drift the MVP doesn't cover (CC-5, AD-32).

**AC.** `EXTEND chaos/mutators/schema_break.py`: a reorder fault permutes column order (a permutation
over the **current, post-rename** column names) and emits a `SchemaDelta` reorder op (`schema_reorder`
fault); `_audit_structural` (chaos_audit) recognizes a reorder as a reorder, **not** a drop+add.
Deterministic. Depends on CC3.1.

---

## Deferred (out of scope for PRD 2)

- **Streams / queues + API/OpenAPI-contract chaos** — PRD 3. The detection-audit results-file contract
  is stream-agnostic and carries forward unchanged.
- **A `RelationalMutator` entry-point port** — cardinality faults ship as a stage (AD-29); promote to a
  discovered port only when a second relational fault family needs it.
- **Live data-QA tool adapters (Great Expectations, dbt)** — the results-file contract is the seam;
  native adapters are follow-ons.
- **Learned / generative missingness models** — rule-based conditioning only.
- **Cardinality faults over out-of-core streaming** — PRD 2 is batch/DB (whole-DB in memory).

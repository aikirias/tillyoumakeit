---
baseline_commit: 1ff8d86
---

# Story 3.6: Fault Manifest

Status: done

## Story

As a user,
I want an auditable manifest of every injected fault,
so that I can validate whether my pipeline detected them.

## Acceptance Criteria

1. **Bidirectional fault contract** — `audit_manifest(baseline, chaotic, manifest)`
   verifies **both** directions: every **listed** fault is **present** in the chaotic
   output (the recorded cell/column change materialized), and every **present** change
   (a cell that differs from the faithful baseline, or a schema difference) is
   **listed** in the manifest. It returns the discrepancies in each direction and a
   `valid` verdict.
2. **Row/column/fault-type per fault** — each manifest entry already carries
   `{mutator, fault_type, ...}` with `row`/`column` for cell faults and
   `column`/`new_name`/`from`/`to` for structural faults; the audit keys off exactly
   those.
3. **Same config + seed → same manifest** — a chaos run is deterministic, so re-running
   with the same seed produces an identical manifest (verified).
4. **Evaluate in `chaos` run_mode (AD-12)** — `evaluate(dataset, *, run_mode, …)`
   discriminates: `chaos` → validates/emits the manifest audit (no fidelity report),
   `faithful` → the Story 2.7 FidelityReport. The orchestrator sets `run_mode`.
5. **Exposed** — `tymi chaos --audit` runs the audit over the run it just produced
   (it has the faithful baseline) and exits non-zero if the manifest is not a faithful
   record of the corruption; the audit is JSON-exportable.

## Tasks / Subtasks

- [ ] **Task 1: Audit artifact** (`src/tymi/domain/artifacts.py`) — `ManifestAudit`
  (`valid`, `listed_not_present`, `present_not_listed`, counts) + `to_json`.
- [ ] **Task 2: The audit** (`src/tymi/eval/chaos_audit.py`) —
  `audit_manifest(baseline, chaotic, manifest)`: reconstruct the expected column set
  from the listed structural faults and compare to the chaotic Schema; diff same-named
  columns cell-by-cell for value faults; report both directions.
- [ ] **Task 3: Evaluate dispatch** (`src/tymi/eval/evaluate.py`) — `evaluate(dataset,
  *, run_mode, baseline, manifest, profile, tolerance)` routing `chaos` → audit,
  `faithful` → fidelity (AD-12).
- [ ] **Task 4: CLI** (`src/tymi/cli/app.py`) — `tymi chaos --audit` runs the audit,
  prints/writes it, exits 1 when invalid.
- [ ] **Task 5: Unit tests** — a clean chaos run audits `valid`; a tampered manifest
  (dropped entry / phantom entry / wrong cell) is caught in the right direction; both
  cell and structural faults; determinism; Evaluate routes by run_mode.
- [ ] **Task 6: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **The backward direction needs the faithful baseline.** "Every present fault is
  listed" means diffing the chaotic output against the pre-chaos (faithful) dataset:
  cells that differ are the faults, and each must appear in the manifest. So the audit
  takes `(baseline, chaotic, manifest)` — the chaos flow keeps the faithful dataset it
  started from.
- **Structural faults are audited via schema reconstruction.** A naive column-set diff
  can't tell a rename from a drop+add. Instead the audit *applies* the listed
  structural faults (missing/extra/renamed/changed_type) to the baseline column set and
  checks the result equals the chaotic Schema's columns — one comparison that covers
  both directions for structure. `changed_type` additionally verifies the declared
  type actually changed.
- **Cell diff is on same-named columns.** Value faults (outliers, format/type,
  duplicate_key, orphan_fk, illegal_null) keep the column name, so the audit diffs
  columns present under the same name in both frames; dropped/renamed/added columns are
  handled by the structural check, not the cell diff. Null-aware equality (both null →
  equal) so `illegal_null` reads as a real change.
- **AD-12 Evaluate.** `evaluate` dispatches on `run_mode`: `chaos` returns the
  `ManifestAudit` (no SDMetrics), `faithful` returns the FidelityReport (Story 2.7).
  The full pipeline orchestrator that sets `run_mode` is still a later concern
  (`core/pipeline.py` is a skeleton); this story delivers the Evaluate branch + the
  chaos-mode audit it calls.
- **Scope.** Epic 3 complete after this. Wiring Chaos → LeakageGate → Evaluate → Export
  into a single orchestrator, and the multi-table chaos surface, remain for the
  pipeline/UI epics.

### References

- [Source: epics.md#Epic-3 Story 3.6; FR-16; AR-11]
- [Source: ARCHITECTURE-SPINE.md — AD-12 (Evaluate branch, chaos run_mode validates the
  FaultManifest, no fidelity), AD-4/AD-11]
- [Source: 3-1..3-5 — FaultManifest entry conventions per fault family]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All tests run **inside the devcontainer**: `uv run ruff check .` / `uv run
  lint-imports` → clean; `uv run pytest tests/unit` → 417 passed.

### Completion Notes List

- `audit_manifest` (bidirectional cell + structural), `evaluate` (AD-12 run_mode
  dispatch), `ManifestAudit` artifact, `tymi chaos --audit`. Epic 3 complete.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 3
  HIGH false-CI-failures on legitimate runs: (a) `duplicate_keys` copying an existing
  value into a repeating/composite-key column left the cell unchanged though listed
  (189/200 seeds failed) → a listed-but-unchanged cell is accepted when it **holds the
  recorded value**; (b) a chain that **renamed** then corrupted, or corrupted then
  **dropped**, the same column false-failed (the frame diff can't follow a structural
  change) → value faults on non-common columns are **excused** (the structural check
  covers the column's fate); (c) an unlisted type change / column drop was reported in
  the **wrong direction** → rewrote the structural audit to bucket every real Schema
  change (drop/add/rename/type) into `present_not_listed` and every unmaterialised
  listed fault into `listed_not_present`, and to **scan for unlisted type changes**.
  Fixed a `min(len)` row-count blind spot (a row-count change is now itself a finding)
  and a crash on a non-integer manifest `row`. Closed test gaps: duplicate-on-repeating
  key valid, combined structural+cell chains valid, unlisted drop/type-change in the
  right direction, non-int row, and the CLI audit-invalid → exit-1 path. All 3 reviewers
  verified the `valid` verdict is correct; null/float/Int64-NA equality all safe.
  +6 tests → 417 unit. All ACs satisfied.

### File List

- `src/tymi/eval/chaos_audit.py` (new — `audit_manifest`)
- `src/tymi/eval/evaluate.py` (new — AD-12 `evaluate` dispatch)
- `src/tymi/domain/artifacts.py` (modified — `ManifestAudit`, `manifest_audit_to_json`)
- `src/tymi/cli/app.py` (modified — `tymi chaos --audit`)
- `tests/unit/test_chaos_audit.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.6 — bidirectional Fault Manifest audit (`audit_manifest`), Evaluate chaos run_mode dispatch (`evaluate`, AD-12), `ManifestAudit` artifact, `tymi chaos --audit`. Completes Epic 3. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Fixed 3 HIGH false-CI-failures (duplicate_keys value coincidence; combined rename/drop + cell chains; wrong-direction structural bucketing + unlisted type-change scan) plus a row-count blind spot and a non-int-row crash. Closed the missing CLI exit-1 and combined-chain test gaps. 417 unit. All ACs satisfied. Status → done. |
| 2026-07-04 | Second-pass verification (audit contract confirmed correct, no residual false-CI-failure, no new hole from the leniency/excuse fixes). Fixed 2 robustness crashes it surfaced on inputs the pipeline never produces: the audit crashed on a chaotic frame with duplicate column names (now only unique-named columns are cell-diffed), and `OutlierMutator` crashed when a column had been corrupted to text earlier in a chain (empty numeric population → min/max of `[]`) — it now skips a column with no coercible numeric/datetime value. +3 tests → 420 unit. |

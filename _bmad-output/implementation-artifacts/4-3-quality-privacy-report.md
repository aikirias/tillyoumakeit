---
baseline_commit: b9f60e9
---

# Story 4.3: Quality & Privacy Report

Status: done

## Story

As a user,
I want a composite quality score plus privacy metrics,
so that I can quantify both fidelity and leakage risk.

## Acceptance Criteria

1. **Composite Quality Score** — `tymi report --quality-privacy` emits a single
   composite Quality Score in `[0, 1]` summarizing source-vs-generated fidelity (built
   from the Story 2.7 KSComplement/TVComplement/CorrelationSimilarity per-column +
   global scores).
2. **≥ 1 membership privacy metric** — the report emits a membership-disclosure metric:
   the share of generated values in sensitive columns that exactly reproduce a real
   source value (measured against the Profile's hashed `LeakageGuard`, AD-6 — never a
   raw value). Lower is safer; a properly gated faithful run scores ~0.
3. **≥ 1 attribute-inference privacy metric** — the report emits an attribute-inference
   risk metric computed on the **released (generated) data**: per sensitive column, the
   strongest single-predictor inference signal — max |Spearman ρ| to another numeric
   column for a numeric target; the best conditional-mode accuracy from a
   low-cardinality predictor for a categorical target. An in-house proxy, not a trained
   attacker; a best-*single*-predictor signal (a joint multi-QI attacker could do
   better), reported as a risk indicator rather than a strict bound.
4. **In-house (AD-9)** — no `sdmetrics` (→ `copulas`, BUSL-1.1). The AC names SDMetrics
   as the reference definition; the metrics are computed in-house on numpy/the Profile,
   exactly as Story 2.7 did for the fidelity metrics.
5. **Exportable + CI gate** — the report serializes to deterministic JSON (`--out`) and
   `report` exits non-zero when the Quality Score is below `--tolerance`, the membership
   metric is above `--membership-threshold`, or the attribute metric is above
   `--attribute-threshold` (each a configurable CI gate).

## Tasks / Subtasks

- [x] **Task 1: Metrics** (`src/tymi/eval/privacy_report.py`) — `quality_score` (composite
  fidelity), `membership_risk` (LeakageGuard hit share, worst column), `attribute_inference_risk`
  (correlation / conditional-mode accuracy), and `quality_privacy_report` assembling them
  with the pass/fail gate.
- [x] **Task 2: Artifact** (`src/tymi/domain/artifacts.py`) — `QualityPrivacyReport`
  dataclass + `quality_privacy_report_to_json` (deterministic, sorted keys).
- [x] **Task 3: CLI** (`src/tymi/cli/app.py`) — `tymi report --quality-privacy` with
  `--membership-threshold` / `--attribute-threshold`; reuse `--tolerance` for quality;
  exit 1 on any gate failure; `--out` to export.
- [x] **Task 4: Unit tests** — composite score aggregates fidelity; membership metric
  detects a planted leaked value and scores ~0 on a gated dataset; attribute metric
  reflects a strong correlation / conditional-mode determination; JSON round-trips; CI
  gate exit codes; degenerate inputs (no leakage guard / no sensitive columns → None).
- [x] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **AD-6 native, no reference rows.** Both privacy metrics run from the Dataset + the
  Profile alone (the AC's inputs). The membership metric reuses the Story 2.5
  `LeakageGuard` — a keyed-BLAKE2b membership set of the source's sensitive values — so a
  generated value is checked for exact membership via `leakage_digest(value, salt)`
  without any raw value ever being stored. This doubles as a verification that the Story
  2.5 leakage gate held (a gated faithful run → ~0) and still catches leakage in an
  externally supplied `--data` Parquet.
- **Attribute inference is an in-house proxy on the released data.** Without raw joint
  rows we cannot train an attacker, so metric 3 measures how inferable each sensitive
  column is **in the generated output itself** (the released data an attacker actually
  sees): for a numeric target, its maximum absolute Spearman correlation to any other
  numeric column; for a categorical target, the best conditional-mode accuracy from a
  single low-cardinality predictor (group by the predictor, guess each group's most
  frequent value — how often an attacker who knows that column guesses the sensitive
  value right). It is a best-*single*-predictor signal, so it can *under*-state a joint
  multi-QI attacker; it is a risk indicator, not a strict bound. A high value can also be
  inherent to the data (a 95%-one-value column) rather than a synthesis fault, which is
  why its CI gate is opt-in (`--attribute-threshold` default 1.0 = never fails). A
  near-unique predictor (cardinality > 50) is skipped — it would "predict" everything
  trivially without reflecting real inference risk.
- **Sensitive columns.** Taken from `Profile.leakage_guard.columns` (the columns marked
  sensitive / auto-classified in Stories 2.5 + 4.1). No leakage guard, or none of its
  columns present in the Dataset → the privacy metrics are `None` (not applicable) and do
  not fail the gate; the Quality Score still reports.
- **Composite Quality Score.** The mean of the Story 2.7 per-column scores and the global
  correlation — one number for a dashboard / CI, with the full `FidelityReport` embedded
  for drill-down. `None` only when nothing was comparable (same rule as 2.7's `passed`).
- **Worst-column, not pooled (gate fix).** `membership_risk` reports the **maximum**
  per-column disclosure rate, not a pooled average across sensitive columns — pooling
  would let a 100%-leaked column be masked by safe columns (averaging to a value that
  slips a relaxed threshold). This is consistent with `attribute_inference_risk`, which
  also reports the worst case.
- **Accepted limitations (documented, not bugs).**
  1. *Cross-type membership.* The membership check inherits the Story 2.5 `leakage_digest`
     exact-string hashing (`str(value)`), so a value whose numeric *type* changes between
     source and output — e.g. an integer `100` re-materialized as float `100.0` by a
     Parquet null-coercion in `--data` — is not matched (`"100" != "100.0"`). The normal
     `generate_faithful` flow preserves types, and the leakage *gate* shares the same
     property; a type-normalized canonical hash is a Story 2.5 follow-up (broad, gate-
     critical) rather than a metric-only patch that would diverge from the gate.
  2. *Attribute-inference blind spot.* A numeric sensitive target is only correlated
     against other numeric columns; a categorical quasi-identifier that determines a
     numeric secret (region → salary) is not scored. Symmetric to the categorical branch
     using low-cardinality predictors only.
  3. *Small-sample noise.* Correlation needs `>= 5` paired rows and a categorical
     predictor needs `>= 2` rows per group on average, or the signal is skipped — a
     2-row frame otherwise yields a meaningless ±1 correlation / trivial mode accuracy.
- **Scope.** The report + CLI surface. It does not wire the privacy *filters* (Story 4.2)
  into a generate pipeline; it *measures* residual risk after the fact.

### References

- [Source: epics.md#Epic-4 Story 4.3; FR-25; SM-2]
- [Source: ARCHITECTURE-SPINE.md — AD-6, AD-9, AD-10, AD-12; eval adapter]
- [Source: fidelity.py (Story 2.7 in-house metrics); leakage.py + LeakageGuard (Story 2.5)]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_privacy_report.py -q` → 20 passed.
- `uv run pytest -q` → 476 passed, 22 deselected.
- `uv run ruff check src/ tests/` → clean; `uv run lint-imports` → 2 contracts kept.
- `grep -rn "sdmetrics\|copulas" src/ pyproject.toml` → none (AD-9).

### Completion Notes List

- Implemented the composite Quality Score (mean of the Story 2.7 per-column + global
  fidelity), the membership-disclosure metric (hashed `LeakageGuard` hit rate, AD-6), and
  the attribute-inference proxy (max Spearman / conditional-mode accuracy on the released
  data); `QualityPrivacyReport` + JSON export; `tymi report --quality-privacy` with three
  CI-gate thresholds.
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). Findings
  applied:
  - **MED (Blind)** — `membership_risk` pooled hits across columns, masking a fully-leaked
    column behind safe ones; now reports the **worst-column** rate (consistent with the
    attribute metric).
  - **Blocking (Acceptance)** — the attribute CI gate was never proven to trip; added a
    unit test (low `--attribute-threshold` → `"attribute_inference"` in `failures`) and a
    CLI privacy-gate exit-1 test.
  - **Blocking (Acceptance)** — the story AC-3/Dev Notes contradicted the code (said
    `Profile.correlations` / marginal mode); reconciled the text to the implementation
    (released-data Spearman + conditional-mode) and softened the "upper-bound" claim to a
    best-single-predictor signal.
  - **LOW (Blind + Edge)** — conditional-mode saturated to 1.0 on a near-unique predictor
    and Spearman degenerated to ±1 on tiny frames; added support guards (avg group ≥ 2
    rows; `>= 5` paired rows for correlation).
  - **LOW (Edge)** — a non-finite quality could slip the gate (`nan < tol` is False); now
    guarded with `math.isfinite`.
  - Documented accepted limitations (cross-type membership from the 2.5 `leakage_digest`
    string hashing; numeric-target/categorical-QI blind spot; small-sample noise).
- Reconciled the AD-9 SDMetrics substitution for the **privacy** metrics in the spine
  (Stack + eval/ + Testing + AD-12 lines), matching the Story 2.7 fidelity precedent.

### File List

- `src/tymi/eval/privacy_report.py` (new) — `quality_score`, `membership_risk`,
  `attribute_inference_risk`, `quality_privacy_report`.
- `src/tymi/domain/artifacts.py` (modified) — `QualityPrivacyReport` +
  `quality_privacy_report_to_json`.
- `src/tymi/cli/app.py` (modified) — `report --quality-privacy` +
  `--membership-threshold` / `--attribute-threshold`.
- `tests/unit/test_privacy_report.py` (new) — 20 tests.
- `tests/unit/test_fidelity.py` (modified) — updated the report-flag-required message.
- `ARCHITECTURE-SPINE.md` (modified) — reconciled the SDMetrics→in-house privacy note.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 4.3 — composite Quality Score + membership + attribute-inference privacy metrics. |
| 2026-07-04 | Implemented metrics + artifact + CLI + tests; passed the 3-layer review gate (worst-column membership, attribute-gate proof, support guards, NaN guard, doc/spine reconciliation). Status → done. |

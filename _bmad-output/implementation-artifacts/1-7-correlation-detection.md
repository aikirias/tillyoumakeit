---
baseline_commit: 6a505513c5fdaef3efd096f420b30df8bd09108e
---

# Story 1.7: Correlation detection

Status: done

## Story

As a user,
I want cross-column correlations detected during profiling,
so that faithful generation (Epic 2) can later preserve them.

## Acceptance Criteria

1. **Numeric correlation matrix** — the Profile includes a pairwise correlation
   matrix over numeric columns, computed with **Spearman rank correlation**
   (robust to non-linearity/outliers and the natural input for the in-house
   Gaussian copula, AD-9). Constant numeric columns (distinct < 2) are excluded.
2. **First-order categorical dependencies** — the Profile includes pairwise
   associations between categorical columns via **Cramér's V** (in [0, 1],
   symmetric). Constant and high-cardinality categorical columns are excluded
   (cardinality capped by `categorical_threshold`).
3. **Serializable within the Profile artifact** — the correlation representation
   round-trips through `profile_to_json` as valid JSON (no bare `NaN`;
   undefined coefficients serialize as `null`).
4. **No raw values (AD-6)** — only aggregate association coefficients + column
   names are stored, never row values.
5. **Deterministic** — detecting correlations on a given Dataset is
   deterministic (stable column ordering, rounded coefficients).
6. **Graceful degradation** — a table with < 2 numeric (resp. categorical)
   columns simply omits that matrix; a fully unprofilable table yields
   `correlations = None` without crashing.
7. **Verified end-to-end** — an integration test profiles a real
   PostgreSQL/MySQL table with correlated numeric + categorical columns and
   asserts the detected correlations have the expected shape and sign.

## Tasks / Subtasks

- [x] **Task 1: Extend the Profile model** (`src/tymi/domain/artifacts.py`) — add
  `CorrelationMatrix` (`method`, `columns`, `matrix`) and `Correlations`
  (`numeric`, `categorical`); add `correlations: Correlations | None` to `Profile`.
- [x] **Task 2: Correlation detection** (`src/tymi/profiling/correlations.py`) —
  `detect_correlations(frame, column_profiles, *, max_categorical_cardinality)`:
  Spearman over numeric columns (pandas `corr`), Cramér's V over categorical
  columns (in-house chi² on numpy, no scipy). Pairwise-complete observations;
  NaN/undefined → `None`; coefficients rounded for determinism.
- [x] **Task 3: Wire into the profiler** (`src/tymi/profiling/profiler.py`) —
  after per-column profiling, call `detect_correlations` (numeric = columns with
  numeric stats; categorical = columns with category labels) and attach to the
  returned `Profile`.
- [x] **Task 4: Unit tests** — numeric Spearman (positive/negative sign,
  constant column excluded), Cramér's V (perfect dependence ≈ 1, independence ≈ 0),
  determinism, graceful degradation (< 2 columns → matrix omitted), JSON validity
  (undefined → `null`), AD-6 (no raw values in serialized output).
- [x] **Task 5: Integration tests** — PostgreSQL + MySQL: create/populate a table
  with correlated numeric columns and dependent categorical columns, sample +
  profile, assert the correlation matrices' shape and expected sign/strength.

## Dev Notes

- Correlation detection is a pipeline-stage helper in `tymi.profiling`
  (imports `tymi.domain` + pandas/numpy only; import-linter-clean).
- **Numeric = Spearman**, deliberately: it is rank-based (robust to skew/outliers)
  and is exactly the correlation the Gaussian copula consumes in Epic 2, so no
  re-estimation is needed downstream. Pearson can be added later if a report needs it.
- **Categorical = Cramér's V** computed from a pairwise-complete contingency table.
  chi² is computed directly (`Σ (O−E)² / E`, `E = outer(row, col)/n`) so no scipy
  dependency is pulled; V = √(χ²/(n·(min(r,k)−1))), clamped to [0, 1].
- Which columns count as numeric vs categorical is taken from the already-computed
  `ColumnProfile`s (numeric stats present → numeric; category labels present →
  categorical), so detection stays consistent with per-column profiling.
- Undefined coefficients (constant column, zero overlap) are stored as `None`
  and serialize to JSON `null` — never a bare `NaN` (which is invalid JSON).
- Deterministic: contingency tables use sorted categories; coefficients are
  rounded to 6 dp to avoid platform float noise in the serialized artifact.

### References

- [Source: epics.md#Epic-1 Story 1.7; FR-5]
- [Source: ARCHITECTURE-SPINE.md — AD-6 (Profile has no raw values), AD-9
  (permissive-only; correlation via in-house Gaussian copula on numpy/scipy),
  AD-10 (canonical artifacts)]
- [Source: 1-6-per-column-profiler.md — Profile model / profile_dataset]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.profiling.correlations` imports `tymi.domain` + numpy/pandas only).
- `uv run pytest tests/unit` → 88 unit passed (correlations: sign, perfect/independent
  dependence, exclusions, determinism, JSON-no-NaN, AD-6).
- `uv run pytest -m integration -k correlation` → 2 passed (real `postgres:16-alpine`
  + `mysql:8.4`): `b = 2*a` Spearman ≈ 1.0, `region → tier` Cramér's V ≈ 1.0.

### Completion Notes List

- Correlation detection attaches a `Correlations` object to the `Profile`:
  numeric = Spearman rank correlation (copula-ready, AD-9); categorical =
  first-order dependencies via in-house Cramér's V (chi² on numpy, no scipy).
- Column selection is driven by the per-column `ColumnProfile`s (numeric stats
  present → numeric; category labels present → categorical), so detection stays
  consistent with profiling and never re-decides types.
- AD-6 upheld: the correlation representation stores only column names +
  coefficients (verified they stay in [-1, 1] / `null`); no raw values.
- Undefined coefficients (constant column, disjoint overlap) serialize as JSON
  `null`, never bare `NaN`. All coefficients rounded to 6 dp for a stable artifact.
- All 7 ACs satisfied; verified end-to-end on PostgreSQL and MySQL.

### File List

- `src/tymi/domain/artifacts.py` (modified — `CorrelationMatrix`, `Correlations`, `Profile.correlations`)
- `src/tymi/profiling/correlations.py` (new — Spearman + Cramér's V detection)
- `src/tymi/profiling/profiler.py` (modified — `profile_dataset` attaches correlations)
- `tests/unit/test_correlations.py` (new)
- `tests/integration/test_correlation_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.7 — cross-column correlation detection (numeric Spearman + categorical Cramér's V, in-house chi²) attached to the Profile and serializable (undefined → `null`, no raw values, AD-6). 86 unit + real PG/MySQL correlation integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: 0 HIGH / 0 MEDIUM. Applied LOW-1 fix — exclude numeric columns that are constant *after* coercion (real exclusion, not NaN-cleaning) + 2 tests (disjoint-overlap → `None`, constant-after-coerce excluded). LOW-2 (small-sample Cramér's V bias) / LOW-3 (diagonal semantics) documented, deferred. 88 unit tests pass; integration re-verified. Status → done. |

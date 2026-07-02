---
baseline_commit: e9839c7
---

# Story 1.6: Per-column statistical profiler

Status: done

## Story

As a user,
I want each column profiled by type (numeric, categorical, date, string),
so that I capture the statistical shape of my data without storing raw values.

## Acceptance Criteria

1. **Numeric profile** — for INTEGER/FLOAT columns: count, null count, distinct count, min, max, mean, std, quantiles (5/25/50/75/95), and a histogram (bin edges + counts).
2. **Categorical profile** — for categorical/boolean and low-cardinality string columns: per-category frequencies (top-K) + distinct count.
3. **Date & string profiles** — DATETIME: range (min/max) + basic seasonality (day-of-week and month frequencies). High-cardinality STRING: length stats (min/max/mean length) only — **no raw values**.
4. **No re-identifiable raw values (AD-6)** — the Profile stores only aggregates: numeric summaries, category labels for low-cardinality columns (documented assumption), and length/pattern stats for free text. Free-text column values are never stored.
5. **`tymi profile <table>`** samples the table (`--rows`, `--seed`) and prints the resulting Profile as JSON (persistence to a file is Story 1.8).
6. **Deterministic** — profiling a given Dataset is deterministic; the JSON serializes cleanly (StrEnum + tuples).
7. **Verified end-to-end** — an integration test profiles a real PostgreSQL/MySQL table with numeric + categorical + date + text columns and asserts the shape of the produced Profile.

## Tasks / Subtasks

- [x] **Task 1: Enrich the Profile model** (`src/tymi/domain/artifacts.py`) — add `NumericStats`, `CategoryFrequency`, `DatetimeStats`, `TextStats`, `ColumnProfile`; enrich `Profile` with `row_count` and `columns: tuple[ColumnProfile,...]`; add `profile_to_json`.
- [x] **Task 2: Profiler** (`src/tymi/profiling/profiler.py`) — `profile_dataset(dataset, *, top_k, categorical_threshold, histogram_bins) -> Profile`, dispatching per `LogicalType`: numeric (numpy quantiles/histogram), categorical (value_counts top-K), datetime (range + dow/month freq), string (categorical if low-cardinality else length stats). Handle nulls and all-null columns.
- [x] **Task 3: Privacy** — free-text (high-cardinality string) columns store only length/pattern stats, never values (AD-6). Category labels are stored only for low-cardinality columns.
- [x] **Task 4: Real `profile` CLI command** — replace the stub: sample the table then profile, print `profile_to_json`; reuse `_load_adapter` + `make_rng`; typed errors; no secrets.
- [x] **Task 5: Unit tests** — profile a hand-built DataFrame+Schema: numeric stats, categorical freqs, datetime seasonality, high-cardinality string → text stats only (assert no values leak), null handling, all-null column.
- [x] **Task 6: Integration tests** — PostgreSQL + MySQL: create/populate a mixed-type table, sample + profile, assert per-column profile shapes.

## Dev Notes

- `profiling` is a pipeline-stage module (`tymi.profiling`), not an adapter; it imports `tymi.domain` + pandas/numpy and is import-linter-clean (not in the forbidden adapter set).
- Reuse `sample()` (Story 1.5) → `Dataset` (DataFrame + Schema) as the profiler input; the CLI `profile` samples then profiles.
- Dispatch by the canonical `LogicalType` from the Schema. STRING with `distinct_count <= categorical_threshold` (default 50) is treated as categorical; otherwise free text (length stats only).
- Numeric: coerce via `pd.to_numeric(errors="coerce")` to tolerate Decimal/object dtypes from drivers; `std` uses sample std (ddof=1) when count > 1 else 0.
- PII suppression of category labels is a later story (Epic 4); for now low-cardinality labels are stored per the FR-4 assumption.
- Profiling is deterministic (no RNG); reproducibility of the *sample* comes from Story 1.5.

### References

- [Source: epics.md#Epic-1 Story 1.6; FR-4]
- [Source: ARCHITECTURE-SPINE.md — AD-6 (Profile has no raw values), AD-10 (canonical artifacts)]
- [Source: 1-5-streaming-sampling.md — sample() / Dataset]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept (`tymi.profiling` imports domain only).
- `uv run pytest` → 72 unit passed (incl. privacy assertion: free-text values absent from serialized Profile).
- `uv run pytest -m integration -k profile` → 2 passed (real `postgres:16-alpine` + `mysql:8.4`): sample + profile a mixed-type table.
- Fixed `test_cli_smoke` (its stub-exit probe now uses `generate`, since `profile` is a real command).

### Completion Notes List

- First real Profile: `profile_dataset(Dataset)` produces per-column aggregates
  dispatched by `LogicalType` — numeric (min/max/mean/std/quantiles/histogram),
  categorical (top-K frequencies), datetime (range + day-of-week/month
  seasonality), high-cardinality string (length stats only).
- AD-6 upheld: free-text values are never stored (verified by asserting a raw
  value is absent from the serialized Profile); only low-cardinality category
  labels are kept (documented FR-4 assumption; PII suppression is Epic 4).
- Enriched the `Profile` domain model (`row_count`, `columns`, stat dataclasses)
  + `profile_to_json`. Real `tymi profile <table>` CLI (sample → profile → JSON).
- All 7 ACs satisfied; verified end-to-end on PostgreSQL and MySQL.

### File List

- `src/tymi/domain/artifacts.py` (modified — Profile stat model + `profile_to_json`)
- `src/tymi/profiling/profiler.py` (new — profiler)
- `src/tymi/cli/app.py` (modified — real `profile` command)
- `tests/unit/test_profiler.py` (new)
- `tests/unit/test_cli_smoke.py` (modified — stub probe → `generate`)
- `tests/integration/test_profile_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.6 — per-column statistical profiler (numeric/categorical/datetime/text), enriched Profile model + `profile_to_json`, real `tymi profile` CLI. AD-6 upheld (no raw free-text values). 72 unit + real PG/MySQL profiling integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: fixed 2 HIGH — (a) numeric column with no finite values crashed `np.histogram` (now returns None); (b) AD-6 leak — low-distinct **long** free-text stored as labels (now length-guarded → text). Also: drop inf, deterministic category/seasonality ordering, +4 tests. LOW count/distinct-vs-coercion dismissed. 76 unit tests pass. Status → done. |
| 2026-07-02 | Full 3-layer `bmad-code-review` gate (Blind Hunter + Edge Case Hunter + Acceptance Auditor, retroactive). AC audit: 7/7 SATISFIED. Fixed 2 MEDIUM — (a) `histogram_bins < 1` now raises `ValueError` instead of an uncaught numpy error; (b) mixed-dtype object categorical columns stringify **before** `value_counts` so `1` and `"1"` no longer split into duplicate labels. +2 tests. Dismissed (by design): count-vs-None-stats consistency, top-k tail truncation. |

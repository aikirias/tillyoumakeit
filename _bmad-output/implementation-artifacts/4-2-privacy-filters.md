---
baseline_commit: c199876
---

# Story 4.2: Privacy Filters

Status: done

## Story

As a user,
I want similarity and outlier filters on faithful output,
so that no synthetic row is suspiciously close to a real record.

## Acceptance Criteria

1. **Similarity filter — no output row within threshold of a real record** — with the
   similarity filter active, every remaining output row is at least the configured
   `threshold` (a mixed-type normalized distance) away from **every** row of the real
   `reference` sample; rows closer than that are dropped.
2. **Outlier filter — removes memorized outliers** — the outlier filter drops output
   rows that are statistical outliers (a numeric value beyond `threshold` standard
   deviations of the generated column) — the tail where memorization of real extreme
   values concentrates.
3. **Configurable (threshold, on/off)** — a `PrivacyConfig` toggles each filter and
   sets its threshold; a disabled filter is a pass-through.
4. **Seed-reproducible / deterministic** — the filters **drop** rows (no re-draw), so
   the same input yields the same filtered output; the canonical Schema is preserved
   (AD-10).
5. **Port + reference (AD-6)** — filters implement `PrivacyFilter.filter(dataset, *,
   reference)`; the real `reference` sample is supplied by a connected caller (the
   Profile stores no raw values, so the similarity filter is a connected-pipeline
   stage, not offline `generate`).

## Tasks / Subtasks

- [x] **Task 1: Distance** (`src/tymi/privacy/filters.py`) — a mixed-type normalized
  row distance (numeric z-scored by the reference; categorical mismatch = 1) and the
  per-generated-row minimum distance to the reference.
- [x] **Task 2: Filters** — `SimilarityFilter(threshold, enabled)` and
  `OutlierFilter(threshold, enabled)`, both `filter(dataset, *, reference) -> Dataset`,
  Schema-preserving, deterministic.
- [x] **Task 3: Config** (`src/tymi/config/models.py`) — `PrivacyConfig`
  (similarity/outlier enabled + thresholds) on `Config`.
- [x] **Task 4: Unit tests** — after the similarity filter no row is within threshold
  of any reference row (constructed near-duplicates dropped, distant rows kept);
  outlier filter drops beyond-k-sigma rows; disabled = pass-through; Schema preserved;
  deterministic; empty/degenerate inputs.
- [x] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **The similarity filter needs raw real rows → connected only.** Distance to a real
  record can't be computed from the Profile's aggregates (AD-6), so the filter takes an
  explicit `reference` Dataset supplied by a caller that still has source access. This
  is why it's a connected-pipeline stage; offline `tymi generate` (no source) can't run
  it. (Contrast the Story 2.5 leakage gate, which works offline off the hashed guard.)
- **Drop, don't re-draw.** Dropping the offending rows is deterministic and needs no
  rng, so the filtered output is reproducible for a given (generated, reference). A
  re-generate-to-target-count variant is a follow-up.
- **Outliers ≈ memorization risk (SM-C1).** Memorization of real values shows up at the
  tails, so the outlier filter drops rows with an extreme numeric value; it is a
  faithful-output quality filter and does not need the reference.
- **Scope.** The two filters + config. Wiring them into a connected generate→filter
  pipeline surface travels with the orchestrator; the Quality & Privacy **report** that
  quantifies residual risk is Story 4.3.
- **Null-aware distance (gate fix).** Both column kinds treat both-null as a match
  (distance 0) and one-sided-null as a 1.0 mismatch, via explicit `isna` masks. This
  matters for privacy: counting a shared null as a mismatch would inflate the distance
  and let a *memorized copy that happens to share a null* survive the similarity filter.
  A raw string sentinel was rejected — pandas `str` vs `object` dtypes round-trip a
  null-byte marker differently, so two nulls could miscompare across dtypes.
- **Robust outlier z (gate fix).** `OutlierFilter` uses a median/MAD modified z-score
  (mean-absolute-deviation fallback when MAD collapses to 0), not mean/std: a *cluster*
  of memorized extremes inflates the std and masks itself under mean/std
  (`[0]*100 + [1e6]*20` escapes) but is caught by the robust estimator.
- **Fail loud, no silent no-ops (gate fix).** Disjoint gen/reference columns raise
  rather than returning "infinitely far" (which would keep every row and disable the
  filter under the guise of success); `threshold <= 0` is rejected in both the filter
  constructors and `PrivacyConfig` (a 0 threshold keeps exact real-record copies).
- **Accepted limitations (documented, not bugs).** (1) A numeric column that is
  *constant in the reference sample* has no scale, so it falls back to raw-unit distance
  (`scale = 1.0`); a row that genuinely differs on that column is correctly kept. (2) The
  outlier filter is a small-sample-limited statistic: at threshold `T` a single extreme
  needs roughly `> T²` rows to be flagged, so tiny outputs cannot surface an outlier —
  inherent to any dispersion estimate, mitigated but not removed by the robust z.
- **Memory (gate fix).** The pairwise distance is computed in `_CHUNK`-row blocks so peak
  memory is `_CHUNK x n_ref`, not `n_gen x n_ref` (a large output would otherwise OOM).

### References

- [Source: epics.md#Epic-4 Story 4.2; FR-24; SM-2, SM-C1]
- [Source: ARCHITECTURE-SPINE.md — AD-6, AD-10; ports.PrivacyFilter]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_privacy_filters.py -q` → 20 passed.
- `uv run pytest -q` → 456 passed, 22 deselected.
- `uv run ruff check src/ tests/` → clean; `uv run lint-imports` → 2 contracts kept.

### Completion Notes List

- Implemented `SimilarityFilter` + `OutlierFilter` (both satisfy the `PrivacyFilter`
  port) and the `nearest_reference_distance` mixed-type distance; added `PrivacyConfig`.
- Ran the full 3-layer `bmad-code-review` gate (Blind Hunter + Edge Case Hunter +
  Acceptance Auditor). Findings applied:
  - **HIGH** — null-vs-null (numeric *and* categorical) was counted as a mismatch,
    inflating the distance so a memorized copy sharing a null survived the filter (a
    privacy leak). Rewrote the distance to be null-aware via explicit `isna` masks
    (both-null → 0, one-null → 1). A first pass used a string sentinel; the Acceptance
    test surfaced that pandas `str` vs `object` dtypes round-trip a null-byte marker
    differently, so masks replaced it.
  - **HIGH** — `pd.NA` in a nullable-string reference crashed `nearest_reference_distance`
    ("boolean value of NA is ambiguous"); the mask path removes the raw `!=` on NA.
  - **HIGH** — disjoint gen/reference columns silently kept every row (a no-op filter
    reporting success); now raises `ValueError`.
  - **MEDIUM** — `OutlierFilter` mean/std self-masked clustered extremes; switched to a
    robust median/MAD modified z-score with a mean-abs-deviation fallback.
  - **MEDIUM** — unbounded `n_gen x n_ref` matrix; now computed in `_CHUNK`-row blocks.
  - **MEDIUM/LOW** — `threshold <= 0` (a filter-enabled no-op / frame-emptier) rejected
    in both the filter constructors and `PrivacyConfig` (`similarity_threshold` `gt=0`).
- Documented accepted limitations in Dev Notes (constant-reference-column raw-unit
  fallback; small-sample outlier detectability). AC-2 "memorized outliers" is delivered
  as "extreme-value (tail) outliers" — a documented quality proxy, per the story AC.

### File List

- `src/tymi/privacy/filters.py` (new) — `SimilarityFilter`, `OutlierFilter`,
  `nearest_reference_distance`.
- `src/tymi/config/models.py` (modified) — `PrivacyConfig` + `Config.privacy`.
- `tests/unit/test_privacy_filters.py` (new) — 20 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 4.2 — similarity + outlier privacy filters. |
| 2026-07-04 | Implemented filters + config + tests; passed the 3-layer review gate (null-aware distance, robust outlier z, fail-loud guards, chunked memory). Status → done. |

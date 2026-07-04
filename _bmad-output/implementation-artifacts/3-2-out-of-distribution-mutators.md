---
baseline_commit: c10339f
---

# Story 3.2: Out-of-distribution fault mutators

Status: done

## Story

As a user,
I want to inject outliers and low-probability values,
so that I can test how my pipeline handles extreme data.

## Acceptance Criteria

1. **Out-of-distribution injection** — an `OutlierMutator` (registered under
   `tymi.mutators`, AD-3) replaces a configurable **proportion** of cells in the
   target columns with values **outside the column's observed range** (numeric:
   `max + magnitude·span` / `min − magnitude·span`; datetime: the same beyond the
   observed date range), so the output carries genuine range-jumps/outliers. Per
   FR-12, "low-probability values" **means** these range-jumps; low-probability
   *categorical* (rare-label) injection is a separate concern, out of scope here.
2. **Proportion honored within the acceptance margin** — for a target column of `n`
   rows, exactly `round(proportion·n)` cells are corrupted, so the realised outlier
   fraction matches the configured proportion well within the default ±2 pp margin.
3. **Targeting by column and type** — with no `columns` set, all numeric
   (INTEGER/FLOAT) and DATETIME columns are targeted; an explicit `columns` list
   targets exactly those; a named column that is not numeric/datetime raises a typed
   `ChaosError` (targeting is honored, never silently dropped). Non-target columns are
   left untouched.
4. **Every injected value is recorded (previews Story 3.6)** — each corruption adds a
   `FaultManifest` entry `{mutator, row, column, fault_type, value}`; the manifest
   count equals the number of injected cells.
5. **Deterministic (AD-4/AD-11)** — row selection and the high/low direction draw from
   the injected `rng`; the same seed + params yields identical output + manifest. The
   canonical Schema is preserved (AD-10); integer columns stay integer-typed.
6. **Parameterized, no core change (AD-3/AD-5)** — `OutlierMutator()` is usable with
   defaults (entry-point discovery) and `OutlierMutator(columns=…, proportion=…,
   magnitude=…)` with validated Pydantic params; it runs through the Story 3.1 engine
   (`apply_chaos`) with zero engine change.

## Tasks / Subtasks

- [ ] **Task 1: The mutator** (`src/tymi/chaos/mutators/outlier.py`) — `OutlierParams`
  (Pydantic: `columns`, `proportion`, `magnitude`) + `OutlierMutator` (`name`,
  `apply(dataset, *, rng)`): resolve targets, pick `round(proportion·n)` rows per
  column, inject out-of-range values, record the manifest, preserve dtypes.
- [ ] **Task 2: Register** (`pyproject.toml`) — `outlier =
  "tymi.chaos.mutators.outlier:OutlierMutator"` under `tymi.mutators`; re-sync so
  `load_mutators()` discovers it.
- [ ] **Task 3: Unit tests** — proportion within margin, targeting (only targets hit,
  others intact, type default), out-of-range values, integer/datetime handling,
  manifest entries, determinism, non-numeric target → `ChaosError`, entry-point
  registration + end-to-end via `apply_chaos`; update `test_plugins` (registry no
  longer empty).
- [ ] **Task 4: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Out-of-distribution is relative to the frame, not the Profile.** The chaos branch
  mutates a **generated** Dataset (DataFrame + Schema), and a Mutator gets no Profile
  — so "outside the distribution" means outside the *column's* observed
  `[min, max]` in the frame, extended by `magnitude·span`. This is genuinely
  out-of-range for that column and needs no Profile access (AD-6 is moot — no source
  rows involved).
- **Exact-count, not per-cell-probability.** Injecting exactly `round(proportion·n)`
  distinct rows (chosen via `rng.choice(replace=False)`) makes the realised proportion
  deterministic and dead-on the target — trivially inside the ±2 pp acceptance margin —
  rather than a noisy Bernoulli draw. High vs low direction is a per-cell `rng` draw.
- **Parameter pattern for all Epic-3 mutators (AD-5).** `OutlierMutator` declares a
  Pydantic `OutlierParams`; `__init__` accepts either a params object or kwargs and
  defaults everything, so no-arg entry-point construction (Story 3.1's
  `resolve_mutators`) yields a usable mutator and Story 3.5's Chaos Policy will pass
  validated config params to the same constructor. Established here, reused by 3.3/3.4.
- **The mutator copies its own frame.** Even though `apply_chaos` already copies at
  entry, the mutator returns a new Dataset (copies the frame) so it is also safe when
  used directly (AD-10 immutability), and preserves the Schema.
- **Scope.** This story ships the numeric/datetime out-of-range fault family + the
  parameter pattern. Format/type violations are Story 3.3, schema/constraint breakage
  Story 3.4, the declarative Chaos Policy + `tymi chaos` CLI Story 3.5, and the
  bidirectional manifest audit Story 3.6.

### References

- [Source: epics.md#Epic-3 Story 3.2; FR-12, FR-13]
- [Source: ARCHITECTURE-SPINE.md — AD-3 (entry points), AD-4/AD-11 (RNG), AD-5 (plugin
  Pydantic param schema), AD-10 (canonical Dataset), chaos acceptance margin ±2 pp]
- [Source: 3-1-pluggable-mutator-engine.md — `apply_chaos`, `Mutator` port,
  FaultManifest entry convention]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All deps/tests run **inside the devcontainer** (`devcontainer exec`): `uv sync`
  (registers the entry point), `uv run ruff check .` / `uv run lint-imports` → clean
  (2 contracts kept); `uv run pytest tests/unit` → 315 passed.
- `load_mutators()` → `{'outlier': OutlierMutator}` after the pyproject entry point.

### Completion Notes List

- `OutlierMutator` (out-of-range injection into numeric/datetime columns) + the
  Pydantic `OutlierParams` pattern, registered under `tymi.mutators` and run through
  the Story 3.1 engine.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 2
  HIGH in the integer path (same lines): a small `magnitude` rounded the "outlier"
  back onto the min/max (a silent in-range value + a false manifest entry), and a
  large-valued Int64 column at the **default** magnitude raised a raw `OverflowError`
  through the engine — both fixed by `_integer_outlier`, which forces the value at
  least one step past the bound and clips to the int64 range (strictly out-of-range,
  no overflow). Fixed 2 MEDIUM: duplicate target columns double-mutated + emitted
  duplicate `(row,column)` manifest keys → target columns are de-duplicated; a target
  present in the Schema but absent from the frame raised a raw `KeyError` → now
  `ChaosError`. Also: injection now targets **non-null** cells only (an outlier
  replaces an observed value; nulls are Story 3.3's fault family) so nulls are no
  longer silently destroyed. Documented edges: extreme `magnitude` yields `inf`
  (float) or upcasts datetime resolution ns→µs — both non-crashing, out-of-range, and
  only reachable at implausible magnitudes. +5 tests → 315 unit. All 6 ACs satisfied.

### File List

- `src/tymi/chaos/mutators/__init__.py` (new)
- `src/tymi/chaos/mutators/outlier.py` (new — `OutlierParams`, `OutlierMutator`)
- `pyproject.toml` (modified — `outlier` under `tymi.mutators`)
- `tests/unit/test_outlier_mutator.py` (new)
- `tests/unit/test_plugins.py` (modified — registry no longer empty)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.2 — `OutlierMutator` (out-of-range injection into numeric/datetime columns) + the Pydantic `OutlierParams` parameter pattern for Epic-3 mutators; registered under `tymi.mutators`, runs via the Story 3.1 engine. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Fixed 2 HIGH (integer outlier rounding back in-range for small magnitude; int64 `OverflowError` at default magnitude on large-valued columns) via `_integer_outlier` (strictly out-of-range + int64-clipped), 2 MEDIUM (duplicate target columns → dedupe; schema/frame divergence → `ChaosError` not `KeyError`); injection now targets non-null cells only. +5 tests → 315 unit. All 6 ACs satisfied. Status → done. |

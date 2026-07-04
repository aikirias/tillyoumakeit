---
baseline_commit: 671a413
---

# Story 2.4: Conditional (seeded) generation

Status: done

## Story

As a user,
I want to condition generation on specific column values/ranges,
so that I can produce targeted test datasets.

## Acceptance Criteria

1. **Conditions expressed simply** — a condition can be an **equality**
   (`region=LATAM`), an **inclusive numeric/datetime range** (`age in [18,25]`),
   or a **membership set** (`region in {LATAM,EMEA}`); the CLI accepts one or more
   via `--where` and the library accepts a parsed `{column: Condition}` map.
2. **100% of rows satisfy the condition** — given any accepted condition, every
   generated row satisfies it (no NULL slips through on a conditioned column).
3. **Non-conditioned columns keep their distribution (within Tolerance)** —
   conditioning restricts only the conditioned column's sampler; every other
   column is generated exactly as faithful generation (marginals preserved, and
   numeric copula correlation still imposed).
4. **Range conditions stay faithful in-range** — a numeric range condition draws
   from the histogram **truncated** to the range (not uniform), so the in-range
   marginal shape is preserved; the copula-driven rank correlation survives the
   truncation (monotone remap of the driving uniform).
5. **Invalid conditions fail with a typed error** — an unknown column, a range on
   a non-numeric/non-datetime column, an unparsable expression, or two conditions
   on the same column raise `GenerationError` (CLI exit 1), never a traceback.
6. **Deterministic (AD-4/AD-11)** — conditional generation draws all randomness
   from the injected `rng`; the same seed + conditions yields identical output.
   AD-6/AD-10 hold (only Profile aggregates consumed; canonical Schema preserved).

## Tasks / Subtasks

- [x] **Task 1: Condition model + parser** (`src/tymi/synth/conditions.py`) —
  `Equals`/`Between`/`Members` dataclasses; `parse_condition(text)` and
  `parse_conditions(list[str]) -> dict[str, Condition]`;
  `validate_conditions(conditions, profile)` (unknown column / wrong type / dup →
  `GenerationError`); `satisfies(frame, conditions)` for tests.
- [x] **Task 2: Restrict the marginal sampler** (`src/tymi/synth/marginals.py`) —
  thread `conditions` into `synthesize`/`_generate_column`; a conditioned column
  is generated without nulls under its restriction: `Equals` → constant, `Members`
  → restricted (add-one-smoothed) categorical / uniform among the set, `Between` →
  truncated inverse-CDF (numeric) or clamped range (datetime).
- [x] **Task 3: Wire into faithful generation** (`src/tymi/synth/generator.py`,
  `faker_values.py`) — `generate_faithful(..., conditions=None)` validates then
  passes conditions down; `apply_formatted_values(..., skip=conditioned)` so a
  conditioned text column is not clobbered by Faker.
- [x] **Task 4: CLI surface** (`src/tymi/cli/app.py`) — `tymi generate --where`
  (repeatable); parse + generate; `GenerationError` → exit 1.
- [x] **Task 5: Unit tests** (`test_conditions.py`, `test_generate_conditional.py`)
  — parsing (all three forms + errors), 100%-satisfaction, non-conditioned marginal
  + copula correlation preserved, truncated-range faithfulness (skewed source),
  determinism, Faker-skip, CLI `--where`.
- [x] **Task 6: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Enforcement is by restriction, not rejection sampling.** The AC requires 100%
  satisfaction *and* that non-conditioned columns keep their (marginal)
  distribution. Rejection sampling would (a) return the *conditional* marginal of
  correlated columns — distorting non-conditioned distributions — and (b) fail to
  terminate for low-probability / continuous-equality conditions. Restricting only
  the conditioned column's sampler guarantees termination and 100% satisfaction
  while leaving every other column's marginal untouched.
- **Range truncation preserves the copula.** For a numeric `Between`, the driving
  uniform (copula-supplied when the column is in the correlation matrix, else an
  independent draw) is remapped into the histogram-CDF sub-interval
  `[F(lo), F(hi)]` before the existing inverse-CDF. A monotone remap preserves the
  rank order the copula imposed, so correlation direction survives among survivors,
  and the in-range values follow the truncated histogram (not a flat uniform).
- **Conditioned columns carry no nulls** — a NULL never satisfies an equality /
  membership / range predicate, so null injection is skipped for conditioned
  columns to keep AC-2 exact.
- **Grammar** (case-insensitive column, unquoted or single/double-quoted values):
  `col=value` (equality), `col in [lo,hi]` (inclusive range, exactly two numeric
  or ISO-datetime bounds), `col in {a,b,c}` (membership set). `[...]` = range,
  `{...}` = set — chosen so `age in [18,25]` reads as the AC's range, not `{18,25}`.
- **Scope**: single-table `tymi generate` gains `--where`; wiring conditions into
  `generate_related` / a multi-table CLI surface travels with the export/pipeline
  stories (the AC does not require it). Tolerance is still the hard-coded default
  (a configurable Tolerance lands with the Config/report stories).

### References

- [Source: epics.md#Epic-2 Story 2.4; FR-10 (Conditional Generation, Seeded)]
- [Source: ARCHITECTURE-SPINE.md — AD-4/AD-11 (RNG), AD-6, AD-10 (canonical Schema)]
- [Source: 2-2-correlation-preservation.md — generate_faithful, copula uniforms]
- [Source: marginals.py — numeric_from_uniform (single-uniform inverse-CDF)]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.synth.conditions` imports only `tymi.core.errors` + `tymi.domain`).
- `uv run pytest tests/unit` → 210 unit passed (parsing of all three condition
  forms + error classes; 100%-satisfaction for equality/range/membership/datetime/
  boolean with no nulls; truncated-range faithfulness on a skewed source; copula
  correlation preserved under a numeric range; non-conditioned marginal preserved;
  determinism; Faker-skip; add-one membership smoothing; unprofiled-column guard;
  `satisfies` numeric/reversed-bounds; CLI `--where` happy path + invalid → exit 1).
- CLI smoke: `tymi generate -p profile.yaml -w "region=LATAM" -w "age in [20,30]"`
  → 100% `region=LATAM` and every `age` in `[20,30]`; invalid `--where` → exit 1
  with a typed "Invalid condition: …" message, no traceback.

### Completion Notes List

- Conditional generation by **restriction** (not rejection sampling): each
  conditioned column's sampler is narrowed so 100% of rows satisfy the predicate
  (no nulls), while every non-conditioned column is generated exactly as faithful
  generation — its marginal and the numeric copula correlation are untouched.
  `Equals` → constant; `Members` → renormalized (add-one-smoothed) categorical /
  set draw; `Between` → histogram truncated to `[F(lo),F(hi)]` via a monotone remap
  of the driving uniform (copula-supplied or independent), so the in-range shape is
  faithful and rank correlation survives. AD-4/AD-11, AD-6, AD-10 hold.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance).
  Fixed 1 HIGH (Edge, convergent with the schema/columns divergence the code
  already contemplates): a condition on a column present in the Schema but absent
  from the profiled columns was silently dropped, emitting an all-null column that
  ignored the condition → now raises `GenerationError` ("no profiled statistics").
  Fixed 2 MEDIUM: `satisfies()` gave false negatives on float columns (string
  compare) and reversed range bounds → now numeric-aware + order-normalized; a
  boolean condition value was silently coerced to `False` for any unrecognized
  literal → now `_coerce_bool` raises like the numeric/datetime coercers. Fixed 2
  LOW: integer equality/membership silently rounded non-integral set values → now
  `_coerce_int` rejects them; `_members_categorical` floored requested-but-unseen
  labels to zero probability → now add-one (Laplace) smoothing so an explicitly
  requested label outside the top-K is still generated. Acceptance test-evidence
  gaps closed: AC-4 truncation now proven on a **skewed** source (median tracks the
  truncated histogram, not the uniform midpoint) + a copula-correlation-under-range
  test; AC-5 now drives the real CLI (`--where` → exit 1, no traceback); AC-2 now
  asserts 100%/no-null on conditioned datetime and boolean columns. All 6 ACs
  satisfied; +11 tests → 210 unit.

### File List

- `src/tymi/synth/conditions.py` (new)
- `src/tymi/synth/marginals.py` (modified — conditioned sampling)
- `src/tymi/synth/generator.py` (modified — conditions param + validation)
- `src/tymi/synth/faker_values.py` (modified — skip conditioned columns)
- `src/tymi/cli/app.py` (modified — `--where`)
- `tests/unit/test_conditions.py` (new)
- `tests/unit/test_generate_conditional.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-03 | Implemented Story 2.4 — conditional (seeded) generation. New `tymi.synth.conditions` (parse/model/validate `Equals`/`Between`/`Members`); the marginal sampler restricts a conditioned column (constant / set draw / truncated inverse-CDF) with no nulls so 100% of rows satisfy it, while non-conditioned columns keep their marginal + copula correlation; `generate_faithful(..., conditions=)` + CLI `tymi generate --where` (repeatable). 187 unit + CLI smoke pass. |
| 2026-07-03 | Full 3-layer `bmad-code-review` gate (Blind + Edge Case + Acceptance). Fixed 1 HIGH (condition on a Schema-only/unprofiled column silently produced an all-null column → now `GenerationError`), 2 MEDIUM (`satisfies` float/reversed-bounds false negatives; boolean value silently coerced to `False` → strict `_coerce_bool`), 2 LOW (integer set values silently rounded → `_coerce_int`; unseen requested membership labels floored to zero → add-one smoothing). Closed AC-4/AC-5/AC-2 test-evidence gaps (skewed-source truncation proof, copula-under-range, real CLI `--where` exit-1, datetime/boolean 100%/no-null). +11 tests → 210 unit. All 6 ACs satisfied. Status → done. |

---
baseline_commit: d1b9618
---

# Story 2.1: Marginal distribution synthesis

Status: done

## Story

As a user,
I want to generate N rows whose per-column distributions match the Profile,
so that the synthetic data is statistically faithful column-by-column.

## Acceptance Criteria

1. **Faithful marginals** — given a Profile, `generate(profile, rows=N, rng)`
   produces a Dataset of N rows where each column's distribution matches the
   Profile within the default Tolerance (numeric shape from the stored histogram,
   categorical from stored frequencies, datetime across the observed range,
   free text length within the observed length range).
2. **Canonical Schema (AD-10)** — the produced Dataset carries the Profile's
   canonical `Schema` unchanged; column names/order/logical types are preserved
   so downstream stages and exporters map from the Schema, never raw dtypes.
3. **Deterministic (AD-4/AD-11)** — synthesis draws all randomness from the
   injected `rng`; the same seed yields byte-identical output, a different seed
   yields different output.
4. **No raw values (AD-6)** — synthesis consumes only Profile aggregates; free
   text is regenerated as synthetic placeholder content of matching length, never
   reproduced from source (the Profile never held the raw values anyway).
5. **Nulls reproduced** — each column reproduces its observed null fraction
   (`null_count / (count + null_count)`); an all-null column stays all-null.
6. **CLI** — `tymi generate --profile profile.yaml --rows N --seed S` loads a
   saved Profile **offline** (no DB), generates, and prints the Dataset as CSV;
   a missing/malformed Profile fails with a typed error and a non-zero exit.
7. **Verified end-to-end** — an integration test profiles a real
   PostgreSQL/MySQL table, generates from that Profile, and asserts the generated
   marginals match (numeric range/mean, categorical labels, row count, seed
   determinism).

## Tasks / Subtasks

- [x] **Task 1: Marginal synthesizer** (`src/tymi/synth/marginals.py`) —
  `MarginalSynthesizer.generate(profile, *, rows, rng) -> Dataset` (structurally
  satisfies the `Synthesizer` port) + a module-level `generate_marginals(...)`.
  Per-column samplers: numeric = inverse-transform from the histogram (clamped to
  [min,max]; INTEGER rounded to nullable `Int64`); categorical/boolean = draw from
  stored frequencies; datetime = uniform across [min,max]; free text = synthetic
  string of length drawn within [min_length, max_length]. Null mask per column.
- [x] **Task 2: CLI `generate`** (`src/tymi/cli/app.py`) — replace the stub with a
  real command: `--profile/-p` (existing file), `--rows/-n`, `--seed/-s`; load the
  Profile offline, generate, print CSV; `ProfileError` → exit 1.
- [x] **Task 3: Unit tests** (`tests/unit/test_marginals.py`) — numeric range/mean
  within tolerance, categorical labels ⊆ profile + frequency within tolerance,
  datetime within range, integer-valued output, null fraction reproduced, all-null
  column stays null, Schema preserved, determinism (same seed ==, different seed
  !=). Update `test_cli_smoke` stub probe (generate → chaos).
- [x] **Task 4: Integration test** (`tests/integration/test_generate_integration.py`)
  — PostgreSQL + MySQL: profile a real table, generate, assert marginal fidelity +
  determinism.

## Dev Notes

- `tymi.synth` is a driven adapter implementing the `Synthesizer` Port; it imports
  `tymi.domain` + pandas/numpy only (import-linter-clean; core/ports/domain never
  import it). The CLI calls the synthesizer directly for now (entry-point
  registration of faithful synthesizers can follow, mirroring how profiling is
  wired directly today).
- **Numeric = inverse-transform sampling from the stored histogram**: pick a bin
  with probability ∝ its count, then draw uniformly within the bin edges; clamp to
  the stored [min, max]; INTEGER columns round to a nullable `Int64`. This
  reproduces the Profile's histogram shape without any distributional assumption.
- **Categorical** draws from the stored top-K frequencies (renormalized). The
  profiler kept only the top-K, so tail categories below the cutoff are not
  reproduced — an honest, documented limitation of marginal-from-Profile.
- **Datetime** is reconstructed uniformly across [min, max] (always in range).
  Finer seasonality weighting (month/day-of-week frequencies the Profile already
  stores) is a later refinement; 2.1 reproduces the range marginal.
- **Free text** has no stored values (AD-6) — only length stats. Output is
  synthetic placeholder content whose length is drawn within [min_length,
  max_length]; content is not meaningful, only the length marginal is faithful.
- Determinism (AD-4/AD-11): every draw comes from the injected `rng`, in a fixed
  column order; no module-level randomness. Cross-column **correlation** is NOT
  preserved here — that is Story 2.2 (in-house Gaussian copula). 2.1 is marginals
  only; columns are independent.

### References

- [Source: epics.md#Epic-2 Story 2.1; FR-7 (Marginal Distribution Reproduction)]
- [Source: ARCHITECTURE-SPINE.md — AD-4/AD-11 (explicit RNG), AD-6 (no raw values),
  AD-8 (pipeline orchestration), AD-10 (canonical Dataset Schema)]
- [Source: ports/__init__.py — `Synthesizer` Protocol]
- [Source: 1-8-persistent-profile.md — offline Profile load feeds generation]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.synth.marginals` imports `tymi.domain` + pandas/numpy only).
- `uv run pytest tests/unit` → 128 unit passed (marginal shape/range, determinism,
  nulls, all-null, Schema preservation, BOOLEAN dtype, histogram-shape tracking,
  CLI offline generate + malformed/invalid-content handling).
- `uv run pytest -m integration -k generate` → 2 passed (real `postgres:16-alpine`
  + `mysql:8.4`): profile → generate → marginals match + same-seed determinism.

### Completion Notes List

- First faithful generation: `MarginalSynthesizer.generate(profile, rows, rng)`
  (satisfies the `Synthesizer` Port) reproduces each column's marginal — numeric
  via inverse-transform from the stored histogram (clamped to [min,max]; INTEGER →
  nullable `Int64`), categorical from stored frequencies, datetime uniform across
  the observed range, free text as length-faithful synthetic content.
- Deterministic (AD-4/AD-11): all draws from the injected `rng` in fixed column
  order; verified byte-identical output for the same seed, including a
  save→YAML→load round-tripped Profile. Correlation is NOT preserved (Story 2.2).
- AD-10 upheld: the produced Dataset carries the Profile's Schema unchanged.
- AD-6 upheld: only Profile aggregates are consumed; free text is regenerated,
  never reproduced.
- Real `tymi generate --profile p.yaml --rows N --seed S` loads a Profile offline
  (no DB) and prints CSV.
- **Full 3-layer `bmad-code-review` gate** (Blind Hunter + Edge Case Hunter +
  Acceptance Auditor). AC audit: 7/7 SATISFIED. Fixed 3 findings + strengthened a
  test (below). All 7 ACs satisfied; verified end-to-end on PostgreSQL and MySQL.

### File List

- `src/tymi/synth/marginals.py` (new — `MarginalSynthesizer` / `generate_marginals`)
- `src/tymi/cli/app.py` (modified — real `generate` command, generation wrapped)
- `tests/unit/test_marginals.py` (new)
- `tests/unit/test_cli_smoke.py` (modified — stub probe generate → chaos)
- `tests/integration/test_generate_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-02 | Implemented Story 2.1 — marginal distribution synthesis (`MarginalSynthesizer`/`generate_marginals`): numeric inverse-transform from the histogram, categorical from stored frequencies, datetime across range, length-faithful synthetic text; nulls reproduced; canonical Schema preserved (AD-10); deterministic (AD-4/AD-11); AD-6 upheld. Real `tymi generate --profile … --rows … --seed …` (offline CSV). 125 unit + real PG/MySQL generate integration tests pass. |
| 2026-07-02 | Full 3-layer `bmad-code-review` gate (Blind Hunter + Edge Case Hunter + Acceptance Auditor). AC audit: 7/7 SATISFIED. Fixed 3 (all convergent across reviewers): (1) BOOLEAN columns were emitted as `"True"/"False"` object strings — now reconstructed as a nullable `boolean` dtype matching the Schema (AD-10); (2) `generate` CLI crashed with a raw traceback on a loadable-but-invalid Profile (e.g. unparsable datetime bound) — now a clean exit-1 message; (3) datetime draws had no `[min,max]` clamp (float64 ns imprecision could round just past the bound) — now clamped like the numeric path. Strengthened the numeric test to assert per-bin histogram-shape tracking (not just mean). +3 tests → 128 unit. Dismissed (documented): uniform datetime seasonality (deferred by design), inf-only column → all-null, year > 2262 datetime overflow (unreachable from our writer). Status → done. |

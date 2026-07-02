---
baseline_commit: fafb5c0
---

# Story 2.2: Correlation preservation (in-house Gaussian copula)

Status: done

## Story

As a user,
I want generated columns to keep their correlations,
so that relationships between fields survive, not just individual columns.

## Acceptance Criteria

1. **Numeric correlation preserved** — given a Profile whose numeric correlation
   matrix (Spearman, Story 1.7) is non-trivial, generated numeric columns
   reproduce that correlation so the global divergence from the source stays
   within the default Tolerance.
2. **In-house Gaussian copula (AR-9)** — correlation is produced by an in-house
   Gaussian copula on numpy/scipy; no SDV/Copulas (BUSL-1.1) dependency.
3. **Marginals still faithful** — preserving correlation does NOT degrade the
   per-column marginals from Story 2.1; each column's marginal stays within
   Tolerance (the copula only re-couples the uniforms fed to the same
   inverse-transform).
4. **Deterministic (AD-4/AD-11)** — the copula draws all randomness from the
   injected `rng`; the same seed yields identical output.
5. **Graceful fallback** — a Profile with no correlations, or fewer than two
   numeric columns, generates exactly as Story 2.1 (independent marginals) with
   no crash; undefined coefficients (`None`) are treated as zero correlation.
6. **Canonical Schema + no raw values** — the produced Dataset still carries the
   Profile's Schema unchanged (AD-10) and consumes only Profile aggregates (AD-6).
7. **Verified end-to-end** — an integration test profiles a real PostgreSQL/MySQL
   table with correlated numeric columns, generates, and asserts the generated
   correlation matches the source within Tolerance.

## Tasks / Subtasks

- [x] **Task 1: Gaussian copula** (`src/tymi/synth/copula.py`) — pure numpy/scipy:
  `spearman_to_pearson` (`r = 2·sin(π·ρ/6)`), `nearest_psd` (eigenvalue clip +
  diagonal renormalization), `gaussian_copula_uniforms(corr, rows, *, rng)` →
  correlated uniforms in `[0, 1]` via Cholesky draw + `scipy.special.ndtr`.
- [x] **Task 2: Uniform-driven marginals** (`src/tymi/synth/marginals.py`) —
  refactor the numeric sampler to an exact piecewise-linear inverse-CDF of the
  histogram driven by a single supplied uniform (`numeric_from_uniform`), so the
  copula can inject correlated uniforms; keep the independent path identical in
  distribution. Expose the per-column builders for reuse.
- [x] **Task 3: Faithful synthesizer** (`src/tymi/synth/generator.py`) —
  `FaithfulSynthesizer.generate(profile, *, rows, rng)` (satisfies the
  `Synthesizer` Port): build correlated uniforms for the numeric block in the
  correlation matrix, thread them through the marginals, fall back to independent
  marginals for everything else. `generate_faithful(...)` module function.
- [x] **Task 4: CLI** (`src/tymi/cli/app.py`) — `generate` uses
  `generate_faithful` (transparent fallback when no correlations).
- [x] **Task 5: Unit tests** (`test_copula.py`, `test_generator.py`) — copula math
  (spearman→pearson, PSD repair, uniforms in range, determinism, `None`→0, k<2
  passthrough); correlation divergence within Tolerance; contrast vs independent
  marginals (≈0 → recovered); marginals still faithful; determinism; fallback.
- [x] **Task 6: Integration test** — PostgreSQL + MySQL: correlated numeric
  columns, profile → generate → assert generated correlation ≈ source.

## Dev Notes

- The Gaussian copula preserves correlation without disturbing marginals: Story
  2.1 samples each numeric column by pushing a uniform through the histogram's
  inverse-CDF. The copula replaces the *independent* uniforms with *correlated*
  ones `U = Φ(Z)`, `Z ~ N(0, R)`, and feeds the SAME inverse-CDF — so the marginal
  is unchanged while the rank correlation is imposed.
- **Spearman → latent Pearson**: for a Gaussian copula, `ρ_Spearman = (6/π)·
  arcsin(r/2)`, hence `r = 2·sin(π·ρ_Spearman/6)`. The Profile stores Spearman
  (Story 1.7), the copula-ready measure, so no re-estimation is needed.
- **PSD repair**: the element-wise sin transform can make the latent matrix
  non-PSD; `nearest_psd` clips negative eigenvalues to a small floor and
  renormalizes the diagonal to 1 before Cholesky.
- **Scope**: this story preserves **numeric** correlation (the copula's natural
  domain). Categorical cross-dependency is deferred to a follow-up (frequency-
  encode categoricals into the same copula — SDV's technique — needs a Spearman
  over the encoded columns; a scalar Cramér's V cannot drive a copula). Marginal
  categorical frequencies are still reproduced (Story 2.1).
- **AD-9**: scipy is a permissive (BSD) dependency, listed in the architecture
  stack; only `scipy.special.ndtr` (the standard-normal CDF Φ) is used. SDV and
  Copulas (BUSL-1.1) remain excluded.
- Determinism (AD-4/AD-11): the latent normal draw and every marginal draw come
  from the injected `rng` in a fixed order; column order follows the correlation
  matrix's `columns` tuple then the Schema.

### References

- [Source: epics.md#Epic-2 Story 2.2; FR-8 (Correlation Preservation)]
- [Source: ARCHITECTURE-SPINE.md — AD-4/AD-11 (RNG), AD-6, AD-9 (in-house copula on
  numpy/scipy; SDV/Copulas excluded), AD-10 (canonical Schema)]
- [Source: 1-7-correlation-detection.md — Spearman numeric matrix in the Profile]
- [Source: 2-1-marginal-distribution-synthesis.md — inverse-transform marginals]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.synth.copula`/`generator` import `tymi.domain` + numpy/scipy only).
- `uv run pytest tests/unit` → 151 unit passed (copula math, correlation within
  Tolerance, contrast vs independent marginals, sign preservation, marginals-still-
  faithful, determinism, fallback, `None`/`inf` handling). Verified warning-clean
  (`-W error::RuntimeWarning`).
- `uv run pytest -m integration -k "correlation or generate"` → PG + MySQL passed:
  profile → copula generate → source-vs-generated Spearman within Tolerance + sign +
  determinism. (Pre-existing, unrelated: `test_mssql_connectivity` fails only
  because `libodbc.so.2` is absent in this environment — not touched by this story.)

### Completion Notes List

- Correlation preservation via an in-house **Gaussian copula** (numpy + only
  `scipy.special.ndtr`): the Profile's Spearman matrix → latent Pearson
  (`r = 2·sin(π·ρ/6)`) → nearest-PSD repair → Cholesky draw from the injected `rng`
  → `Φ(Z)` correlated uniforms, threaded through the SAME marginal inverse-CDF as
  Story 2.1, so marginals are unchanged while rank correlation is imposed.
- Refactored the numeric marginal sampler to an exact piecewise-linear inverse-CDF
  driven by a single uniform (`numeric_from_uniform`), enabling the copula to inject
  correlated uniforms; the 128 Story-2.1 tests stay green under the refactor.
- Scope: **numeric** correlation preserved (copula's natural domain); categorical
  cross-dependency deferred to a follow-up (frequency-encode into the same copula —
  SDV's technique — since a scalar Cramér's V cannot drive a copula). Categorical
  marginals remain reproduced.
- Deterministic (AD-4/AD-11), canonical Schema preserved (AD-10), AD-6 upheld,
  SDV/Copulas (BUSL-1.1) excluded (AD-9); scipy added as a permissive (BSD) dep.
- **Full 3-layer `bmad-code-review` gate** (Blind Hunter + Edge Case Hunter +
  Acceptance Auditor). AC audit: 7/7 SATISFIED; all three confirmed the copula math
  (Spearman→Pearson, PSD repair via congruence, Cholesky orientation, the
  marginals-unchanged invariant from unit-diagonal R). Fixed 3 + strengthened tests
  (below). All 7 ACs satisfied; verified end-to-end on PostgreSQL and MySQL.

### File List

- `pyproject.toml` (modified — add `scipy>=1.11`)
- `src/tymi/synth/copula.py` (new)
- `src/tymi/synth/marginals.py` (modified — uniform-driven numeric sampler)
- `src/tymi/synth/generator.py` (new)
- `src/tymi/cli/app.py` (modified — `generate` uses the faithful synthesizer)
- `tests/unit/test_copula.py` (new)
- `tests/unit/test_generator.py` (new)
- `tests/integration/test_generate_correlation_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-02 | Implemented Story 2.2 — correlation preservation via an in-house Gaussian copula (`copula.py`: Spearman→Pearson, nearest-PSD, `ndtr`-based correlated uniforms; `generator.py`: `FaithfulSynthesizer`/`generate_faithful`). Refactored the numeric marginal sampler to a uniform-driven inverse-CDF so the copula re-couples uniforms without disturbing marginals. Added `scipy>=1.11` (BSD; AD-9). `generate` CLI now preserves correlations. 148 unit + real PG/MySQL correlation integration pass. |
| 2026-07-02 | Full 3-layer `bmad-code-review` gate (Blind Hunter + Edge Case Hunter + Acceptance Auditor). AC audit: 7/7 SATISFIED; core copula math independently confirmed correct by all three. Fixed 3: (1) `gaussian_copula_uniforms` cleaned only NaN, so a non-finite (`inf`) coefficient from a corrupted profile silently poisoned a column with NaNs — now `isfinite`-guarded + clamped to `[-1, 1]`; (2) `rows == 0` now short-circuits before the Cholesky factorization; (3) the inverse-CDF div-by-zero on an empty top bin no longer emits a RuntimeWarning (masked division). Strengthened tests: different-seed→different output, `None` coefficients driven end-to-end through `generate_faithful`, and a genuinely moderate (ρ≈0.5) correlation case exercising the transform/PSD path. +5 tests → 151 unit. Dismissed (documented): theoretical Cholesky failure (matrix is PD after repair; 0/20k random trials), Tolerance-as-module-constant (Config wiring deferred). Status → done. |

---
baseline_commit: edc0a4f
---

# Story 2.5: Leakage gate over declared sensitive columns

Status: done

## Story

As a user,
I want a pre-export gate that blocks any real sensitive value from leaking,
so that faithful output is provably safe.

## Acceptance Criteria

1. **Sensitive columns are declared in the Config** — `source.sensitive_columns`
   lists column names to protect; a `tymi profile --sensitive COL` flag overrides
   it for ad-hoc runs. A declared column absent from the source table fails loudly
   with a typed error (never silently ignored).
2. **The Profile carries a hashed membership set (AD-7), never raw values (AD-6)** —
   at profile time (source connected) each declared sensitive column's distinct
   real values are stored **only** as keyed one-way digests (BLAKE2b + a
   per-Profile salt) in a `LeakageGuard`, and the column's ordinary
   value-bearing stats are **suppressed**: a sensitive free-text `STRING` keeps
   length stats only (its real content is never materialized), and every other
   sensitive type (numeric/datetime/categorical/boolean) keeps counts only — so no
   category label and no numeric/datetime **min/max order statistic** (which are
   themselves two real row values) is ever written to the Profile artifact. The
   saved Profile round-trips the guard.
3. **Every emitted value is checked and regenerated on collision (AR-7)** — the
   leakage gate hashes every value of a sensitive column in the generated Dataset
   with the guard's salt and, on membership in the hashed set, regenerates just the
   colliding cells from the same sampler, repeating until the column is collision-
   free. Non-colliding cells and non-sensitive columns are untouched.
4. **The run fails closed if a collision cannot be resolved** — if regeneration
   still collides after a bounded number of attempts, the gate raises a typed
   `LeakageError` (CLI exit 1) rather than emitting a leaked value. No branch
   reaches output ungated.
5. **The gate is a core stage, independent of the CLI/UI (AD-7/AD-8)** — it runs
   inside faithful generation (`generate_faithful`) as the terminal step, so any
   caller (CLI, library, future UI) is gated identically. Absent sensitive columns
   the guard is `None` and the gate is a no-op (output byte-identical to pre-2.5).
6. **Deterministic (AD-4/AD-11)** — regeneration draws all randomness from the
   injected `rng`; the same seed + Profile yields identical output. AD-6/AD-10 hold
   (only hashed aggregates persisted; canonical Schema preserved). The salt is a
   security nonce generated once at profile time (deliberately outside the pipeline
   `rng`); gate determinism holds because the salt is fixed inside the Profile.

## Tasks / Subtasks

- [ ] **Task 1: Guard artifact + digest** (`src/tymi/domain/artifacts.py`) —
  `LeakageGuard(salt, algorithm, columns: dict[str, tuple[str, ...]])` frozen
  dataclass; `Profile.leakage_guard: LeakageGuard | None`; a pure
  `leakage_digest(value, salt) -> str` (keyed BLAKE2b, stdlib only, no adapter
  import so it stays in `domain`).
- [ ] **Task 2: Typed error** (`src/tymi/core/errors.py`) — `LeakageError(TymiError)`
  for the fail-closed path.
- [ ] **Task 3: Config surface** (`src/tymi/config/models.py`) —
  `SourceConfig.sensitive_columns: list[str]`.
- [ ] **Task 4: Build the guard at profile time** (`src/tymi/profiling/`) —
  `build_leakage_guard(dataset, sensitive_columns, *, salt) -> LeakageGuard | None`;
  `profile_dataset(..., sensitive_columns=(), salt=None)` validates each declared
  column exists (`ConfigError` otherwise), generates a salt when absent, and
  attaches the guard.
- [ ] **Task 5: Round-trip the guard** (`src/tymi/profiling/profile_io.py`) —
  serialize (already via `asdict`) + rebuild the guard on load so
  `load_profile(save_profile(p)) == p`.
- [ ] **Task 6: The gate + resampler** (`src/tymi/synth/leakage.py`,
  `generator.py`, `marginals.py`) — `enforce_leakage_gate(dataset, guard, *, rng,
  resample, max_attempts)`; a `resample(name, n, rng)` that mirrors how the column
  was generated (conditioned marginal → Faker formatted → plain marginal, via a
  public `resample_column`); wire the gate as the terminal step of
  `generate_faithful` (guard `None` → no-op).
- [ ] **Task 7: CLI** (`src/tymi/cli/app.py`) — `tymi profile --sensitive`
  (repeatable, merges with `config.source.sensitive_columns`); `LeakageError` →
  exit 1 on `tymi generate`.
- [ ] **Task 8: Unit tests** — guard build/no-raw-values, digest determinism,
  profile round-trip with guard, gate regenerates on collision, fail-closed on an
  unresolvable collision, no-op when guard absent, determinism, conditioned +
  sensitive interaction, unknown sensitive column raises, CLI `--sensitive`.
- [ ] **Task 9: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Why a hashed set, and its honest privacy scope.** AD-7 mandates an exact
  membership check against a *hashed* set of the source's real values. Keyed
  BLAKE2b with a per-Profile salt keeps raw values out of the Profile (AD-6) and
  defeats generic/precomputed rainbow tables. It is **not** an unbreakable privacy
  guarantee: an attacker holding the Profile file has both salt and digests and can
  brute-force low-entropy values (a dictionary of emails/SSNs). This is a
  leakage-**detection** mechanism that provably keeps the emitted dataset free of
  the exact real values it was built from — consistent with NFR-1's "exact
  membership check, not sampling" — while materially reducing (not eliminating) the
  re-identifiability of the stored set versus persisting raw values. The residual
  risk is documented, not hidden (per the PRD reviewer's caution against
  overclaiming zero-leakage).
- **Enforcement by regeneration, fail-closed.** On collision the gate re-draws only
  the colliding cells from the same sampler and re-checks, up to `max_attempts`;
  an unresolvable collision (e.g. a column whose entire faithful value space is
  real sensitive values, or a condition pinning a column to a real value) raises
  `LeakageError` rather than leaking. Fail-closed satisfies "no branch reaches
  Export ungated".
- **Determinism.** The gate draws from the injected `rng` only when it must
  regenerate; with no collisions it draws nothing, so pre-2.5 outputs are
  unchanged and existing tests still pass. The salt is a one-time security nonce
  (`secrets`), deliberately *not* from the pipeline `rng` — it must vary run-to-run
  to be a useful salt — and does not affect gate determinism because it is frozen
  into the Profile the gate reads.
- **Resampling mirrors generation.** A sensitive column that is *conditioned*
  (Story 2.4) resamples under its condition (so an `Equals` to a real value fails
  closed, a range/set draws a fresh in-restriction value); a formatted STRING
  sensitive column (email/name/uuid) resamples via Faker; everything else
  resamples from its marginal. Nulls never collide (only non-null distinct values
  are hashed), so conditioned/no-null invariants are preserved.
- **Sensitive non-STRING columns generate as typed NULL in MVP.** Because a
  faithful numeric/datetime/categorical distribution can only be reproduced from
  representations that embed real values (histogram min/max, category labels), and
  those are suppressed, a sensitive column of those types is emitted as a null
  column. Only free-text `STRING` sensitive columns get a usable synthetic value
  (Faker for email/name/uuid, else length-faithful text). Rich typed PII synthesis
  (numeric perturbation, format-preserving generation) is deferred to Epic 4. This
  is the privacy-first default; the leakage gate still guarantees zero real values
  for every type regardless.
- **Scope.** Faithful branch only (the chaos branch's reject-on-collision variant
  travels with Epic 3). The gate lives in `synth` (invoked by `generate_faithful`);
  wiring it into a full multi-table orchestrator and the chaos branch is later.
  Auto-classification of sensitive columns is Story 4.1 — this story consumes the
  Config-declared set.

### References

- [Source: epics.md#Epic-2 Story 2.5; AR-7, FR-9; NFR-1]
- [Source: ARCHITECTURE-SPINE.md — AD-6, AD-7 (exact-membership leakage gate),
  AD-8 (core stage), AD-4/AD-11 (RNG), AD-10 (canonical Schema)]
- [Source: prd.md — NFR-1 (exact membership check, not sampling); SM-2]
- [Source: 2-4-conditional-seeded-generation.md — generate_faithful, resampling]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.synth.leakage`/`tymi.domain.leakage_digest` respect hexagonal layering —
  the digest is stdlib-only so it stays in `domain`).
- `uv run pytest tests/unit` → 234 unit passed (24 in `test_leakage.py`).
- Leak-closure sweep: sensitive INTEGER-with-nulls (float64 source) over 60 seeds →
  **0** runs leak (down from 50/60 pre-fix); Profile artifact contains no raw value.

### Completion Notes List

- Conditional leakage gate by **regeneration, fail-closed** (AD-7): at profile time
  each sensitive column's distinct real values are hashed (keyed BLAKE2b + per-Profile
  salt) into a `LeakageGuard` on the Profile, and the column's value-bearing stats are
  suppressed (STRING → length stats; other types → counts only) so no raw value is
  persisted. `generate_faithful` runs `enforce_leakage_gate` as its terminal core
  stage: every generated sensitive value is hashed and, on membership, its cell is
  regenerated from the same sampler until clean, or `LeakageError` is raised after
  `DEFAULT_MAX_ATTEMPTS`. AD-4/AD-11 (gate draws from the injected rng only on a
  collision), AD-6, AD-10 hold.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 2
  HIGH (all three reviewers converged): (a) a **false-negative leak** — profile-time
  hashing used `Series.astype(str)` while the gate used `str(scalar)`, so a sensitive
  INTEGER column (loaded as float64 when it has nulls) hashed `"1002.0"` at profile
  time but `"1002"` at gate time → real values slipped through (verified 50/60 seeds
  leaking); (b) sensitive **numeric/datetime** columns wrote real `min`/`max` order
  statistics into the Profile. Both are closed by the same design change — value-bearing
  stats are suppressed for sensitive columns, so numeric/datetime sensitive columns are
  never generated (no undetected collision) and never persist boundary values; the
  builder now hashes raw values (symmetric with the gate) as defense-in-depth. Fixed 2
  MEDIUM: the resampler reinjected nulls, letting a saturated value space "resolve" a
  collision by nulling the cell instead of failing closed (now `inject_nulls=False`);
  a sensitive BOOLEAN/CATEGORICAL column emitted random text (AD-10) — now suppressed to
  a typed null column. Fixed 1 LOW: `--load` + `--sensitive` is now rejected. Closed
  test-evidence gaps: CLI `--sensitive` merge + unknown-column exit-1, a **non-vacuous**
  regenerate-to-success test (single-letter partial-collision proves the gate acted),
  gate-regeneration determinism, and the AC-2 no-raw-value assertion across
  numeric/datetime/categorical/boolean. +24 tests. All 6 ACs satisfied.

### File List

- `src/tymi/domain/artifacts.py` (modified — `LeakageGuard`, `leakage_digest`,
  `Profile.leakage_guard`)
- `src/tymi/core/errors.py` (modified — `LeakageError`)
- `src/tymi/config/models.py` (modified — `SourceConfig.sensitive_columns`)
- `src/tymi/profiling/profiler.py` (modified — `build_leakage_guard`, sensitive
  suppression, salt)
- `src/tymi/profiling/profile_io.py` (modified — guard round-trip)
- `src/tymi/synth/leakage.py` (new — `enforce_leakage_gate`)
- `src/tymi/synth/generator.py` (modified — gate wiring + `_make_resampler`)
- `src/tymi/synth/marginals.py` (modified — `resample_column`, `inject_nulls`)
- `src/tymi/cli/app.py` (modified — `profile --sensitive`, `generate` LeakageError)
- `tests/unit/test_leakage.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-03 | Implemented Story 2.5 — leakage gate over Config-declared sensitive columns. New `LeakageGuard` (keyed BLAKE2b hashed membership set) on the Profile; `enforce_leakage_gate` regenerates colliding generated values and fails closed with `LeakageError`; sensitive columns suppress value-bearing stats; `tymi profile --sensitive` + `tymi generate` gated. |
| 2026-07-03 | Full 3-layer `bmad-code-review` gate (Blind + Edge Case + Acceptance). Fixed 2 HIGH (false-negative INTEGER leak from asymmetric stringification; numeric/datetime min/max persisted in the Profile — both closed by suppressing sensitive value-bearing stats + symmetric hashing), 2 MEDIUM (resampler null-reinjection masking fail-closed → `inject_nulls=False`; sensitive BOOLEAN/CATEGORICAL emitting random text → typed null), 1 LOW (`--load` + `--sensitive` rejected). Closed CLI/e2e/determinism/AC-2 test gaps. +24 tests → 234 unit. All 6 ACs satisfied. Status → done. |

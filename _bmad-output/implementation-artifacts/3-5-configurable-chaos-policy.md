---
baseline_commit: 7c4e5ff
---

# Story 3.5: Configurable Chaos Policy

Status: done

## Story

As a user,
I want to declare corruption rate, targeting, and output mode,
so that I control exactly how chaotic the dataset is.

## Acceptance Criteria

1. **Declarative Chaos Policy in the Config** — `ChaosConfig` carries `mode`
   (`mixed` | `fully_chaotic`), `rate`, and an ordered `mutators` chain of
   `MutatorSpec{name, params}`; it loads via the standard Config loader and is fully
   declarative (no code).
2. **`tymi chaos --profile profile.yaml --config config.yaml`** — generates faithful
   data from the Profile (offline), applies the policy, and emits the chaotic data as
   CSV; `--manifest` writes the auditable fault manifest, `--out` writes the data.
3. **Mixed mode ≈ rate (±2 pp)** — in `mixed` mode exactly `round(rate·n)` rows are
   corrupted and the rest stay faithful, so the realised fraction of corrupted rows
   matches the configured `rate` within the default ±2 pp acceptance margin.
4. **Fully-Chaotic + FKs needs confirmation** — `fully_chaotic` corrupts the whole
   table; over a table whose Schema has foreign keys it raises `ChaosError` unless
   confirmed (`--confirm`), because it breaks referential integrity by design.
5. **Resolution + params (AD-3/AD-5)** — the chain is resolved from the
   `tymi.mutators` entry points; each `MutatorSpec.params` is validated and passed to
   its mutator; an unknown mutator or invalid params raises a typed `ChaosError`.
6. **Deterministic (AD-4/AD-11)** — the same seed + policy yields identical chaotic
   output + manifest. Structural (schema-changing) mutators are rejected in `mixed`
   mode (a per-row schema change is meaningless) and allowed in `fully_chaotic`.

## Tasks / Subtasks

- [ ] **Task 1: Config** (`src/tymi/config/models.py`) — `MutatorSpec` + evolve
  `ChaosConfig` to `mode` / `rate` / `mutators: list[MutatorSpec]`.
- [ ] **Task 2: Policy engine** (`src/tymi/chaos/policy.py`) — `resolve_policy`
  (build the chain with params) + `apply_policy` (mixed sub-frame + merge-back;
  fully-chaotic + FK confirmation; structural-in-mixed guard).
- [ ] **Task 3: CLI** (`src/tymi/cli/app.py`) — `tymi chaos` (generate → apply policy
  → CSV + optional manifest); remove the `chaos` stub.
- [ ] **Task 4: Unit tests** — mixed-mode ±2 pp across rates, faithful rows preserved,
  structural rejected; fully-chaotic FK confirmation (block + run); resolution +
  params + errors; determinism; mode validation; CLI end-to-end (mixed + FK-confirm).
- [ ] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **`rate` is the single density knob; per-mutator `proportion` is overridden to 1.0.**
  `rate`/`mode` govern *how much* is corrupted; the mutator params govern *how* (columns,
  magnitude, size, field name). A `proportion` set inside a `MutatorSpec` is superseded
  by the policy (documented; a test pins it).
- **Mixed mode corrupts the whole table, then keeps a `rate` fraction of the corrupted
  rows.** Selecting `round(rate·n)` rows *blindly* would drift below `rate` whenever a
  targeted column is null (cell mutators only touch non-null cells), so instead the
  chain runs at full intensity over the whole table and exactly `round(rate·n)` of the
  rows that were **actually** corrupted are kept — the rest are reverted to faithful.
  This hits `rate` within the ±2 pp margin even on heavily-null columns. A column is
  degraded to `object` only when a fault requires it (a numeric outlier keeps its
  numeric dtype), and the manifest lists only the kept rows.
- **Mixed mode is row-scoped; structural faults are not.** A per-row schema change
  (drop/rename/retype a column for *some* rows) is incoherent, so `missing_field`,
  `extra_field`, `renamed_column`, `changed_type` (tagged `structural = True`) are
  rejected in mixed mode and belong to `fully_chaotic`. Row-level faults (outliers,
  format/type, `duplicate_keys`, `orphan_fk`) run in either mode.
- **Merge-back keeps faithful rows byte-identical.** The chain runs on a sub-frame of
  the selected rows; only the *touched* columns are cast to `object` and written back
  at the selected positions, and manifest rows are remapped sub-position → full
  position, so unselected rows are untouched and every manifest entry points at the
  real corrupted cell.
- **FK confirmation is reachable end-to-end.** A Profile built from an introspected
  table carries its `foreign_keys` (round-tripped through save/load), so the generated
  Dataset's Schema has them and `tymi chaos --config <fully_chaotic>` trips the
  confirm gate without `--confirm`.
- **Scope.** The bidirectional manifest audit + Evaluate `chaos` run_mode is Story 3.6.

### References

- [Source: epics.md#Epic-3 Story 3.5; FR-11, FR-16; chaos acceptance margin ±2 pp]
- [Source: ARCHITECTURE-SPINE.md — AD-3, AD-4/AD-11, AD-5, AD-8]
- [Source: 3-1-pluggable-mutator-engine.md — `apply_chaos`, `ChaosConfig.mutators`]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All tests run **inside the devcontainer**: `uv run ruff check .` / `uv run
  lint-imports` → clean; `uv run pytest tests/unit` → 399 passed.

### Completion Notes List

- Declarative Chaos Policy (`ChaosConfig.mode/rate/mutators`) + `chaos/policy.py`
  (`resolve_policy`, `apply_policy`) + `tymi chaos` CLI; removed the `chaos` stub.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 1
  HIGH: mixed mode selected `round(rate·n)` rows **blindly**, but cell mutators only
  touch non-null cells, so on a null-bearing target column the realised corrupted
  fraction drifted well below `rate` (0.055 vs 0.10 at 50% null — outside the ±2 pp
  AC) — rewritten to corrupt the whole table then **keep exactly `round(rate·n)` of the
  rows that were actually corrupted** (revert the rest), which hits `rate` even with
  nulls. Fixed 1 MEDIUM: the merge-back cast every touched column to `object`,
  degrading a numeric outlier column — now object only when the fault requires it (a
  numeric outlier keeps `float64`). Fixed a silent no-op on a positive `rate` over a
  tiny frame (floor to ≥1 corrupted row). Verified clean by all three reviewers:
  manifest↔frame consistency, faithful rows byte-identical, FK confirm gate reachable
  end-to-end via the CLI, determinism. The silent `proportion→1.0` override is
  documented + test-pinned. +3 tests → 399 unit. All ACs satisfied.

### File List

- `src/tymi/config/models.py` (modified — `MutatorSpec`, `ChaosConfig` mode/rate/chain)
- `src/tymi/chaos/policy.py` (new — `resolve_policy`, `apply_policy`)
- `src/tymi/chaos/mutators/schema_break.py` (modified — `structural = True` tags)
- `src/tymi/cli/app.py` (modified — `tymi chaos`; removed the `chaos` stub)
- `tests/unit/test_chaos_policy.py` (new)
- `tests/unit/test_chaos_engine.py` / `test_cli_smoke.py` (modified — MutatorSpec, stub)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.5 — declarative Chaos Policy (`mixed`/`fully_chaotic`, rate, mutator chain with params) + `tymi chaos` CLI. Mixed mode corrupts a `rate` fraction of rows; fully-chaotic over a FK table requires `--confirm`. `MutatorSpec` replaces the bare mutator-name list. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Fixed HIGH mixed-mode fraction drift on null-bearing target columns (corrupt-whole-then-keep-`rate`-of-corrupted-rows instead of blind selection); fixed the merge-back degrading a numeric column to `object`; floored `k` so a positive rate never silently no-ops. Documented + pinned the `proportion→1.0` override. 399 unit. All ACs satisfied. Status → done. |

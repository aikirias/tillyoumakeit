---
baseline_commit: 6997d33
---

# Story 5.4: Chaos Policy Configuration and Preview

Status: done

## Story

As a user,
I want to configure a Chaos Policy and preview corrupted rows,
so that I can see exactly what will be injected.

## Acceptance Criteria

1. **Configure + preview** — given a Profile, setting rate / targeting (mutators) / mode
   and clicking "Preview" generates a faithful baseline, applies the Chaos Policy
   in-process, and renders a sample.
2. **Chaotic cells highlighted** — the previewed sample highlights the rows/cells that
   were actually corrupted (from the Fault Manifest), so the user sees exactly what the
   policy injected.
3. **Fully-Chaotic + FKs needs explicit confirmation** — selecting `fully_chaotic` mode
   over a table with foreign keys requires an explicit confirmation in the UI; without it
   the preview refuses (mirrors the CLI `--confirm` gate, Story 3.5).
4. **Policy written to the shared Config** — mode/rate/mutators land on `Config.chaos`
   (the same `ChaosConfig` the CLI reads, AD-5/AD-8).
5. **No profile → guidance** — with no Profile yet, the page directs the user to the
   Profile step (no crash).

## Tasks / Subtasks

- [x] **Task 1: Services** (`src/tymi/ui/services.py`) — `available_mutators`,
  `requires_confirmation`, `set_chaos` (re-validated write), `run_chaos_preview`
  (baseline `generate_faithful` → `apply_policy`), `fault_locations` + `fault_style_frame`
  (manifest → highlighted cells).
- [x] **Task 2: App page** (`src/tymi/ui/app.py`) — `render_chaos`: mode/rate/mutators/
  confirm form (stable keys), preview, highlighted sample + fault count; write back.
- [x] **Task 3: Tests** — preview corrupts + returns a manifest (deterministic);
  `fault_locations`/`fault_style_frame` match the manifest; `requires_confirmation` +
  FK-confirmation refuse **and** allow (service + UI flow); re-preview honors a changed
  selection; `set_chaos` persists + YAML round-trips; `AppTest` (preview + write-back +
  mode pre-fill); no-profile guidance.
- [x] **Task 4: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Same chaos path as the CLI (AD-8).** `run_chaos_preview` generates the faithful
  baseline with `generate_faithful` and applies `apply_policy(baseline, ChaosConfig,
  rng=make_rng(seed), confirmed=)` — the identical pipeline the CLI `chaos` command runs,
  so the preview is the real chaotic output + its Fault Manifest, reproducible for a given
  (Profile, seed, policy).
- **Highlighting from the Manifest (bidirectional contract, Story 3.6).** The corrupted
  cells shown are exactly the Manifest's `(row, column)` entries — the same auditable
  record the CLI emits — so the highlight can't drift from what was actually injected.
- **FK confirmation gate.** `fully_chaotic` over a table with foreign keys breaks
  referential integrity by design; the UI shows a confirmation checkbox (surfaced by
  `requires_confirmation`) and `run_chaos_preview` refuses without it, mirroring the CLI
  `--confirm`. Structural mutators in `mixed` mode are rejected by `apply_policy` and the
  error is surfaced cleanly.
- **Scope.** Policy config + highlighted preview. Exporting the chaotic data and the Fault
  Manifest view live in Story 5.5; per-mutator parameter editing (targeting specific
  columns / proportions) is a follow-up — the UI selects mutators by name with their
  validated defaults.

### References

- [Source: epics.md#Epic-5 Story 5.4; FR-22]
- [Source: ARCHITECTURE-SPINE.md — AD-3/AD-5/AD-8; policy.apply_policy; ChaosConfig]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_ui_chaos.py -q` → 14 passed.
- `uv run pytest -q` → 531 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added the chaos services + `render_chaos` page. Preview uses the identical
  `generate_faithful` + `apply_policy` path (single threaded rng) as the CLI `chaos`
  command (AD-8, deterministic AD-4); corrupted cells are highlighted from the Fault
  Manifest via the pure, tested `fault_style_frame`.
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). Findings
  applied:
  - **HIGH (Edge)** — a re-preview with a changed mutator selection or rate silently
    re-ran the *previous* policy: the config-derived widget defaults reset the un-keyed
    widgets on rerun. Fixed with stable `key=` on every config-derived widget (the initial
    value seeds the first render, edits then persist) — applied to `render_chaos` **and**
    the same latent pattern in `render_generate`; a regression test drives a changed
    re-preview.
  - **Acceptance (AC-3)** — added the affirmative FK test (`fully_chaotic` + FK +
    `confirmed=True` proceeds) and an AppTest exercising the mode selectbox + confirm
    checkbox UI flow (refuse without the tick, proceed with it).
  - **Acceptance (AC-2)** — extracted the highlight mapping into `fault_style_frame` (pure,
    tested) instead of an untestable in-view closure.
  - **LOW (Blind)** — the mode selectbox now pre-fills from the saved policy (parity with
    `render_generate`'s pre-fill).
- Accepted (documented): `rate=0.0` still injects one fault row — a pre-existing Story 3.5
  `apply_policy` floor (`if k == 0: k = 1`); the UI shows the fault count honestly.

### File List

- `src/tymi/ui/services.py` (modified) — `available_mutators`, `requires_confirmation`,
  `set_chaos`, `run_chaos_preview`, `fault_locations`, `fault_style_frame`, `FAULT_STYLE`.
- `src/tymi/ui/app.py` (modified) — `render_chaos` page; stable widget keys on the chaos
  and generate forms.
- `tests/unit/test_ui_chaos.py` (new) — 14 tests.
- `tests/unit/test_ui_shell.py` (modified) — placeholder-step tests updated (Chaos is now
  a real page).

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 5.4 — chaos policy config + preview. |
| 2026-07-04 | Implemented chaos services + page; passed the 3-layer gate (re-preview widget-key fix, FK confirmation flow, tested highlight). Status → done. |

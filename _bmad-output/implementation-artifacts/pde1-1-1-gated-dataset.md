---
baseline_commit: 5afc610
---

# Story 1.1 (PRD 1, Epic 1): The GatedDataset load boundary

Status: done

## Story

As a maintainer,
I want a `GatedDataset` type that can only be built by passing a `Dataset` through the leakage
gate, so that un-gated data can never reach a destination (a type error, not a discipline).

## Acceptance Criteria (AD-21)

1. The **only** way to obtain a `GatedDataset` is the gate producer — there is no public
   constructor from a raw `Dataset` (direct construction fails closed).
2. The leakage-gate producer returns a `GatedDataset`; a raw `Dataset` passed where a
   `GatedDataset` is required is rejected (the `load` boundary uses the type).
3. The `GatedDataset` preserves the canonical Schema (AD-10) and carries the gate result.
4. The wrapped data is provably free of real sensitive values (inherits the gate guarantee,
   AD-6/AD-7).

## Tasks

- [x] `GatedDataset` + `GateReport` in `tymi.domain.artifacts` — gate-only constructor (key
  validated at `__init__`, **not stored**, so `dataclasses.replace` can't forge; `eq=False`,
  custom sensitive-safe `__repr__`).
- [x] `require_gated(...)` boundary helper — accepts a `GatedDataset`, rejects a raw `Dataset`.
- [x] `gate_dataset(...)` in `tymi.synth.leakage` — runs `enforce_leakage_gate`, seals an
  **independent copy** into a `GatedDataset` (the sole producer). The per-table
  `enforce_leakage_gate` (embedded in `generate_faithful`) is unchanged.
- [x] Unit tests (10): producer yields a `GatedDataset`; direct + `replace`-forge fail;
  `require_gated` rejects a raw `Dataset`; Schema preserved + accurate `columns_checked`; seal
  independent of caller input; safe `==`/`hash`/`repr`; zero real values; determinism.
- [x] Full 3-layer `bmad-code-review` gate before done.

## Dev Notes

- **Why a new producer, not a changed signature.** `generate_faithful` returns
  `enforce_leakage_gate(...)` directly (a `Dataset`, used pervasively). Changing that ripples
  everywhere. Story 1.1 adds the provisioning-boundary producer `gate_dataset` that seals into a
  `GatedDataset`; the per-table embedded gate stays a `Dataset` stage. The Story 3.1 scan-and-
  reject mode will be a second producer of `GatedDataset`.
- **Unforgeable-enough constructor (AD-21).** Python can't truly hide a constructor; the barrier
  is a module-private `_GATE_KEY` sentinel that only `synth.leakage` holds — direct construction
  raises. Good enough to make un-gated data a type error in practice, not a fabricable object.

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_gated_dataset.py -q` → 10 passed.
- `uv run pytest -q` → 551 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added `GatedDataset` + `GateReport` + `require_gated` (domain) and `gate_dataset` (leakage) —
  strictly additive; `generate_faithful` / `enforce_leakage_gate` unchanged (no ripple).
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). Findings applied:
  - **HIGH (Blind)** — `dataclasses.replace()` forged an un-gated instance because the gate key
    was a stored field; redesigned so the key is validated at `__init__` and **never stored**
    (`init=False`, manual `__init__`) → `replace`/`copy`/`pickle` can't resurrect it. Regression
    test added.
  - **MED (Blind + Edge)** — the seal aliased the caller's mutable input frame (the no-op gate
    returns the same object); `gate_dataset` now seals an **independent deep copy**. Documented
    as a point-in-time seal.
  - **MED/LOW (all three)** — `GateReport` advertised a dead `regenerated_cells` (always 0) and a
    constant `passed`, and `columns_checked` listed declared-not-inspected columns; report
    trimmed to an **accurate `columns_checked`** (present-in-frame + non-empty guard).
  - **LOW (Edge)** — `==`/`hash(GatedDataset)` raised on the inner DataFrame, and `repr` dumped
    sensitive cell values; fixed with `eq=False` (identity) and a value-free `__repr__`.
- Deferred (by design): `require_gated` has no production call site yet — the provisioning
  `load` boundary is wired in Story 3.3; AD-21 is a type-establishment here, enforced there.

### File List

- `src/tymi/domain/artifacts.py` (modified) — `GatedDataset`, `GateReport`, `require_gated`,
  `_GATE_KEY`.
- `src/tymi/synth/leakage.py` (modified) — `gate_dataset`.
- `tests/unit/test_gated_dataset.py` (new) — 10 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 1.1 — GatedDataset load boundary. |
| 2026-07-05 | Implemented; passed the 3-layer gate (replace-forge fix, defensive-copy seal, honest report, safe eq/hash/repr). Status → done. |

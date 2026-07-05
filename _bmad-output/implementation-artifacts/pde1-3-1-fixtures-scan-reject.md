---
baseline_commit: 5326bea
---

# Story 3.1 (PRD 1, Epic 3): Pinned fixtures with scan-and-reject

Status: done

## Story

As a self-service provisioner, I want to pin exact login/test accounts that appear verbatim but
are still checked for real PII, so that people can log in without opening a PII bypass (PDE-8,
PDE-9, PDE-10; AD-17).

## Acceptance Criteria

1. Given a Spec fixture allow-list (in the reserved keyspace), fixtures are overlaid verbatim,
   FK-consistent, and exempt from regeneration (PDE-8/9).
2. The overlaid frame passes a scan-and-reject gate mode (leakage guard + PIIClassifier) that
   fails closed on a real value / PII, with no regeneration, before minting the `GatedDataset`
   (AD-17).
3. Adding a fixture records a logged attestation; generated rows never collide with fixture keys
   (PDE-10).

## Tasks

- [ ] `tymi/synth/fixtures.py` — `overlay_fixtures` (append verbatim fixture rows in the reserved
  block; validate keys-in-block, unknown columns, FK-consistency; log an attestation).
- [ ] `tymi/synth/leakage.py` — `scan_and_gate` (scan-and-reject seal: leakage collision scan +
  PII scan on fixture rows, **no regeneration**, fail closed, then mint the `GatedDataset`).
- [ ] `FixtureError(TymiError)`.
- [ ] Wire into `generate_from_spec`: shared keys → fixtures overlay → scan-and-gate (replaces the
  regenerating seal — fixtures must survive verbatim).
- [ ] Unit tests: overlay verbatim + reserved block + FK-consistency + fail-closed; scan rejects
  a real value / un-guarded PII, accepts a synthetic fixture; attestation logged; E2E via
  `generate_from_spec`.
- [ ] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **Scan-and-reject, not regenerate** (AD-17): the seal for the whole DB is now `scan_and_gate`,
  which never regenerates (a fixture is verbatim). Generated rows are already clean from the
  embedded per-table gate, so the collision scan is a no-op on them; it catches a real-valued
  fixture. The PII scan runs `classify_sensitive_columns` on the **fixture rows** and fails closed
  on PII in a column the guard does not cover (an un-guarded-PII smuggle). Guarded PII columns are
  handled by the collision scan (synthetic OK, real rejected).
- **Reserved block / no collision (PDE-10):** fixture keys must be in `[0, reserved_key_block)`;
  generated shared keys are at/above it (AD-16), so generated rows never collide with fixture keys.
- **FK-consistency:** a fixture FK must reference an existing (generated or fixture) parent key.
- **Attestation:** a logged record per fixture overlay (`tymi.provision.fixtures` logger).

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_fixtures.py -q` → 15 passed.
- `uv run pytest -q` → 613 passed; `uv run ruff check` + `uv run lint-imports` clean (2 contracts kept).

### Completion Notes List

- New `synth/fixtures.py` `overlay_fixtures` (append verbatim fixture rows in the reserved block;
  validate keys-in-block, unknown columns, PK-uniqueness, FK-consistency; log an attestation) and
  `synth/leakage.py` `scan_and_gate` (scan-and-reject seal, never regenerates). Wired into
  `generate_from_spec`: generate → shared keys → fixtures overlay → scan-and-gate. New
  `FixtureError`.
- Ran the full 3-layer gate (Blind + Acceptance; Edge interrupted). **Two HIGH bypasses found and
  fixed:**
  - **HIGH — real-value bypass via shared/key columns.** The seal used a guard *reduced* to
    non-key/non-shared columns (correct for synthetic generated keys), but fixtures are verbatim
    and could smuggle a real value through a shared/PK/FK column that was then unscanned. **Fix:**
    `scan_and_gate` now scans **fixture** rows against the **full** guard and only skips structural
    columns for **generated** rows (`structural_columns` param). Regression test.
  - **HIGH — minority-PII bypass.** The PII classifier ran at `min_match_rate=0.5`, so a single
    real-PII cell among ≥3 fixture rows escaped. **Fix:** run it at `min_match_rate = 1/n_fixtures`
    so any single PII cell trips it. Regression test.
  - **MED — non-integer PK fixture** raised a raw `TypeError`; now a clean `FixtureError`. Test.
  - **Acceptance — no post-overlay PK-uniqueness check** (collision guarantee leaned only on
    AD-16); added `_validate_fixture_pk_uniqueness` (fail closed if a fixture key duplicates a
    generated PK). Fixed the stale `whole_db` module docstring (said `gate_dataset`).
- **Accepted:** the un-guarded-PII scan is deliberately fail-closed and can over-reject synthetic
  PII in an un-guarded column — the Spec author must mark such columns sensitive (guard them). The
  legacy `gate_dataset` remains for the embedded per-table gate / its own tests but is no longer on
  the provisioning seal path (`scan_and_gate` is the sole whole-DB producer).

### File List

- `src/tymi/synth/fixtures.py` (new) — `overlay_fixtures` + validators + `_attest`.
- `src/tymi/synth/leakage.py` (modified) — `scan_and_gate`, `_reject_collisions`.
- `src/tymi/synth/whole_db.py` (modified) — fixtures overlay + scan-and-gate seal; `_structural_columns`.
- `src/tymi/core/errors.py` (modified) — `FixtureError`.
- `tests/unit/test_fixtures.py` (new) — 15 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Drafted Story 3.1 — pinned fixtures + scan-and-reject (AD-17). |
| 2026-07-05 | Implemented; passed the 3-layer gate (fixed 2 HIGH fixture bypasses + PK-uniqueness). Status → done. |

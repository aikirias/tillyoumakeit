---
baseline_commit: 9fc8fcf
---

# Story 3.3 (PRD 1, Epic 3): One-command `tymi provision --spec` with report

Status: done

## Story

As a self-service provisioner, I want a single command that provisions a whole obfuscated DB into
a non-prod destination, so that I can do it myself in minutes, runnable in CI/DAG (PDE-13, PDE-15;
AD-19). Closes Epic 3 and Phase 1.

## Acceptance Criteria

1. Given a Spec, `tymi provision --spec <spec>` runs a composition-adapter pipeline: load-Spec →
   generate (gate per-table) → substreams → shared keys → fixtures overlay + scan → `GatedDataset`
   → guardrail → `EngineAdapter.load` → report, callable identically by a CI job / DAG (AD-19,
   PDE-13).
2. Provisioning is idempotent (clean-replace; a failed run self-heals on re-run) (NFR-F).
3. The run emits a provisioning report: tables, row counts, fidelity, gate result, fixtures
   present, and the consistency-unit fingerprint (PDE-15).

## Tasks

- [x] `tymi/provision/pipeline.py` — `provision(spec, adapter, *, deny_list, deps)` +
  `ProvisionReport`/`TableProvisionReport` (`render()`).
- [x] `tymi provision --spec --engine --config` CLI command (calls the same `provision`).
- [x] Cross-check the runner's `--config` connection against the Spec's affirmed destination.
- [x] Unit tests: pipeline (happy path, guardrail-first fail-closed, read-only adapter, determinism,
  zero-real-values, fixtures in the report) + CLI (success, prod-spec, prod-connection, host
  mismatch, registered).
- [x] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **AD-19 identical entry points:** the CLI command and any CI/DAG in-process call both go through
  the one `provision` function; the guardrail lives *inside* the pipeline (runs first, fail-closed
  before any generation or write).
- **AD-21 at the load site:** each table is `require_gated`-checked before `EngineAdapter.load`, so
  only a `GatedDataset` ever reaches a destination.
- **Idempotency (NFR-F):** `EngineAdapter.load` uses `if_exists="replace"`, so a re-run overwrites
  (self-heals). Loads are per-table transactions, not one whole-DB transaction — a mid-run failure
  leaves partial state a re-run corrects; whole-DB atomicity is out of Phase-1 scope.
- **Report (PDE-15):** per-table rows, fixtures count, gated columns (gate result), and fidelity
  (scored on the faithful columns — shared-key columns are dropped since they intentionally
  diverge), plus the consistency-unit fingerprint (AD-15).

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_provision.py tests/unit/test_cli_provision.py -q` → 12 passed.
- `uv run pytest -q` → 637 passed; `uv run ruff check` + `uv run lint-imports` clean (2 contracts kept).

### Completion Notes List

- New `provision/pipeline.py` `provision` composes guardrail → `generate_from_spec` →
  `require_gated` → `adapter.load` → `fidelity_report` → `ProvisionReport(fingerprint,
  environment, tables)`. New `tymi provision` CLI command calling the same function. Layering:
  `tymi.provision` is forbidden for core/ports/domain (Story 3.2 contract) and composes synth +
  engines.
- Ran the full 3-layer gate. Findings applied:
  - **HIGH — guardrail-vs-connection divergence.** The pipeline guardrail affirms `spec.destination`,
    but the write goes to the `--config` connection, which could point at prod (a destructive
    `replace` on an unvalidated target). **Fix:** the CLI `_assert_connection_matches_destination`
    deny-lists the **real** connection host/database and requires them to equal the Spec's affirmed
    destination — fail closed on a prod connection or a host/database mismatch. Two regression tests.
  - **MED — `ProfileError` from embedded-profile reconstruction escaped the CLI error mapping.**
    **Fix:** added `ProfileError` to the provision command's caught runtime errors.
  - **MED — "no partial state" over-claimed.** Loads are per-table `replace`, not a whole-DB
    transaction. **Fix:** AC-2 + docstrings reworded honestly (idempotent per-table; a failed run
    self-heals on re-run; whole-DB atomicity out of Phase-1 scope).
  - **LOW — fidelity noise on shared-key columns.** Position-derived shared keys intentionally
    diverge, depressing the score. **Fix:** fidelity is scored on the frame with shared-key columns
    dropped.
- **Accepted / deferred:** whole-DB transactional atomicity (one transaction spanning all tables)
  is deferred — the external orchestrator retries a failed run, which self-heals via clean-replace.

### File List

- `src/tymi/provision/pipeline.py` (new) — `provision`, `ProvisionReport`, `TableProvisionReport`.
- `src/tymi/cli/app.py` (modified) — `provision` command + `_assert_connection_matches_destination`.
- `tests/unit/test_provision.py`, `tests/unit/test_cli_provision.py` (new) — 12 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Implemented Story 3.3 — provision pipeline + CLI + report (AD-19). Passed the 3-layer gate (fixed the guardrail/connection HIGH). Status → done. Closes Epic 3 and Phase 1. |

---
baseline_commit: edb8073
---

# Story 1.2 (PRD 1, Epic 1): Whole-DB Spec model and auto-bootstrap

Status: done

## Story

As a self-service provisioner, I want to introspect a whole database and get a first-cut
versioned Spec I can edit, so that I can describe an obfuscated dev environment without
hand-writing it (PDE-1, PDE-2, PDE-3; AD-14).

## Acceptance Criteria

1. Bootstrapping a Spec over a schema (all/declared tables) produces a versioned `Spec`
   (`schema_version`) carrying, per table, the **pinned Profile** (FK graph + stats +
   sensitive marks live in it), plus fixture/shared-key placeholders, seed, tolerance (AD-14).
2. The Spec **bundles the pinned Profile artifacts** — regeneration reads them, never a live
   source (AD-15 precondition).
3. The Spec loads/validates via Pydantic (`extra="forbid"`) and **round-trips through YAML**
   (the reconstructed Profiles equal the originals); an unknown major version is rejected.

## Tasks

- [x] `profile_to_dict` / `profile_from_dict` public helpers in `profiling.profile_io`
  (`load_profile` refactored to reuse them).
- [x] `tymi/config/spec.py` — `Spec` + `TableSpec` (Pydantic, `extra="forbid"`, semver),
  `bootstrap_spec`, `spec_profiles`, `save_spec`/`load_spec`, `bootstrap_from_source`.
- [x] Unit tests (9): bootstrap; FK-bearing YAML round-trip (Profile + scalars); `extra="forbid"`
  + major-version gating; `bootstrap_from_source` via a fake adapter + seed-reproducibility;
  tolerance bounds; save-error wrapping.
- [x] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **Profiles bundled as plain dicts.** Each `TableSpec.profile` is the Profile's plain-dict form
  (reusing `profile_to_json`/`_profile_from_dict`), so the Spec is one YAML with the pinned
  Profiles embedded — no external file/live-source reference (AC-2). The FK graph + sensitive
  marks are already in the Profile.
- **Introspection scope.** `bootstrap_from_source` takes an explicit table list (the port has no
  `list_tables`; PRD 1 scopes that out) and samples+profiles each via the shipped
  `profile_dataset`. Injectable adapter → testable with no DB.
- **Fixtures / shared-keys are placeholders here** — filled by Story 3.1 / 2.2.

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_spec.py -q` → 9 passed.
- `uv run pytest -q` → 560 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added `Spec`/`TableSpec` + bootstrap/round-trip in `config/spec.py`; public
  `profile_to_dict`/`profile_from_dict` in `profile_io` (and refactored `load_profile` to reuse
  them — no behavior change, `test_profile_io.py` 17/17 pass).
- **Design note (AD-14 divergence, deliberate):** the Spec is a **standalone** Pydantic model,
  not an inheritance of `config.models.Config` (which is single-table). "Superset of Config" is
  read semantically — composition over inheritance, since the whole-DB per-table shape is
  genuinely different. Honest divergence from the spine's "extends Config" wording.
- Ran the full 3-layer gate (Blind + Edge + Acceptance). All 3 ACs met; Blind found no HIGH/MED
  (Profile round-trip fidelity incl. salt/FKs/Int64 verified clean). Findings applied:
  - **MED (Edge)** — `bootstrap_from_source(salt=None)` was non-reproducible (random salt per
    run → different Spec digests); now the salt is **derived from the seed** when unset, so the
    same source+seed yields an identical Spec (AD-15 offline reproducibility). Regression test.
  - **LOW (Edge)** — `save_spec` leaked a raw `FileNotFoundError`; now wrapped in `ConfigError`.
  - **Acceptance** — strengthened the round-trip test with an FK-bearing Profile + Spec-scalar
    asserts.
- Accepted (documented boundaries): `TableSpec.profile` is an open `dict` (extra="forbid" can't
  reach inside — junk is inert, ignored on reconstruct); `load_spec` validates structure, not
  embedded-Profile validity (that surfaces cleanly as `ProfileError` at `spec_profiles`).

### File List

- `src/tymi/config/spec.py` (new) — `Spec`, `TableSpec`, `bootstrap_spec`,
  `bootstrap_from_source`, `spec_profiles`, `save_spec`, `load_spec`.
- `src/tymi/profiling/profile_io.py` (modified) — public `profile_to_dict`/`profile_from_dict`;
  `load_profile` refactored to reuse them.
- `tests/unit/test_spec.py` (new) — 9 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Drafted Story 1.2 — whole-DB Spec model + auto-bootstrap. |
| 2026-07-05 | Implemented; passed the 3-layer gate (seed-reproducible bootstrap, wrapped save error, FK round-trip). Status → done. |

---
baseline_commit: 5a1c420
---

# Story 3.4: Schema and constraint breakage mutators

Status: done

## Story

As a user,
I want to break schema and constraints on purpose,
so that I can test my data contracts.

## Acceptance Criteria

1. **Structural breakages, each toggleable** — a mutator per breakage, registered
   under `tymi.mutators` (AD-3), toggled by chain membership: `missing_field` (drops a
   column from frame + Schema), `extra_field` (adds an undeclared column),
   `renamed_column` (renames a column), `changed_type` (changes a column's logical
   type in the Schema), `duplicate_keys` (duplicate values in a PK/unique column),
   `orphan_fk` (FK values pointing at no real parent).
2. **Each declared breakage materializes** — the resulting `Dataset` reflects the
   breakage in **both** the canonical `Schema` (columns/types/keys) and the frame, and
   every breakage is recorded in the `FaultManifest`.
3. **Targeting** — with no `columns`, each mutator picks a sensible default
   (`duplicate_keys` → PK/unique columns; `orphan_fk` → FK columns; the single-column
   structural faults → the first column); an explicit `columns` list targets exactly
   those; an unknown column raises a typed `ChaosError`.
4. **Schema ↔ frame stay consistent** — after a structural mutator the Schema's column
   set matches the frame's columns (a dropped/renamed/added column changes both), so
   downstream stages still receive a coherent `Dataset` (the *contract* is what's
   broken, not the artifact's internal consistency).
5. **Deterministic (AD-4/AD-11)** — row/value choices draw from the injected `rng`;
   same seed + params → identical Dataset + manifest. Parameterized via Pydantic
   (AD-5); no-arg construction works; runs through the Story 3.1 engine.
6. **Scope** — check-constraint violations beyond PK/unique/FK are **deferred**: the
   canonical `Schema` carries no check-constraint metadata (MVP), and value-level
   constraint breaks are already covered by the out-of-distribution (3.2) and
   format/type (3.3) families; documented, not silently dropped.

## Tasks / Subtasks

- [ ] **Task 1: Structural mutators** (`src/tymi/chaos/mutators/schema_break.py`) —
  the six mutators, each returning a new `Dataset` (mutated Schema + frame) +
  manifest; a small shared params model.
- [ ] **Task 2: Register** (`pyproject.toml`) — all six under `tymi.mutators`; re-sync.
- [ ] **Task 3: Unit tests** — each breakage materializes in Schema + frame + manifest;
  targeting defaults + explicit + unknown → `ChaosError`; PK/unique duplication
  actually duplicates; orphan FK values reference no parent value; determinism;
  toggling via a mixed chain; entry-point registration.
- [ ] **Task 4: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **These mutate the Schema, not just cells.** Unlike Stories 3.2/3.3 (cell-value
  faults), a structural mutator returns a `Dataset` whose `Schema` differs
  (fewer/more/renamed columns, a changed logical type, …). AD-10 still holds: the
  returned artifact is internally consistent (Schema column set == frame columns) — the
  *data contract* against the original Schema is what the fault breaks, which is the
  point of the test.
- **duplicate_keys / orphan_fk are row-level.** They pick a proportion of rows and
  overwrite the target column: `duplicate_keys` copies one surviving key value across
  the chosen rows (so the PK/unique column now has repeats); `orphan_fk` writes values
  that cannot match any value present in the FK column (a sentinel derived from the
  data), so a referential-integrity check fails.
- **Defaults do something on entry-point discovery.** A no-arg structural mutator
  picks the first column; `duplicate_keys`/`orphan_fk` default to the Schema's
  PK/unique/FK columns. The Chaos Policy (Story 3.5) supplies explicit targets.
- **Check constraints are deferred (honestly).** The MVP `Schema` models columns, PK,
  FK, unique and indexes — but not arbitrary check constraints, so a "check-constraint
  violation" has no declared target to break here; value-level violations live in the
  3.2/3.3 families. This is called out, not silently skipped.

### References

- [Source: epics.md#Epic-3 Story 3.4; FR-15]
- [Source: ARCHITECTURE-SPINE.md — AD-3, AD-4/AD-11, AD-5, AD-10]
- [Source: domain/artifacts.py — `Schema` (columns, primary_key, foreign_keys,
  unique_constraints)]
- [Source: 3-3-format-type-violation-mutators.md — the mutator/param pattern]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All tests run **inside the devcontainer**: `uv sync` (registers six entry points),
  `uv run ruff check .` / `uv run lint-imports` → clean; `uv run pytest tests/unit` →
  381 passed. `load_mutators()` → all 12 chaos mutators.

### Completion Notes List

- Six structural breakage mutators on a small `_SchemaBreakMutator` base; each returns
  a `Dataset` with a mutated Schema and/or frame (Schema column set == frame columns)
  + a manifest. Check-constraints deferred (no check metadata in the MVP `Schema`).
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 1
  HIGH: `duplicate_keys` duplicated key columns **independently**, so a **composite**
  PK/unique key was violated only by coincidence (32/40 seeds produced ZERO real
  violations) — rewritten to copy the whole key **tuple** from one surviving row (now
  40/40), and to work **positionally** so a non-unique frame index no longer crashes
  (`frame.index.get_loc` → slice). Fixed the `orphan_fk` string sentinel colliding with
  an existing `"__ORPHAN__"` value (now derives one proven absent). Preemptively fixed
  dangling `indexes` references after drop/rename (`_drop_from_schema`/`_rename_in_schema`
  now handle indexes). Added `field_name` non-empty validation. Closed test gaps:
  composite-key violation, non-unique-index no-crash, string-orphan absence, negative
  Pydantic validation, parametrized unknown-column `ChaosError`. Noted for Story 3.6:
  `duplicate_keys` records `fault_type "duplicate_key"` (singular). +7 tests → 381 unit.
  All ACs satisfied (check-constraints deferred, documented).

### File List

- `src/tymi/chaos/mutators/schema_break.py` (new — six mutators + Schema helpers)
- `pyproject.toml` (modified — six entry points under `tymi.mutators`)
- `tests/unit/test_schema_break_mutators.py` (new)
- `tests/unit/test_plugins.py` (modified — expects all 12 mutators)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.4 — six schema/constraint breakage mutators (`missing_field`, `extra_field`, `renamed_column`, `changed_type`, `duplicate_keys`, `orphan_fk`) that mutate the canonical Schema + frame; check-constraints deferred (no check metadata in the MVP Schema). Registered under `tymi.mutators`, run via the Story 3.1 engine. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Fixed HIGH composite-key non-violation (`duplicate_keys` now copies the whole key tuple, positionally — also fixes a non-unique-index crash); fixed the `orphan_fk` string sentinel colliding with an existing value; handled dangling `indexes` refs on drop/rename; added `field_name` non-empty validation. Closed composite-violation / index-crash / orphan-absence / Pydantic-validation / unknown-column test gaps. 381 unit. All ACs satisfied. Status → done. |

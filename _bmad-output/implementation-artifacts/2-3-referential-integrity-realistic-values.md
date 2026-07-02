---
baseline_commit: 41f4a50
---

# Story 2.3: Referential integrity and realistic synthetic values

Status: done

## Story

As a user,
I want related tables generated consistently with realistic-looking values,
so that the dataset is usable end-to-end without leaking real values.

## Acceptance Criteria

1. **Referential integrity across tables** — given a set of related table Profiles
   with PK/FK constraints, generation produces one Dataset per table where
   **parents are generated before children** (topological order; a cycle raises a
   typed error) and **every foreign-key value points to an existing parent
   primary-key value**.
2. **Primary keys are unique** — each table's primary key (single or composite)
   holds no duplicate values in the generated Dataset.
3. **Unique constraints respected** — declared single-column unique constraints
   hold in the generated Dataset (best-effort dedup for constraints under our
   control; documented limits for FK-bound/composite ones).
4. **Realistic formatted values (Faker)** — text columns that look like
   email/name/phone/id get synthetic realistic values via **Faker** instead of the
   length-only placeholder, so single-table `tymi generate` output is usable.
5. **No real value leaked (AD-6)** — formatted values are synthetic (Faker),
   never copied from the source; the Profile never held raw values anyway. (The
   full config-driven leakage gate is Story 2.5.)
6. **Deterministic (AD-4/AD-11)** — related generation and Faker draw all
   randomness from the injected `rng`; the same seed yields identical output.
7. **Verified end-to-end** — an integration test profiles real related
   PostgreSQL/MySQL tables (parent + child with a FK), generates them, and asserts
   FK validity + PK uniqueness + realistic values in the output.

## Tasks / Subtasks

- [x] **Task 1: Faker formatted values** (`src/tymi/synth/faker_values.py`) —
  `formatted_kind(name)` (name heuristic → `email`/`name`/`phone`/`uuid`/`None`),
  `fake_values(kind, rows, *, rng)` (a Faker seeded from the injected `rng`);
  `apply_formatted_values(dataset, *, rng)` overrides matching **text** columns
  (preserving nulls). Robust PII classification is Epic 4.
- [x] **Task 2: Wire Faker into faithful generation** (`src/tymi/synth/generator.py`)
  — `generate_faithful` applies formatted values as a post-step so single-table
  `tymi generate` emits realistic emails/names/phones.
- [x] **Task 3: Relational generation** (`src/tymi/synth/relational.py`) —
  `generate_related(profiles, *, rows, rng) -> dict[str, Dataset]`: topological
  order over FKs (cycle → `GenerationError`), per-table `generate_faithful`, then
  enforce unique PKs, FK values sampled from the parent PK pool (composite-
  consistent), and single-column unique constraints.
- [x] **Task 4: Typed error** (`src/tymi/core/errors.py`) — add
  `GenerationError(TymiError)` for cyclic/unsatisfiable relational requests.
- [x] **Task 5: Unit tests** (`test_faker_values.py`, `test_relational.py`) —
  formatted detection + synthetic values + determinism; topo order, FK validity,
  PK uniqueness, unique constraints, cycle detection, composite FK, fallback.
- [x] **Task 6: Integration test** — PostgreSQL + MySQL: real parent+child tables
  with a FK, profile both, `generate_related`, assert FK ⊆ parent PKs + unique PKs.

## Dev Notes

- **Scope**: multi-table referential integrity is delivered as a library capability
  (`generate_related`); wiring a multi-table surface into the CLI/pipeline
  orchestrator (AD-8) lands with the export/pipeline stories (the AC does not
  require a CLI). Single-table `tymi generate` gains Faker formatted values now.
- **Topological order**: build a dependency graph from each Schema's
  `foreign_keys[].referred_table`; parents (referred) sort before children. A cycle
  (or self-cycle) raises `GenerationError`. A FK to a table not in the given set is
  left as-generated (can't source parent PKs) — documented.
- **PK uniqueness is FK-aware** (enforcement order: sample non-self FKs → make PK
  unique → publish → resolve self-FKs → dedupe unique constraints). A PK with any
  non-FK column uniquifies that column (the tuple is then unique while FK-bound PK
  columns keep valid parent values). A **pure junction PK** (every PK column is
  FK-bound, e.g. `enrollment(student_id, course_id)`) is filled with unique valid
  parent-key **combinations**, raising `GenerationError` if the requested row count
  exceeds the available combinations. FK values (including composite and self-
  referential) are sampled from the parent's *published* frame, so a FK to a
  non-PK **unique** column resolves too; dtype is preserved via `Series.take`.
- **Faker detection is name-based** (case-insensitive substring) and restricted to
  **text** columns so a low-cardinality categorical "name" is not clobbered. This
  is an MVP heuristic; semantic/PII classification is Epic 4.
- **Determinism**: Faker is seeded from an int drawn off the injected numpy `rng`,
  and every relational draw uses that same `rng`, so the whole run is reproducible.
- AD-6/AD-10 hold: only Profile aggregates are consumed; each Dataset keeps its
  Profile's canonical Schema.

### References

- [Source: epics.md#Epic-2 Story 2.3; FR-9 (Referential Integrity & Realistic Values)]
- [Source: ARCHITECTURE-SPINE.md — AD-4/AD-11 (RNG), AD-6, AD-8 (orchestrator),
  AD-9 (permissive deps — Faker is MIT), AD-10 (canonical Schema)]
- [Source: 2-2-correlation-preservation.md — generate_faithful]
- [Source: domain/artifacts.py — Schema PK/FK/unique_constraints]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.synth.relational`/`faker_values` import `tymi.domain` + `tymi.core.errors`
  + faker/numpy/pandas only).
- `uv run pytest tests/unit` → 175 unit passed (formatted detection incl. id→uuid,
  synthetic values + null preservation + determinism; topo order, FK validity, PK
  uniqueness, junction PK unique+valid, junction capacity error, PK-that-is-also-FK,
  surrogate+FK PK, FK→non-PK-unique column, numeric unique dtype-preserved,
  dedup collision-safety, FK dtype, cycle detection, self-ref, composite FK).
- `uv run pytest -m integration -k relational` → 2 passed (real `postgres:16-alpine`
  + `mysql:8.4`): profile parent+child → `generate_related` → FK ⊆ parent PKs +
  unique PKs + synthetic emails. 2.1/2.2 integration re-verified after the
  `generate_faithful` change.

### Completion Notes List

- Realistic values: text columns named like email/name/phone/id/uuid get synthetic
  **Faker** values (seeded from the injected `rng`), applied inside `generate_faithful`
  so single-table `tymi generate` output is usable; only free-text (`STRING`) columns
  are overridden so categoricals/numerics are intact. AD-6 upheld (synthetic, never
  copied).
- Referential integrity: `generate_related` orders tables topologically (cycle →
  `GenerationError`), makes each PK unique (FK-aware, incl. pure-junction combos),
  and points every FK at a real parent value (PK or non-PK unique column), preserving
  dtype. Deterministic from the injected `rng`.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). AC audit:
  5/7 initially SATISFIED, 2 PARTIAL → both fixed to SATISFIED. Fixed the HIGH
  (convergent Blind+Auditor): a column that is both PK and FK (junction / 1:1
  identifying) had its unique PK silently overwritten by FK sampling → now FK-aware PK
  enforcement + unique junction combos. Also fixed: FK→non-PK-unique-column left
  invalid; `_dedupe` stringified numeric unique columns and could collide; Int64
  PK/FK dtype drift; and added the AC-4 "id" Faker kind. All 7 ACs satisfied; verified
  end-to-end on PostgreSQL and MySQL.

### File List

- `pyproject.toml` (modified — add `faker>=30`)
- `src/tymi/core/errors.py` (modified — `GenerationError`)
- `src/tymi/synth/faker_values.py` (new)
- `src/tymi/synth/generator.py` (modified — apply formatted values)
- `src/tymi/synth/relational.py` (new)
- `tests/unit/test_faker_values.py` (new)
- `tests/unit/test_relational.py` (new)
- `tests/integration/test_relational_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-02 | Implemented Story 2.3 — realistic Faker formatted values (email/name/phone/id/uuid on text columns, seeded from `rng`, applied in `generate_faithful`) + `generate_related` multi-table referential integrity (topological order, unique PKs, FKs sampled from parents). Added `faker>=30` (MIT) and `GenerationError`. 166 unit + real PG/MySQL relational integration pass. |
| 2026-07-02 | Full 3-layer `bmad-code-review` gate (Blind + Edge Case + Acceptance). AC audit: 5/7 SATISFIED + 2 PARTIAL → all 7 fixed to SATISFIED. Fixed 1 HIGH (Blind+Auditor convergent): a PK column that is also an FK (junction / 1:1 identifying tables) had its unique PK silently overwritten by many-to-one FK sampling → FK-aware PK enforcement + unique valid junction-key combinations (with a capacity check → `GenerationError`). Also fixed (Blind/Edge): FK → non-PK unique column left invalid (now sampled from the parent's published frame); `_dedupe` stringified numeric unique columns and its suffix could collide (now numeric-safe + collision-free); Int64 PK/FK dtype drift (now preserved via `Series.take`); added the AC-4 "id"→uuid Faker kind. +9 tests → 175 unit. Dismissed (verified correct): topo/cycle detection, self-ref, determinism, Faker rng discipline, YAML round-trip. Status → done. |

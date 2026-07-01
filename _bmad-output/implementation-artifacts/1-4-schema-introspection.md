---
baseline_commit: a34294d
---

# Story 1.4: Schema introspection

Status: done

## Story

As a user,
I want to extract a table's schema (columns, types, nullability, PK, FK, unique constraints, indexes),
so that generation and chaos can respect the real structure.

## Acceptance Criteria

1. **`tymi schema <table>` prints the structured schema** as JSON, for any of the four engines (`--engine`, `--config`). Exit 0 on success.
2. **Common, engine-agnostic model.** Introspection returns the canonical `Schema` (enriched with columns+logical types, nullability, primary key, foreign keys, unique constraints, indexes), normalized across engines via SQLAlchemy reflection.
3. **FK relationships captured** — each foreign key records its local columns, the referred table, and the referred columns.
4. **Serializable output** — the `Schema` serializes to JSON deterministically.
5. **Actionable errors** — a missing table raises a typed `TableNotFoundError` (subclass of `EngineError`); connection failures still scrub secrets (reuse Story 1.2/1.3 handling). No secret leaks.
6. **Verified end-to-end** — integration tests against real PostgreSQL and MySQL containers create a parent/child table pair and assert columns, PK, and FK are introspected correctly.

## Tasks / Subtasks

- [x] **Task 1: Enrich the canonical `Schema`** (`src/tymi/domain/artifacts.py`) — add `primary_key: tuple[str,...]`, `ForeignKey(columns, referred_table, referred_columns)`, `Index(name, columns, unique)`, `unique_constraints`, and `Column.primary_key`. Keep existing fields/defaults so current code stays valid.
- [x] **Task 2: Type mapping** — a helper mapping a SQLAlchemy column type to `LogicalType` (Boolean→BOOLEAN, Integer→INTEGER, Numeric/Float→FLOAT, Date/DateTime/Time→DATETIME, Enum→CATEGORICAL, else STRING).
- [x] **Task 3: Implement `introspect` in the base** (`SqlAlchemyEngineAdapter`) using SQLAlchemy `inspect()` reflection (`get_columns`, `get_pk_constraint`, `get_foreign_keys`, `get_unique_constraints`, `get_indexes`; `get_check_constraints` best-effort). Works for all four engines. Wrap `NoSuchTableError` → `TableNotFoundError`; other failures scrubbed like `test_connection`.
- [x] **Task 4: Errors** — add `TableNotFoundError(EngineError)` in `core/errors.py`.
- [x] **Task 5: Schema serialization** — a `schema_to_json(schema) -> str` helper (or `Schema.to_dict`) producing deterministic JSON.
- [x] **Task 6: Real `schema` CLI command** — replace the stub: load config, resolve adapter, `introspect(table)`, print JSON, exit 0; typed errors → clear message + non-zero exit; no secrets.
- [x] **Task 7: Unit tests** — type-mapping table; `Schema` JSON round-trip/shape; CLI guardrails (unknown engine, missing table surfaced) without a DB.
- [x] **Task 8: Integration tests** — PostgreSQL + MySQL: create `parent(id PK)` and `child(id PK, parent_id FK→parent.id)`, introspect both, assert columns/types/PK/FK. Docker-gated skip.

## Dev Notes

- SQLAlchemy reflection is dialect-agnostic, so `introspect` lives in the **base** and covers all four engines — do not write per-engine introspection.
- Reuse the connection/secret-scrubbing path already in `_base.py`; introspection opens an engine the same way.
- Some engines don't support every reflection call (e.g. check constraints, or StarRocks FKs) — guard those and return empty rather than failing.
- Keep `sample`/`load` unimplemented (Story 1.5 / Epic 2).
- The enriched `Schema` is consumed later by profiling (Epic 1) and generation (Epic 2); keep it JSON-clean (StrEnum + tuples).

### References

- [Source: epics.md#Epic-1 Story 1.4; FR-2]
- [Source: ARCHITECTURE-SPINE.md — AD-2, AD-10 (canonical Schema)]
- [Source: 1-3-postgres-mysql-starrocks-adapters.md — SqlAlchemyEngineAdapter base]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept.
- `uv run pytest` → 53 unit passed.
- `uv run pytest -m integration -k introspect` → 2 passed (real `postgres:16-alpine` + `mysql:8.4`); introspects columns/types/PK/FK on a parent/child pair.
- Fixed a test-DDL gotcha: MySQL ignores an inline column-level `REFERENCES`; switched to a table-level `FOREIGN KEY` (honored by both engines).

### Completion Notes List

- `introspect()` implemented once in the `SqlAlchemyEngineAdapter` base via
  SQLAlchemy reflection — works for all four engines (AD-2, AD-10). Reflection
  helper `reflect_schema` + `map_logical_type` in `engines/_introspect.py`.
- Enriched the canonical `Schema` (primary key, `ForeignKey`, `Index`, unique
  constraints, `Column.primary_key`); added `schema_to_json` (deterministic,
  StrEnum-safe).
- Real `tymi schema <table>` CLI command; shared `_load_adapter` helper with
  `test-connection`. Missing table → typed `TableNotFoundError`; connection
  failures still scrub secrets.
- Dialect-specific reflection gaps (check constraints, StarRocks FKs) are guarded
  and return empty rather than failing.
- All 6 ACs satisfied; verified end-to-end on PostgreSQL and MySQL.

### File List

- `src/tymi/domain/artifacts.py` (modified — enriched Schema + `schema_to_json`)
- `src/tymi/core/errors.py` (modified — `TableNotFoundError`)
- `src/tymi/engines/_introspect.py` (new — reflection + type mapping)
- `src/tymi/engines/_base.py` (modified — `introspect` implementation)
- `src/tymi/cli/app.py` (modified — real `schema` command + `_load_adapter`)
- `tests/unit/test_introspect.py` (new)
- `tests/integration/test_introspect_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.4 — schema introspection via SQLAlchemy reflection in the base (all four engines), enriched canonical Schema (PK/FK/indexes), `schema_to_json`, real `tymi schema` CLI. 53 unit tests + real PG/MySQL introspection integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: no CRITICAL/HIGH defects. Closed the one MEDIUM (test-coverage gap): integration tests now assert unique constraints, indexes, and the missing-table `TableNotFoundError` path. Status → done. |

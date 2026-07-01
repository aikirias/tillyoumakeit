---
baseline_commit: 23ff4f8
---

# Story 1.5: Streaming, seed-reproducible sampling

Status: done

## Story

As a user,
I want to sample N rows of a table without loading the whole table,
so that I can feed profiling on large tables safely and reproducibly.

## Acceptance Criteria

1. **`tymi sample <table> --rows N`** returns up to N rows for any of the four engines (`--engine`, `--config`, `--seed`), printed as CSV. Exit 0 on success.
2. **Bounded client memory** — only the sampled rows are ever held in the tool (we `LIMIT`/`TOP` to N server-side), so a ≥10M-row table does not exhaust memory (NFR-2).
3. **Random sample** — rows are drawn randomly (a dialect-appropriate random ordering), not just the first N physical rows.
4. **Seed-reproducible** where the dialect supports it — same seed ⇒ same rows for PostgreSQL (`setseed` + `random()`) and MySQL (`RAND(seed)`). **MSSQL** (`NEWID()`) and **StarRocks** (distributed `RAND` across BEs) are random but **not** seed-reproducible; this is surfaced via the `reproducible_sample` class flag and a CLI stderr notice (documented limitation). *(Corrected in review: StarRocks was initially assumed reproducible — it is not.)*
5. **Returns a canonical `Dataset`** — the sampled `pandas.DataFrame` paired with the table's `Schema` (from introspection) (AD-10).
6. **Typed errors, no secret leak** — missing table → `TableNotFoundError`; connection failures scrubbed (reuse base handling).
7. **Verified end-to-end** — integration tests against real PostgreSQL and MySQL sample a seeded table and assert row count, schema alignment, and seed reproducibility.

## Tasks / Subtasks

- [x] **Task 1: `sample` in the base** — implement `SqlAlchemyEngineAdapter.sample(table, *, rows, rng)`: derive an int seed from `rng`, `introspect` the table (validates existence + gives Schema), run per-dialect `_sample_sql`, read into a DataFrame via `pandas.read_sql`, return `Dataset`. Quote the table via the dialect preparer. Reuse the scrubbed error handling.
- [x] **Task 2: Per-dialect `_sample_sql(table_quoted, rows, seed) -> (setup_stmts, query)`** — PostgreSQL (`setseed` + `ORDER BY random() LIMIT`), MySQL/StarRocks (`ORDER BY RAND(seed) LIMIT`), MSSQL (`SELECT TOP (n) … ORDER BY NEWID()`).
- [x] **Task 3: Real `sample` CLI command** — replace the stub: `tymi sample <table> --engine --config --rows --seed`; build `rng` via `make_rng(seed)`; print `frame.to_csv(index=False)`; typed errors → non-zero exit; no secrets.
- [x] **Task 4: Unit tests** — each adapter's `_sample_sql` contains the expected clause (`setseed`/`RAND(<seed>)`/`TOP`/`ORDER BY random()`); a bad `rows` (≤0) raises; CLI guardrails reuse `_load_adapter`.
- [x] **Task 5: Integration tests** — PostgreSQL + MySQL: create a table with ~100 rows, `sample(rows=10)`, assert 10 rows + schema columns; sample twice with the same seed ⇒ identical frames (reproducibility). Docker-gated skip.

## Dev Notes

- Random sampling with `ORDER BY random()/RAND()` makes the DB do a scan/sort but the **tool** only ever holds N rows — that satisfies NFR-2 (client memory). Efficient page/`TABLESAMPLE`-based sampling is a later optimization.
- `sample` reuses `introspect` for the Schema and for missing-table validation — one code path, consistent errors.
- Seed derivation: `int(rng.integers(0, 2**31 - 1))` — stable given a seeded `rng`.
- MSSQL seeded per-row randomness isn't straightforward; `NEWID()` gives a random (non-reproducible) sample. Reproducibility for MSSQL is deferred and documented in AC-4.
- Keep `load` unimplemented (Epic 2).

### References

- [Source: epics.md#Epic-1 Story 1.5; FR-3, NFR-2, NFR-4]
- [Source: ARCHITECTURE-SPINE.md — AD-2, AD-4 (seeded RNG), AD-10 (Dataset)]
- [Source: 1-4-schema-introspection.md — base adapter + Schema]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept.
- `uv run pytest` → 58 unit passed.
- `uv run pytest -m integration -k sample` → 2 passed (real `postgres:16-alpine` + `mysql:8.4`): sample 10 of 100 rows, schema aligned, and **same seed → same rows** verified.

### Completion Notes List

- `sample()` implemented in the base: derive an int seed from the `rng`,
  `introspect` for the Schema (and missing-table validation), run a per-dialect
  seeded random `_sample_sql`, read into a DataFrame, return a `Dataset` (AD-10).
- Seeded reproducibility: PostgreSQL (`setseed` + `random()`), MySQL/StarRocks
  (`RAND(seed)`). MSSQL uses `TOP (n) … ORDER BY NEWID()` — random but **not**
  reproducible (documented, deferred).
- Bounded client memory (LIMIT/TOP N server-side); table identifier quoted via
  the dialect preparer.
- Real `tymi sample <table> --rows --seed` CLI command (CSV output); typed
  errors; secrets scrubbed.
- All 7 ACs satisfied; PG + MySQL verified end-to-end incl. reproducibility.

### File List

- `src/tymi/engines/_base.py` (modified — `sample` + default `_sample_sql`)
- `src/tymi/engines/postgres.py`, `mysql.py`, `starrocks.py`, `mssql.py` (modified — `_sample_sql`)
- `src/tymi/cli/app.py` (modified — real `sample` command)
- `tests/unit/test_sample_sql.py` (new)
- `tests/integration/test_sample_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.5 — seed-reproducible streaming sampling in the base (per-dialect random SQL), real `tymi sample` CLI. 58 unit tests + real PG/MySQL sampling+reproducibility integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: fixed 1 HIGH (type-guard `rows` against SQL injection via the library API) + 1 MEDIUM (PG reproducibility robustness: disable parallel gather so `setseed` holds) + 1 MEDIUM (added non-int `rows` injection tests). Column-order / RAND-tie / empty-table LOWs dismissed. 62 unit tests pass. Status → done. |
| 2026-07-01 | Full 3-layer review (1.3–1.5): corrected the StarRocks reproducibility claim (not reproducible — distributed RAND), added `reproducible_sample` flag + CLI notice for MSSQL/StarRocks, made base `_sample_sql` mandatory, and strengthened the reproducibility test (different seed → different rows). 66 unit tests pass. |

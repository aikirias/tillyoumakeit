---
baseline_commit: 0122820
---

# Story 2.6: Multi-destination export

Status: done

## Story

As a user,
I want to export generated data to files, SQL, or any engine,
so that I can load it wherever I need it.

## Acceptance Criteria

1. **Four export targets** — `tymi generate --to csv|parquet|json` writes a file
   (`--out PATH`), and `--to sql --engine <any> --config <cfg> --table <t>` loads
   the generated Dataset directly into any of the four engines. Source and
   destination are independent (a Profile from Postgres can be loaded into MySQL).
2. **Files are re-importable** — a CSV/Parquet/JSON file written by TYMI reads back
   into an equivalent DataFrame (round-trips values; Parquet round-trips dtypes).
3. **Direct load works against each standard-SQL engine** —
   `EngineAdapter.load(dataset, table)` (re)creates the destination table from the
   canonical Schema and inserts every row, over the shared SQLAlchemy path. Verified
   on real **PostgreSQL + MySQL** containers; **MSSQL** uses the same standard
   `CREATE TABLE`/`INSERT` DDL. **StarRocks is a documented exception** — its
   `CREATE TABLE` needs a distribution/keys clause that pandas `to_sql` does not
   emit, so StarRocks direct auto-create load is deferred (use a file export + the
   StarRocks bulk loader). The load is **idempotent** (`if_exists="replace"`).
4. **Deterministic exporters (NFR-4)** — the same Profile + seed + config produces
   **byte-identical** file output on repeated runs, for every file format.
5. **Exporters map from the canonical Schema, not raw pandas dtypes (AR-10)** —
   each column is serialized according to its `LogicalType` (INTEGER as integers,
   DATETIME as ISO-8601, BOOLEAN as `true/false`, …), and the SQL loader builds the
   destination column types from the Schema (via an explicit type map, never
   pandas dtype inference).
6. **Typed errors, no traceback** — an unknown format, a missing `--out` for a file
   format, a missing `--engine/--config/--table` for `--to sql`, or an unwritable
   path raises a typed error (CLI exit 1/2), never a traceback. AD-4/AD-6/AD-10 hold.

## Tasks / Subtasks

- [ ] **Task 1: Schema-driven export normalization** (`src/tymi/io/schema_map.py`)
  — `normalize_for_export(dataset) -> DataFrame` coerces each column to its
  `LogicalType`'s canonical representation; `logical_to_sqltype(logical_type)` maps
  a `LogicalType` to a SQLAlchemy column type for DDL.
- [ ] **Task 2: File exporters** (`src/tymi/io/exporters.py`) — `CsvExporter`,
  `ParquetExporter`, `JsonExporter` implementing the `Exporter` port
  (`export(dataset, *, target)`); `get_exporter(fmt)` factory; deterministic +
  Schema-mapped writes.
- [ ] **Task 3: Engine load** (`src/tymi/engines/_base.py`) — implement
  `SqlAlchemyEngineAdapter.load(dataset, *, table)`: create the table from the
  Schema type map and insert rows (`to_sql` with an explicit `dtype=` map, so
  column types come from the Schema, not pandas — AR-10).
- [ ] **Task 4: CLI** (`src/tymi/cli/app.py`) — `tymi generate --to
  csv|parquet|json|sql`, `--out PATH`, and (for `sql`) `--engine/--config/--table`;
  default stays CSV-to-stdout; typed errors → exit 1/2.
- [ ] **Task 5: Unit tests** — determinism (byte-identical) + re-import + Schema
  mapping per format; unknown-format / missing-out / missing-sql-args errors;
  `logical_to_sqltype` map; `to_sql` dtype map built from Schema.
- [ ] **Task 6: Integration test** (`-m integration`) — `load` a generated Dataset
  into real PG + MySQL and read it back (source≠destination).
- [ ] **Task 7: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Map from the Schema, not the frame (AR-10).** The generated frame's pandas
  dtypes are an implementation detail (nullable `Int64`, `object`, `datetime64`);
  exporters and the SQL loader consult the canonical `Schema.logical_type` per
  column so a downstream consumer gets the declared type regardless of how pandas
  happened to back it. The SQL loader passes an explicit `dtype=` map to `to_sql`
  for the same reason (never let pandas infer the DDL).
- **Determinism (NFR-4).** CSV/JSON are byte-identical by construction (fixed column
  order from the Schema, ISO dates, no index). Parquet byte-identity holds for a
  fixed `pyarrow` version (its `created_by` footer string is version-constant and no
  wall-clock is embedded) — asserted in tests. `pyarrow` (Apache-2.0) is a new
  permissive dependency (AD-9).
- **Scope.** File formats + single-table direct `load` on the shared SQLAlchemy
  base (all four engines). Wiring a full multi-table export/orchestrator (topological
  load of related tables) travels with the pipeline story; this story exports one
  Dataset. No AD-6 concern — exporters write already-synthetic data.
- **`--to sql` vs files.** File formats need `--out` (Parquet must have a path;
  CSV/JSON without `--out` print to stdout). `--to sql` needs `--engine/--config/
  --table` and ignores `--out`.

### References

- [Source: epics.md#Epic-2 Story 2.6; FR-17]
- [Source: ARCHITECTURE-SPINE.md — AD-2 (bidirectional EngineAdapter), AD-10/AR-10
  (canonical Schema drives export), AD-8 (Export is a core stage), NFR-4]
- [Source: ports/__init__.py — `Exporter` protocol; `EngineAdapter.load`]
- [Source: engines/_introspect.py — `map_logical_type` (SQL→LogicalType, reversed here)]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All deps/tests run **inside the devcontainer** (`devcontainer exec`): `uv add
  pyarrow` (Apache-2.0), `uv run ruff check .` / `uv run lint-imports` → clean
  (2 contracts kept), `uv run pytest tests/unit` → 251 passed.
- `uv run pytest tests/integration/test_export_integration.py -m integration` →
  2 passed (real PostgreSQL + MySQL `load` round-trip).

### Completion Notes List

- File exporters (CSV/JSON/Parquet) + direct SQL `load`, all mapping from the
  canonical Schema via `normalize_for_export` (AR-10) and deterministic (NFR-4).
  `load` uses `to_sql` with a Schema-derived `dtype=` map and `if_exists="replace"`
  (idempotent). New permissive dep `pyarrow` (AD-9). CLI: `generate --to
  csv|json|parquet|sql`.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 2
  reachable HIGH/MEDIUM faithfulness bugs: JSON silently truncated every float to 10
  significant digits (pandas default) → `double_precision=15`; datetimes exported at
  three different precisions (CSV whole-seconds, JSON ms, Parquet ns) losing the
  generator's sub-second data → CSV now full-precision and JSON `date_unit="ns"`.
  Fixed: `load` wrapped every failure as a *connection* error and normalized outside
  the try → now raises `EngineError` with normalization inside the try; a STRING
  column backed by an extension dtype wasn't stringified (`.where` → `.map`);
  non-finite floats could crash the INTEGER cast / emit non-portable `inf` → dropped
  to NA; `if_exists="append"` made SQL load non-idempotent → `replace`; the stale
  `export` CLI stub (claimed "not implemented" while `generate --to` shipped it) was
  removed; AC-3 StarRocks claim corrected to a documented exception. Closed test
  gaps: DDL column-types inspected (proves Schema-driven, not pandas-inferred),
  unwritable-path typed error, load idempotency, JSON float precision, sub-second
  datetime, extension-dtype STRING. +N tests → 251 unit + 2 integration. All 6 ACs
  satisfied.

### File List

- `src/tymi/io/schema_map.py` (new — `normalize_for_export`)
- `src/tymi/io/exporters.py` (new — Csv/Json/Parquet + `get_exporter`)
- `src/tymi/engines/_introspect.py` (modified — `logical_to_sqltype`)
- `src/tymi/engines/_base.py` (modified — `load`)
- `src/tymi/core/errors.py` (modified — `ExportError`)
- `src/tymi/cli/app.py` (modified — `generate --to/--out/--engine/--config/--table`;
  removed the `export` stub)
- `pyproject.toml` / `uv.lock` (modified — `pyarrow`)
- `tests/unit/test_export.py` (new)
- `tests/integration/test_export_integration.py` (new)
- `tests/unit/test_cli_smoke.py` (modified — dropped the removed `export` stub)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 2.6 — multi-destination export. New `tymi.io` exporters (CSV/JSON/Parquet, Schema-driven + deterministic) and `EngineAdapter.load` (Schema DDL + insert via `to_sql`); CLI `tymi generate --to` (csv/json/parquet/sql). New dep `pyarrow`. Verified `load` on real PG + MySQL. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate (Blind + Edge Case + Acceptance). Fixed HIGH/MEDIUM faithfulness bugs (JSON float truncation → `double_precision=15`; cross-format datetime precision loss → full-precision CSV + `date_unit="ns"` JSON), plus `load` error typing/idempotency (`EngineError`, `if_exists="replace"`), extension-dtype STRING stringification, non-finite guards, and removed the stale `export` stub; corrected the StarRocks load claim to a documented exception. Closed DDL-type / unwritable-path / idempotency / precision test gaps. 251 unit + 2 integration. All 6 ACs satisfied. Status → done. |

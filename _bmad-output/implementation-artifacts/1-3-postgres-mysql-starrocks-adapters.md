---
baseline_commit: bce04df
---

# Story 1.3: PostgreSQL, MySQL, and StarRocks adapters via plugins

Status: done

## Story

As a user,
I want the same connectivity for PostgreSQL, MySQL, and StarRocks,
so that all four engines are usable as source or destination.

## Acceptance Criteria

1. **Three new adapters.** `PostgresAdapter`, `MySqlAdapter`, and `StarRocksAdapter` implement the `EngineAdapter` port with capability flags all `True`; `introspect`/`sample`/`load` raise `NotImplementedError` (later stories). Connectivity only.
2. **Shared base (DRY).** The credential resolution, `SELECT 1` connection check, and secret-scrubbing logic live in one `SqlAlchemyEngineAdapter` base; every engine (including MSSQL, refactored) reuses it and only supplies `build_url`. The hardened secret handling from Story 1.2 is preserved.
3. **Plugin registration.** `postgres`, `mysql`, and `starrocks` are registered under the `tymi.engines` entry point; `load_engines()` returns all four adapters.
4. **Correct dialects/ports.** PostgreSQL → `postgresql+psycopg` (default port 5432); MySQL → `mysql+pymysql` (3306); StarRocks → `mysql+pymysql` over the FE query port (default 9030). Per-engine default port applied when config omits `port`.
5. **`tymi test-connection --engine <e>` works for all four.** Same command, engine chosen by flag; credentials from env; no secrets leaked.
6. **Integration tests.** Real testcontainers tests for PostgreSQL and MySQL assert `test_connection()` succeeds; each skips cleanly without Docker. StarRocks has an adapter + a gated integration test (opt-in via env, heavy image).
7. **CI.** The integration job runs the PG/MySQL integration tests (Docker on the runner); psycopg/pymysql need no system driver install. The unit matrix stays Docker-free.

## Tasks / Subtasks

- [x] **Task 1: Dependencies** — add `psycopg[binary]>=3.3` and `pymysql>=1.2` (runtime); extend dev extra to `testcontainers[mssql,postgres,mysql]`; `uv sync`.
- [x] **Task 2: Generalize `ConnectionConfig`** — make `port: int | None = None` (adapters supply per-engine defaults); keep MSSQL-only fields (`driver`/`encrypt`/`trust_server_certificate`) optional.
- [x] **Task 3: Extract `SqlAlchemyEngineAdapter` base** (`src/tymi/engines/_base.py`) — capability flags, `__init__(connection)`, `_resolve_credentials` (non-empty env), `test_connection` (`create_engine` + `SELECT 1`, scrubbed catch-all), `_scrub` (raw + URL-encoded), and `introspect`/`sample`/`load` raising `NotImplementedError`. Abstract `build_url`.
- [x] **Task 4: Refactor `MssqlAdapter`** to subclass the base (only `build_url` remains: `mssql+pyodbc` + driver/Encrypt/TrustServerCertificate, default port 1433).
- [x] **Task 5: New adapters** — `postgres.py` (`postgresql+psycopg`, 5432), `mysql.py` (`mysql+pymysql`, 3306), `starrocks.py` (`mysql+pymysql`, 9030).
- [x] **Task 6: Register entry points** for postgres/mysql/starrocks in `pyproject.toml`.
- [x] **Task 7: Unit tests** — URL/dialect/default-port per engine; all four discovered via `load_engines()`; MSSQL tests still pass after refactor.
- [x] **Task 8: Integration tests** — `PostgresContainer` and `MySqlContainer` real connection tests (Docker-gated skip); StarRocks gated behind `TYMI_TEST_STARROCKS=1`.
- [x] **Task 9: CI + docs** — ensure the integration job covers PG/MySQL; update `docs/status.md`.

## Dev Notes

- Reuse the Story 1.2 pattern and the hardened secret handling; do not duplicate it — centralize in the base (AC2).
- `psycopg[binary]` and `pymysql` are pure-wheel / no system driver, so PG/MySQL integration tests run on any Docker host (unlike MSSQL's ODBC driver).
- StarRocks speaks the MySQL wire protocol → the adapter is a thin `mysql+pymysql` variant on port 9030; a real StarRocks container (`starrocks/allin1-ubuntu`) is multi-GB, so its integration test is opt-in.
- Keep `introspect`/`sample`/`load` unimplemented — scope is connectivity.
- Licenses (AD-9): psycopg (LGPL, dynamic dep — allowed), pymysql (MIT), testcontainers (MIT/Apache). All acceptable.

### References

- [Source: epics.md#Epic-1 Story 1.3]
- [Source: ARCHITECTURE-SPINE.md — AD-2, AD-3, AD-9]
- [Source: 1-2-engine-adapter-and-mssql-connectivity.md — adapter + secret-scrubbing pattern]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv sync` → psycopg[binary] 3.3.4, pymysql 1.2.0.
- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept.
- `uv run pytest` → 42 unit passed (incl. refactored MSSQL + 3 new engines).
- `uv run pytest -m integration -k "postgres or mysql"` → **2 passed** against real
  `postgres:16-alpine` and `mysql:8.4` containers (62s incl. image pulls).

### Completion Notes List

- Extracted `SqlAlchemyEngineAdapter` base — credentials, `SELECT 1` check, and
  URL-encoded secret scrubbing now live once; MSSQL refactored to subclass it
  (only `_query` remains). PostgreSQL/MySQL/StarRocks are ~3-line subclasses
  declaring dialect + default port (AD-2).
- All four engines registered under `tymi.engines` (AD-3); `test-connection`
  works for each (engine chosen by flag).
- `ConnectionConfig.port` is now optional (per-engine default); MSSQL-only
  fields (`driver`/`encrypt`/`trust_server_certificate`) are ignored by others.
- PostgreSQL + MySQL connectivity **verified end-to-end** against real
  containers. StarRocks: adapter + opt-in integration test (`TYMI_TEST_STARROCKS=1`;
  handles the passwordless-root default by setting a password first).
- Licenses (AD-9): psycopg (LGPL, dynamic dep), pymysql (MIT) — acceptable.

### File List

- `pyproject.toml` (modified — deps, 3 entry points, testcontainers extras)
- `src/tymi/engines/_base.py` (new — shared base)
- `src/tymi/engines/mssql.py` (modified — subclass base)
- `src/tymi/engines/postgres.py`, `mysql.py`, `starrocks.py` (new)
- `src/tymi/config/models.py` (modified — optional port, optional driver)
- `tests/unit/test_engine_registration.py` (modified — all four)
- `tests/unit/test_engine_urls.py` (new)
- `tests/unit/test_mssql_url.py` (modified — imports after base extraction)
- `tests/integration/test_pg_mysql_connectivity.py` (new)
- `tests/integration/test_starrocks_connectivity.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.3 — PostgreSQL/MySQL/StarRocks adapters on a shared `SqlAlchemyEngineAdapter` base (MSSQL refactored to reuse it), optional per-engine port, all four registered. 42 unit tests + real PG/MySQL integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: no CRITICAL/HIGH/MEDIUM defects; Story 1.2 secret-hardening confirmed preserved through the refactor. Applied 1 LOW patch (defensive guard against a 0/unset port); 1 LOW (opt-in StarRocks test flakiness) dismissed. Status → done. |

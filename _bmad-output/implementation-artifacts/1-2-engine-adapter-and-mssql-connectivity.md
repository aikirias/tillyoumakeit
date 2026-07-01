---
baseline_commit: d92da2e1566ecc7341e9e14a01293b0653d2381b
---

# Story 1.2: EngineAdapter port and MSSQL connectivity

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to connect to MSSQL with a configurable connection string and securely-provided credentials,
so that TYMI can reach my database (as source or destination) without me hardcoding secrets.

## Acceptance Criteria

1. **First concrete adapter.** A `MssqlAdapter` implements the existing `EngineAdapter` port (`src/tymi/ports/__init__.py`) with capability flags `supports_introspect = supports_sample = supports_write = True`. `introspect`/`sample`/`load` may raise `NotImplementedError` (delivered in Stories 1.4/1.5/Epic 2); **only connectivity is in scope here**. [AD-2]
2. **Plugin registration.** `MssqlAdapter` is registered under the `tymi.engines` entry point (`mssql = "tymi.engines.mssql:MssqlAdapter"`), so `tymi.core.plugins.load_engines()` returns `{"mssql": MssqlAdapter}`. The core still imports no adapter directly. [AD-3]
3. **Real `test-connection` command.** `tymi test-connection --engine mssql` connects and runs a lightweight `SELECT 1`. On success it prints a clear success line and exits 0; the `test-connection` stub is removed from the CLI stub set. [FR-1]
4. **Credentials from the environment (never hardcoded).** The adapter reads the username and password from environment variables named in config (defaults `TYMI_DB_USER` / `TYMI_DB_PASSWORD`); connection non-secrets (host/port/database/driver/TLS) come from the declarative config. No credential value is ever written to any artifact or config file. [NFR-6, AC of epic]
5. **No secrets in logs or errors.** Nothing ever logs the connection URL with a password. Any place a URL is shown uses SQLAlchemy's `engine.url.render_as_string(hide_password=True)`. Invalid credentials / unreachable host raise a typed `EngineConnectionError` with an actionable message (engine, host:port, cause) and **no secret**. [NFR-6, FR-1]
6. **Integration test (testcontainers).** An integration test spins up an MSSQL `SqlServerContainer`, points the adapter at it via env + config, and asserts `test_connection()` succeeds. It is marked `@pytest.mark.integration` and skips cleanly when Docker or the ODBC driver is unavailable. Unit tests cover URL building and password redaction without a container.
7. **CI runs integration.** A CI job installs the ODBC Driver 18 (`msodbcsql18` + `unixodbc-dev`) and runs the integration tests; the existing fast unit job stays green without Docker.

## Tasks / Subtasks

- [x] **Task 1: Dependencies** (AC: 1, 6)
  - [x] Add runtime deps `sqlalchemy>=2.0.51` and `pyodbc>=5.3` to `pyproject.toml`.
  - [x] Add dev dep `testcontainers[mssql]>=4.14`.
  - [x] `uv sync` and confirm resolution.
- [x] **Task 2: Connection config** (AC: 4)
  - [x] Add a `ConnectionConfig` Pydantic model (`extra="forbid"`) in `src/tymi/config/models.py`: `host: str`, `port: int = 1433`, `database: str | None = None`, `driver: str = "ODBC Driver 18 for SQL Server"`, `encrypt: bool = True`, `trust_server_certificate: bool = True`, `user_env: str = "TYMI_DB_USER"`, `password_env: str = "TYMI_DB_PASSWORD"`. **No `user`/`password` fields** — only the env-var *names*.
  - [x] Extend `SourceConfig` with `connection: ConnectionConfig | None = None`.
- [x] **Task 3: Engine errors** (AC: 5)
  - [x] Add `EngineError(TymiError)` and `EngineConnectionError(EngineError)` to `src/tymi/core/errors.py`.
- [x] **Task 4: MSSQL adapter** (AC: 1, 3, 4, 5)
  - [x] `src/tymi/engines/mssql.py`: `MssqlAdapter` with capability flags all `True`.
  - [x] `build_url(conn: ConnectionConfig) -> sqlalchemy.URL`: resolve user/password from `os.environ[conn.user_env|password_env]` (raise `EngineConnectionError` with an actionable message — naming the missing env var, not its value — if unset); construct `mssql+pyodbc://...` with `driver`, `Encrypt`, and `TrustServerCertificate` query params. Prefer `sqlalchemy.URL.create(...)` + `query=` so the password is never string-formatted by hand.
  - [x] `test_connection(conn) -> None`: `create_engine(url).connect()` then `execute(text("SELECT 1"))`; wrap any `sqlalchemy.exc.SQLAlchemyError`/`pyodbc.Error` in `EngineConnectionError(f"Cannot connect to MSSQL at {host}:{port}: {redacted cause}")`. Never include the password; log only `url.render_as_string(hide_password=True)` if logging.
  - [x] `introspect`/`sample`/`load` raise `NotImplementedError("delivered in a later story")`.
- [x] **Task 5: Register the plugin** (AC: 2)
  - [x] In `pyproject.toml`, under `[project.entry-points."tymi.engines"]` add `mssql = "tymi.engines.mssql:MssqlAdapter"`. Re-run `uv sync` so the entry point registers.
- [x] **Task 6: Real `test-connection` CLI command** (AC: 3, 5)
  - [x] In `src/tymi/cli/app.py`, remove `"test-connection"` from `_STUB_COMMANDS` and add a real Typer command: `test_connection(engine: str = typer.Option(...), config: Path = typer.Option(...))`. Load config, resolve the engine adapter via `load_engines()[engine]`, call `test_connection`; on success `typer.echo` a success line and exit 0; on `EngineConnectionError` echo the message (no secret) and `raise typer.Exit(1)`; on unknown engine, exit 2.
- [x] **Task 7: Tests** (AC: 5, 6)
  - [x] Unit `tests/unit/test_mssql_url.py`: `build_url` produces a URL containing the driver + `TrustServerCertificate=yes`; a missing env var raises `EngineConnectionError`; `render_as_string(hide_password=True)` never contains the password. (Set env vars in the test; do not require a DB.)
  - [x] Unit: `load_engines()` includes `"mssql"` and it satisfies the `EngineAdapter` protocol (`isinstance(..., EngineAdapter)` via `@runtime_checkable`, or capability-flag checks).
  - [x] Integration `tests/integration/test_mssql_connectivity.py` (`@pytest.mark.integration`): `SqlServerContainer("mcr.microsoft.com/mssql/server:2022-latest")`, set the env vars from the container creds, build a `ConnectionConfig` pointing at it (`trust_server_certificate=True`), assert `test_connection()` succeeds. `pytest.importorskip("testcontainers")` / skip if Docker unavailable.
  - [x] Register the `integration` marker in `pyproject.toml` (`[tool.pytest.ini_options] markers`), and make the default unit run exclude it (e.g. `addopts = "-m 'not integration'"`).
- [x] **Task 8: CI** (AC: 7)
  - [x] Add an `integration` job to `.github/workflows/ci.yml`: install ODBC Driver 18 (see Dev Notes snippet), `uv sync`, then `uv run pytest -m integration`. Keep the existing unit job (`-m 'not integration'`, no Docker/driver) intact.

### Review Findings

*Code review of commit 6e5f5a5 (Blind Hunter + Acceptance Auditor; Edge Case Hunter layer was interrupted). All 7 ACs verified met; findings harden the secret-redaction error path.*

- [x] [Review][Patch] `_scrub` bypassed by URL-encoded password — scrub raw + percent-encoded variants so a secret cannot leak via a SQLAlchemy/ODBC error message [src/tymi/engines/mssql.py] (blind, HIGH)
- [x] [Review][Patch] `test_connection` exception handling too narrow — catch any Exception at the connection boundary and scrub, so no unexpected error type leaks the password [src/tymi/engines/mssql.py] (blind+auditor, MED)
- [x] [Review][Patch] CLI ignores `--engine` vs `source.engine` mismatch — reject with exit 2 when they disagree [src/tymi/cli/app.py] (blind, MED)
- [x] [Review][Patch] No test on the error-path redaction — add tests for `_scrub` (raw+encoded), `test_connection` wrapping/scrubbing, both-env-missing, and CLI mismatch/no-connection [tests] (blind+auditor, LOW)

*Second pass (Edge Case Hunter rerun):*

- [x] [Review][Patch] `load_config` leaks a raw traceback on an unreadable/non-UTF-8 `--config` file (`read_text` outside the try) — wrap file read, convert to `ConfigError` so the CLI exits 2 cleanly [src/tymi/config/loader.py] (edge, HIGH)
- [x] [Review][Patch] Empty-string credential env var accepted — reject an env var that is set but empty with a clear `EngineConnectionError` [src/tymi/engines/mssql.py] (edge, LOW)
- [x] [Review][Dismiss] `except Exception` in `test_connection` could mislabel a programmer error — accepted: the scrubbed original message is retained (bug not hidden) and the broad catch guarantees no secret leak at the credentials boundary
- [x] [Review][Dismiss] Short/substring passwords over-scrub error text — cosmetic only, no security impact; scrubbing is kept (security first)

## Dev Notes

### Previous story intelligence (Story 1.1 — DONE)

- The package, hexagonal layering (`core → ports → domain`), import-linter contracts, config module, RNG, plugin registry, and Typer CLI shell already exist. **Reuse them — do not recreate.**
- `EngineAdapter` is already defined as a `@runtime_checkable Protocol` in `src/tymi/ports/__init__.py` with `introspect`/`sample(*, rng)`/`load` and the three `supports_*` flags. Implement against it structurally (no inheritance needed).
- `load_engines()` / `load_plugins(group)` already exist in `src/tymi/core/plugins.py` (uses `importlib.metadata.entry_points(group=...)`).
- CLI stub pattern is in `src/tymi/cli/app.py`: `_STUB_COMMANDS` dict + `_make_stub`. Remove the `test-connection` entry when adding the real command; keep the other stubs.
- Config models use Pydantic v2 with `model_config = ConfigDict(extra="forbid")` and `Field` bounds — follow that pattern for `ConnectionConfig`. Errors subclass `TymiError`.
- Tests: `tests/unit/` pure, `tests/integration/` was created empty in 1.1 (only a `.gitkeep`).

### Architecture constraints (binding)

- **AD-2** — one bidirectional `EngineAdapter` per engine (read + write) with capability flags; source/destination are runtime roles. [Source: ARCHITECTURE-SPINE.md#AD-2]
- **AD-3** — discover via `tymi.engines` entry point; core imports no concrete adapter. The import-linter contract must stay green (the adapter lives in `tymi.engines`, which core/ports/domain must not import). [Source: ARCHITECTURE-SPINE.md#AD-3]
- **AD-9** — permissive deps only. pyodbc (MIT), SQLAlchemy (MIT), testcontainers (MIT) are all fine. [Source: ARCHITECTURE-SPINE.md#AD-9]
- **NFR-6** — credentials never persisted in plaintext; use env vars / secret managers. [Source: prd.md#NFR-6]

### Web research (verified mid-2026)

- **Versions/licenses:** pyodbc **5.3.0 (MIT)**, SQLAlchemy **2.0.51 (MIT)**, testcontainers-python **4.14.2 (MIT)** with the `[mssql]` extra. [Source: PyPI]
- **System dependency:** pyodbc needs an ODBC driver. Use **ODBC Driver 18 for SQL Server** (`msodbcsql18`). CI install (Debian/Ubuntu):
  ```bash
  curl -sSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
  curl -sSL https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
  sudo apt-get update && sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
  ```
- **⚠️ Driver-18 gotcha:** encryption is **ON by default** (changed vs. driver 17). Against test containers with self-signed certs you MUST set `TrustServerCertificate=yes` (or `Encrypt=no`) or connections fail with a TLS error. This is why `ConnectionConfig.trust_server_certificate` defaults to `True`.
- **URL form:** `mssql+pyodbc://<user>:<pass>@<host>:1433/<db>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes`. Prefer `sqlalchemy.URL.create("mssql+pyodbc", username=..., password=..., host=..., port=..., database=..., query={...})` so the password is handled by SQLAlchemy, not hand-formatted.
- **Connectivity check:** `with create_engine(url).connect() as c: c.execute(text("SELECT 1"))`.
- **testcontainers:** `from testcontainers.mssql import SqlServerContainer`; image `mcr.microsoft.com/mssql/server:2022-latest`; it sets `ACCEPT_EULA=Y` and the SA password and exposes `.get_connection_url()`. **SA password must meet complexity** (≥8 chars, 3 of 4: upper/lower/digit/symbol) or the container won't start.
- **Credential hygiene:** never log `get_connection_url()` or the engine URL (both embed the password). Redact with `engine.url.render_as_string(hide_password=True)`.

### Project Structure Notes

- New files: `src/tymi/engines/mssql.py`, `tests/unit/test_mssql_url.py`, `tests/integration/test_mssql_connectivity.py`.
- Modified: `pyproject.toml` (deps, entry point, pytest markers/addopts), `src/tymi/config/models.py`, `src/tymi/core/errors.py`, `src/tymi/cli/app.py`, `.github/workflows/ci.yml`.
- Keep `introspect`/`sample`/`load` as `NotImplementedError` — do not scope-creep schema/sampling (Stories 1.4/1.5).

### Testing standards

- Unit tests must not require a database or Docker (mock/skip). The URL/redaction logic is unit-testable with env vars only.
- Integration tests are `@pytest.mark.integration`, excluded from the default run, and skip gracefully without Docker/driver. CI runs them in a dedicated job with the ODBC driver installed.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-1 Story 1.2]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md — AD-2, AD-3, AD-9; EngineAdapter port]
- [Source: _bmad-output/planning-artifacts/prds/prd-tymi-2026-07-01/prd.md — FR-1, NFR-6]
- [Source: _bmad-output/implementation-artifacts/1-1-project-scaffold-and-hexagonal-skeleton.md — scaffold, ports, plugins, CLI, config patterns]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv sync` → added sqlalchemy 2.0.51, pyodbc 5.3.0, testcontainers 4.14.2 (+docker, pymssql).
- `uv run ruff check .` → All checks passed (added per-file B008 ignore for Typer's Option-in-default pattern).
- `uv run lint-imports` → 2 contracts kept, 0 broken (adapter isolated in `tymi.engines`).
- `uv run pytest` → 22 passed, 1 deselected (integration).
- `uv run pytest -m integration` → 1 skipped (no Docker locally, by design).
- CLI smoke: unknown engine → exit 2; unreachable MSSQL → exit 1 with actionable message and **no password in output** (verified even in the driver-missing case: "libodbc.so.2 …" surfaced cleanly, secret scrubbed).

### Completion Notes List

- Implemented the first concrete `EngineAdapter` (`MssqlAdapter`) — connectivity only; `introspect`/`sample`/`load` raise `NotImplementedError` for later stories (AD-2).
- `pyodbc` is not imported at module level; SQLAlchemy loads it lazily at connect, so URL/redaction logic is unit-testable without the ODBC driver.
- Credentials come only from env vars named in `ConnectionConfig` (no secret fields); missing env vars raise `EngineConnectionError` naming the variable (NFR-6). Errors scrub the password (`_scrub`) and rendered URLs use `hide_password=True`.
- Registered under the `tymi.engines` entry point (AD-3); real `test-connection` CLI command replaces the stub.
- Driver-18 encryption gotcha handled via `ConnectionConfig.trust_server_certificate=True` default.
- Tests: 6 URL/credential/redaction unit tests, 2 registration/protocol tests, 1 testcontainers integration test (Docker-gated). CI gains an `integration` job that installs `msodbcsql18`; the unit matrix stays Docker-free.
- All 7 ACs satisfied.

### File List

- `pyproject.toml` (modified — deps, entry point, pytest markers/addopts, ruff per-file-ignore)
- `.github/workflows/ci.yml` (modified — split unit / integration jobs)
- `src/tymi/engines/mssql.py` (new)
- `src/tymi/config/models.py` (modified — `ConnectionConfig`, `SourceConfig.connection`)
- `src/tymi/core/errors.py` (modified — `EngineError`, `EngineConnectionError`)
- `src/tymi/cli/app.py` (modified — real `test-connection` command)
- `tests/unit/test_mssql_url.py` (new)
- `tests/unit/test_engine_registration.py` (new)
- `tests/unit/test_plugins.py` (modified — engines group now has mssql)
- `tests/integration/test_mssql_connectivity.py` (new)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.2 — MSSQL EngineAdapter (connectivity), ConnectionConfig with env-var credentials, engine errors, real `test-connection` CLI, entry-point registration, unit + testcontainers integration tests, CI integration job. 22 unit tests pass; ruff + import-linter green. Status → review. |
| 2026-07-01 | Code review (3 adversarial layers, Edge Case Hunter rerun). Applied 6 patches: harden `_scrub` for URL-encoded secrets, broaden+scrub connection catch, reject `--engine`/`source.engine` mismatch, robust `load_config` file read, reject empty credential env vars, +error-path/CLI/config tests. 2 findings dismissed with rationale. 30 unit tests pass. Status → done. |

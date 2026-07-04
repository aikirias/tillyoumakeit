---
baseline_commit: 281838d
---

# Story 5.1: Streamlit App Shell and Connection Management

Status: done

## Story

As a user,
I want a browser app where I configure and test connections,
so that I can start without the CLI.

## Acceptance Criteria

1. **`tymi ui` launches the app** — a `tymi ui` CLI command starts the Streamlit app
   (in-process core; no separate API server / REST layer, AD-8).
2. **Add + test a connection** — the app has a connection form (engine + host/port/db +
   the *names* of the env vars holding credentials); a "Test connection" action builds the
   engine adapter in-process and reports success or an actionable failure.
3. **Credentials never shown in plaintext** — only env-var *names* are entered and stored
   (NFR-6); the app never accepts or displays a raw username/password.
4. **Stored in the shared Config** — a saved connection updates the one Pydantic `Config`
   held in session state — the same artifact the CLI loads (AD-5/AD-8 CLI↔UI parity), so
   later pages (profile/generate/chaos) read it.
5. **App shell** — a sidebar navigates the wizard steps (Connection → Profile → Generate →
   Chaos → Reports); steps beyond Connection are placeholders filled by Stories 5.2–5.5.

## Tasks / Subtasks

- [x] **Task 1: UI services** (`src/tymi/ui/services.py`) — `default_config`,
  `set_connection` (returns an updated `Config`, Pydantic-validated + normalized),
  `test_connection` (injectable engine registry → `ConnectionResult{ok,message}`, no
  credentials), `connection_summary` (env-var names only, for display).
- [x] **Task 2: App shell** (`src/tymi/ui/app.py`) — session-state `Config`, sidebar
  nav, `render_connection` page; placeholder pages for the later steps.
- [x] **Task 3: Launcher + CLI** (`src/tymi/ui/launch.py`, `src/tymi/cli/app.py`) —
  `build_ui_command` (pure, testable) + a real `tymi ui` command replacing the stub.
- [x] **Task 4: Tests** — services unit tests (set/validate/normalize connection,
  test-connection ok + failure + misbehaving-adapter via a fake adapter, no credentials
  in output); `AppTest` of the shell + connection page (save + test-connection button +
  nav); launcher command shape; `tymi ui --help`; Config YAML round-trip.
- [x] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Driving adapter, in-process (AD-1/AD-8).** `tymi.ui` is a driving adapter beside
  `tymi.cli`: it builds the same `Config` and calls the core library in-process. No REST
  layer (explicitly out of scope, PRD). Import-linter already forbids core/ports/domain
  from importing `tymi.ui`.
- **Testability split.** All logic lives in `services.py` as pure functions returning
  artifacts/results; `app.py` is a thin Streamlit view. The engine registry is injectable
  so tests use a fake adapter (no DB / testcontainer). `streamlit.testing.v1.AppTest`
  drives the view without a browser.
- **No secrets (NFR-6).** `ConnectionConfig` already stores only the env-var names that
  hold credentials; the UI mirrors that — the form collects `user_env`/`password_env`,
  never a raw secret, so nothing sensitive is entered or rendered.
- **Scope.** Shell + connection only. Profile/generate/chaos/report pages are placeholders
  here and delivered in 5.2–5.5.

### References

- [Source: epics.md#Epic-5 Story 5.1; FR-22]
- [Source: ARCHITECTURE-SPINE.md — AD-1, AD-5, AD-8; ports.EngineAdapter; Stack: Streamlit 1.x]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_ui_shell.py -q` → 18 passed.
- `uv run pytest -q` → full suite green; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Built `tymi.ui` as a driving adapter beside `tymi.cli`: a pure `services.py` controller,
  a thin `app.py` Streamlit view, and `launch.py`; a real `tymi ui` command. Tests use a
  fake engine registry and `streamlit.testing.v1.AppTest` (no DB, no browser).
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). Acceptance:
  all ACs met, no functional defects — added the suggested hardening (all placeholder
  steps, Test-connection button via injected registry, Config YAML round-trip). Findings
  applied:
  - **MED (Edge)** — a blank/whitespace host saved as a silent "success"; `set_connection`
    now strips + rejects an empty host and normalizes blank optionals (database → None,
    env-var names → the documented defaults).
  - **LOW (Blind + Edge)** — a misbehaving 3rd-party adapter raising a non-`TymiError`
    could crash the UI / echo a raw driver traceback (DSN leak); `test_connection` now has
    a generic-message catch-all (no raw text, NFR-6).
  - **LOW (Blind)** — corrected the `set_connection` docstring (`ValidationError`, not
    `ConfigError`).

### File List

- `src/tymi/ui/services.py` (new), `src/tymi/ui/app.py` (new), `src/tymi/ui/launch.py` (new).
- `src/tymi/cli/app.py` (modified) — real `ui` command; `_STUB_COMMANDS` emptied.
- `pyproject.toml` (modified) — `streamlit>=1.40` (Apache-2.0, AD-9).
- `tests/unit/test_ui_shell.py` (new) — 18 tests.
- `tests/unit/test_cli_smoke.py` (modified) — `ui` is now a real command, not a stub.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 5.1 — Streamlit app shell + connection management. |
| 2026-07-04 | Implemented services + app + launcher + `tymi ui`; passed the 3-layer gate (blank-host guard, no-leak catch-all, test hardening). Status → done. |

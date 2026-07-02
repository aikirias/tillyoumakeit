# Dev container

A reproducible environment that runs the **entire** TYMI stack — including the
parts that need native drivers and Docker — so `uv run pytest -m integration`
works out of the box (the local host was missing `libodbc.so.2`).

## What's inside

| Piece | Why |
| --- | --- |
| Debian 12 + **Python 3.12** (`mcr.microsoft.com/devcontainers/python`) | Matches `requires-python >=3.11` (CI runs 3.11–3.13). |
| **uv** (Astral) | Packaging / dependency management (`uv sync`, `uv run`). |
| **ODBC Driver 18 for SQL Server** (`msodbcsql18` + `unixodbc-dev`) | Provides `libodbc.so.2`; without it `import pyodbc` and the MSSQL integration tests fail. The adapter defaults to this exact driver name. |
| **Docker-in-Docker** feature | `testcontainers` spins up `postgres:16-alpine` / `mysql:8.4` for the integration tests. |

## Usage

Open the folder in VS Code → **Reopen in Container** (or GitHub Codespaces).
On first create, `post-create.sh` runs automatically: it `uv sync`s, verifies the
native imports + ODBC driver, and runs ruff + import-linter + the unit tests.

### Commands

```bash
uv run pytest                 # unit tests (integration excluded by default)
uv run pytest -m integration  # integration tests (Docker + ODBC; all engines)
uv run ruff check .           # lint
uv run lint-imports           # hexagonal import contracts
uv run tymi --help            # the CLI
```

## Notes

- The venv lives at `.venv/` inside the workspace so the VS Code Python
  extension picks it up automatically.
- The MS ODBC driver is installed from `packages.microsoft.com/config/debian/12`
  — bump the `12` if the base image's Debian release changes.
- This mirrors the CI workflow (`.github/workflows/ci.yml`), which installs the
  same driver on the Ubuntu runner for the integration job.

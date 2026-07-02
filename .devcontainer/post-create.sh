#!/usr/bin/env bash
# Provision + smoke-test the dev container: install dependencies, confirm the
# native/ODBC stack imports, and run the lint + unit gates. Integration tests
# (Docker/testcontainers) are printed as a follow-up command, not run here.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> uv sync (project + dev dependencies)"
uv sync

echo
echo "==> Tool versions"
uv run python --version
uv run ruff --version
echo -n "uv "; uv --version

echo
echo "==> Native / driver imports"
uv run python - <<'PY'
import numpy, scipy, pandas, pydantic, sqlalchemy, pymysql, psycopg, pyodbc
print("core imports OK — pyodbc", pyodbc.version)
PY

echo
echo "==> Installed ODBC drivers (MSSQL engine needs 'ODBC Driver 18 for SQL Server')"
odbcinst -q -d || echo "(odbcinst not found)"

echo
echo "==> Lint (ruff) + import contracts (import-linter)"
uv run ruff check .
uv run lint-imports

echo
echo "==> Unit tests"
uv run pytest -q

echo
echo "==> Docker (for integration / testcontainers)"
if docker version >/dev/null 2>&1; then
  echo "Docker daemon reachable — integration tests can run:"
else
  echo "Docker daemon not ready yet (it starts with the container). Integration tests:"
fi
echo "    uv run pytest -m integration"

echo
echo "Dev container ready."

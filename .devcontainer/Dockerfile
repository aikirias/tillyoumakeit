# TYMI dev container.
#
# Debian 12 (bookworm) + Python 3.12, plus everything the full test suite needs:
#   - uv (Astral) for packaging / dependency management
#   - Microsoft ODBC Driver 18 for SQL Server (pyodbc / the MSSQL engine) — this
#     provides libodbc.so.2, without which `import pyodbc` and the MSSQL
#     integration tests fail.
# Docker (for testcontainers-based integration tests) is provided by the
# docker-in-docker devcontainer feature, see devcontainer.json.
FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# --- Microsoft ODBC Driver 18 for SQL Server -------------------------------
# The MSSQL adapter defaults to "ODBC Driver 18 for SQL Server" (msodbcsql18).
ENV ACCEPT_EULA=Y
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl gnupg apt-transport-https ca-certificates; \
    curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg; \
    curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
      | tee /etc/apt/sources.list.d/mssql-release.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev; \
    rm -rf /var/lib/apt/lists/*

# --- uv --------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy (not hardlink) into the container's mounted volume, and keep the venv
# inside the workspace so the VS Code Python extension finds it.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspaces/tillyoumakeit/.venv

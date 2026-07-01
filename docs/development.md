# Development

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency and environment management
- Docker (only for the integration tests)

## Setup

```bash
uv sync            # create the venv and install runtime + dev dependencies
uv run tymi --help # sanity check the CLI
```

## Everyday commands

```bash
uv run ruff check .        # lint
uv run lint-imports        # enforce the hexagonal dependency contracts
uv run pytest              # unit tests (integration tests are excluded by default)
uv run pytest -m integration   # integration tests (needs Docker + the ODBC driver)
```

## Project layout (hexagonal / ports & adapters)

```text
src/tymi/
  domain/   # shared artifacts (Dataset, Schema, Profile, …) — the base layer
  ports/    # abstract interfaces (EngineAdapter, Synthesizer, Mutator, …)
  core/     # the brain: pipeline orchestrator, RNG, plugin registry, errors
  engines/  # concrete DB adapters (mssql, …)          [plugins: tymi.engines]
  chaos/    # fault mutators                            [plugins: tymi.mutators]
  profiling/ synth/ privacy/ eval/ io/                  # pipeline stages
  config/   # Pydantic config models + YAML loader
  cli/      # Typer command-line app  (driving adapter)
  ui/       # Streamlit web app       (driving adapter)
tests/
  unit/ integration/ statistical/
```

**Dependency rule (enforced by import-linter):** `core → ports → domain`.
The core and ports never import a concrete adapter package; adapters are
discovered at runtime via entry points.

## Adding an engine or a mutator (plugin)

1. Implement the relevant port (`EngineAdapter` for an engine, `Mutator` for a
   fault) in `src/tymi/engines/` or `src/tymi/chaos/`.
2. Register it under the entry-point group in `pyproject.toml`:
   ```toml
   [project.entry-points."tymi.engines"]
   mysql = "tymi.engines.mysql:MySqlAdapter"
   ```
3. `uv sync` so the entry point is registered. The core will discover it via
   `load_engines()` / `load_mutators()` — no core changes needed.

## Conventions

- Only permissively-licensed dependencies (MIT / Apache-2.0 / BSD /
  LGPL-as-dynamic-dep). **SDV and Copulas are excluded** (BUSL-1.1).
- All randomness flows through a single seeded `numpy.random.Generator` passed
  explicitly (keyword-only `rng`). No global random state.
- Config is validated by Pydantic (`extra="forbid"`); errors subclass
  `TymiError`.
- Credentials come from environment variables named in the config — never stored
  in any artifact, and never printed in logs or error messages.

## CI

`.github/workflows/ci.yml` runs two jobs on every push/PR:

- **unit** — ruff + import-linter + pytest across Python 3.11–3.13 (no Docker).
- **integration** — installs the MSSQL ODBC driver and runs `pytest -m integration`.

## Codebase intelligence (repowise)

The repo is indexed by [repowise](https://repowise.dev) — a dependency graph,
git-history, dead-code and docs layer exposed to Claude Code (and any
MCP-compatible agent). It is a **development tool only**, installed separately
(not a TYMI dependency), so it does not affect the runtime license posture
(repowise itself is AGPL-3.0; TYMI's own dependencies stay permissive).

```bash
uv tool install repowise      # one-time, per machine
repowise init --index-only    # (re)build the index after significant changes
repowise serve                # optional local dashboard at http://localhost:3000
```

Committed to the repo: `.mcp.json` (the MCP server registration) and
`.claude/CLAUDE.md` (auto-generated codebase-intelligence instructions, between
the `REPOWISE` markers). Generated and **git-ignored**: the `.repowise/` index
and caches — regenerate them with `repowise init`. Re-index after large changes
to keep the generated context fresh.

---
baseline_commit: b5e5065f1b46d731c12927fbdd67665a51f0ff08
---

# Story 1.1: Project scaffold and hexagonal skeleton

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want a uv-managed `tymi` package with the hexagonal skeleton, config loader, a CLI shell, seeded-RNG plumbing, and CI,
so that every later story has a consistent, import-safe, testable base to build on.

## Acceptance Criteria

1. **Installable package.** `uv sync` succeeds and `uv run tymi --help` prints the (stubbed) subcommands with exit code 0. The package is `src`-layout, named `tymi`, requiring Python ≥ 3.11.
2. **Dependency direction enforced.** `tymi.core` imports only from `tymi.ports` (and stdlib/third-party) — never from adapter packages (`tymi.engines`, `tymi.synth`, `tymi.chaos`, `tymi.privacy`, `tymi.eval`, `tymi.io`, `tymi.cli`, `tymi.ui`). This is enforced by an automated import-lint contract that fails CI on violation. [AD-1]
3. **Versioned config.** A Pydantic-v2 `Config` model loads from a YAML file, carries a semver `schema_version`, and the loader **rejects an unknown major version** with a typed error. [AD-5]
4. **Seeded RNG plumbing.** A single `numpy.random.Generator` is created from `config.seed` by a core factory; the same seed produces the same first draws (unit-tested). No module uses global `random`/`np.random.*`. [AD-4, AD-11]
5. **Ports defined.** `tymi.ports` declares the seven Port interfaces (`EngineAdapter`, `Synthesizer`, `Mutator`, `PIIClassifier`, `PrivacyFilter`, `Evaluator`, `Exporter`) as abstract types; every stochastic method takes a keyword-only `rng: numpy.random.Generator`; `EngineAdapter` exposes `introspect`/`sample`/`load` plus capability flags. [AD-2, AD-11]
6. **Plugin groups declared.** `pyproject.toml` declares (initially empty) entry-point groups `tymi.engines` and `tymi.mutators`; a core registry loads them via `importlib.metadata` and returns an empty registry cleanly. [AD-3]
7. **CI green.** A CI workflow runs on every push: `uv sync`, `ruff check`, the import-lint contract, and `pytest` — all passing on the scaffold.

## Tasks / Subtasks

- [x] **Task 1: uv project + package skeleton** (AC: 1, 2)
  - [x] `uv init` an application/package; author `pyproject.toml` with `[project]` (name `tymi`, `requires-python = ">=3.11"`), runtime deps (`typer`, `pydantic`, `pyyaml`, `numpy`), and a `[project.scripts]` `tymi = "tymi.cli.app:app"`.
  - [x] Create `src/tymi/` with subpackages, each with `__init__.py`: `core/`, `ports/`, `engines/`, `profiling/`, `synth/`, `chaos/`, `privacy/`, `eval/`, `io/`, `config/`, `cli/`, `ui/`.
  - [x] Create `tests/` with `unit/`, `integration/`, `statistical/` and an empty `conftest.py`.
- [x] **Task 2: Config module** (AC: 3)
  - [x] `tymi/config/models.py`: Pydantic-v2 `Config` model with at least `schema_version: str`, `seed: int | None`, and nested placeholders (`source`, `generation`, `chaos`) as optional sub-models.
  - [x] `tymi/config/loader.py`: `load_config(path) -> Config` reading YAML (`yaml.safe_load`), validating, and raising `ConfigVersionError` when the file's `schema_version` major ≠ the supported major.
  - [x] `tymi/core/errors.py`: base `TymiError(Exception)` and subclasses (`ConfigError`, `ConfigVersionError`). All raised errors subclass `TymiError`. [Conventions: typed errors]
- [x] **Task 3: Core skeleton + seeded RNG** (AC: 4)
  - [x] `tymi/core/rng.py`: `make_rng(seed: int | None) -> numpy.random.Generator` wrapping `numpy.random.default_rng(seed)`.
  - [x] `tymi/core/artifacts.py`: dataclasses/Pydantic stubs for `Schema` (per-column logical type + engine-agnostic dtype), `Dataset` (`pandas.DataFrame` + `Schema`), `Profile`, `FidelityReport`, `FaultManifest` — fields may be minimal but the types must exist and be importable. [AD-10]
  - [x] `tymi/core/pipeline.py`: `Orchestrator` skeleton with a `run(config, rng)` method stub raising `NotImplementedError` for the stages `connect→profile→generate→gate→evaluate→export`. [AD-8]
  - [x] Ensure `tymi/core/**` imports only `tymi.ports`, stdlib, and third-party — never adapter packages. [AD-1]
- [x] **Task 4: Ports module** (AC: 5)
  - [x] `tymi/ports/__init__.py` (or per-file): abstract interfaces using `typing.Protocol` or `abc.ABC`:
    - `EngineAdapter`: `introspect()`, `sample(*, rng)`, `load(...)`, and capability flags `supports_introspect`/`supports_sample`/`supports_write`. [AD-2]
    - `Synthesizer.generate(*, rng, ...)`, `Mutator.apply(*, rng, ...)`, `PIIClassifier.classify(...)`, `PrivacyFilter.filter(...)`, `Evaluator.evaluate(...)`, `Exporter.export(...)`.
  - [x] Every stochastic method signature takes keyword-only `rng: numpy.random.Generator`. [AD-11]
- [x] **Task 5: Plugin registry** (AC: 6)
  - [x] `tymi/core/plugins.py`: `load_plugins(group: str) -> dict[str, type]` via `importlib.metadata.entry_points(group=...)`; helpers `load_engines()` / `load_mutators()` returning `{}` cleanly when none are installed. Core imports no concrete adapter. [AD-3]
  - [x] Declare empty `[project.entry-points."tymi.engines"]` and `[project.entry-points."tymi.mutators"]` tables in `pyproject.toml`.
- [x] **Task 6: CLI shell** (AC: 1)
  - [x] `tymi/cli/app.py`: Typer `app` with stub subcommands `test-connection`, `schema`, `sample`, `profile`, `generate`, `chaos`, `report`, `export`, `ui`; each prints "not implemented yet" and exits non-zero (e.g. code 2) so CI can distinguish stubs from real success later.
  - [x] `tymi --help` exits 0 and lists all subcommands.
- [x] **Task 7: Import-lint contract** (AC: 2, 7)
  - [x] Add dev dep `import-linter`; add `[tool.importlinter]` with a **forbidden** contract: `tymi.core` must not import `tymi.engines|synth|chaos|privacy|eval|io|cli|ui`; and a **layers** contract with `tymi.ports` below `tymi.core`.
  - [x] Add a pytest wrapper `tests/unit/test_import_contracts.py` that shells out to `lint-imports` (or asserts a violation-free run) so the contract is also enforced in `pytest`.
- [x] **Task 8: Tests + CI** (AC: 1, 3, 4, 7)
  - [x] `tests/unit/test_cli_smoke.py`: `tymi --help` returns exit 0 and mentions each subcommand (use Typer's `CliRunner`).
  - [x] `tests/unit/test_config.py`: valid YAML loads; unknown major `schema_version` raises `ConfigVersionError`.
  - [x] `tests/unit/test_rng.py`: `make_rng(42)` and `make_rng(42)` produce identical first draws; different seeds differ.
  - [x] `.github/workflows/ci.yml`: on push/PR — set up uv + Python 3.11–3.13 matrix, `uv sync`, `uv run ruff check`, `uv run lint-imports`, `uv run pytest`.
  - [x] Add `[tool.ruff]` config; add a `README`-level dev note in `pyproject` or `CONTRIBUTING` only if trivial (do not expand scope).

## Dev Notes

### Architecture constraints (binding — from the spine)

- **Paradigm:** Hexagonal (Ports & Adapters) + pipes-and-filters. `tymi.core` = brain; `tymi.ports` = interfaces; adapters implement ports. Dependencies point **inward only**. [Source: ARCHITECTURE-SPINE.md#Design-Paradigm]
- **AD-1** core imports only ports — this story stands up the import-lint that guarantees it for all future work. [Source: ARCHITECTURE-SPINE.md#AD-1]
- **AD-3** engines/mutators are discovered via entry points (`tymi.engines`, `tymi.mutators`); core never imports a concrete adapter. Registry is created here (empty is valid). [Source: ARCHITECTURE-SPINE.md#AD-3]
- **AD-4 / AD-11** one seeded `numpy.random.Generator`, passed explicitly as keyword-only `rng`; no global random state. Establish the factory + the Port signature convention now. [Source: ARCHITECTURE-SPINE.md#AD-4]
- **AD-5** Config is Pydantic-v2 + YAML with semver `schema_version`; reject unknown major. Per-plugin param schemas come later (when plugins exist). [Source: ARCHITECTURE-SPINE.md#AD-5]
- **AD-10** canonical `Dataset` = `DataFrame` + `Schema`; define the types now so later stages share them. [Source: ARCHITECTURE-SPINE.md#AD-10]
- **AD-2** `EngineAdapter` is one bidirectional interface with capability flags; only the **interface** is defined here, concrete engines are Stories 1.2–1.3. [Source: ARCHITECTURE-SPINE.md#AD-2]
- **AD-9** permissive-license-only deps. Everything added here (typer, pydantic, pyyaml, numpy, ruff, pytest, import-linter) is MIT/BSD/Apache. Do **not** add SDV or Copulas (BUSL-1.1). [Source: ARCHITECTURE-SPINE.md#AD-9]

### Conventions [Source: ARCHITECTURE-SPINE.md#Consistency-Conventions]

- `snake_case` modules/functions, `PascalCase` classes; Port names are nouns (`EngineAdapter`, `Exporter`); artifact types match Glossary (`Profile`, `Dataset`, `FaultManifest`, `FidelityReport`).
- Errors are typed `TymiError` subclasses — never bare strings/exceptions.
- Config only via Pydantic; dates ISO-8601; `seed` is an `int`.

### Source tree (target for this story) [Source: ARCHITECTURE-SPINE.md#Structural-Seed]

```text
tymi/
  pyproject.toml
  .github/workflows/ci.yml
  src/tymi/
    core/    { errors, rng, artifacts, pipeline, plugins }
    ports/   { the 7 Port interfaces }
    engines/ profiling/ synth/ chaos/ privacy/ eval/ io/ config/ cli/ ui/   # (stub __init__ + config, cli filled)
  tests/ { unit/, integration/, statistical/ }
```

Create **only** the scaffold + the modules named in the tasks. Other subpackages get a stub `__init__.py` (and a short `# TODO(Story x.y)` docstring). Do not implement engines, synthesis, chaos, etc. here — those are later stories.

### Tech stack & versions [Source: ARCHITECTURE-SPINE.md#Stack]

- Python 3.11+ (CI matrix 3.11–3.13); **uv** for packaging/deps/venv.
- Runtime: `typer` ~0.24, `pydantic` ~2.13, `pyyaml`, `numpy`. (`pandas` is referenced by `artifacts.py` types — add it now as a runtime dep.)
- Dev: `pytest`, `ruff`, `import-linter`. Pin to the latest stable at implementation time; verify on PyPI before pinning.

### Testing standards

- `pytest`; unit tests live in `tests/unit/` and are pure (no DB, no network). Integration (`testcontainers`) and statistical-validation tests arrive in later stories — create the empty dirs only.
- Every AC in this story is covered by a unit test (CLI smoke, config version, RNG determinism, import contract).

### Project Structure Notes

- Greenfield — **no external starter template** (architecture chose a custom hexagonal scaffold). This story *is* the initial project setup. [Source: epics.md#Additional-Requirements: "No external starter template"]
- `src`-layout is intentional (keeps import hygiene and matches the import-lint contract).
- **Variance (rationale):** the spine's structural seed placed the canonical artifacts under `core/`. During implementation this created a layering conflict — `tymi.ports` must reference the artifact types (`Dataset`, `Schema`, …), so keeping them in `core` would force `ports → core`, violating the inward-only direction. Resolved by extracting the shared artifacts into a new lowest layer **`tymi.domain`**, giving a clean acyclic layering **`core → ports → domain`**. This preserves AD-1's intent (core/ports never import adapters) and AD-10 (canonical Dataset/Schema). The import-linter `layers` contract encodes it.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-1 / Story 1.1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md — AD-1..AD-12, Stack, Structural Seed, Conventions]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-tymi-2026-07-01/solution-design.md — plain-language overview]
- [Source: _bmad-output/planning-artifacts/prds/prd-tymi-2026-07-01/prd.md — FR-19 (config), FR-20 (CLI), FR-21 (library), NFR-4 (reproducibility), NFR-5 (extensibility)]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv sync` — resolved & installed (typer 0.26.8, pydantic 2.13.4, numpy 2.5.0, pandas 3.0.3, pytest 9.1.1, ruff 0.15.20, import-linter).
- `uv run ruff check .` → All checks passed (scoped to `src`/`tests`; `_bmad*`/`.claude` excluded).
- `uv run lint-imports` → 2 contracts kept, 0 broken.
- `uv run pytest -q` → 11 passed.
- `uv run tymi --help` → exit 0, lists all 9 subcommands.

### Completion Notes List

- Built the greenfield `tymi` package (src-layout, uv/hatchling), hexagonal skeleton with `core → ports → domain` layering enforced by import-linter (AD-1).
- Config: Pydantic v2 models + YAML loader; rejects unknown `schema_version` major with `ConfigVersionError` (AD-5). Seeded `numpy` RNG factory (AD-4/AD-11). Canonical `Dataset`/`Schema` artifacts (AD-10). Plugin registry via entry points, empty by default (AD-3). Typer CLI shell with 9 stub subcommands. All deps permissive (AD-9; no SDV/Copulas).
- **Design decision:** extracted shared artifacts to a new `tymi.domain` layer to keep ports independent of core (see Project Structure Notes → Variance).
- All 7 ACs satisfied; every AC covered by a unit test (11 tests total). CI workflow added (uv + Python 3.11–3.13 matrix; ruff + lint-imports + pytest).

### File List

- `pyproject.toml` (new)
- `.github/workflows/ci.yml` (new)
- `src/tymi/__init__.py` (new)
- `src/tymi/core/__init__.py`, `core/errors.py`, `core/rng.py`, `core/plugins.py`, `core/pipeline.py` (new)
- `src/tymi/domain/__init__.py`, `domain/artifacts.py` (new)
- `src/tymi/ports/__init__.py` (new)
- `src/tymi/config/__init__.py`, `config/models.py`, `config/loader.py` (new)
- `src/tymi/cli/__init__.py`, `cli/app.py` (new)
- `src/tymi/{engines,profiling,synth,chaos,privacy,eval,io,ui}/__init__.py` (new stubs)
- `tests/unit/test_cli_smoke.py`, `test_config.py`, `test_rng.py`, `test_import_contracts.py`, `test_plugins.py` (new)
- `tests/integration/.gitkeep`, `tests/statistical/.gitkeep` (new)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.1 — project scaffold + hexagonal skeleton (core/ports/domain), config, RNG, plugin registry, CLI shell, import-linter contracts, unit tests, CI. Status → review. |

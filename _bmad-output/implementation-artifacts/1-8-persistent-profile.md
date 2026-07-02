---
baseline_commit: 44d20740
---

# Story 1.8: Persistent, versioned Profile

Status: done

## Story

As a user,
I want to save and load a Profile file,
so that I can regenerate data later without reconnecting to the source.

## Acceptance Criteria

1. **Save** — `tymi profile <table> -o profile.yaml` writes the Profile to a YAML
   file (human-inspectable, UTF-8), carrying its `schema_version`.
2. **Load (offline)** — `tymi profile --load profile.yaml` reads a saved Profile
   and prints it, with **no source connection** (no engine/config/table needed).
3. **Round-trip** — `load_profile(save_profile(p)) == p`: the Profile reconstructs
   with identical values (schema, per-column stats, correlations), including the
   `schema_version`.
4. **Version gating** — loading a Profile whose `schema_version` major is not
   supported raises a typed `ProfileVersionError` (mirrors the config loader);
   malformed/unreadable files raise `ProfileError`.
5. **Offline consumption** — a loaded Profile is a fully-populated domain object;
   downstream generation (Epic 2) can consume it without touching the source.
6. **No raw values (AD-6)** — persistence changes representation only; the file
   contains exactly the aggregates already in the Profile, never raw values.
7. **Verified end-to-end** — an integration test profiles a real
   PostgreSQL/MySQL table, saves it, loads it back **offline**, and asserts the
   loaded Profile equals the in-memory one.

## Tasks / Subtasks

- [x] **Task 1: Typed errors** (`src/tymi/core/errors.py`) — add
  `ProfileError(TymiError)` and `ProfileVersionError(ProfileError)`.
- [x] **Task 2: Profile IO** (`src/tymi/profiling/profile_io.py`) —
  `save_profile(profile, path)` (serialize via the existing JSON projection →
  plain types → `yaml.safe_dump`, so tuples/enums never reach the dumper) and
  `load_profile(path) -> Profile` (typed reconstruction of the nested dataclasses;
  `schema_version` major gate; `ProfileError` on unreadable/malformed YAML).
- [x] **Task 3: CLI save/load** (`src/tymi/cli/app.py`) — add `-o/--out` (write
  YAML) and `--load` (read a saved Profile offline, skipping the DB) to the
  `profile` command; make `table/--engine/--config` optional and validate that
  the DB path has them (or use `--load`).
- [x] **Task 4: Unit tests** — round-trip equality (numeric/categorical/datetime/
  text + correlations), version gate (unsupported major → `ProfileVersionError`),
  malformed YAML → `ProfileError`, AD-6 (no raw values in the file), `--load`
  CLI path prints without a DB.
- [x] **Task 5: Integration test** — PostgreSQL + MySQL: profile a real table,
  save, load offline, assert equality.

## Dev Notes

- `save_profile` reuses `profile_to_json` then `json.loads` to obtain plain
  dict/list/str/number types before `yaml.safe_dump` — `SafeDumper` cannot
  serialize tuples or `StrEnum`, so the JSON projection is the normalization step.
- `load_profile` rebuilds the frozen dataclasses explicitly (typed builders per
  artifact) rather than via reflection: safer, and it coerces YAML-loaded numbers
  to the declared `float`/`int` so round-trip equality holds.
- Version gate mirrors `config/loader.py`: `PROFILE_SCHEMA_MAJOR = 1`; a
  mismatched or malformed major raises `ProfileVersionError`.
- The `Profile.schema_version` field already exists (default `"1.0.0"`); this
  story makes it round-trip and enforces it on load.
- Persistence is representation-only; AD-6 holds because we serialize exactly the
  in-memory aggregates.

### References

- [Source: epics.md#Epic-1 Story 1.8]
- [Source: ARCHITECTURE-SPINE.md — AD-5 (schema_version gating), AD-6 (no raw
  values), AD-10 (canonical artifacts)]
- [Source: config/loader.py — version-gate pattern]
- [Source: 1-7-correlation-detection.md — full Profile model]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) — bmad-dev-story

### Debug Log References

- `uv run ruff check .` / `uv run lint-imports` → clean; 2 contracts kept
  (`tymi.profiling.profile_io` imports `tymi.domain` + `tymi.core.errors` + yaml).
- `uv run pytest tests/unit` → 104 unit passed (round-trip incl. rich Schema +
  correlations, version gate, malformed-shape → `ProfileError`, offline `--load` CLI).
- `uv run pytest -m integration -k persistence` → 2 passed (real `postgres:16-alpine`
  + `mysql:8.4`): profile → save → load offline → `==`.

### Completion Notes List

- Persisted Profile as versioned YAML: `save_profile` normalizes via the JSON
  projection (tuples→lists, `StrEnum`→str) before `yaml.safe_dump`; `load_profile`
  rebuilds the dataclasses with typed builders and gates on `schema_version` major.
- Offline consumption proven: `tymi profile --load profile.yaml` prints a fully
  reconstructed Profile with no engine/config/table and no DB connection.
- Round-trip identity holds (`load(save(p)) == p`) for a fully-populated Profile —
  per-column stats + numeric & categorical correlations + Schema with
  PK/FK/unique-of-tuples/indexes — verified on real PostgreSQL and MySQL.
- AD-6 upheld: persistence is representation-only; the file holds exactly the
  in-memory aggregates (verified free-text values are absent).
- Adversarial review: fixed 1 HIGH (raw `AttributeError` on wrong-shaped sections
  now surfaces as `ProfileError`) + 1 MEDIUM (`--load` + `-o` now rejected instead
  of silently ignoring `-o`). All 7 ACs satisfied. **Epic 1 complete.**

### File List

- `src/tymi/core/errors.py` (modified — `ProfileError`, `ProfileVersionError`)
- `src/tymi/profiling/profile_io.py` (new — `save_profile` / `load_profile`)
- `src/tymi/cli/app.py` (modified — `profile` gains `-o/--out` + offline `--load`)
- `tests/unit/test_profile_io.py` (new)
- `tests/integration/test_profile_persistence_integration.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-01 | Implemented Story 1.8 — persistent, versioned Profile (`save_profile`/`load_profile` YAML round-trip, `schema_version` gate, typed `ProfileError`/`ProfileVersionError`); `tymi profile -o` saves and `--load` reads offline. 99 unit + real PG/MySQL round-trip integration tests pass. Status → review. |
| 2026-07-01 | Adversarial review: 1 HIGH (raw `AttributeError` on malformed-shape files → now `ProfileError`) + 1 MEDIUM (`--load` + `-o` → now rejected) fixed, + tests. 104 unit tests pass; integration re-verified. Status → done. Epic 1 complete. |

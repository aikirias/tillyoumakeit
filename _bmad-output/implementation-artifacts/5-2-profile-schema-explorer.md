---
baseline_commit: a8f01bf
---

# Story 5.2: Profile and Schema Explorer

Status: done

## Story

As a user,
I want to browse tables, schema, and detected distributions,
so that I understand my data before generating.

## Acceptance Criteria

1. **Profile a table from the UI** — with a connection configured, entering a table name
   and clicking "Profile" samples + profiles it in-process and stores the resulting
   `Profile` in the shared session state.
2. **Schema view** — the page shows the introspected/normalized Schema (column name,
   logical type, nullability, primary-key flag).
3. **Per-column distribution charts** — each column renders a distribution view from the
   Profile's stored aggregates: numeric → histogram, categorical → top-category
   frequencies, datetime → day-of-week/month frequency, text → length summary.
4. **Same artifact as the CLI** — the Profile the UI builds is byte-for-byte the artifact
   `tymi profile` produces (same `profile_dataset` call, AD-8), so it round-trips through
   `save_profile`/`load_profile` and feeds the later steps.
5. **No connection → clear guidance** — with no connection yet, the page tells the user to
   configure one first (no crash).

## Tasks / Subtasks

- [x] **Task 1: Services** (`src/tymi/ui/services.py`) — `run_profile` (adapter →
  sample → `profile_dataset`, mirroring the CLI), `schema_table` (Schema → display rows),
  `profile_charts` (per-`ColumnProfile` chart data), `ColumnChart` dataclass.
- [x] **Task 2: App page** (`src/tymi/ui/app.py`) — `render_profile`: table/rows/seed
  form, profile action, schema table + per-column charts; store `Profile` in session.
- [x] **Task 3: Tests** — `run_profile` equals `profile_dataset` on the same sample (same
  artifact), the non-empty sensitive-merge + `classify_pii` wiring, and round-trips
  through `save/load_profile`; chart builders for each column kind (incl. datetime month);
  `AppTest` of the page (profile → schema + charts render, no-leak on failure);
  no-connection guidance.
- [x] **Task 4: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Same Profile as the CLI (AD-8).** `run_profile` builds the adapter from the shared
  `Config`, samples with `adapter.sample(table, rows, rng=make_rng(seed))`, and calls the
  same `profile_dataset(...)` the CLI's `profile` command calls — so the UI and CLI emit
  the identical `Profile` artifact (proven by a round-trip test), never a UI-only variant.
- **Charts come from the Profile, not raw rows (AD-6).** Distribution views are rendered
  from the Profile's stored aggregates (`NumericStats.histogram_*`, `CategoryFrequency`,
  `DatetimeStats.*_frequency`, `TextStats` lengths) — no raw sampled values are held or
  displayed, consistent with the privacy-safe Profile.
- **Testable split.** Chart/table builders are pure functions returning pandas frames /
  dataclasses; the engine registry is injectable so tests profile a canned Dataset with no
  DB; `AppTest` drives the page.
- **Scope.** Profile + schema + distribution views only. Generation/chaos/report pages are
  the later stories; browsing an arbitrary *table list* needs an engine `list_tables`
  capability the port doesn't expose (the user enters the table name), noted as a follow-up.

### References

- [Source: epics.md#Epic-5 Story 5.2; FR-22]
- [Source: ARCHITECTURE-SPINE.md — AD-6, AD-8; profiler.profile_dataset; domain ColumnProfile]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_ui_profile.py -q` → 10 passed.
- `uv run pytest -q` → 504 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added `run_profile` (byte-identical to the CLI `profile` wiring), `schema_table`, and
  `column_chart`/`profile_charts` to `services.py`; a `render_profile` page in `app.py`.
  Charts are built only from the Profile's stored aggregates (AD-6).
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). Acceptance:
  all 5 ACs met. Findings applied:
  - **MED (Blind + Edge)** — histogram bin labels collapsed to identical strings for a
    large-magnitude column (`1e6` bins), merging the bars; now `.4g` labels with a
    fall-back to `bin N` indices when they collide.
  - **MED (Blind)** — `render_profile` echoed a raw driver error that can embed a
    DSN/password; now surfaces only `ValueError`/`TymiError` text and a generic message
    for anything else (NFR-6, matching `test_connection`).
  - **LOW (Blind)** — a stale profile persisted after a failed re-profile; the page now
    clears `session_state["profile"]` before each attempt.
  - **LOW (Edge)** — a negative `seed` raised a cryptic numpy error; `run_profile` now
    validates `seed >= 0`.
  - **Acceptance narrowing** — the datetime chart now also renders `month_frequency`
    (AC-3 named it); added the non-empty sensitive-merge/`classify_pii` parity test and an
    AppTest assertion that the distribution section renders.
- Accepted (documented): a frame whose columns don't match the schema raises inside
  `profile_dataset` (an adapter-contract violation) and is surfaced by the page's generic
  catch-all; browsing an arbitrary *table list* needs an engine `list_tables` capability
  the port doesn't expose (the user types the table name).

### File List

- `src/tymi/ui/services.py` (modified) — `run_profile`, `schema_table`, `column_chart`,
  `profile_charts`, `ColumnChart`.
- `src/tymi/ui/app.py` (modified) — `render_profile` page + wiring.
- `tests/unit/test_ui_profile.py` (new) — 10 tests.
- `tests/unit/test_ui_shell.py` (modified) — placeholder-step tests updated (Profile is
  now a real page).

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 5.2 — profile & schema explorer. |
| 2026-07-04 | Implemented services + profile page; passed the 3-layer gate (unique histogram labels, no-leak errors, stale-profile clear, month-frequency chart). Status → done. |

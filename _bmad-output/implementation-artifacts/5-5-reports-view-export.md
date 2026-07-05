---
baseline_commit: f5f436d
---

# Story 5.5: Reports View and Export

Status: done

## Story

As a user,
I want to view reports and export results from the UI,
so that I can finish the whole flow in the browser.

## Acceptance Criteria

1. **Reports panel** — with a generated Dataset in session, the Reports page shows the
   right report: for a **faithful** run the Fidelity Report + Quality & Privacy Report;
   for a **chaos** run the Fault Manifest.
2. **Export to files** — the previewed Dataset can be exported to `csv` / `json` /
   `parquet` and downloaded, byte-identical to the CLI exporter (NFR-4).
3. **Load into any engine** — the Dataset can be loaded into the configured engine
   (`adapter.load`), the same destination path the CLI `--to sql` uses (AD-2).
4. **Same artifacts as the CLI (AD-8)** — the reports are the exact `FidelityReport` /
   `QualityPrivacyReport` / `FaultManifest` the CLI produces; exports go through the same
   deterministic exporters.
5. **Nothing generated → guidance** — with no generated/chaotic Dataset yet, the page
   directs the user to the Generate or Chaos step (no crash).

## Tasks / Subtasks

- [x] **Task 1: Services** (`src/tymi/ui/services.py`) — `faithful_reports`,
  `manifest_table`, `export_bytes` (deterministic exporter → bytes), `load_to_engine`,
  `EXPORT_FORMATS`.
- [x] **Task 2: App page** (`src/tymi/ui/app.py`) — `render_reports`: faithful/chaos
  selection from session (+ a "Report for" toggle when both are present), the reports, and
  an export section (download per format + load-into-engine).
- [x] **Task 3: Tests** — `faithful_reports` returns the CLI artifacts; `manifest_table`
  (incl. ragged-entry integer rows); `export_bytes` byte-identical to the CLI exporter +
  bad-format rejection; `load_to_engine` calls `adapter.load` (fake adapter) + guards;
  `AppTest` (faithful reports, chaos manifest, both-present toggle, export section,
  guidance).
- [x] **Task 4: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Same artifacts + exporters as the CLI (AD-8, NFR-4).** The reports call the identical
  `fidelity_report` / `quality_privacy_report` (Stories 2.7/4.3) and the manifest is the
  Story 3.6 `FaultManifest`; file export goes through `io.exporters.get_exporter`, so a
  UI download is byte-identical to `tymi generate --to csv/json/parquet`. Loading uses the
  configured engine adapter's `load` — the same destination path as `--to sql` (AD-2:
  source and destination are interchangeable).
- **Faithful vs chaos by session state (AD-12).** A `chaotic` Dataset + `manifest` in
  session means a chaos run → show the Fault Manifest; otherwise a `generated` Dataset +
  `profile` means a faithful run → show the fidelity + quality/privacy reports. This
  mirrors the Evaluate branch's `run_mode` discrimination.
- **Export via the exporter, not a UI re-serialization.** `export_bytes` runs the real
  exporter to a temp file and returns its bytes, so determinism/quirk-handling (dtype
  mapping from the canonical Schema, AD-10) is inherited rather than re-implemented.
- **Faithful/chaos selection.** With only one run in session the page shows its report
  directly; when BOTH a `generated`+`profile` and a `chaotic`+`manifest` are present a
  "Report for" toggle lets the user pick, so a chaos run never silently shadows the
  faithful reports.
- **Scope.** Reports + export/load for the in-session Dataset. A destination distinct from
  the source connection (separate destination config) is a follow-up — the wizard loads
  into the one configured connection, which is engine-agnostic (any of the four adapters,
  AD-2).

### References

- [Source: epics.md#Epic-5 Story 5.5; FR-22]
- [Source: ARCHITECTURE-SPINE.md — AD-2/AD-8/AD-10/AD-12; io.exporters; eval reports]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_ui_reports.py -q` → 11 passed.
- `uv run pytest -q` → 541 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added the report + export services and the `render_reports` page. Reports are the exact
  `fidelity_report` / `quality_privacy_report` / `FaultManifest` the CLI produces; file
  export runs the real `io.exporters.get_exporter` (byte-identical, NFR-4); loading uses
  the configured engine adapter's `load` (the CLI `--to sql` path, AD-2).
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). No HIGH/MED
  defects. Findings applied:
  - **Acceptance (AC-1 narrowing)** — a chaos run silently shadowed the faithful reports;
    added a "Report for" toggle (with stable radio keys) so both stay reachable when both
    runs are in session, plus its test.
  - **LOW (Blind)** — `_export_section` caught only `TymiError`; added a broad catch so an
    unexpected serializer error can't crash the page (symmetric with the load path).
  - **NIT (Blind)** — the fidelity/privacy pass-fail now honors the tolerance the user set
    in the Generate step (`Config.generation.tolerance`) instead of a hardcoded 0.9.
  - **LOW (Edge)** — `manifest_table` rendered `row` as `3.0` on ragged manifests; cast to
    nullable `Int64` so rows stay integers with `<NA>` for structural entries.
- Accepted (documented): `export_bytes` re-serializes on each render (Streamlit's
  download button needs the payload upfront) — fast for realistic sizes; loading targets
  the one configured connection (a distinct destination is a follow-up).

### File List

- `src/tymi/ui/services.py` (modified) — `faithful_reports`, `manifest_table`,
  `export_bytes`, `load_to_engine`, `EXPORT_FORMATS`.
- `src/tymi/ui/app.py` (modified) — `render_reports` + `_export_section`; stable keys on
  the wizard-step and report-mode radios.
- `tests/unit/test_ui_reports.py` (new) — 11 tests.
- `tests/unit/test_ui_shell.py` (modified) — placeholder-step tests replaced (all five
  steps are now real pages).

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 5.5 — reports view + export. |
| 2026-07-04 | Implemented report + export services and page; passed the 3-layer gate (faithful/chaos toggle, byte-identical export, engine load). Status → done. Completes Epic 5. |

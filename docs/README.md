# TYMI Documentation

Living documentation for **TYMI — Fake It Till You Make It**. Updated as the
project progresses; each story that changes behavior should update the relevant
page here.

## Contents

- [Overview](overview.html) — a single-page visual walkthrough of **all** of TYMI (faithful generator, chaos monkey, privacy & eval, reach, hexagonal architecture, test coverage, whole-DB provisioning). Open in a browser; shareable as an Artifact.
- [How It Works](how-it-works.md) — the concepts and the end-to-end flow (Profile, Config, pipeline, engines).
- [Provisioning](provisioning.md) — whole-DB obfuscated dev environments: the `Spec`, cross-team consistency, pinned fixtures, the non-prod guardrail, and `tymi provision` (PRD 1, Phase 1).
- [Development](development.md) — local setup, testing, CI, project layout, and how to add a plugin.
- [Status](status.md) — what is implemented today, mapped to epics and stories (MVP + PRD 1).

## Canonical planning artifacts

The product/technical planning lives under `_bmad-output/planning-artifacts/`:

### MVP

- PRD — `prds/prd-tymi-2026-07-01/prd.md`
- Architecture spine + solution design — `architecture/architecture-tymi-2026-07-01/`
- Epics & stories — `epics.md`

### PRD 1 — Obfuscated Prod-Like Dev Environments (Phase 1)

- PRD — `prds/prd-tymi-obfuscated-dev-env-2026-07-04/prd.md`
- Architecture spine (AD-13..21) — `architecture/architecture-tymi-pde1-phase1-2026-07-04/`
- Epics & stories — `epics-pde1-phase1.md`
- Per-story implementation records — `_bmad-output/implementation-artifacts/pde1-*.md`

This `docs/` folder is the human-facing, always-current explanation of the code
as it actually exists; the planning artifacts are the design of record.

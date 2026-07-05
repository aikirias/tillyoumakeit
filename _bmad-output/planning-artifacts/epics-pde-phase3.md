# PRD 1 — Phase 3 epics & stories (depth & controls)

Three in-memory depth/control features over the shipped whole-DB engine. Architecture:
`architecture-tymi-pde-phase3-2026-07-05/` (AD-25..27). No new dependencies (AD-9). Each story runs
the full 3-layer `bmad-code-review` gate before `done`; build/test in the devcontainer.

## Epic P3 — Depth & controls

### Story P3.1: Cross-table single-hop correlation

As a data engineer, I want a child column to statistically depend on its parent's value the way the
source does, so that cross-table analytics behave realistically (PDE-6, AD-25).

**AC.** A declared cross-correlation `(child.column ↔ parent.column, ρ)` is induced **after** FK
edges are set, by rank-correlation reordering that achieves Spearman ≈ ρ against the referenced
parent value while **preserving the child column's marginal**. Both columns must be numeric.
Deterministic; the declaration is part of the consistency fingerprint. Single-hop only — a
multi-hop (no direct FK), self-referential, non-numeric, or key-column declaration fails closed.
Wired into `generate_from_spec` (in-memory; combining with out-of-core streaming is deferred).

### Story P3.2: Referentially-consistent subsetting

As a self-service provisioner, I want a small referentially-consistent subset of a generated DB, so
that I can spin up a tiny but valid dev dataset (PDE-16, AD-26).

**AC.** Given a root table + fraction (or row count), keep a deterministic subset of the root; every
FK-reachable table is filtered to only the rows referenced by (or referencing, upward) kept rows, so
RI holds. Shared keys are **not** renumbered — a subset still joins to a full dataset from the same
Spec. Each subset table is returned as a `GatedDataset`. Fails closed on a cyclic FK graph.

### Story P3.3: Incremental / delta refresh

As a self-service provisioner, I want to regenerate only the tables whose inputs changed, so that
refreshing a large DB after a small Spec edit is cheap (PDE-17, AD-27).

**AC.** Given a previous Spec and a new Spec, a per-table diff marks a table **dirty** iff its
Profile, row count, shared-key/fixture decls, or a depended-on global (seed, chunk_rows, deps)
changed, or an FK ancestor is dirty; a clean table with clean ancestors is **reused**. Regenerated
tables' position-derived keys still line up with reused tables' FKs (RI preserved). The refresh
reports regenerated vs reused tables + the new consistency fingerprint.

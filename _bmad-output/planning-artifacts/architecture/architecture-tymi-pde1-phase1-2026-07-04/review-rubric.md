---
title: Rubric Review — TYMI PRD-1 Phase-1 Architecture Spine
type: architecture-review
reviews: architecture-tymi-pde1-phase1-2026-07-04/ARCHITECTURE-SPINE.md
against: prd-tymi-obfuscated-dev-env-2026-07-04, architecture-tymi-2026-07-01 (parent MVP spine)
created: '2026-07-04'
---

# Rubric Review — Phase-1 Obfuscated Prod-Like Dev Environments spine

## Overall verdict: **ADEQUATE**

A disciplined, lean, correctly-inherited epic spine. Every new AD is a genuine
divergence-preventing invariant with Binds/Prevents/Rule intact; the parent's 12 ADs are
cited by original ID and not re-derived or renumbered; the Structural Seed and Stack are
appropriately minimal. What holds it back from *strong*: one **high-severity internal
contradiction** on the safety-critical path (the LeakageGate runs *before* the fixtures
overlay in both AD-19 and the flow diagram, which lets fixtures reach the destination
ungated — directly contradicting AD-17, the spine's own fixtures-as-PII-bypass guard), plus
two **medium coverage gaps** in the operational envelope (idempotent/partial-write load
semantics NFR-F, and source-side credential isolation NFR-D are silent).

Finding counts: **1 high, 2 medium, 3 low.**

---

## Per-dimension verdicts

### 1. Invariant vs seed discipline — **STRONG**

Everything under "Invariants & Rules" (AD-13..19) is a real cross-unit invariant, not
implementation detail the code should own:

- AD-13 (single generation path), AD-14 (one versioned Spec superset), AD-15 (consistency
  unit tuple), AD-16 (source-independent keys), AD-17 (fixtures gate-always), AD-18
  (fail-closed destination), AD-19 (thin pipeline / external orchestration) each name a
  divergence two independently-built stories could hit.
- Seed is correctly pushed out of the invariant list: the Structural Seed is just 6 module
  paths with one-line purposes and an explicit "owned by the code once built; listed to
  prevent placement drift" — no over-specification.
- AD-16 is careful: the *invariant* is fixture/generated-key non-collision and cross-team
  alignment; the *mechanism* (reserved keyspace range) is flagged `[ASSUMPTION → OQ-5]`
  rather than hard-coded. Correct instinct — the collision boundary is the invariant, the
  range is seed.
- Grounding an invariant in existing code ("ratifies the existing `_unique_column` arange",
  "reuses `generate_related`") is legitimate anchoring, not seed leakage.

### 2. AD completeness — **STRONG**

All seven of AD-13..19 carry Binds / Prevents / Rule. The Prevents are concrete divergences,
not truisms:

- AD-13 Prevents "a second, divergent multi-table generator or table-ordering scheme" — a
  real risk once several stories touch generation.
- AD-19 Prevents "the CLI and a DAG each re-implementing the flow" — the classic
  two-driving-adapter divergence, exactly what a spine exists to stop.
- AD-17 Prevents "fixtures becoming a PII bypass around the leakage gate" — a real
  two-unit hole (fixtures builder vs pipeline builder).
- None are empty ("prevents bugs"-style) truisms.
- Binds trace cleanly to PDE FRs (PDE-2/3→AD-14, PDE-11→AD-15, PDE-12/10→AD-16,
  PDE-8/9/10→AD-17, PDE-14→AD-18, PDE-13→AD-19); binding a goal (G4) and inherited NFRs
  (NFR-E/CM2) as targets is acceptable.

### 3. Inherited-invariants correctness — **ADEQUATE**

Inheritance mechanics are handled well, but there is a real conflict to surface.

- Strong: all 12 parent ADs are accounted for in the Inherited Invariants table by original
  ID; new ADs start at AD-13; the AD-4/AD-11 and AD-6/AD-7 pairings match the parent; AD-19
  explicitly frames itself as "AD-8 extended", and the Deferred section honestly flags that
  Phase 2 "Supersedes AD-10's single-DataFrame-per-run assumption" rather than silently
  weakening it.
- **Conflict (see H-1):** AD-19's pipeline `... → LeakageGate → fixtures overlay → load` and
  the flow diagram (`Gate → Fix → Guard → Load`) place the gate *before* fixtures are
  overlaid, which contradicts AD-17's rule that fixtures are "still passed through the
  LeakageGate + PII scan." A new AD weakening/contradicting a sibling invariant on the
  safety path is the failure mode this dimension is meant to catch.

### 4. Coverage — **ADEQUATE**

The destination-safety boundary and the Deferred honesty are strong; the operational
envelope has two real silences.

- Strong: AD-18 fully owns the destination-safety boundary (affirmation + deny-list, fail
  closed, "no code path loads un-obfuscated source"). Deferred is honest and matches the
  PRD phasing exactly — Phase 2 (scale/rewrite, supersedes AD-10), Phase 3 (PDE-6/16/17),
  plus OQ-2 and OQ-5 called out as open.
- **Gap (M-1):** Idempotent provisioning / partial-write safety (NFR-F, PDE-13 "idempotently")
  is uncovered. AD-18 only guards *before any write*; nothing in the spine governs a failure
  *mid-load* (transactional vs clean-replace, partial/corrupt-state cleanup, re-run
  semantics). This is a cross-unit concern the epic owns.
- **Gap (M-2):** Credential isolation / source read-only (NFR-D) is silent. The spine's
  safety story is one-sided — destination via AD-18, but no invariant for source-side
  read-only access or "requester never sees prod credentials," which UJ-1 leans on. Partly
  inherited via AD-2's read/write role split, but not made explicit as a boundary.

### 5. Right-sizing — **STRONG**

Appropriately thin for an inherited epic spine. It does not re-list the parent stack (just
"no new runtime dependency for Phase 1; re-verify AD-9 for Phase 2/3"), does not re-derive
inherited ADs, and keeps the Structural Seed to the 6 genuinely-new modules. The two mermaid
diagrams (provisioning flow, dependency direction) are load-bearing for the new flow, not
padding. No bloat.

---

## Findings

### H-1 (HIGH) — LeakageGate ordered before fixtures overlay: fixtures can reach the destination ungated
**Location:** AD-19 Rule (pipeline `... → LeakageGate → fixtures overlay → load`, lines
120–123) and the Provisioning-flow diagram (`Gate → Fix → Guard → Load`, lines 132–135),
contradicting AD-17 (lines 100–103).
AD-17 requires fixtures to be "still passed through the LeakageGate + PII scan" so a real PII
value smuggled in as a fixture "fails closed" — this is the spine's core safety thesis
(G2, CM1, PDE-9). But both the AD-19 pipeline and the flow diagram overlay fixtures *after*
the gate stage, so fixture rows are added between gating and load and never hit the gate. The
Structural Seed hints at a second gate ("`fixtures.py` — overlay + attestation + gate hook"),
but that second invocation is invisible in AD-19's linear pipeline and unreconciled with the
"one gate" framing. This is exactly the two-unit divergence a spine must prevent: the
pipeline-builder ships "gate → overlay → load" while the fixtures-builder assumes the pipeline
gates its output → ungated fixtures by construction. **Resolve:** either move the LeakageGate
to run *after* the fixtures overlay (gate the union), or make AD-17/AD-19 state explicitly
that the fixtures overlay runs a dedicated gate+PII scan on fixture rows and show it as a
stage in the diagram.

### M-1 (MEDIUM) — Idempotency / partial-write / re-run safety uncovered
**Location:** whole spine; NFR-F and PDE-13 in the PRD have no counterpart AD or convention.
AD-18 aborts "before any write," but nothing governs a failure *after* the load begins
(transactional-vs-clean-replace load, no partial/corrupt state, safe re-run). For a
whole-DB multi-table load this is a genuine cross-unit invariant (the load stage and any
re-run must agree on replace semantics). **Resolve:** add an invariant or a Consistency-
Conventions row for idempotent load semantics, or explicitly defer with rationale.

### M-2 (MEDIUM) — Source-side credential isolation / read-only (NFR-D) silent
**Location:** whole spine; NFR-D not reflected.
The destination boundary is well-owned (AD-18) but the source boundary — read-only source
access, secrets on the runner, requester never sees prod credentials — is only implicitly
inherited from AD-2's read/write role split. Given the PRD frames this as a hard safety
property (UJ-1, NFR-D), a one-line convention or AD would make the safety boundary
symmetric. **Resolve:** add a Destination/Source-safety convention row asserting read-only
source access + credential isolation, or note it as an ops-envelope deferral.

### L-1 (LOW) — PDE-15 (provisioning report) in frontmatter `binds` but claimed by no AD
**Location:** frontmatter `binds` (line 11) vs AD Binds lines.
Only the report's fingerprint sub-part is covered (AD-15). The rest of PDE-15 (row counts,
fidelity summary, leakage result incl. fixture scan, fixtures present) is seed the code owns,
which is fine — but no AD lists PDE-15 in its Binds, so the traceability is incomplete.
Cosmetic; consider a one-line Convention row for the report envelope.

### L-2 (LOW) — AD-13 binds PDE-1 (whole-DB introspection), but AD-13 is a generation invariant
**Location:** AD-13 Binds (line 57).
Whole-DB introspection is really governed by inherited AD-2 (EngineAdapter). AD-13 binding
PDE-1 is a loose fit; PDE-1 is better traced to AD-2. Minor mis-binding.

### L-3 (LOW) — Two of seven new invariants rest on unresolved assumptions
**Location:** AD-16 `[ASSUMPTION → OQ-5]` (line 85), AD-18 `[ASSUMPTION → OQ-2]` (line 105).
Handled honestly (both point at open questions and the Deferred section restates them), so
this is a risk flag, not a defect: the mechanisms OQ-2/OQ-5 resolve to could shift the
invariant's shape (esp. AD-16's reserved-keyspace scheme). Worth confirming before the
stories that depend on them start.

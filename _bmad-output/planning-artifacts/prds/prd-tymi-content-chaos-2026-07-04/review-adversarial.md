# Adversarial Review — PRD 2 "Content Chaos"

**Reviewer stance:** hostile PM (Cagan/Torres). I don't care what you *plan* to build; I care whether this bet is falsifiable, whether it's genuinely new, and whether the scope validates the risky assumption or dodges it. On all three, this PRD is soft.

**Verdict: MAJOR REVISION.** ~50–60% of the "new" fault families are a re-skin of already-shipped mutators; the one genuinely differentiating deliverable (the detection audit, CC-11) is deferred to Phase 3; the headline falsifiable goal (G1) depends on an artifact — a "reference pipeline + alert suite" — that is defined nowhere and scoped as no FR. The PRD front-loads the cheap, already-solved half and defers the expensive, unvalidated half. That is the build trap.

---

## F1 — [CRITICAL] Much of CC-1..CC-7 already ships. The PRD is not honest about what is new.

I mapped every CC-x to the working tree (`src/tymi/chaos/mutators/`):

| PRD "new" family | Already shipped? | Evidence |
|---|---|---|
| **CC-2 nullification, MCAR** | **Shipped.** MCAR = uniform random null. `IllegalNullMutator` (`format_type.py:92`) nulls cells; `CellFaultMutator.apply` (`_base.py:50-54`) picks cells via `rng.choice(positions, size=k)` — that *is* MCAR. Explicit `columns=` targeting already works. | `illegal_null` + `CellFaultMutator` |
| **CC-4 partial records** | **Mostly shipped.** Nulling a subset of columns per row = `illegal_null` across N columns; only the *row-correlation* ("same rows across columns") is new. | `illegal_null` |
| **CC-5 column drift** (rename/drop/add/reorder) | **Shipped, minus reorder.** `MissingFieldMutator` (drop), `ExtraFieldMutator` (add), `RenamedColumnMutator` (rename) — `schema_break.py:64-122`. Only *reorder* is new, and a name-keyed pipeline won't even notice a reorder. | 3 of 4 shipped |
| **CC-6 type / nullability drift** | **~90% shipped.** "integer becomes a string" is literally `ChangedTypeMutator` → `LogicalType.STRING` (`schema_break.py:125`, `_other_type` at :245). Only the *nullable-flag flip on the Schema contract* is new (observable effect — nulls in a NOT NULL col — is `illegal_null`). | `changed_type` |
| **CC-8 policy** | **Shipped.** `apply_policy` already targets mutators by column/type with rate + mixed/fully-chaotic mode (`policy.py:58`). | Chaos Policy |
| **CC-9 manifest coverage** | **Shipped.** `FaultManifest` + every mutator emits per-cell/per-column entries. | all mutators |

**What is genuinely new** (and the PRD should say *only this* is new):
- **CC-1 dropped records** — nothing today deletes rows.
- **CC-3 sequence gaps** — monotonic-column-aware gap injection is new.
- **CC-2's MAR/MNAR conditioning only** — and see F4, that's the one piece left undefined.
- **CC-7 versioned schema delta** — new framing, though the delta data already lives in manifest entries (`renamed_column` already records `new_name`, `changed_type` records `from`/`to`).
- **CC-11 detection audit** — the actual value. See F2.

**Fix:** Add a "Delta vs shipped MVP" table to the PRD stating, per CC-x, `NEW / EXTENDS <mutator> / ALREADY SHIPPED`. Kill or de-scope CC-5-reorder and the shipped 90% of CC-6/CC-2-MCAR to one line each ("extend existing mutator with policy hook"). Reallocate the saved scope to CC-1, CC-3, MAR/MNAR, and CC-11 — the only work that isn't already done.

---

## F2 — [CRITICAL] The riskiest assumption is deferred, not validated. Phases 1–2 ship what you already have and prove nothing.

The bet is: *"content chaos breaks pipelines / trips alerts, and teams want to generate it."* The learning that validates it is **CC-11 — "did it catch it?"** That is the whole differentiation ("Great Expectations validates but doesn't generate"; TYMI closes the loop by auditing detection). It is scoped to **Phase 3** (line 63).

Meanwhile Phase 1 + Phase 2 ship faults that are ~60% already in the tree (F1). So the plan front-loads the cheap, de-risked output and defers the one expensive, unvalidated thing that would prove the thesis. G1 itself says it is *"Measured via the Fault Manifest + the detection audit"* (line 47) — i.e. **G1 cannot be demonstrated until Phase 3.** You will ship two phases of mutators and still not know if anyone can tell whether their pipeline caught anything.

**Fix:** Pull a thin CC-11 forward into Phase 1 against *one* fault family (dropped records is the sharpest). "Generate → run → audit detection" end-to-end on one family beats "generate seven families, audit none." If CC-11 is genuinely Phase-3-hard, then the honest MVP is *smaller* (one new family + one audit), not *broader*.

---

## F3 — [CRITICAL] G1 is not falsifiable: the "reference pipeline + reference alert suite" is defined nowhere and scoped as no deliverable.

G1 (line 44) hinges on *"a reference pipeline + a reference data-QA alert suite."* Search the PRD: this artifact appears in G1 and nowhere else. **No FR builds it. No fixture names it. No user journey produces it.** And **OQ-1** (line 131) openly admits the forcing function — *"a specific pipeline/team"* — is still unknown. You cannot measure "≥1 injected fault family is not handled *on a reference pipeline*" when neither the pipeline nor the alert suite exists, is chosen, or is a committed deliverable.

As written G1 is aspirational, not falsifiable. It depends on (a) the undefined reference harness and (b) CC-11, which is Phase 3.

**Fix:** Either add an FR that *builds and version-controls* a named reference pipeline + alert suite as a test fixture (Phase 1 deliverable), or downgrade G1 to what Phase 1 can actually falsify (e.g. "on fixture pipeline X with alert suite Y, injected family Z produces an unhandled run"). A goal you can't run is not a goal.

---

## F4 — [MAJOR] MCAR/MAR/MNAR is borrowed vocabulary that OQ-2 leaves undefined — dissolving CC-2's own acceptance criterion.

The taxonomy is Rubin's, and CC-2's plain-language gloss (MAR = conditioned on another column; MNAR = conditioned on the column's own value) is defensible. The problem is what happens next:

- **G2 makes it an acceptance criterion:** *"the missingness mechanism (MCAR/MAR/MNAR) is honored"* (line 50).
- **OQ-2 then dissolves it:** *"Rule-based conditioning only, or a fitted missingness model? How faithful must the mechanism be?"* (line 133), and the [ASSUMPTION] at line 82 says "a simple rule/threshold."

A **hard rule/threshold** (`null y where x > t`) is *deterministic selection*, not a statistical MAR mechanism (where `P(missing | x)` varies smoothly with x). The PRD never specifies the conditioning *function*, the probability curve, or — critically — **how you would verify "the mechanism was honored."** Proving MAR ≠ MCAR requires a statistical test of missingness against the covariate; the PRD names no such test. So G2's criterion is untestable until OQ-2 decides *what the mechanism is*. **The single genuinely-new piece of CC-2 (MAR/MNAR — MCAR is already `illegal_null`) is exactly the piece left unspecified.**

**Fix:** Close OQ-2 *before* CC-2 is buildable. Specify the conditioning as an explicit probability function of the covariate (e.g. logistic `P(missing|x)`), and add a verification: a run-level check that empirical missingness correlates with the covariate for MAR/MNAR and does not for MCAR. Without that, "mechanism honored" is a slogan.

---

## F5 — [MAJOR] Single-table scope contradicts the Problem/Vision — the marquee "breaks real multi-table pipelines" scenario is unreachable in Phase 1.

The Problem sells multi-table breakage ("records arrive dropped… an upstream change renames/retypes/drops a column"; the whole pitch is breaking *real pipelines*, which are joins). But Out-of-Scope (line 126) + OQ-4 (line 137) restrict Phase 1 to *"a single table's stream of records."*

The contradiction bites hardest on **CC-1 dropped records**, the flagship new fault. A dropped record only *breaks a pipeline* when a **child row is orphaned or a join loses its parent** — i.e. cross-table. Drop a row in an isolated single table and nothing downstream breaks; you've made a smaller table. **The scenario that motivates CC-1 is excluded by the scope that contains CC-1.**

And this exclusion is *not* justified by cost: the shipped code already has `OrphanFkMutator` and full FK-aware schema surgery (`schema_break.py:207`, `_drop_from_schema` propagating FK/unique/index drops at :275). Whole-DB referential faults are *more within reach* than the PRD admits.

Related — **CM1 (subtlety) is at risk:** the Phase-1 flagships (dropped records, column drift) are the most *glaring* faults imaginable, while the *subtle* one (MNAR) is the one gated behind OQ-2. The phasing front-loads theater and defers subtlety — the opposite of CM1's intent.

**Fix:** Close OQ-4 now. If the differentiator is breaking real pipelines, Phase 1 must include at least referential drop (drop parent → orphan children) — reusing the shipped FK machinery — or the PRD must stop claiming multi-table breakage in the Problem/Vision and honestly scope to "single-table data-quality alert testing."

---

## F6 — [MAJOR] "Zero core change" (CC-8 / AD-3) is likely false for the row-count-changing faults, and the shipped manifest audit *cannot* handle them.

CC-8 and the header (line 14) promise *"new families land as new Mutator plugins… core untouched."* Two shipped facts contradict this for CC-1/CC-3:

1. **The manifest audit already declares row-count changes unauditable.** `_audit_cells` (`chaos_audit.py:108-112`) does `present_not_listed.append("row count changed … (unauditable)")`. CC-1 (dropped records) and CC-3 (sequence gaps, if it removes rows) will trip exactly this and **fail the bidirectional contract** that CC-9 claims to "extend." The manifest entry shape is positional (`"row": int`); after a deletion, positions shift and a deleted row references an index absent from the output — the `present → listed` direction *structurally cannot* confirm a deletion.

2. **Mixed mode forbids and mis-handles them.** `apply_policy` mixed mode raises on structural mutators (`policy.py:79-84`) and its row-selection keeps a `rate` fraction of *corrupted-cell rows* by positional index (`policy.py:93-113`). A row-*deleting* mutator breaks that positional bookkeeping. CC-1/CC-3 don't fit the "corrupt a cell, keep rate of rows" model at all.

So CC-1/CC-3 almost certainly require changes to the audit, the manifest schema, and the policy engine — i.e. **core change**, violating the AD-3 claim the PRD leans on to argue this is cheap.

**Fix:** Acknowledge that row-cardinality faults need (a) a new manifest entry type for deletions/gaps, (b) an audit path that compares by *key* not position, and (c) a policy mode for cardinality faults. Budget it. Don't sell CC-1 as "just another plugin, core untouched."

---

## Summary of required fixes (priority order)

1. **F3 / F2 / F6 (blockers):** define & scope the reference pipeline+alert fixture (or downgrade G1); pull a thin CC-11 into Phase 1; budget the core changes CC-1/CC-3 actually need.
2. **F1:** publish an honest NEW/EXTENDS/SHIPPED delta table; stop presenting shipped mutators as new families.
3. **F4:** close OQ-2 with an explicit conditioning function + a verification test before CC-2 is buildable.
4. **F5:** close OQ-4 — either include referential drop in Phase 1 (the machinery exists) or stop claiming multi-table breakage.

The honest MVP here is *narrower and deeper* (one genuinely-new family + detection audit, end-to-end, against a real fixture), not *broader and shallower* (seven families, mostly re-skinned, audit deferred).

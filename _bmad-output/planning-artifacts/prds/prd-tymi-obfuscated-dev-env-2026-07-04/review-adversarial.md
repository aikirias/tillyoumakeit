---
title: Adversarial PM Review — TYMI PRD 1 (Obfuscated Prod-Like Dev Environments)
reviewer: Adversarial PM (hostile edition)
date: 2026-07-04
verdict: MAJOR REVISIONS REQUIRED before this becomes an epic plan
---

# Adversarial PM Review — PRD 1

**Overall verdict: This is a well-written vision document wearing an MVP's clothes.** It is
coherent, the prose is honest in patches, and the "shared spec → aligned IDs" idea is a
genuinely interesting wedge. But as a *plan to validate cheaply*, it is a wishlist. 17 FRs
across 6 groups, three of which (FR-6, FR-16, FR-17) are each a research project. The North
Star is not falsifiable as written. And the single most differentiated claim in the whole
document — cross-team join consistency — is built on an assumption the PRD never states and
that does not hold. Below, by severity.

---

## CRITICAL

### C1 — The differentiated claim (cross-team consistency) rests on a false premise. §Vision, FR-11/FR-12, G4
**What's wrong.** The PRD's crown jewel is: *"reproducible from a shared, versioned spec so
every team and environment generates identical synthetic entities, aligning cross-team IDs
for free"* (lines 37–39), formalized as FR-11 (`(Spec, seed) → byte-identical output`) and
FR-12 (`entity keys stable across runs … datasets produced by different teams join
consistently`).

This is only true if every team generates from the **same source database state**. FR-11 is
honest — it says `(Spec, seed)` determines output. But FR-12 quietly upgrades that to *"teams
join consistently"* without stating the load-bearing precondition: **the Spec is not the
only input — the source DB is.** The generator profiles a *source* (FR-1/FR-2: introspection
→ per-table profiles → detected correlations). Two teams pointing the same Spec at:
- two different source databases (team A's staging snapshot vs team B's), or
- the same source at two different times (source data drifts — new customers, churned rows,
  changed distributions),

will NOT produce identical entities. Row counts differ, distributions the generator samples
from differ, therefore the seeded draws differ, therefore `customer_id=12345` is a different
synthetic human on each side. The join "consistency" silently produces **garbage joins that
look valid** — the worst failure mode, because nothing errors.

The PRD half-knows this: NFR-C (line 194) admits *"Cross-machine reproducibility requires
pinned dependency versions."* It pins the *code* but never pins the *source profile*. That is
the actual determinism boundary and it is missing from the requirements.

**What to do.**
1. State the precondition explicitly: cross-team consistency holds **only when teams share a
   frozen Profile artifact, not merely a Spec.** The unit of sharing must be `(Spec + pinned
   Profile snapshot + seed + pinned deps)`. FR-2 already produces a Profile — make it a
   versioned, hashable, shareable artifact and make FR-12 depend on *it*, not on the source.
2. Add an FR: the provisioning report (FR-15) must emit the Profile hash, and `provision`
   must refuse / warn when two runs claim the same entity space but carry different Profile
   hashes.
3. If entity keys must be stable *independent of source drift* (the real user promise), then
   IDs cannot be positional draws from a sampled distribution — they need a deterministic
   keyspace (e.g. seed-derived key allocation independent of source row count). The PRD has
   not decided this and it is the difference between the feature working and quietly lying.
   This belongs in Open Questions at minimum; it's arguably the riskiest assumption in the
   doc and it isn't even listed as one.

### C2 — The riskiest assumption is untested by the chosen scope; the scope tests the *table-stakes* instead.
**What's wrong.** Per the brief's own framing: SDV and Tonic already do FK-aware multi-table
synthesis. So "faithful whole-DB generation" (FR-1, FR-4, FR-5, FR-7) is catch-up — necessary
plumbing, but not where the bet lives. The *differentiated* bet is C1's cross-team-identical-
entities-from-a-shared-artifact. Yet the bulk of the 17 FRs (A, B, F groups = 10 of 17) fund
the catch-up half, and the differentiated half (D group, FR-11/12) is **2 FRs and no
validation plan.** The PRD invests most heavily in the part that is least risky (because
others have proven it's buildable) and least in the part that is both riskiest and the only
reason to exist.

**What to do.** Invert the emphasis. The cheapest thing that validates the core assumption is
NOT a whole-DB out-of-core engine spanning "megabytes to hundreds of terabytes" (NFR-A). It
is: **two teams, two environments, a 3–5 table schema, one shared Profile artifact — do their
`customer_id`s actually join and mean the same thing?** That experiment needs FR-1..FR-5,
FR-8..FR-12. It does NOT need FR-6, FR-16, FR-17, or the terabyte scale envelope. Make that
the Phase-1 boundary and you find out in weeks whether the wedge is real.

---

## MAJOR

### M1 — Scope creep: FR-6, FR-16, FR-17 are three separate research projects riding in on one PRD.
- **FR-6 (cross-table statistical correlation)** — the addendum (lines 28–33) admits the
  mechanism is unknown ("candidate approaches … architecture to choose"), that SDV/Copulas
  are license-barred (AD-9), and that it's "likely an in-house extension of the Gaussian
  copula across the FK join." That is a from-scratch multivariate synthesis research effort.
  OQ-3 further admits they haven't even decided *which correlations* must hold or to what
  tolerance. **You cannot scope, estimate, or acceptance-test a requirement whose success
  criterion is an open question.**
- **FR-16 (referentially-consistent subsetting / connected subset)** — OQ-4 admits the core
  semantics (how far the FK closure is walked) are undecided. Transitive FK closure on a real
  schema commonly explodes to "half the database" (the classic subsetting problem). This is a
  known-hard problem that Tonic sells as a headline feature; it is not a rider on an MVP.
- **FR-17 (incremental/delta refresh)** — the PRD *itself* flags it as "highest-complexity"
  and "a candidate for a later phase" (lines 170–171), and OQ-1 openly asks whether to ship
  it at all in phase 1. Then it's left in the FR list anyway. **If your own doc is asking
  "should this be in scope," the answer for an MVP is no.**

**What's wrong at the PRD level:** listing a requirement and simultaneously listing an Open
Question that dissolves its acceptance criterion is having it both ways. It lets scope look
committed while remaining unfalsifiable.

**What to do.** Cut FR-6, FR-16, FR-17 from Phase 1 into an explicit "Phase 2 (post-
validation)" section. Phase 1 = A, B (minus FR-6), C, D, E. Correlation, subsetting, and
delta-refresh each get their own scoping once the wedge (C1) is proven. This is not
conservatism — it's refusing to fund three research projects before you've confirmed anyone
wants the core.

### M2 — The North Star (G1) is not falsifiable, and NFR-B guts its own metric.
**What's wrong.** G1 (lines 47–52): *"self-service provisioning in minutes … median
time-to-provision → minutes."* Then NFR-B (lines 189–191): *"There is no fixed absolute time
cap — 'minutes' is a function of size and resources."* So the headline metric is "minutes,"
and the NFR says "minutes" is undefined and unbounded. **That is not a target; it is a mood.**
If a run takes 40 minutes on a big DB, did G1 pass or fail? The doc has arranged things so
the answer is always "depends" — which means the North Star can never be missed, which means
it can never be *learned from*.

The other G1 sub-metrics have the same problem: "self-service ratio … high" (how high? vs
what baseline?), "ticket volume → ~0" (over what window? measured how, given the tool is
open-source and the design partner is a single internal team?).

**What to do.**
1. Define "minutes" for a *named reference workload*: e.g. "P50 ≤ 10 min for a schema ≤ N
   tables / ≤ M GB on a 1-runner baseline." Scale can vary; the *promise* must be pinned to a
   concrete case or it isn't a promise.
2. Give self-service-ratio and ticket-volume a baseline and a measurement window (e.g.
   "current: X tickets/quarter at design partner; target: ≤1 within 2 quarters of adoption").
3. G3's "a prod bug now reproduces on the dev data" is a lovely qualitative signal but is
   anecdote, not metric. Keep it as a milestone gate, not a success metric.

### M3 — The fixtures exemption is a PII bypass with no compensating control. FR-8/FR-9, G2, CM1
**What's wrong.** FR-8: fixtures are "exact rows … injected **verbatim**." FR-9: fixtures are
"**exempt** from obfuscation and from leakage-gate regeneration." G2/CM1 promise "zero real
values / PII reach non-prod" and "100% leakage-gate pass." **These directly contradict each
other.** The leakage gate is the entire safety story (G2, NFR-1, AD-6/AD-7), and FR-9 punches
a hole in it that is, by construction, invisible to the gate. Nothing stops a well-meaning
practitioner from pasting a *real* login account ("just use my real test user, it already
exists in prod") into the fixture allow-list. It's verbatim, it's exempt, it's now in every
team's non-prod, and the 100%-pass report (FR-15) will show green because the gate never
looked. The "zero real values" guarantee becomes "zero real values except the ones you
promised weren't real."

The PRD does not even *acknowledge* this tension. Out of Scope (lines 207–223) covers DP,
orchestration, engines — but not the one place the safety model is deliberately bypassed.

**What to do.**
1. Fixtures must NOT be exempt from the leakage *gate*; only from *regeneration/obfuscation*.
   Run every fixture value through the same PII classifier + leakage check the rest of the DB
   gets. Real PII in a fixture must **fail closed** (CM1-consistent) unless explicitly
   attested.
2. Require an explicit, logged attestation per fixture ("this value is synthetic/non-PII,
   author X") captured in the Spec and surfaced in the provisioning report.
3. Add a positive requirement: fixtures should be *generatable* (synthetic accounts with
   known-good synthetic PII), and real-value fixtures should be the discouraged exception,
   not the default framing. Right now "login/test accounts" invites real credentials.

### M4 — Counter-metrics are partly theater. §Counter-metrics, CM1/CM2/CM3
**What's wrong.** A guardrail metric is only real if it's *measurable and can trip*.
- **CM1** ("fast but leaks = failure") — this isn't a counter-metric, it's a restatement of
  G2. It measures nothing G2 doesn't. Fine as a principle, not a guardrail.
- **CM2** ("self-service must not enable a footgun … prod destination / no obfuscation") — this
  is real and good, and it's the one with teeth. But it's an *assertion of a control* (FR-14/
  NFR-E fail-closed), not a *metric*. There is no number that tells you it's working (e.g.
  "count of guardrail-blocked runs," "count of prod-destination near-misses caught"). Without
  a counter you can't tell a guardrail that works from one that's never been exercised.
- **CM3** ("no memorizing/over-fitting") — inherited from MVP SM-C1, fine, but with FR-8
  injecting verbatim rows the over-fitting surface just got a legitimized channel (see M3).

**What to do.** Convert CM2 into an observable counter (guardrail-trip count, prod-destination
rejections) emitted in the report and tracked. Drop CM1 as a redundant metric (keep as
principle). Note CM3's new interaction with fixtures.

---

## MODERATE

### m5 — "Role-agnostic, one user" erases the reviewer and hides the governance cost. §Users, lines 74–80
The PRD dissolves all personas into "the self-service provisioner" and asserts *"Governance
lives in the versioned Spec (reviewed like code), not in a gatekeeper person"* (line 80). But
"reviewed like code" **is** a gatekeeping handoff — someone has to review the Spec, and that
someone must understand PII classification, fixture safety (M3), and tolerance settings. The
PRD claims to remove the handoff while relocating it to Spec review and then not counting it.
The North Star ("no mandatory gatekeeping handoff," G1) may be technically won while the human
still waits on a Spec PR review. **Name the Spec reviewer as a role and account for that
latency in G1**, or the metric is gamed by definition.

### m6 — "Faithful" fixtures + generated children: the correlation promise and the fixture promise collide. FR-6 vs FR-9
FR-9 says child rows referencing fixtures are "generated consistently." FR-6 says cross-table
correlations are preserved within tolerance. But fixture parents are *verbatim, arbitrary,
human-authored* rows — they have no distributional relationship to anything. Generating
statistically-correlated children for a hand-picked parent is either impossible (the parent's
attributes are off-distribution) or forces the children off-distribution too, breaking FR-5/
FR-6 tolerances locally. The PRD never says how fixtures interact with the fidelity gates.
Small in row-count, but it's an unspecified interaction between two headline features. Decide:
are fixtures excluded from fidelity/correlation accounting? (They should be — say so.)

### m7 — Idempotency (NFR-F) vs delta-refresh (FR-17) vs fixtures: three-way unspecified interaction.
NFR-F promises "clean-replace or transactional" idempotent loads. FR-17 promises applying
"only what changed." A clean-replace destroys the environment other teammates may be actively
using; a delta-apply on a non-deterministically-drifted source (C1) can corrupt referential
integrity mid-stream. These three requirements have not been reconciled. This is more evidence
FR-17 should be Phase 2 (M1).

### m8 — Buy-vs-build honesty: the PRD is *implicitly* honest but never states the trade. §Vision, Out of Scope
To the brief's Q3: the PRD is reasonably honest by *omission* — it never claims the faithful-
generation half is novel, it repeatedly says "generalizes MVP FR-X," and Out of Scope shows
restraint (no SaaS, no DP, no new engines). That restraint is the doc's best quality. **But it
never explicitly says "the faithful whole-DB half is table-stakes vs SDV/Tonic; our bet is the
shared-spec consistency wedge + open-source + permissive-license (no BUSL)."** For an internal
forcing-function that's survivable, but a one-paragraph "Why us / why not just buy Tonic"
section would force the team to keep the differentiator in view instead of sinking effort into
re-implementing FK-aware synthesis (which is exactly what FR-4/FR-6 are). The permissive-
license angle (AD-9, no SDV BUSL) is a *real* open-source differentiator that the PRD buries in
an addendum — surface it.

---

## What's actually good (so this isn't pure demolition)
- Out of Scope is disciplined and specific — it resists the usual everything-bucket.
- The fail-closed prod-destination guardrail (FR-14/NFR-E/CM2) is the right instinct.
- "Scale as a property, not a target" (NFR-A) is a mature framing — even if NFR-B then
  weaponizes it against G1 (M2).
- Rejecting keyed pseudonymization (Option B) up front is a clean, defensible boundary.

---

## Required changes before this becomes epics (priority order)
1. **C1** — Redefine the consistency unit as `(Spec + pinned Profile + seed + pinned deps)`;
   decide whether entity keys are source-independent. Add it to Open Questions as the #1 risk.
2. **C2 / M1** — Cut FR-6, FR-16, FR-17 to an explicit Phase 2. Phase 1 validates the wedge on
   a small multi-team, multi-table experiment.
3. **M3** — Close the fixtures/leakage hole: gate fixtures for PII, require attestation, prefer
   synthetic fixtures.
4. **M2** — Pin "minutes" to a named reference workload; give self-service/ticket metrics a
   baseline + window.
5. **M4** — Make CM2 an observable counter; demote CM1 to a principle.

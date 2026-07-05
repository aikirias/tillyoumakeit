---
title: 'Adversarial Architecture Review — TYMI PRD-1 Phase-1 Spine'
type: architecture-review
method: adversarial-divergence (two-builders-obey-every-AD-yet-clash)
target: ARCHITECTURE-SPINE.md (AD-13..AD-19)
reviewer: adversary
created: '2026-07-04'
status: findings
---

# Adversarial Review — "Two builders, every AD obeyed, incompatible anyway"

I read the spine and the PRD, then I read the code the spine claims to reuse
(`src/tymi/synth/relational.py`, `src/tymi/synth/leakage.py`,
`src/tymi/profiling/profiler.py`, `src/tymi/domain/artifacts.py`). The spine is
elegant at altitude and rotten at the seams. Below are **eight concrete divergence
pairs** — each a scenario where two developers (or two stories) obey *every letter*
of AD-1..AD-19 and still ship parts that will not join, will collide, or will
silently leak. Every pair names the AD gap and the fix.

The headline: **three of these breaches defeat the two guarantees this PRD exists
to prove** — cross-team key alignment (G4) and zero-real-values (G2). This spine
is not ready to open stories on.

---

## VERDICT: REJECT — reopen AD-16, AD-17, AD-19 before any story starts

Load-bearing invariants (shared-key scheme, fixture keyspace, gate/fixture
ordering) are drafted as prose assumptions (`[ASSUMPTION → OQ-5]`,
`[ASSUMPTION → OQ-2]`) that two competent builders will resolve *differently and
compatibly-looking-until-integration*. Two of them are outright **self-contradictions
inside the spine** (H1: AD-16 vs PDE-12; H5: AD-17 vs AD-19). The wedge this PRD
is funded to validate breaks under them.

---

## H1 — [CRITICAL] Shared keys: `arange` vs "seed-derived" is a spine-internal contradiction

**The pair.**
- Dev A reads **AD-16**: *"ratifies the existing `_unique_column` arange … a
  deterministic monotonic sequence keyed by `(table, row-position)`."* A wires
  shared keys to the shipped code: `_unique_column` in `relational.py:276` returns
  `np.arange(n)` → `customer_id ∈ {0,1,…,n-1}`. **Position-derived. Seed-independent.
  Source-independent.**
- Dev B reads **PDE-12** (which AD-16 *binds*): *"Shared entity keys … are generated
  **source-independently (seed-derived)**."* B builds the new `synth/keys.py` the
  Structural Seed lists, deriving keys from the RNG: e.g.
  `rng.permutation(N)` or a seed-hashed token per position. **Seed-derived.
  Position-independent** (a shuffle).

Both obey their cited rule. **A's `customer_id` for row 5 is `5`; B's is
`hash(seed, 5)` or `permutation[5]`.** The two teams' `customer_id` columns share
not one value. Every cross-team join — the *entire differentiated bet (G4)* —
returns zero rows. And it passes every test each team writes in isolation, because
each is internally consistent. It only dies at the first cross-team integration,
which is the one thing this PRD promised to make free.

**AD gap.** AD-16 says "position-deterministic, ratifies arange." PDE-12 says
"seed-derived." **`arange` is not seed-derived** — it ignores the seed entirely.
The spine cites both as if they were the same mechanism. They are two different key
functions.

**Fix (tighten AD-16).** Pick ONE and delete the other's wording:
> Shared keys are the **position-deterministic `arange(offset, offset+n)`**
> emitted by `_unique_column`, **not** seed-derived. Alignment derives from the
> pinned per-table row count alone; the seed does not enter shared-key values.
> `synth/keys.py` **wraps** `_unique_column` (offset + reserved-range guard, H3),
> it does **not** re-derive keys.

Then **file a PRD change** against PDE-12: strike "seed-derived," replace with
"position-derived from the pinned row count." (Seed-derived keys would *also* break
alignment the moment two teams' RNG state diverges — see H2 — so `arange` is the
correct choice; the PRD wording is the bug.)

---

## H2 — [CRITICAL] Same shared keys, divergent FK wiring → joins that look valid and are garbage

**The pair.** Both teams take H1's fix: `customer_id = arange(n)`, aligned. Both
pin the same `customers` row count. But the Spec pins row counts **per table**, and
`orders.customer_id` is a foreign key sampled by `rng.integers(0, parent_len, n)`
(`relational.py:146`) — **RNG-state-dependent**.
- Team A pins `audit_log` at 10k rows. `audit_log` sorts before `orders` in the
  topological order (`_topological_order` uses `sorted(ready)` — alphabetical tie-break).
- Team B pins `audit_log` at 12k rows (their source is bigger — **PDE-12 explicitly
  permits differing source snapshots**).

`audit_log` generation consumes a *different number of RNG draws* for the two
teams. By the time `orders` generates, the shared `rng` is in a **different state**.
`rng.integers` for `orders.customer_id` therefore samples **different parent rows**.
Result: Team A's `order#5000 → customer 3`; Team B's `order#5000 → customer 917`.

**The keys align (both have customers 3 and 917), so every join *executes* and
*returns rows* — but the relationships are different.** This is precisely the
failure AD-15 names ("joins that look valid but are garbage"), reintroduced through
a side door AD-15 does not close: **AD-15 pins Profiles and seed, but the RNG stream
consumed before a shared table is a function of every prior table's row count**,
and row counts are *not required to be equal across teams* — PDE-12 celebrates that
they differ.

**AD gap.** AD-16 guarantees shared **key values** align. Nothing guarantees the
**FK edges between shared entities** align. Two teams get the same nodes and
different graph. The spine never says whether cross-team consistency means "same
keys" or "same relationships." G4's "identical synthetic entities" is silent on
edges.

**Fix (new AD-20).**
> **Shared-relationship determinism.** Any FK whose parent is a table with `shared`
> keys must be resolved from an **independent, table-local RNG substream**
> (`SeedSequence(seed).spawn` per `(table, purpose)`), never from the single
> threaded generator. A shared entity's *inbound edges* are then a pure function of
> `(seed, that table's pinned row count, the child's pinned row count)` — invariant
> to unrelated tables' sizes. Consistency across teams requires the child and
> parent row counts to match; the Spec must **flag which tables participate in
> cross-team joins** and pin their counts as part of the consistency unit (AD-15).

Without this, "cross-team consistency" is true for `SELECT customer_id` and false
for every join anyone actually runs.

---

## H3 — [CRITICAL] Fixture-key collision: a human writes `id: 1`, `arange` also writes `1`

**The pair.** AD-16 says *"a reserved keyspace block is set aside for fixtures;
generated shared keys never enter it,"* but names **no range** and ships **no
offset** — `_unique_column` returns `arange(0, n)`, hard-coded to start at **0**.
- Dev A implements the reserved block as **negative ids** (`fixtures use -1, -2…`).
  `arange(0,n)` never goes negative → no collision. Ships. Green.
- Dev B implements it as a **high block** (`fixtures live at ≥ 1_000_000_000`).
  `arange(0,n)` with `n < 1e9` never reaches it → no collision *at his test scale*.
  Ships. Green.

Now the humans author the fixtures the PRD requires (PDE-8: "login/test accounts").
A real person writes the obvious login fixture:
```yaml
fixtures:
  customers: [{ customer_id: 1, email: qa@test.local }]   # the QA login everyone uses
```
- On **Dev B's** build, `arange` generates `customer_id = 1` for the second
  generated row. **Direct PK collision** with the fixture at load. PDE-10 ("no key
  collision with fixtures") **violated** — while Dev B obeyed AD-16 to the letter,
  because AD-16 never told him the block was `≥ 1e9` *and never offset the arange
  away from it*.
- On **Dev A's** build, the same fixture (`id: 1`) collides too — negatives were
  reserved, but the human wrote a positive human-friendly id, which is exactly what
  humans do. Both schemes fail against real fixture authors.

Worse, at scale (**PDE says up to hundreds of TB in Phase 2, but even a medium
table can exceed 1e9 rows over a few refreshes**) Dev B's `arange` marches straight
into the high fixture block. **Generated keys silently overwrite fixture keys** with
no error — `arange` has no awareness of the reserved range at all.

**AD gap.** AD-16 asserts a reserved block exists and generated keys avoid it, but
(a) does not pin the range, (b) does not offset `arange`, (c) does not reserve the
block from *human-authored* fixture ids. It is an assertion with no mechanism.

**Fix (tighten AD-16 + AD-17).**
> The fixture keyspace is a **pinned, closed high block** — `[K_FIX, ∞)` with
> `K_FIX` a Spec constant (e.g. `2**62`). `_unique_column` for shared columns emits
> `arange(0, n)` and **must assert `n < K_FIX`** (fail closed otherwise). Fixture
> PK/unique values **must fall in `[K_FIX, ∞)`**; a fixture with a key `< K_FIX`
> (e.g. the human's `id: 1`) is **rejected at Spec-load with a typed error**, not at
> generation. Auto-bootstrap (PDE-2) assigns fixture keys from `K_FIX` upward so
> humans never hand-pick a colliding id.

The check must be **structural (Spec validation)**, not documentation, or two
builders will keep re-deriving incompatible ranges.

---

## H4 — [CRITICAL] Fixtures overlaid *after* the gate = an ungated PII path (AD-17 vs AD-19)

**The self-contradiction.** This one needs no two developers — the spine
contradicts itself in two adjacent ADs, and the mermaid diagram confirms the
losing order.

- **AD-17** promises: fixtures *"skip obfuscation/regeneration but are **still
  passed through the LeakageGate + PII scan** — a real PII value smuggled in as a
  fixture **fails closed**."* This is the whole point of PDE-9, G2, and CM1.
- **AD-19** pins the order: `… → LeakageGate → fixtures overlay → load`. The flow
  diagram is explicit: `Gate[LeakageGate] --> Fix[fixtures overlay] --> Guard --> Load`.

**Fixtures are added to the dataset *after* the gate has already run and *before*
load, with no gate between them.** The gate inspected only the generated rows.
The fixture rows — the exact rows AD-17 says must be scanned — reach
`EngineAdapter.load` **unscanned**. A real customer's PII pasted into a fixture
sails straight into non-prod. This is the *fixtures-as-PII-bypass hole PDE-9 was
written to close*, reopened by the pipeline order in the very next AD.

Two devs implementing "AD-17 says fixtures are scanned" will *both assume the gate
covers them* and *neither will add a second gate pass*, because AD-19 shows the gate
already ran. The guarantee is prose; the wiring drops it.

**AD gap.** AD-17 (fixtures are gated) and AD-19 (fixtures applied after the gate)
are mutually exclusive as written.

**Fix (tighten AD-19 — pin the order so the gate dominates the union).**
> Pipeline order is:
> `generate_related → shared-key emission → **fixtures overlay** → LeakageGate + PII
> scan (over the FULL dataset incl. fixtures) → guardrail → load`.
> The gate runs **once, last, over generated ∪ fixture rows.** Fixtures are exempt
> from *regeneration* (a gate collision on a fixture value is **fatal, not
> resampled** — resampling a pinned fixture would corrupt it), but never exempt from
> the *scan*. Update the flow diagram to `Fix → Gate`, not `Gate → Fix`.

This also forces a decision the spine dodges: **the gate's resample loop
(`leakage.py:67`) must not run on fixture rows** (they are inject-verbatim). So the
gate needs a "fixture mask" — fixtures that collide **fail closed** rather than
regenerate. Spell that out or a builder will let the gate silently rewrite a pinned
login account.

---

## H5 — [HIGH] Fixture overlay breaks the PK/FK integrity `generate_related` just established (AD-13 vs AD-17)

**The pair.** AD-13 says Phase-1 capabilities *"layer around"* `generate_related`;
AD-17 says fixtures are a *"post-generation overlay."* Read the code:
`generate_related` guarantees unique PKs and valid FKs **only over the rows it
generated** — `_enforce_primary_key` makes `arange` PKs unique *among generated
rows* (`relational.py:152`), and `_enforce_foreign_keys` points child FKs at
*published generated parent keys* (`relational.py:123`). It has **no knowledge of
fixtures**, which arrive afterward.

- Dev A injects fixtures **inside** the loop, before `_enforce_primary_key`, so
  fixture keys participate in uniqueness enforcement. (Violates AD-17's "post-
  generation overlay" wording — but keeps integrity.)
- Dev B injects fixtures **after** `generate_related` returns, per AD-17 verbatim.
  Now:
  1. **PK uniqueness lost** unless H3's reserved block is enforced — a fixture at
     `customer_id: 500` collides with the generated `arange` PK `500`. Load throws
     a duplicate-key error, or worse (clean-replace load, NFR-F) silently keeps one.
  2. **FK validity lost the other direction.** A *fixture child row* —
     `orders: [{order_id: <K_FIX+1>, customer_id: <K_FIX+7>}]` referencing a
     *fixture parent* — is fine only if that parent fixture exists. But a fixture
     child referencing a **generated** parent must carry a `customer_id ∈
     arange(0,n)`; a human who writes `customer_id: 999999` (not a real generated
     key, not a fixture key) creates a **dangling FK** that `generate_related`'s
     integrity pass never sees, because the row was added after it ran. Referential
     integrity — PDE-4, the whole "FK-consistent across all tables" promise —
     silently broken.

Both devs obey their cited AD. Dev B obeys AD-17 exactly and produces a
non-referentially-valid database.

**AD gap.** AD-13 ("layer around") and AD-17 ("post-generation overlay") never say
**how fixtures re-enter the integrity contract** `generate_related` owns. The
overlay is described as if it were a free append; it is a mutation of a structure
with invariants.

**Fix (tighten AD-17).**
> The fixtures overlay is **validated against the generated keyspace before load**:
> (a) fixture PK/unique keys must be in `[K_FIX,∞)` (H3) → no collision with
> generated `arange` PKs; (b) every fixture FK must resolve to **either** a fixture
> PK **or** a generated key `∈ arange(0,n)` of the referred table — a fixture FK
> resolving to neither **fails closed** at overlay time (a new `FixtureIntegrityError`).
> Fixture children of generated parents are FK-sampled from the generated keyspace by
> the overlay, not hand-written. The overlay is a **checked merge**, not an append.

---

## H6 — [HIGH] "Pinned Profile snapshot" is underspecified — two teams pin different things, both claim the same consistency unit

**The pair.** AD-15 makes identity `(Spec + pinned source-Profile snapshots + seed +
pinned deps)` and emits a fingerprint "so two environments can prove they are the
same unit." But **what is *in* a pinned Profile snapshot is never defined**, and the
code makes the ambiguity fatal:

`LeakageGuard.salt` defaults to `secrets.token_hex(16)` — **a fresh random nonce
every profiling run** (`profiler.py:122`). The gate's collision predicate hashes
generated values with *this salt* (`leakage.py:98`).

- Dev A pins the snapshot as **the serialized Profile artifact** (marginals, copula
  params, and the guard **including its salt**). Regeneration reuses the exact salt.
- Dev B pins the snapshot as **"re-profile from this pinned source extract"** — a
  data snapshot, re-run through the profiler. **New `secrets.token_hex(16)` → new
  salt → a different `LeakageGuard`.** On any table where the gate actually fires
  (a collision), the resample path (`leakage.py:74`) draws differently → **different
  output bytes**. Byte-identity (G4) lost.

Both call their artifact "the pinned Profile snapshot." Both compute an AD-15
fingerprint. **If the fingerprint hashes the Spec + a *source digest* (Dev B's
mental model) the two fingerprints match while the outputs differ** — the
fingerprint *lies*, which is worse than no fingerprint. The consistency unit's
proof-of-identity certifies two non-identical environments as identical.

Two further undefined members of the "unit":
- **Is the fixture list in the consistency unit?** AD-14 bundles fixtures *into the
  Spec*, so editing a fixture *is* editing the Spec — but `schema_version` is semver
  of the **format**, not the content (AD-14/AD-5). Two Specs, same `schema_version`,
  different fixture rows → different output. If the fingerprint keys on
  `schema_version` rather than content, same problem as the salt.
- **BLAS thread count.** The copula uses `eigh`/`cholesky` (per NFR-C). AD-15 pins
  "dependency versions" but **not thread count**. Two Phase-1 runners, same unit,
  `OMP_NUM_THREADS=1` vs `=8` → different float reduction order → different copula
  draws → non-byte-identical (NFR-C admits this — but *defers the pin to Phase 2*,
  while G4 claims byte-identity *in Phase 1*). Same unit, different bytes, AD-15
  obeyed.

**AD gap.** AD-15 lists the *tuple* but never **defines each member as a concrete,
serialized, content-hashed artifact**, and the fingerprint's input set is unstated.

**Fix (tighten AD-15).**
> The consistency unit is a set of **serialized artifacts**, and the fingerprint is
> the **content hash of that exact byte set**: (1) the Spec file bytes (incl.
> fixtures — so any fixture edit changes the fingerprint); (2) each **serialized
> Profile snapshot including its salt** (never "re-profile the source" — the salt is
> random and would drift); (3) the seed; (4) a **lockfile** of dependency versions;
> (5) for Phase 1, the **BLAS thread pin** (`OMP_NUM_THREADS`/`MKL_NUM_THREADS`) — or
> G4's Phase-1 byte-identity claim must be **downgraded to "identical within a pinned
> thread count," documented now**, not silently inherited. The fingerprint MUST hash
> content, never `schema_version`.

---

## H7 — [HIGH] The guardrail has two possible owners and an unspecified deny-list format — prod slips through

**The pair.** AD-18 requires `environment: nonprod` affirmation **AND** no
prod-deny-list match, but never says **where the affirmation lives** or **what the
deny-list matches**.

- Dev A puts the affirmation on the **Spec** ("the Spec governs the run" — AD-14).
- Dev B puts it on the **destination config** (AD-18 literally says *"the
  destination config must carry … affirmation"*).

Now a shared Spec marked `environment: nonprod` (Dev A's location) is pointed via a
CLI `--dest` arg at a **prod** database. Dev A's guardrail reads the Spec, sees
`nonprod`, and **writes to prod** — the affirmation described the *spec*, not the
*destination*. Two owners of one flag; the flag guards the wrong thing.

**Deny-list format** is "host/database patterns" — unspecified:
- Dev A: shell globs on hostname (`*prod*`).
- Dev B: regex on database name.
A prod host `db-primary.internal` (no "prod" substring) matches neither; a prod DB
reached by IP matches neither. The deny-list is **configurable and empty by
default**, so the *only* real gate is the self-asserted `environment: nonprod`
boolean — which a copy-pasted config sets to `nonprod` by accident. **CM2 / NFR-E
"fails closed" degrades to "fails closed if someone remembered to populate a
deny-list in a format the other dev also used."**

Finally, AD-18's *"there is no code path that loads un-obfuscated source data"* is
**aspirational, not enforceable**: the gate is a pipeline *stage*, not a *type
boundary*. H4 already produced one un-gated path (fixtures). A dev adding a
`--skip-gate` debug flag, or a Phase-2 fast loader, adds another — nothing in the
architecture *prevents* `EngineAdapter.load` from receiving raw source rows.

**AD gap.** AD-18 fixes neither the affirmation's location, the deny-list's match
semantics, nor a structural (type-level) guarantee that only gated data can be
loaded.

**Fix (tighten AD-18 + new AD-21).**
> **AD-18:** the affirmation lives on the **destination config only** (never the
> Spec); it is checked against the **resolved destination connection** (host, port,
> database — post-substitution), not against config text. The deny-list is a
> **pinned, typed schema** (explicit host/db/port match rules with defined
> semantics), ships with a **non-empty default**, and a **missing or empty deny-list
> is itself a fail-closed condition** (you must affirmatively configure it).
>
> **AD-21 (new — structural gate):** `EngineAdapter.load` accepts only a
> **`GatedDataset`** — a type mintable *exclusively* by the LeakageGate stage
> (private constructor / sealed factory). No `Dataset` reaches `load`. This turns
> "no un-obfuscated code path" from a promise into a **compile/type constraint** the
> fixtures overlay (H4) and any future fast path must satisfy.

---

## H8 — [MEDIUM] `arange` length vs surviving-row count — keys detach from rows under any filter/dedup

**The pair.** `_enforce_primary_key` calls `_unique_column(frame[col], n)` with `n`
= the **requested** row count (`_rows_for`), but assigns onto a `frame` whose length
can differ from `n`:
- The junction-PK path (`_assign_unique_junction_pk`) can only produce up to
  `capacity` distinct combos and **raises** if `n` exceeds it — but a builder who
  later adds subsetting (PDE-16, Phase 3) or any conditional-generation filter that
  drops rows will have `len(frame) < n`.
- Team A runs no filter → `len(frame) == n` → `arange(0,n)` aligns 1:1.
- Team B enables a privacy/outlier filter or a conditional constraint that drops
  rows → `len(frame) = n - k`. `_unique_column(series, n)` builds a length-`n`
  arange indexed to a shorter frame — **keys and rows misalign, or keys `n-k..n-1`
  are emitted for rows that no longer exist.**

Both "pin the same row count `n`" (AD-16) and get **different key→row bindings**,
because AD-16 pins the *requested* count while the *surviving* count is what carries
keys. Cross-team joins land on the aligned prefix and silently mismatch on the tail.

**AD gap.** AD-16 says keys align "given the Spec's pinned per-table row counts" but
never states **which count** — requested or surviving — is the pinned invariant, and
the code keys off the requested count while filters change the surviving count.

**Fix (tighten AD-16).**
> Shared-key emission is defined over the **final, post-filter row count**, computed
> **after** all row-dropping stages and **before** load; `_unique_column` must be
> called with `len(frame)`, never a separately-tracked `n`. Shared tables **may not**
> be subject to any non-deterministic row-dropping filter (or the filter's drop set
> must itself be part of the consistency unit). Pin: **"pinned row count" = the
> surviving count that carries keys**, and it is identical across teams by
> construction, not by hope.

---

## Summary table — holes → fixes

| # | Sev | Divergence (both obey the AD, still clash) | AD gap | Fix |
|---|-----|--------------------------------------------|--------|-----|
| H1 | CRIT | `arange` keys vs "seed-derived" keys → zero shared values | AD-16 ⟂ PDE-12 contradiction | Tighten AD-16: keys are position-derived `arange`, delete "seed-derived"; fix PRD PDE-12 |
| H2 | CRIT | Same keys, RNG-state-divergent FK edges → valid-looking garbage joins | No AD on *relationship* determinism | **New AD-20**: per-table RNG substreams; Spec flags cross-team tables |
| H3 | CRIT | Human fixture `id:1` collides with `arange(0,n)`; high-block vs negatives diverge | AD-16 reserved block unpinned, no offset | Tighten AD-16/17: pinned `[K_FIX,∞)` block, Spec-load rejects low fixture keys, `arange` asserts `n<K_FIX` |
| H4 | CRIT | Fixtures overlaid *after* the gate → ungated PII to non-prod | AD-17 ⟂ AD-19 order contradiction | Tighten AD-19: `Fix → Gate` (gate over the union, once, last); fixture collisions fail closed |
| H5 | HIGH | Post-gen overlay breaks PK uniqueness + FK validity `generate_related` established | AD-13/AD-17 silent on re-entering integrity | Tighten AD-17: overlay is a **checked merge** (key-range + FK resolution or fail closed) |
| H6 | HIGH | "Pinned Profile snapshot" undefined → random salt / fixtures / BLAS drift; fingerprint lies | AD-15 members not defined as hashed artifacts | Tighten AD-15: content-hash serialized artifacts incl. salt; Phase-1 thread pin or downgrade G4 |
| H7 | HIGH | Affirmation on Spec vs dest; deny-list format/empty → prod slips through | AD-18 location/format/enforcement unspecified | Tighten AD-18 (dest-only, typed non-empty deny-list) + **new AD-21** typed `GatedDataset` boundary |
| H8 | MED | `arange(n_requested)` vs surviving rows under filter → key/row detachment | AD-16 "pinned count" ambiguous | Tighten AD-16: keys over post-filter `len(frame)`; no non-deterministic drops on shared tables |

**Three new/renumbered ADs required:** AD-20 (shared-relationship determinism),
AD-21 (typed gated-load boundary). **Five ADs must be tightened:** AD-15, AD-16,
AD-17, AD-18, AD-19. **One PRD FR (PDE-12) must be corrected.** Two of the CRIT
findings (H1, H4) are outright contradictions *within the spine* and cannot survive
a careful read; the other two CRITs (H2, H3) are the kind that pass every unit test
and detonate at the first cross-team integration — which is the single event this
PRD is funded to make succeed.

Close these before opening stories, or the wedge you are validating validates
nothing.

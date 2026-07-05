---
title: Technical-Feasibility Review — TYMI PRD 1 (Obfuscated Prod-Like Dev Environments)
reviewer: staff-engineer feasibility gate
date: 2026-07-04
verdict: CONDITIONAL — vision sound; two NFRs (NFR-A scale, NFR-C determinism) require a
  fundamental rework of the shipped generation engine, not an extension. FR-6 and FR-17 are
  research-grade. The PRD is mostly honest about this but understates how deeply the MVP's
  single-RNG / whole-frame-in-RAM model has to be torn up.
severity_legend:
  BLOCKER: NFR/FR is not achievable as scoped without a core-engine rework; architecture must resolve before commit.
  HIGH: achievable but load-bearing and easy to get wrong; a wrong choice invalidates a headline claim.
  MEDIUM: real gap, bounded, solvable with known techniques.
  LOW: note / watch-item.
---

# Technical-Feasibility Review — PRD 1

Scope of the assessment: whether the PRD's non-functional claims are achievable against the
**shipped** MVP architecture (12 ADs, pandas-whole-Dataset-in-memory per AD-10), and which
risks the architecture phase must solve. Findings are grounded against the actual source, not
just the spec.

## What the shipped engine actually does (baseline)

Three facts about the MVP set every finding below:

1. **Whole-DB-in-RAM, not chunked.** `generate_related` (`src/tymi/synth/relational.py:37-61`)
   builds `result: dict[str, Dataset]` and keeps **every generated table as a full
   `pandas.DataFrame` in memory simultaneously** for the whole run. Parents are never freed —
   children sample FKs directly out of the parent's materialized frame
   (`_parent_values`, `relational.py:100-120`). This is the opposite of NFR-A's
   "generate a chunk → load it → free it."
2. **One sequential RNG threaded in topological order.** A single `numpy.random.Generator`
   is passed through `generate_faithful(...)` for each table in turn (`relational.py:49`,
   AD-4). Every draw's byte-output depends on the exact order and count of all prior draws.
3. **FK resolution is a uniform sample of parent row positions with no attribute
   conditioning.** `idx = rng.integers(0, parent_len, size=n)` (`relational.py:146`) picks
   parent rows uniformly at random; child columns are copied from those rows. There is **zero**
   statistical coupling between a child's own generated attributes and its parent's attributes.
   Cross-table correlation (FR-6) is genuinely unbuilt, not merely un-tuned.

---

## 1. Scale NFR (NFR-A / NFR-B) — MB → hundreds of TB, bounded memory, out-of-core, table-parallel

**Finding S-1 [BLOCKER] — NFR-A requires a rewrite of the generation engine, not an extension.**
The shipped `generate_related` holds the entire generated DB in RAM (`relational.py:45,56`),
and the leakage gate operates on a whole table with `frame.copy()`
(`src/tymi/synth/leakage.py:56,84`). Nothing in the pipeline is chunked. The PRD's own
addendum concedes this ("rules out the MVP's pandas-whole-Dataset-in-memory assumption",
addendum §Scale), but the FR/NFR body reads as if bounded-memory is a property to *assert*
(NFR-A "never holding … a whole large table in RAM"). It is not an assertion — it is a
ground-up re-architecture of `synth/`. The honest gap between "MVP holds a table in RAM" and
"hundreds of TB, bounded memory" is: **the entire post-profiling generation path
(`relational.py`, `generator.py`, `leakage.py`, the exporters) must be converted from
materialize-then-transform to a streaming iterator-of-chunks model.** Treat this as a new
subsystem, not a patch.

**Finding S-2 [BLOCKER] — several primitives are intrinsically whole-column and do not chunk.**
Even granting a chunked driver, these shipped mechanisms assume the full table is present:
- **PK uniqueness.** `_unique_column` emits `np.arange(n)` over the whole table
  (`relational.py:276-282`); `_unique_index_tuples` grows a `seen: set` to `n` entries
  (`relational.py:229-242`). Across chunks/workers, unique-key allocation needs a globally
  coordinated, deterministic partition of the key space (e.g. per-chunk disjoint integer
  ranges) — the current global counter cannot be parallelized without a serialization point.
- **Junction-table capacity.** `_assign_unique_junction_pk` materializes and de-duplicates the
  full parent-key cross-product and raises if `capacity < n` (`relational.py:213-221`). At
  scale this cross-product is itself unbounded.
- **`_dedupe_object`** suffixes duplicates in `series.tolist()` order (`relational.py:285-304`)
  — order-dependent and whole-column; must become a global, order-stable scheme.

**Finding S-3 [HIGH] — "table-parallel respecting FK order" understates the parent-materialization cost.**
NFR-B's table-parallelism is fine for *independent* tables, but the FK order forces a barrier:
a child cannot start until its parent's **complete key domain** exists, because FK sampling
(`relational.py:146`) draws over `parent_len` = the parent's full row count. For a 10-billion-row
parent, even holding *just the PK column* to sample from is tens of GB — that alone can breach
the memory bound before any child runs. Architecture must decide a **deterministic key-derivation
scheme** (child FK computed as a pure function of child-row-index → parent-key, e.g. a keyed hash
into the parent's known key range) so children need the parent's key *range/count*, not its
materialized *values*. Without that, "bounded memory" fails on any large parent.

**Guidance for architecture:** (a) Define a streaming `ChunkedSynthesizer` port that yields
`(Dataset chunk)` iterators; the orchestrator loads-and-frees per chunk. (b) Replace
sampled FK resolution with deterministic index→key derivation so parents need not be
materialized. (c) Partition unique-key space deterministically per (table, chunk). (d) State
plainly in the architecture that this supersedes AD-10's "Dataset = one DataFrame" for the
large-table path — AD-10 becomes "Dataset = a **stream** of Schema-tagged chunks."

---

## 2. Determinism under chunking + parallelism (NFR-C, AD-4)

**Finding D-1 [BLOCKER] — byte-identical output cannot be preserved *relative to today's MVP output*; it can only be redefined against a new seed-splitting scheme.**
The single sequential RNG (AD-4, `relational.py:49`) makes every table's bytes depend on the
draw history of all prior tables and rows. The moment you split the seed per (table, chunk)
via `SeedSequence.spawn` (addendum's proposal, correct), the draw sequence changes and the
output is **not** byte-identical to the current MVP. That is acceptable — but the architecture
must explicitly declare a determinism epoch/versioning: "byte-identical *within* the
seed-split scheme, keyed to a `generation_algorithm_version`." NFR-C and FR-11 read as if
determinism is unconditionally preserved; it is preserved *going forward from the rework*, not
across it. Flag this so cross-team consistency (FR-12) is not silently broken by the migration.

**Finding D-2 [HIGH] — real non-determinism leaks the seed-split does NOT cover.**
`SeedSequence.spawn` fixes RNG-draw order. It does **not** fix floating-point reduction order,
which the copula relies on:
- `nearest_psd` calls `np.linalg.eigh` (`src/tymi/synth/copula.py:47`) and the generator uses
  `np.linalg.cholesky` + `standard @ chol.T` (`copula.py:81-83`). LAPACK/BLAS results and
  matrix-multiply reduction order **vary with the BLAS backend (MKL vs OpenBLAS) and the thread
  count**. NFR-C's "pinned dependency versions" does not pin `OMP_NUM_THREADS` / BLAS vendor.
  Two runners with different NumPy wheels can produce different low-order bits → different
  uniforms → different inverse-CDF values → non-byte-identical output.
- **Mitigation architecture must specify:** pin BLAS threading to 1 (or a fixed count) for the
  copula path, or round/quantize the copula's latent draws to a fixed precision before the
  inverse-CDF, and pin the BLAS vendor in the lockfile. Add a cross-backend determinism test to
  CI (the current statistical tests assert *thresholds*, not *byte-identity*).

**Finding D-3 [HIGH] — parallel FK resolution + unique-key allocation are order-sensitive.**
FK sampling consumes `rng.integers(...)` sized to the chunk (`relational.py:146`); if chunks
are generated in parallel, each must draw from its **own** spawned stream keyed by
(table, chunk-index), never from a shared generator, or worker scheduling order leaks into
output. Likewise the global `seen` set in `_unique_index_tuples` (`relational.py:231`) and the
`result`-dict iteration must be replaced with deterministic, worker-order-independent schemes.
Any place the code today relies on "the order tables/rows were processed" is a determinism leak
under parallelism.

**Finding D-4 [LOW] — dict/hash ordering is currently safe but fragile.**
`guard.columns.items()` (`leakage.py:58`) and the `result` dict rely on insertion order, which
CPython preserves — fine today, but the architecture should mandate explicit `sorted()` at every
merge/aggregation boundary (manifest merges, multi-worker result collation) so a future refactor
can't reintroduce nondeterminism.

**Verdict on Q2:** byte-identical output under chunking+parallelism is *achievable* with a
disciplined seed-split **plus** floating-point-determinism controls — but the addendum only
names the seed-split half. The BLAS/reduction-order half is the sharp, under-flagged risk.

---

## 3. Cross-table statistical correlation (FR-6) without SDV/Copulas (AD-9)

**Finding C-1 [BLOCKER for FR-6 as written; HIGH overall] — this is the item that took SDV years, and it is currently unbuilt.**
Today the copula is strictly **intra-table** (`gaussian_copula_uniforms` operates on one
profile's Spearman matrix over that table's own numeric columns, `copula.py:58-84`), and
cross-table linkage is a **uniform random** parent-row pick (`relational.py:146`) with no
attribute conditioning. FR-6 ("preserve statistical correlations between columns of related
tables … within tolerance") therefore requires an entirely new mechanism. The addendum's
candidates (condition child on parent attributes / joined-view copula over a denormalized
target / hierarchical synthesis) are exactly the family SDV's HMA and hierarchical copulas
occupy — multi-year, subtle work (cardinality-aware conditioning, propagation of correlation
through one-to-many joins without distorting marginals, avoiding compounding error across
FK hops). Reproducing even a *narrow* slice in-house on numpy/scipy is realistic **only if the
scope is aggressively bounded** to parent→child single-hop conditioning on a small set of
declared correlation targets. Full multi-hop joined correlation is not a bounded MVP.

**Finding C-2 [HIGH] — FR-6 is in direct tension with NFR-A (bounded memory). This interaction is not called out anywhere.**
To condition a child's attributes on its parent's attributes, the parent's **per-row attribute
values** (not just its keys) must be available when the child is generated. That contradicts the
out-of-core promise of "generate parent → load it → free it" (addendum §Scale) and Finding S-3's
key-only derivation. You cannot both (a) free the parent frame for bounded memory and
(b) condition children on parent attribute values. The architecture must pick a lane per
correlation target: either persist a compact **parent-attribute summary** (e.g. the joint
distribution / conditioning table the child samples from — an aggregate, AD-6-friendly) rather
than the parent rows, or accept a higher memory bound on tables that participate in cross-table
correlation. OQ-3 correctly flags "depth"; it does **not** flag this memory conflict.

**Guidance:** Bound FR-6 in the architecture to **single-hop parent→child conditioning via a
persisted conditioning aggregate** (a small joint histogram / per-parent-stratum marginal),
explicitly deferring multi-hop joined copulas (as the MVP spine already deferred "cross-table
statistical correlation" and "vine copulas"). Tie the accepted scope to OQ-3's resolution before
any story is written.

---

## 4. FK-consistent whole-DB + connected-subset (FR-16) + delta refresh (FR-17)

**Finding F-1 [HIGH] — whole-DB FK integrity at scale is the S-3 problem restated: the current design needs the full parent in RAM.**
Covered above; the fix (deterministic key-derivation) is a precondition for FR-4 at scale, not
just an optimization.

**Finding F-2 [HIGH] — connected-subset (FR-16) collides with determinism *and* bounded memory simultaneously.**
A referentially-complete subset means selecting seed rows and walking the FK closure. Three
constraints fight:
- **Memory:** the selected-key frontier for a transitive closure over a dense graph can grow
  large; holding it violates NFR-A. Naive closure is unbounded.
- **Determinism (FR-11/12):** the subset must be reproducible byte-for-byte and must yield the
  **same** `customer_id`s as a full run for cross-team joins (FR-12). That means subsetting
  cannot be "generate then filter" (RNG history would differ) — it must be a deterministic
  *selection function over the same key space* the full run uses. This only works if key
  derivation is deterministic and independent of row-processing order (Finding S-3 again).
- **Semantics (OQ-4):** direct-parents-only vs full transitive closure changes both the memory
  bound and the completeness guarantee. Must be resolved before design.
This triple-constraint (subset ⊗ determinism ⊗ bounded memory) is the second-hardest thing in
the PRD and is only partially surfaced (OQ-4 covers semantics, not the memory/determinism
interaction).

**Finding F-3 [HIGH] — delta refresh (FR-17) is correctly flagged highest-risk and *depends on the NFR-C rework landing first*.**
The current byte-identity comes from regenerating everything in one sequential RNG pass. Any
"regenerate only affected tables" delta (addendum option 2) changes the RNG consumption order and
would break byte-identity of the *unchanged* tables — **unless** per-table `SeedSequence.spawn`
(the D-1 rework) is already in place so each table's stream is independent of the others. So
FR-17 is not independently schedulable: it is gated on NFR-C. The "diff against last provisioned
state" option (addendum option 1) additionally requires persisting or re-deriving prior output
deterministically. OQ-1's instinct to phase FR-17 last is correct; the architecture should make
the **NFR-C seed-split a hard prerequisite** of FR-17 and phase accordingly.

---

## 5. Leakage gate over a whole DB, out-of-core (FR-7)

**Finding L-1 [BLOCKER] — the hashed membership set does NOT fit in bounded memory at scale.**
The guard stores, per sensitive column, the **sorted distinct digests of every real source
value** (`LeakageGuard.columns`, `artifacts.py:176-189`), and the gate loads them into a Python
`set` (`digest_set = set(digests)`, `leakage.py:61`). Each digest is a 128-bit BLAKE2b hex
string (`_LEAKAGE_DIGEST_SIZE = 16`, `artifacts.py:23`; `leakage_digest`, `artifacts.py:26-39`)
— as a Python `str` in a `set`, ~80–100 bytes each with overhead. The set size is proportional
to **source distinct cardinality**, which at hundreds of TB is unbounded: a high-cardinality
sensitive column (email, SSN, per-customer token) with ~1e9 distinct real values →
**~100 GB in-memory set**, replicated into *every* parallel worker that runs the gate. This
directly breaks NFR-A. The PRD asserts FR-7 "runs over the entire generated database" as if the
reference set is free; it is not.

**Finding L-2 [HIGH] — the gate is also a throughput problem: per-cell Python map.**
`enforce_leakage_gate` calls `column.astype(object).map(_hits)` (`leakage.py:105`), an
O(rows) Python-level function call per cell, on the whole column at once (`.copy()`,
`leakage.py:64`). At billions of rows this is both non-streaming and Python-bound — orders of
magnitude too slow for NFR-B. It must be re-expressed as a vectorized, chunked membership test.

**Guidance for architecture:**
- Replace the exact in-memory `set` with a **disk/mmap-backed or probabilistic membership
  structure** sized to a configured false-positive rate — a Bloom/cuckoo filter or an on-disk
  sorted-digest index. A Bloom filter's false positives fail in the **safe** direction (spurious
  regenerate, never a missed leak), but note two consequences the design must own: (i) spurious
  regenerations must still be **deterministic** (draw from the same spawned stream), and (ii) a
  pathological false-positive rate could trip the `max_attempts` fail-closed
  (`DEFAULT_MAX_ATTEMPTS = 100`, `leakage.py:32`) — size the filter so this can't happen in
  practice. Shrinking the digest (16 → 8 bytes) plus a filter cuts the footprint hard.
- Run the gate **per chunk** inside the streaming pipeline (AD-7 stays a mandatory core stage;
  it just consumes a chunk stream), and vectorize `_hits` (hash the column with a vectorized
  BLAKE2b / numpy path, not `.map`).
- The membership structure is built once at profile time and is **read-only** during
  generation, so it can be shared (mmap) across workers rather than copied — call this out so
  L-1's "replicated into every worker" trap is avoided.

---

## Cross-cutting: the sharpest interactions (for the architecture phase)

1. **FR-6 ⊗ NFR-A** (C-2): conditioning children on parent attributes vs. freeing parents for
   bounded memory — mutually exclusive unless you persist an *aggregate* conditioning table.
2. **FR-16 ⊗ FR-11/12 ⊗ NFR-A** (F-2): connected-subset must be a deterministic selection over
   a shared key space, with a bounded closure frontier.
3. **FR-17 ⊗ NFR-C** (F-3): delta refresh is gated on the per-table seed-split landing first.
4. **NFR-C ⊗ BLAS** (D-2): seed-splitting is necessary but not sufficient for byte-identity;
   floating-point reduction order in the copula is an unaddressed leak.
5. **FR-7 ⊗ NFR-A** (L-1): the leakage reference set is O(source distinct cardinality) and is the
   quiet way "bounded memory" dies.

## Is the PRD honest?

Mostly yes, and better than typical: the addendum openly states the pandas model is ruled out,
names seed-splitting, and flags FR-17 as highest-risk with an Open Question. The **gaps in
honesty** are: (a) NFR-A/NFR-C are framed as *properties to assert* when they are a core-engine
rewrite; (b) the FR-6 ⊗ bounded-memory conflict and the FR-7-reference-set memory cost are
unacknowledged; (c) determinism is presented as preserved when it can only be *redefined* across
the rework; (d) the BLAS/floating-point half of determinism is missing. None of these sink the
vision — they are architecture-phase problems — but they should be surfaced as named risks so the
architecture is scoped to solve them rather than discovering them mid-epic.

## Recommended gates before committing epics

- Resolve **OQ-3** (FR-6 depth) to single-hop conditioning-via-aggregate, or FR-6 is unbounded.
- Resolve **OQ-4** (FR-16 closure depth) *together with* its memory/determinism interaction.
- Make **per-table seed-split (NFR-C)** a foundational story that lands before FR-6/FR-16/FR-17.
- Add a **cross-backend byte-identity CI test** and pin BLAS threading, before claiming FR-11.
- Prototype the **out-of-core leakage structure** (L-1/L-2) early — it is a load-bearing, novel
  component, not a late polish item.

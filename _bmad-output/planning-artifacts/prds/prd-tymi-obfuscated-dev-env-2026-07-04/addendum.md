# Addendum — TYMI PRD 1 (Obfuscated Prod-Like Dev Environments)

Technical-how / mechanism notes captured during discovery. These belong to the
architecture/solution-design phase, not the PRD body.

## Scale & performance mechanism (drives FR-4..7, FR-13, FR-16/17 and the scale NFR)

The scale span (megabytes → hundreds of terabytes, open-source) rules out the MVP's
pandas-whole-Dataset-in-memory assumption for large DBs. Architecture must decide the
execution model; the PRD only asserts the *property* (bounded-memory throughput).

- **Out-of-core / chunked generation:** generate a table in row-chunks, stream each chunk
  to the destination loader, free it — memory footprint bounded and configurable,
  independent of table/DB size. The canonical Schema (AD-10) applies per chunk.
- **Table-level parallelism:** independent tables (no FK dependency between them) generate
  concurrently; the FK dependency graph (FR-4) defines the partial order / barriers.
- **Determinism under chunking + parallelism (AD-4/NFR-4):** the single seeded RNG must be
  split deterministically per table/chunk (e.g. `numpy` `SeedSequence.spawn` keyed by
  table+chunk index) so output is byte-identical regardless of chunk size or worker count.
  This is the load-bearing constraint on the parallel design.
- **Distributed generation (escape hatch, deferred):** if single-runner throughput is
  insufficient at the extreme tail, the same chunked/seed-split design extends to multiple
  workers/nodes. Was a named MVP-PRD v2 deferral ("distributed / cluster-scale generation").
- **Backend:** `polars` / streaming engines were flagged in the MVP architecture as the
  ">10M rows" revisit; candidate for the chunked path. License must stay AD-9-permissive.

## Cross-table correlation mechanism (FR-6)

Beyond referential integrity: preserve statistical correlation between columns of related
tables. Candidate approaches (architecture to choose): conditioning child-table generation
on parent attributes; a joined-view copula over the denormalized correlation targets;
or hierarchical/graph-aware synthesis. Must respect AD-9 (no SDV/Copulas BUSL) — likely an
in-house extension of the existing Gaussian copula across the FK join.

## Incremental / delta refresh mechanism (FR-17, highest risk)

The delta must stay FK-consistent, preserve pinned fixtures, and keep determinism. Options:
regenerate deterministically and diff against the last provisioned state (apply only the
diff), or track source/spec changes and regenerate only affected tables + their FK
closure. Open question in the PRD.

## Feasibility notes (from the finalize review — for the architecture phase)

**Phase 2 scale is a rewrite of the generation engine, not an extension.**
- Today `synth/relational.py` holds every table as a full `pandas.DataFrame` for the whole
  run and resolves FKs by sampling the parent's *materialized* frame; `synth/leakage.py`
  `.copy()`s whole tables. Bounded-memory out-of-core means converting the whole
  post-profiling path from materialize-then-transform to a chunk-stream model and
  superseding AD-10's "Dataset = one DataFrame" per run.
- **Leakage reference-set is the quiet memory killer (PDE-7 / NFR-A).** The guard loads the
  distinct digests of *every real source value* into a Python `set` (O(source
  cardinality)) — a high-cardinality column at hundreds of TB is a ~100 GB set, replicated
  per worker, checked per-cell via a non-streaming `.map`. Phase 2 needs a disk/mmap-backed
  or Bloom/cuckoo membership structure with a bounded false-positive budget (a false
  positive only forces a regeneration, so it's safe — it never lets a real value through).

**Determinism (NFR-C) — the BLAS half.** `SeedSequence.spawn` per table/chunk is necessary
but not sufficient: `np.linalg.eigh` / `cholesky` / matmul in the copula have BLAS-vendor-
and thread-count-dependent floating-point reduction order. The reproducible run environment
must pin BLAS threading (e.g. single-threaded BLAS or a fixed thread count + vendor), not
just dependency versions. Byte-identity is *redefined* across the Phase-2 rewrite, not
preserved against the current MVP output.

**Cross-table correlation (PDE-6, Phase 3) is SDV-class and fights bounded memory.** FKs
today are a *uniform* parent-row pick with zero attribute conditioning; the copula is
intra-table only. Conditioning children on parent attributes contradicts "free the parent"
(streaming) — bound the first cut to **single-hop parent→child conditioning via a persisted
per-parent aggregate**, not full multi-hop joined correlation. Must stay AD-9-permissive
(no SDV/Copulas BUSL) — an in-house extension of the Gaussian copula across the FK join.

**Reference-DB benchmark (for G1a).** Define a fixed public-ish schema (e.g. a ~10–20 table
OLTP schema, ~1–10M total rows) as the G1a "minutes" benchmark, so the north-star time is
measured against a stable target rather than an unbounded "typical DB".

**FR interactions to watch.** Subsetting (PDE-16) ⊗ determinism ⊗ bounded memory is three
constraints at once (deterministic connected-subset selection over a shared key space with
a bounded closure frontier); delta refresh (PDE-17) cannot be scheduled before the Phase-2
per-table seed-split lands.

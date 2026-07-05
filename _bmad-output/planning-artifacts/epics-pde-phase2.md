# PRD 1 — Phase 2 epics & stories (out-of-core streaming)

Scale the whole-DB provisioning to arbitrarily large databases with bounded memory, on the shipped
in-memory engine, via chunked streaming. Architecture: `architecture-tymi-pde-phase2-2026-07-05/`
(AD-22..24 over Phase 1's AD-13..21). No new dependencies (AD-9). Each story runs the full 3-layer
`bmad-code-review` gate before `done`; build/test in the devcontainer.

## Epic P2 — Out-of-core streaming provisioning

### Story P2.1: Chunk-aware substreams + chunked single-table generation

As a maintainer, I want a table generated in bounded-memory row-blocks, byte-identical for a given
block size, so that an arbitrarily large table never has to fit in RAM (AD-22). (Keys are
position-derived and therefore chunk-boundary-independent; the non-key data is pinned by
`chunk_rows`, which is part of the consistency unit.)

**AC.** `table_substream(seed, table, chunk)` extends the Phase-1 substream with a chunk index
(chunk `None` = the Phase-1 whole-table stream, unchanged). A chunked generator yields blocks of
`chunk_rows` from `generate_faithful`, with **global-position** surrogate PK / shared keys. The
concatenation of blocks is byte-identical for a given `(seed, table, chunk_rows)`; the leakage gate
runs per block. `chunk_rows` added to `TableSpec`/`Spec` (pinned, in the fingerprint).

### Story P2.2: Position-addressable FK resolution across chunks

As a maintainer, I want a child block's foreign keys resolved from parent **positions** without
loading the parent, so that referential integrity holds out-of-core (AD-23).

**AC.** A resolver maps a drawn parent position to the parent key via its key rule (surrogate
`pos`, shared `reserved+pos`). A child block emits valid FKs pointing at parent keys that will
exist; RI holds across chunks; self-FKs resolve against the table's own total. A non-position-
addressable (natural-key / composite) FK target fails closed with a clear error (Phase-2 limit).

### Story P2.3: Streaming load + `stream_from_spec`

As a self-service provisioner, I want the whole DB generated and written chunk-by-chunk, so that
peak memory is one chunk at any DB size (AD-24).

**AC.** `stream_from_spec(spec)` yields `(table, chunk_index, GatedDataset)` in FK-topological order,
each chunk sealed (AD-21). `EngineAdapter` gains a streaming write (`load_stream`): first chunk
replaces (truncate), the rest append; idempotent on re-run. Only `GatedDataset` chunks are written.

### Story P2.4: Out-of-core `provision` + aggregated report

As a self-service provisioner, I want `tymi provision` to stream by default, so that I can provision
a DB of any size in minutes with bounded memory (AD-19 preserved, AD-22..24).

**AC.** `provision` routes through the streaming path (guardrail first, unchanged); the report
aggregates per-table row counts across chunks + fixtures + fidelity (sampled on the first chunk) +
the consistency-unit fingerprint. Peak memory is one chunk regardless of total rows (asserted).
`provision` stays idempotent and callable identically by CLI / CI / DAG.

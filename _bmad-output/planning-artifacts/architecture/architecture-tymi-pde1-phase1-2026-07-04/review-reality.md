# Reality-Check Review — ARCHITECTURE-SPINE (TYMI PRD-1 Phase-1)

Reviewer pass: verify every committed decision against the ACTUAL codebase, not
assumption. Scope: the reuse claims (AD-13, AD-16, AD-6/7, AD-2), the "no new
dependency" claim, and the Structural-Seed module placements vs the hexagonal
import-linter contracts.

**Verdict: CHANGES REQUESTED.** The spine's *behavioral* reuse claims are largely
accurate — `generate_related`, `_unique_column`, `EngineAdapter.load`, and the
"no new dependency" claim all check out against source. But one **HIGH** finding
is load-bearing: the placement of `tymi/core/provision.py` as an orchestrator that
imports the synth/engines concretes **directly violates the repo's import-linter
`forbidden` contract and AD-1** — and there is no port through which core could
reach `generate_related`. Several supporting claims about *where* the LeakageGate
lives and *when* it runs are also out of date.

---

## Verified accurate (claims the code supports)

- **AD-13 — `generate_related` behavior.** `src/tymi/synth/relational.py:37`
  (`generate_related`) does exactly what AD-13 asserts: `_topological_order`
  (relational.py:72, parents-before-children, raises on cycles), per-table
  `generate_faithful` (relational.py:49), unique-PK enforcement
  (`_enforce_primary_key`, relational.py:152), and pure-junction PK handling
  (`_assign_unique_junction_pk`, relational.py:177, raises when requested rows
  exceed distinct parent-key combos). Claim is grounded. ✓
- **AD-16 — `_unique_column` arange.** `relational.py:276` returns
  `np.arange(n, dtype="int64")` (as nullable `Int64`) for integer columns, float
  arange for floats, `str(i)` for objects. The "arange-style monotonic integer
  key" claim is accurate. ✓ (But see MEDIUM below on the parts of AD-16 the code
  does *not* support.)
- **AD-2 — `EngineAdapter.load()`.** `src/tymi/ports/__init__.py:32`:
  `def load(self, dataset: Dataset, *, table: str) -> None`. Present on the
  `EngineAdapter` Protocol. ✓
- **"No new runtime dependency for Phase 1."** SOLID. `pyproject.toml`
  `[project].dependencies` already ships `pyyaml>=6.0` and `pydantic>=2.11`
  (Spec + fixtures YAML), plus numpy/pandas/sqlalchemy for generation+load. The
  topological sort is hand-rolled in `relational.py:72` — **no graph library**
  (networkx etc.) is pulled in, and nothing in the spine implies a schema-registry
  or other hidden dep. Claim holds. ✓

---

## Findings

### HIGH-1 — `tymi/core/provision.py` (AD-19 / Structural Seed) violates the import-linter `forbidden` contract and AD-1

**Location:** ARCHITECTURE-SPINE.md — Structural Seed (`tymi/core/provision.py`),
AD-19, the "Dependency direction" diagram (`core -.imports only.-> ports`), and
the Design-Paradigm table ("Whole-DB provisioning pipeline → `tymi.core`").

**What's wrong:** `pyproject.toml` `[tool.importlinter]` defines a **`forbidden`**
contract (pyproject.toml:96-110):

```
source_modules   = ["tymi.core", "tymi.ports", "tymi.domain"]
forbidden_modules = ["tymi.engines", "tymi.synth", "tymi.chaos",
                     "tymi.privacy", "tymi.eval", "tymi.io", "tymi.cli", "tymi.ui"]
```

`tymi.core` is **banned from importing `tymi.synth` and `tymi.engines`.** Today
core honors this completely (grep of `src/tymi/core/*.py` finds zero imports of
synth/engines — only a docstring mention and the `"tymi.engines"` entry-point-group
*string* in `plugins.py`). But the AD-19 pipeline —
`generate_related → LeakageGate → fixtures overlay → keys → EngineAdapter.load` —
requires calling:

- `generate_related` (in `tymi.synth.relational`),
- `enforce_leakage_gate` (in `tymi.synth.leakage`),
- the new `tymi/synth/keys.py` and `tymi/synth/fixtures.py`,
- `EngineAdapter.load` (a `tymi.engines` concrete).

If `tymi/core/provision.py` imports any of these directly, `lint-imports` **fails**
and AD-1 is broken.

**Why it can't be waved through as "route via ports":** the `Synthesizer` port
(`ports/__init__.py:36`) exposes only single-table
`generate(profile, *, rows, rng)`. **There is no port for multi-table/relational
generation**, and `generate_related` / `enforce_leakage_gate` / keys / fixtures are
free functions, not port methods. So core *cannot* reach the reused generator
through `tymi.ports` as the spine's dependency diagram claims. The spine commits to
"core orchestrator" without either (a) moving `provision` to a composition/adapter
layer (the CLI already plays this role — `cli/app.py:353` calls `adapter.load(...)`
directly, and `ui/services.py:531` does too), or (b) introducing a new relational
`Synthesizer`-style port. Neither is stated. **This is the decision most likely to
break the build the first day a story implements it.**

**Fix options:** either relocate the pipeline to a driving/composition layer
(`tymi.cli` / a new `tymi.app` composition root that is *not* in the forbidden
source set) and keep core holding only pure logic; or add explicit ports
(`RelationalSynthesizer`, a gate port, key/fixture ports) and inject concretes —
and say so in AD-19. As written, AD-19 + the Structural Seed are internally
inconsistent with AD-1.

### MEDIUM-1 — AD-6/7 mischaracterizes where the LeakageGate lives and when it runs

**Location:** Inherited-Invariants table (AD-6/7 "the core **LeakageGate** runs
pre-export"), Design-Paradigm assertion, and the Provisioning-flow diagram
(`Gen → Keys → Gate[LeakageGate + PII scan] → Fix`).

**What's wrong on two counts:**

1. **It is not in core.** The gate is `enforce_leakage_gate` in
   `src/tymi/synth/leakage.py` — inside `tymi.synth`, an adapter package the
   forbidden contract keeps core *out* of. Calling it "the core LeakageGate" is
   inaccurate about its package home and compounds HIGH-1.
2. **It does not run as a discrete stage after `generate_related`.** It is invoked
   *inside* `generate_faithful` as its terminal step (`generator.py:71`,
   commented "Terminal core stage"), which `generate_related` calls **per table**
   (`relational.py:49`). So in the real code the gate has already run, per-table,
   *before* any shared-key emission or fixtures overlay would happen. The flow
   diagram's ordering (`generate_related → Keys → Gate → Fix`) is a fiction — the
   gate is embedded, not downstream. Any shared keys or fixtures added *after*
   `generate_related` are therefore **not** covered by the gate that already ran.

### MEDIUM-2 — AD-17 "fixtures still passed through the LeakageGate" is not a drop-in reuse

**Location:** AD-17, and the flow diagram `Gate → Fix`.

**What's wrong:** the existing gate's contract (leakage.py:39-88) is
*regenerate-on-collision*: on a hit it calls a `resample` callback up to
`max_attempts` (default 100) and only *then* fails closed (`LeakageError`).
Fixtures are declared **regenerate-never** (AD-17). So the gate cannot be reused
verbatim for fixtures — regenerating a fixture contradicts the fixture contract.
Making fixtures "fail closed on a real-PII hit" needs a *new* scan-and-reject mode
(or a resampler that raises immediately), plus plumbing a per-table `LeakageGuard`
to the overlay (the gate is single-Dataset + single-guard; there is no whole-DB
gate). The spine presents this as reuse; it is materially new behavior. Also note
the flow labels this stage "LeakageGate **+ PII scan**" — the gate does no PII
classification (that is the separate `PIIClassifier` port, `ports/__init__.py:54`);
the gate only checks against an already-declared hashed guard. The "+ PII scan"
is unbacked by the cited code.

### MEDIUM-3 — AD-16's "reserved keyspace" and "(table, row-position)" keying are not supported by `_unique_column`

**Location:** AD-16 ("emitted … keyed by `(table, row-position)`", "a **reserved
keyspace block** is set aside for fixtures; generated shared keys never enter it",
"ratifies the existing `_unique_column` arange").

**What's wrong:** `_unique_column` (relational.py:276) is `np.arange(n)` keyed by
**row-position only** — it always starts at **0** and has **no `table`
component**. Consequences the spine glosses:

- Two tables of equal row count get *identical* 0…n-1 sequences — fine if that is
  the intended shared-key semantic, but the code does not key by table.
- A "reserved fixture block" is **not** honored: arange starts at 0, so it would
  collide with any low reserved range. The claim that "generated shared keys never
  enter [the fixture block]" is aspirational; nothing in `_unique_column` offsets
  past a reserved block.

The spine *does* hedge this correctly as `[ASSUMPTION → OQ-5]`, so this is not a
false assertion — but the word "ratifies" overstates what the shipped arange
provides. OQ-5 should explicitly own "add a table/keyspace offset" as new work,
not a ratification.

### LOW-1 — "reuse" of `generate_related` is first-wiring, not extending a live path

**Location:** AD-13 ("**existing** `generate_related`, reused"), paradigm table.

**Context, not a defect:** `generate_related` has **zero callers** in the repo
(grep across `src/tymi/`). It is shipped, tested Story-2.3 code, and its behavior
matches AD-13 — but no pipeline/CLI/UI invokes it today. "Reuse" here means wiring
it in for the first time. Worth stating so estimation doesn't assume a live,
exercised integration path. This also intersects HIGH-1: the *first* caller
(`core/provision.py`) is the one that would trip the import contract.

---

## Bottom line

The behavioral reuse claims (AD-13, AD-16 arange, AD-2, no-new-dep) are grounded in
source and correct. The architectural placement is not: **AD-19 + the
`tymi/core/provision.py` seed contradict the repo's own import-linter forbidden
contract and AD-1**, with no port to legitimize the core→synth reach. Resolve
HIGH-1 (relocate provision to a composition/adapter layer, or add explicit ports)
and correct the LeakageGate location/ordering (MEDIUM-1/2) before any story opens
against this spine.

# How It Works

TYMI turns a **real dataset** into a **statistical description** and then uses
that description to **generate synthetic data** — faithful or deliberately
chaotic — that can be published to another database, with **no real values ever
leaving the source**.

## The end-to-end flow

```text
[ source DB (real) ]                              [ destination DB (elsewhere) ]
        │                                                     ▲
        ▼                                                     │
   1. Connect ──► 2. Profile ──► (Profile file) ──► 3. Generate ──► 4. Export / Load
                       │                                  ▲
               "description of                       reads the Profile
                the sample"                        (contains no real data)
```

1. **Connect** to a source engine (MSSQL, StarRocks, PostgreSQL, MySQL).
2. **Profile** — sample the data (never the whole table) and compute its
   statistical signature: distributions, correlations, schema metadata, PII
   tags. The result is the **Profile**.
3. **Generate** synthetic rows *from the Profile* — either **faithful**
   (statistically identical) or **chaotic** (deliberately broken). The source is
   not touched again.
4. **Export / Load** to files (CSV/Parquet/JSON), SQL `INSERT`s, or a direct
   load into any of the four engines.

## The two intermediate files

There are two artifacts between "analyze" and "publish", with distinct roles:

| Artifact | What it is | Role |
| --- | --- | --- |
| **Profile** (`*.profile.yaml` / `.json`) | The statistical *description* of the sample — histograms, quantiles, category frequencies, correlations, PII tags, schema metadata. **Never stores raw values.** | The reusable "mold". Produce it once; move it anywhere; regenerate offline. |
| **Declarative Config** (`tymi.yaml`) | The *recipe* for a run: which source, generation rules, chaos policy, `seed`, and destination. | Ties the flow together; shared verbatim by the CLI and the web UI. |

## Why the Profile is the key decoupling point (privacy by design)

Because the Profile contains **no real values**, it is the boundary that lets
you separate "where the real data lives" from "where synthetic data is
produced":

- **Profile in environment A** (where the sensitive, production data lives) →
  you get a Profile with zero real values.
- **Carry that Profile to environment B** (dev / staging / another company) and
  **generate + publish there**, without environment B ever touching production
  data.

The Profile is versioned and usable offline, so you generate it once and
regenerate data as many times as you want, targeting any engine. With the same
`seed`, the output is identical every time (reproducible for CI).

## Example (target design)

```bash
# In the environment that holds the real data:
tymi profile --config tymi.yaml -o customers.profile.yaml    # the "description"

# In another environment (only the Profile, no access to the source):
tymi generate --profile customers.profile.yaml --rows 1000000 --config dest.yaml
#   └─ generates 1M faithful rows and loads them into the destination DB
```

## Engines are interchangeable

Every engine is one bidirectional adapter (read **and** write), discovered as a
plugin. So the source and the destination are chosen independently — e.g.
profile from MSSQL, load into PostgreSQL.

## Faithful vs Chaos

- **Faithful Generator** — reproduces marginal distributions, correlations, and
  referential integrity; realistic synthetic values; a leakage gate guarantees
  no real sensitive value reaches the output.
- **Data Chaos Monkey** — injects out-of-distribution values, invalid
  formats/types, and schema/constraint violations under a declarative policy,
  emitting an auditable manifest of every fault it injected.

See [Status](status.md) for what is implemented today versus designed.

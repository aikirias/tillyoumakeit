"""Multi-table relational generation (Story 2.3).

Generates a set of related tables so the result is referentially consistent:
tables are produced in **topological order** (parents before children), each
table's **primary key is unique**, every **foreign key points at an existing
parent value** (a PK or any referenced unique column), and declared
**single-column unique constraints** hold.

Each table is first generated independently by ``generate_faithful`` (marginals +
correlation + realistic Faker values), then post-processed to enforce the
constraints against the parents already generated in this run. All randomness
comes from the injected ``rng`` (AD-4/AD-11); each Dataset keeps its Profile's
canonical Schema (AD-10).

Enforcement order per table: sample non-self FKs from parents → make the PK unique
(FK-aware) → publish the table → resolve self-referential FKs → dedupe single-
column unique constraints.

Scope / documented limits: a foreign key whose parent table is not in the given
set is left as-generated (no parent to source from). A pure *junction* PK (every
PK column is FK-bound) is filled with unique valid parent-key combinations, and
raises ``GenerationError`` if the requested row count exceeds the number of
available parent-key combinations. Composite (multi-column) unique constraints
beyond the PK are left as-generated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import Dataset, Profile, Schema
from tymi.synth.generator import generate_faithful


def generate_related(
    profiles: dict[str, Profile],
    *,
    rows: int | dict[str, int],
    rng: np.random.Generator,
) -> dict[str, Dataset]:
    """Generate related tables with referential integrity, keyed by table name."""
    order = _topological_order(profiles)
    result: dict[str, Dataset] = {}
    for table in order:
        profile = profiles[table]
        n = _rows_for(rows, table)
        frame = generate_faithful(profile, rows=n, rng=rng).frame.copy()
        schema = profile.schema
        # 1. Point non-self FKs at real parent values (parents are already final).
        _enforce_foreign_keys(frame, schema, result, table, rng, only_self=False)
        # 2. Make the primary key unique (FK-aware: surrogate vs pure junction).
        _enforce_primary_key(frame, schema, result, table, n, rng)
        # 3. Publish so children (next iterations) and self-FKs can reference it.
        result[table] = Dataset(frame=frame, schema=schema)
        # 4. Self-referential FKs draw from this table's now-final keys.
        _enforce_foreign_keys(frame, schema, result, table, rng, only_self=True)
        # 5. Single-column unique constraints (best-effort, dtype-preserving).
        _enforce_unique_constraints(frame, schema)
    return result


def _rows_for(rows: int | dict[str, int], table: str) -> int:
    if isinstance(rows, dict):
        if table not in rows:
            raise GenerationError(f"no row count provided for table {table!r}")
        return rows[table]
    return rows


def _topological_order(profiles: dict[str, Profile]) -> list[str]:
    """Parents (referred tables) before children; raise on a cyclic FK graph."""
    names = set(profiles)
    deps: dict[str, set[str]] = {t: set() for t in profiles}
    for table, profile in profiles.items():
        for fk in profile.schema.foreign_keys:
            parent = fk.referred_table
            # Self-references and FKs to tables outside the set impose no ordering
            # constraint (a self-FK draws from the table's own finalized keys).
            if parent in names and parent != table:
                deps[table].add(parent)

    order: list[str] = []
    remaining = {t: set(d) for t, d in deps.items()}
    while remaining:
        ready = sorted(t for t, d in remaining.items() if not d)
        if not ready:
            raise GenerationError(
                f"cyclic foreign-key dependency among tables: {sorted(remaining)}"
            )
        for table in ready:
            order.append(table)
            del remaining[table]
        for d in remaining.values():
            d.difference_update(ready)
    return order


def _parent_values(
    result: dict[str, Dataset],
    frame: pd.DataFrame,
    table: str,
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> dict[str, pd.Series] | None:
    """Candidate parent values for the referred columns, or ``None`` if unavailable.

    Draws from the parent's *published* frame (so FK → PK and FK → any unique
    column both work); a self-reference draws from this table's own frame.
    """
    source = frame if referred_table == table else None
    if source is None:
        dataset = result.get(referred_table)
        if dataset is None:
            return None
        source = dataset.frame
    if not all(col in source.columns for col in referred_columns):
        return None
    return {col: source[col].reset_index(drop=True) for col in referred_columns}


def _enforce_foreign_keys(
    frame: pd.DataFrame,
    schema: Schema,
    result: dict[str, Dataset],
    table: str,
    rng: np.random.Generator,
    *,
    only_self: bool,
) -> None:
    """Point each FK's columns at sampled parent rows (dtype-preserving)."""
    n = len(frame)
    if n == 0:
        return
    for fk in schema.foreign_keys:
        if (fk.referred_table == table) != only_self:
            continue
        parent = _parent_values(result, frame, table, fk.referred_table, fk.referred_columns)
        if parent is None:
            continue  # parent not generated / referred column missing → cannot enforce
        parent_len = len(next(iter(parent.values())))
        if parent_len == 0:
            continue
        # One parent-row index per child row keeps composite FKs internally consistent.
        idx = rng.integers(0, parent_len, size=n)
        for child_col, parent_col in zip(fk.columns, fk.referred_columns, strict=False):
            if child_col in frame.columns:
                frame[child_col] = _take(parent[parent_col], idx, frame.index)


def _enforce_primary_key(
    frame: pd.DataFrame,
    schema: Schema,
    result: dict[str, Dataset],
    table: str,
    n: int,
    rng: np.random.Generator,
) -> None:
    """Make the primary key unique without breaking FK validity."""
    pk = list(schema.primary_key)
    if not pk or n == 0:
        return
    fk_cols = {c for fk in schema.foreign_keys for c in fk.columns}
    non_fk_pk = [c for c in pk if c not in fk_cols]
    if non_fk_pk:
        # A single unique non-FK column makes the whole PK tuple unique while the
        # FK-bound PK columns keep their valid parent values.
        col = non_fk_pk[-1]
        if col in frame.columns:
            frame[col] = _unique_column(frame[col], n)
        return
    # Pure junction PK: every PK column is FK-bound → fill with unique valid combos.
    _assign_unique_junction_pk(frame, schema, result, table, pk, n, rng)


def _assign_unique_junction_pk(
    frame: pd.DataFrame,
    schema: Schema,
    result: dict[str, Dataset],
    table: str,
    pk: list[str],
    n: int,
    rng: np.random.Generator,
) -> None:
    """Fill an all-FK primary key with ``n`` unique, referentially-valid combos."""
    groups: list[tuple[list[tuple[str, str]], pd.DataFrame]] = []
    covered: set[str] = set()
    for fk in schema.foreign_keys:
        pk_in_fk = [c for c in fk.columns if c in pk]
        if not pk_in_fk:
            continue
        parent = _parent_values(result, frame, table, fk.referred_table, fk.referred_columns)
        if parent is None:
            raise GenerationError(
                f"cannot enforce unique primary key on junction table {table!r}: "
                f"parent {fk.referred_table!r} is unavailable"
            )
        pairs = [(c, fk.referred_columns[i]) for i, c in enumerate(fk.columns) if c in pk]
        # De-duplicate the referred value-tuples so distinct sampled indices map to
        # distinct PK tuples even when the referred column is not itself unique;
        # capacity is then counted in value space, not parent-row space.
        candidates = (
            pd.DataFrame({referred: parent[referred] for _, referred in pairs})
            .drop_duplicates()
            .reset_index(drop=True)
        )
        groups.append((pairs, candidates))
        covered.update(pk_in_fk)
    if any(col not in covered for col in pk):
        raise GenerationError(f"primary key of {table!r} mixes FK and unknown columns")

    lengths = [len(candidates) for _, candidates in groups]
    capacity = 1
    for length in lengths:
        capacity *= length
    if capacity < n:
        raise GenerationError(
            f"cannot generate {n} unique rows for junction table {table!r}: "
            f"only {capacity} distinct parent-key combinations exist"
        )
    combos = _unique_index_tuples(lengths, n, rng)
    for group_i, (pairs, candidates) in enumerate(groups):
        selection = np.array([combos[row][group_i] for row in range(n)])
        for pk_col, referred_col in pairs:
            frame[pk_col] = _take(candidates[referred_col], selection, frame.index)


def _unique_index_tuples(lengths: list[int], n: int, rng: np.random.Generator) -> list[tuple]:
    """``n`` distinct index tuples, each component drawn from ``range(lengths[i])``."""
    seen: set[tuple] = set()
    out: list[tuple] = []
    while len(out) < n:
        batch = (n - len(out)) * 4
        draws = [rng.integers(0, length, size=batch) for length in lengths]
        for combo in zip(*draws, strict=False):
            if combo not in seen:
                seen.add(combo)
                out.append(combo)
                if len(out) == n:
                    break
    return out


def _enforce_unique_constraints(frame: pd.DataFrame, schema: Schema) -> None:
    """De-duplicate declared single-column unique constraints (dtype-preserving).

    Skips the primary key (already unique) and FK-bound columns (uniqueness would
    contradict many-to-one FK sampling). Already-unique columns are left untouched
    so realistic Faker values survive. Composite unique constraints are best-effort.
    """
    fk_columns = {c for fk in schema.foreign_keys for c in fk.columns}
    pk = tuple(schema.primary_key)
    for cols in schema.unique_constraints:
        if tuple(cols) == pk or len(cols) != 1:
            continue
        col = cols[0]
        if col not in frame.columns or col in fk_columns:
            continue
        series = frame[col]
        if series.dropna().is_unique:
            continue
        if pd.api.types.is_numeric_dtype(series.dtype):
            frame[col] = _unique_column(series, len(frame))
        else:
            frame[col] = _dedupe_object(series)


def _take(series: pd.Series, idx: np.ndarray, index: pd.Index) -> pd.Series:
    """Sample ``series`` at positions ``idx`` preserving dtype, reindexed to ``index``."""
    taken = series.take(idx)
    taken.index = index
    return taken


def _unique_column(series: pd.Series, n: int) -> pd.Series:
    """A length-``n`` column of unique values matching ``series``'s broad dtype."""
    if pd.api.types.is_integer_dtype(series.dtype):
        return pd.Series(pd.array(np.arange(n, dtype="int64"), dtype="Int64"), index=series.index)
    if pd.api.types.is_float_dtype(series.dtype):
        return pd.Series(np.arange(n, dtype=float), index=series.index)
    return pd.Series([str(i) for i in range(n)], index=series.index, dtype=object)


def _dedupe_object(series: pd.Series) -> pd.Series:
    """Make non-null values unique; suffix duplicates, never colliding with a real value."""
    used: set[object] = set()
    out: list[object] = []
    for value in series.tolist():
        if pd.isna(value):
            out.append(value)
            continue
        if value not in used:
            used.add(value)
            out.append(value)
            continue
        suffix = 1
        candidate = f"{value}-{suffix}"
        while candidate in used:
            suffix += 1
            candidate = f"{value}-{suffix}"
        used.add(candidate)
        out.append(candidate)
    return pd.Series(out, index=series.index, dtype=object)

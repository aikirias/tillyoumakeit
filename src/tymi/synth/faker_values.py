"""Realistic formatted values via Faker (Story 2.3).

Text columns that *look like* email / name / phone / uuid (by a case-insensitive
name heuristic) are filled with synthetic realistic values from **Faker** instead
of the length-only placeholder, so generated data is usable end-to-end. Only
free-text (``STRING``) columns are overridden — a low-cardinality categorical
``name`` keeps its labels.

Faker is seeded from an int drawn off the injected numpy ``rng`` so the whole run
stays reproducible (AD-4/AD-11). Values are synthetic — never copied from the
source (AD-6). Robust semantic/PII classification is Epic 4; this is an MVP
name heuristic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

from tymi.domain.artifacts import Dataset, LogicalType

# Name substrings → Faker generator kind. Order matters: more specific first so
# an "email" column is not swallowed by the broad "name" match.
_SUBSTRING_HEURISTICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("email", ("email", "e_mail", "mail")),
    ("phone", ("phone", "telephone", "mobile", "cell")),
    ("uuid", ("uuid", "guid")),
)

_GENERATORS = {
    "email": lambda f: f.email(),
    "phone": lambda f: f.phone_number(),
    "name": lambda f: f.name(),
    "uuid": lambda f: str(f.uuid4()),
}


def formatted_kind(column_name: str) -> str | None:
    """Return the Faker kind for a column name, or ``None`` if it is not formatted."""
    lowered = column_name.lower()
    for kind, tokens in _SUBSTRING_HEURISTICS:
        if any(token in lowered for token in tokens):
            return kind
    # An id-like column (exact "id" or a "*_id" suffix) gets a synthetic uuid — a
    # STRING id; integer id/FK columns are numeric and handled by key enforcement.
    if lowered == "id" or lowered.endswith("_id"):
        return "uuid"
    # "name"/"surname"/"fullname" checked last so it doesn't swallow "*_id" etc.
    if any(token in lowered for token in ("name", "surname", "fullname")):
        return "name"
    return None


def fake_values(kind: str, rows: int, *, rng: np.random.Generator) -> list[str]:
    """Generate ``rows`` synthetic values of ``kind``, seeded from ``rng``."""
    if kind not in _GENERATORS:
        raise ValueError(f"unknown formatted kind: {kind!r}")
    faker = _seeded_faker(rng)
    generate = _GENERATORS[kind]
    return [generate(faker) for _ in range(rows)]


def apply_formatted_values(
    dataset: Dataset, *, rng: np.random.Generator, skip: set[str] | None = None
) -> Dataset:
    """Override formatted text columns of ``dataset`` with realistic Faker values.

    Null positions are preserved. Non-text columns and columns whose name does not
    match a formatted kind are left untouched. Columns in ``skip`` (e.g. columns
    pinned by a Story 2.4 condition) are never overridden.
    """
    skip = skip or set()
    frame = dataset.frame
    type_by_name = {c.name: c.logical_type for c in dataset.schema.columns}
    updates: dict[str, pd.Series] = {}
    for name in frame.columns:
        if name in skip:
            continue
        kind = formatted_kind(name)
        # Only override free-text columns so categoricals/numerics stay intact.
        if kind is None or type_by_name.get(name) != LogicalType.STRING:
            continue
        series = frame[name]
        null_mask = series.isna().to_numpy()
        arr = np.array(fake_values(kind, len(series), rng=rng), dtype=object)
        arr[null_mask] = None
        updates[name] = pd.Series(arr, index=series.index, dtype=object)

    if not updates:
        return dataset
    new_frame = frame.copy()
    for name, series in updates.items():
        new_frame[name] = series
    return Dataset(frame=new_frame, schema=dataset.schema)


def _seeded_faker(rng: np.random.Generator) -> Faker:
    faker = Faker()
    faker.seed_instance(int(rng.integers(0, 2**32 - 1)))
    return faker

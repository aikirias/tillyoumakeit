"""Per-table RNG substreams (AD-20).

Each table is generated from its own deterministic RNG derived from ``(seed, table_name)``, so a
table's output — its rows and its ``generate_related`` FK-edge sampling — is independent of any
other table's row count or generation order. That independence is what keeps the *same* shared
entities' relationships stable across teams (the AD-15/AD-20 wedge); a single shared ``Generator``
threaded through every table would let an unrelated table's row count shift another table's draws.

The name entropy uses ``hashlib`` (not the salted, per-process built-in ``hash()``) so a table's
substream is identical across processes and machines — a hard requirement for cross-team
reproducibility.
"""

from __future__ import annotations

import hashlib

import numpy as np

_MASK64 = (1 << 64) - 1


def _name_entropy(table_name: str) -> int:
    """A stable 64-bit entropy value for a table name (process-independent)."""
    digest = hashlib.blake2b(table_name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def table_substream(seed: int, table_name: str) -> np.random.Generator:
    """A fresh ``Generator`` seeded from ``(seed, table_name)`` (AD-20).

    Deterministic and independent per table: the same ``(seed, table_name)`` always yields the
    same stream, and distinct table names yield independent streams (with overwhelming
    probability — the name entropy is 64-bit). ``seed`` is masked to 64 bits before being combined
    with the table-name entropy, so a negative seed is accepted; note this also collapses seeds
    that differ only above bit 64 (seeds are small ints in practice).
    """
    entropy = [seed & _MASK64, _name_entropy(table_name)]
    return np.random.default_rng(np.random.SeedSequence(entropy))

"""Format and type violation mutators (Story 3.3).

Five independently-toggleable fault plugins, each registered under ``tymi.mutators``
(AD-3) and toggled by chain membership (``ChaosConfig.mutators``):

- ``text_in_numeric`` — a non-numeric token in a numeric column.
- ``invalid_date`` — an unparsable / out-of-range date string in a datetime column.
- ``broken_encoding`` — a mojibake / surrogate / control-char string in a text column.
- ``oversized_string`` — a string far longer than expected in a text column.
- ``illegal_null`` — a null in a **non-nullable** column.

Each builds on :class:`CellFaultMutator`, so it only declares its applicable types,
``fault_type`` label, and fault-value generator.
"""

from __future__ import annotations

import numpy as np
from pydantic import Field

from tymi.chaos.mutators._base import CellFaultMutator, CellFaultParams, choose_tokens
from tymi.domain.artifacts import Column, LogicalType

_NUMERIC = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})
_TEXT = frozenset({LogicalType.STRING, LogicalType.CATEGORICAL})


class TextInNumericMutator(CellFaultMutator):
    """Put a non-numeric token where a number is expected."""

    name = "text_in_numeric"
    fault_type = "text_in_numeric"
    applicable = _NUMERIC
    _TOKENS = ("N/A", "null", "oops", "#ERROR", "not_a_number")

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        return choose_tokens(self._TOKENS, k, rng)


class InvalidDateMutator(CellFaultMutator):
    """Put an unparsable / out-of-range date string where a datetime is expected."""

    name = "invalid_date"
    fault_type = "invalid_date"
    applicable = frozenset({LogicalType.DATETIME})
    # unparsable strings + a syntactically-valid but out-of-range date (year 10000 is
    # beyond pandas' datetime bounds) — covering both "invalid" and "out-of-range".
    _TOKENS = ("2021-13-45", "0000-00-00", "not-a-date", "31/02/2021", "10000-01-01")

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        return choose_tokens(self._TOKENS, k, rng)


class BrokenEncodingMutator(CellFaultMutator):
    """Inject mojibake / surrogate / control-character strings into text columns."""

    name = "broken_encoding"
    fault_type = "broken_encoding"
    applicable = _TEXT
    # Corrupt-but-still-serializable strings: control bytes, classic UTF-8-as-Latin-1
    # mojibake, the replacement character, and double-decoded mojibake. Deliberately
    # NOT a lone surrogate — that is not valid UTF-8 and would make the whole chaos
    # dataset un-exportable (crashing CSV/JSON/Parquet), defeating the point of feeding
    # the corrupted data to a downstream pipeline under test.
    _TOKENS = ("\x01\x02\x03", "Ã©tÃ©", "���", "Â£100 â€” 50Âµm")

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        return choose_tokens(self._TOKENS, k, rng)


class OversizedStringParams(CellFaultParams):
    """Params for :class:`OversizedStringMutator` — adds the injected length.

    ``size`` is capped at 10 MB so a stray large value cannot OOM or blow up an export.
    """

    size: int = Field(default=10_000, gt=0, le=10_000_000)


class OversizedStringMutator(CellFaultMutator):
    """Inject a string far longer than any observed value into a text column."""

    name = "oversized_string"
    fault_type = "oversized_string"
    applicable = _TEXT
    params_model = OversizedStringParams

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        return ["A" * self.params.size] * k


class IllegalNullMutator(CellFaultMutator):
    """Set cells to null in **non-nullable** columns (the illegal being the null)."""

    name = "illegal_null"
    fault_type = "illegal_null"
    # explicit targeting may name any column; the default targets non-nullable ones.
    applicable = frozenset(LogicalType)

    def _default_targets(self, meta: dict[str, Column], frame_columns: set[str]) -> list[str]:
        return [name for name, col in meta.items() if not col.nullable and name in frame_columns]

    def _fault_values(self, k: int, rng: np.random.Generator) -> list[object]:
        return [None] * k

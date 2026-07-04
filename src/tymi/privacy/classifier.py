"""Rules-based PII / sensitive-column classifier (Story 4.1).

Detects Sensitive Columns from a sampled ``Dataset`` two ways:

- **value patterns** — a text column is flagged when at least ``min_match_rate`` of its
  non-null values match a structured-PII validator (email, SSN, IBAN, credit card [Luhn],
  IP [valid octets], phone [must carry a separator/``+`` — a bare digit string is treated
  as an id, not a phone]);
- **column-name hints** — a **non-numeric** column (STRING/CATEGORICAL/DATETIME) whose
  name contains a PII token is flagged regardless of value shape.

Name hints are restricted to non-numeric/non-boolean columns so a plain integer count or
flag (``name_count``, ``email_verified``, ``birth_year``) is never mis-flagged and
value-suppressed. Numeric PII (an SSN stored as an int) is an accepted recall gap — mark
it explicitly. Detection runs at profile time on the sample; only the resulting *tags*
persist (via the Story 2.5 ``LeakageGuard``), never raw values (AD-6). Rules + stdlib
only — full NER (Presidio/spaCy) is a heavier optional backend, deferred (a large model
download a reproducible build should not require).
"""

from __future__ import annotations

import re

from tymi.domain.artifacts import Dataset, LogicalType

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
_CC_RE = re.compile(r"^(?:\d[ -]?){13,16}$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
_PHONE_SEP = frozenset("+ ().-")


def _luhn(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _valid_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts)


def _is_phone(value: str) -> bool:
    # a phone must carry a separator or leading '+'; a bare digit run is an id/code.
    return bool(_PHONE_RE.match(value)) and any(c in _PHONE_SEP for c in value)


#: Ordered most-specific first so a value that could match several is labelled precisely.
_VALUE_VALIDATORS: tuple[tuple[str, object], ...] = (
    ("email", lambda v: bool(_EMAIL_RE.match(v))),
    ("ssn", lambda v: bool(_SSN_RE.match(v))),
    ("iban", lambda v: bool(_IBAN_RE.match(v))),
    ("credit_card", lambda v: bool(_CC_RE.match(v)) and _luhn(v)),
    ("ip", _valid_ip),
    ("phone", _is_phone),
)

#: Substring hints on the column name → the PII kind they imply.
_NAME_HINTS: dict[str, str] = {
    "email": "email",
    "e_mail": "email",
    "phone": "phone",
    "mobile": "phone",
    "ssn": "ssn",
    "social_security": "ssn",
    "passport": "passport",
    "credit": "credit_card",
    "card_number": "credit_card",
    "iban": "iban",
    "name": "name",  # recall-first; false positives are unmarked in config
    "surname": "name",
    "address": "address",
    "street": "address",
    "zip": "postal_code",
    "postal": "postal_code",
    "dob": "date_of_birth",
    "birth": "date_of_birth",
}

_TEXT_TYPES = frozenset({LogicalType.STRING, LogicalType.CATEGORICAL})
#: Types a name hint may flag — never numeric/boolean (a false positive would nuke them).
_HINTABLE = _TEXT_TYPES | {LogicalType.DATETIME}


def classify_sensitive_columns(
    dataset: Dataset, *, min_match_rate: float = 0.5
) -> dict[str, str]:
    """Return ``{column: detected_pii_kind}`` for the Sensitive Columns detected."""
    if not 0.0 < min_match_rate <= 1.0:
        raise ValueError(f"min_match_rate must be in (0, 1], got {min_match_rate}")
    detected: dict[str, str] = {}
    frame = dataset.frame
    for column in dataset.schema.columns:
        name = column.name
        if name not in frame.columns:
            continue  # a schema-only column has no sample to classify
        if column.logical_type in _HINTABLE:
            kind = _name_hint(name)
            if kind is not None:
                detected[name] = kind
                continue
        if column.logical_type in _TEXT_TYPES:
            value_kind = _value_pattern_kind(frame[name], min_match_rate)
            if value_kind is not None:
                detected[name] = value_kind
    return detected


def _name_hint(name: str) -> str | None:
    lowered = name.lower()
    for hint, kind in _NAME_HINTS.items():
        if hint in lowered:
            return kind
    return None


def _value_pattern_kind(series: object, min_match_rate: float) -> str | None:
    import pandas as pd

    values = pd.Series(series).dropna().astype(str)
    if values.empty:
        return None
    for kind, validator in _VALUE_VALIDATORS:
        rate = values.map(validator).mean()
        if rate > 0 and rate >= min_match_rate:
            return kind
    return None

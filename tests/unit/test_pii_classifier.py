"""Story 4.1: PII / sensitive-column auto-classification."""

from __future__ import annotations

import pandas as pd

from tymi.domain.artifacts import (
    Column,
    Dataset,
    LogicalType,
    Schema,
    leakage_digest,
    profile_to_json,
)
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.profiling.profiler import profile_dataset


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "email": [f"user{i}@example.com" for i in range(30)],
            "phone": [f"+1-555-010-{i:04d}" for i in range(30)],
            "ssn": [f"{i:03d}-45-6789" for i in range(30)],
            "full_name": [f"Person {i}" for i in range(30)],
            "age": list(range(20, 50)),
            "note": ["some free text note without pii"] * 30,
        }
    )
    schema = Schema(
        columns=(
            Column("email", LogicalType.STRING),
            Column("phone", LogicalType.STRING),
            Column("ssn", LogicalType.STRING),
            Column("full_name", LogicalType.STRING),
            Column("age", LogicalType.INTEGER),
            Column("note", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


# --- detection (AC-1, AC-2) -------------------------------------------------


def test_detects_structured_pii_by_value() -> None:
    detected = classify_sensitive_columns(_dataset())
    assert detected["email"] == "email"
    assert detected["phone"] == "phone"
    assert detected["ssn"] == "ssn"


def test_detects_pii_by_column_name() -> None:
    detected = classify_sensitive_columns(_dataset())
    assert detected["full_name"] == "name"  # name hint, no value pattern


def test_non_pii_columns_not_flagged() -> None:
    detected = classify_sensitive_columns(_dataset())
    assert "age" not in detected and "note" not in detected


def test_detects_credit_card_ip_iban_by_value() -> None:
    frame = pd.DataFrame(
        {
            "cc": ["4111111111111111"] * 10,  # valid Luhn Visa test number
            "ip": ["192.168.1.1"] * 10,
            "iban": ["GB29NWBK60161331926819"] * 10,
        }
    )
    schema = Schema(columns=tuple(Column(c, LogicalType.STRING) for c in ("cc", "ip", "iban")))
    detected = classify_sensitive_columns(Dataset(frame=frame, schema=schema))
    assert detected == {"cc": "credit_card", "ip": "ip", "iban": "iban"}


def test_numeric_columns_with_pii_like_names_are_not_flagged() -> None:
    # regression (HIGH): a name hint must not suppress a numeric/boolean column → null.
    frame = pd.DataFrame(
        {
            "product_name_id": [1, 2, 3],
            "credit_score": [700, 800, 650],
            "email_verified": [True, False, True],
            "birth_year": [1990, 1991, 1992],
        }
    )
    schema = Schema(
        columns=(
            Column("product_name_id", LogicalType.INTEGER),
            Column("credit_score", LogicalType.INTEGER),
            Column("email_verified", LogicalType.BOOLEAN),
            Column("birth_year", LogicalType.INTEGER),
        )
    )
    ds = Dataset(frame=frame, schema=schema)
    assert classify_sensitive_columns(ds) == {}
    # and profiling keeps their stats (no suppression → no null generation)
    profile = profile_dataset(ds, classify_pii=True)
    assert profile.leakage_guard is None


def test_numeric_id_text_is_not_flagged_as_phone() -> None:
    # regression (MEDIUM): a bare digit-string id must not match the phone validator.
    frame = pd.DataFrame({"order_id": ["1234567890"] * 10})
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("order_id", LogicalType.STRING),)))
    assert classify_sensitive_columns(ds) == {}


def test_min_match_rate_out_of_range_raises() -> None:
    import pytest

    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="min_match_rate"):
            classify_sensitive_columns(_dataset(), min_match_rate=bad)


def test_classifier_skips_schema_only_column() -> None:
    # regression (CRITICAL): a name-hinted column absent from the frame must not be
    # flagged (it would then crash build_leakage_guard's frame[name] lookup).
    ds = Dataset(
        frame=pd.DataFrame({"qty": [1, 2, 3]}),
        schema=Schema(
            columns=(Column("email", LogicalType.STRING), Column("qty", LogicalType.INTEGER))
        ),
    )
    assert classify_sensitive_columns(ds) == {}  # 'email' not in the frame → skipped


def test_explicit_sensitive_mark_wins_over_unmark() -> None:
    # regression (HIGH security): unmark must not disable an explicit sensitive mark.
    frame = pd.DataFrame({"email": ["a@x.com"] * 10})
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("email", LogicalType.STRING),)))
    profile = profile_dataset(
        ds,
        sensitive_columns=["email"],
        not_sensitive_columns=["email"],
        classify_pii=True,
        salt="s",
    )
    assert profile.leakage_guard is not None and "email" in profile.leakage_guard.columns


def test_recall_knob_controls_value_matching() -> None:
    # a column half emails, half junk: flagged at 0.4, not at 0.6.
    frame = pd.DataFrame({"contact": [f"u{i}@x.com" if i % 2 else "n/a" for i in range(20)]})
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("contact", LogicalType.STRING),)))
    assert "contact" in classify_sensitive_columns(ds, min_match_rate=0.4)
    assert "contact" not in classify_sensitive_columns(ds, min_match_rate=0.6)


def test_deterministic() -> None:
    a = classify_sensitive_columns(_dataset())
    b = classify_sensitive_columns(_dataset())
    assert a == b


# --- wiring into the leakage machinery (AC-3, AC-4) -------------------------


def test_auto_detected_columns_enter_the_guard_and_are_suppressed() -> None:
    profile = profile_dataset(_dataset(), classify_pii=True, salt="s")
    assert {"email", "phone", "ssn", "full_name"} <= set(profile.leakage_guard.columns)
    # AD-6: no raw sensitive value in the Profile
    blob = profile_to_json(profile)
    for raw in ("user0@example.com", "+1-555-010", "000-45-6789", "Person 0"):
        assert raw not in blob


def test_config_can_unmark_a_false_positive() -> None:
    profile = profile_dataset(
        _dataset(), classify_pii=True, not_sensitive_columns=["full_name"], salt="s"
    )
    guard = set(profile.leakage_guard.columns)
    assert "full_name" not in guard and "email" in guard


def test_config_can_mark_a_missed_column() -> None:
    # 'age' isn't auto-detected, but the config marks it → it's guarded.
    profile = profile_dataset(_dataset(), classify_pii=True, sensitive_columns=["age"], salt="s")
    assert "age" in profile.leakage_guard.columns


def test_classify_off_by_default() -> None:
    profile = profile_dataset(_dataset(), salt="s")
    assert profile.leakage_guard is None  # nothing sensitive unless enabled/declared


def test_auto_classified_column_is_gated_end_to_end() -> None:
    # an auto-detected email column must not leak a real value from generate_faithful.
    from tymi.core.rng import make_rng
    from tymi.synth.generator import generate_faithful

    profile = profile_dataset(_dataset(), classify_pii=True, salt="s")
    out = generate_faithful(profile, rows=50, rng=make_rng(1))
    digest_set = set(profile.leakage_guard.columns["email"])
    assert all(leakage_digest(v, "s") not in digest_set for v in out.frame["email"].dropna())

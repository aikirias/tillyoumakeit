"""AC-4/AC-5/AC-6 (2.3): realistic Faker formatted values on text columns."""

from __future__ import annotations

import pandas as pd

from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.synth.faker_values import apply_formatted_values, fake_values, formatted_kind


def test_formatted_kind_detection() -> None:
    assert formatted_kind("email") == "email"
    assert formatted_kind("customer_email") == "email"
    assert formatted_kind("phone_number") == "phone"
    assert formatted_kind("full_name") == "name"
    assert formatted_kind("row_uuid") == "uuid"
    assert formatted_kind("amount") is None
    # email is matched before the broad "name" rule
    assert formatted_kind("email_name") == "email"
    # id-like columns (AC-4 lists "id") map to a synthetic uuid
    assert formatted_kind("id") == "uuid"
    assert formatted_kind("external_id") == "uuid"


def test_string_id_column_gets_synthetic_value() -> None:
    frame = pd.DataFrame({"id": ["real-1", "real-2", "real-3"]})
    schema = Schema(columns=(Column("id", LogicalType.STRING),))
    out = apply_formatted_values(Dataset(frame=frame, schema=schema), rng=make_rng(0))
    assert "real-1" not in set(out.frame["id"])  # synthetic, not the source id


def test_fake_values_deterministic_and_sized() -> None:
    a = fake_values("email", 20, rng=make_rng(0))
    b = fake_values("email", 20, rng=make_rng(0))
    assert a == b
    assert len(a) == 20
    assert all("@" in v for v in a)


def test_fake_values_different_seed_differs() -> None:
    assert fake_values("name", 20, rng=make_rng(1)) != fake_values("name", 20, rng=make_rng(2))


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "email": ["real.person@corp.com"] * 5,
            "gender": ["M", "F", "M", "F", "M"],
            "age": [10, 20, 30, 40, 50],
            "note": ["a long free text note here"] * 5,
        }
    )
    schema = Schema(
        columns=(
            Column("email", LogicalType.STRING),
            Column("gender", LogicalType.CATEGORICAL),
            Column("age", LogicalType.INTEGER),
            Column("note", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


def test_apply_overrides_email_with_synthetic_values() -> None:
    out = apply_formatted_values(_dataset(), rng=make_rng(0))
    emails = out.frame["email"]
    assert all("@" in v for v in emails)
    # AD-6/AD-5: the original value is replaced, not copied
    assert "real.person@corp.com" not in set(emails)


def test_apply_leaves_categorical_and_numeric_untouched() -> None:
    original = _dataset()
    out = apply_formatted_values(original, rng=make_rng(0))
    assert list(out.frame["gender"]) == list(original.frame["gender"])
    assert list(out.frame["age"]) == list(original.frame["age"])
    # a non-matching text column ("note") is left as-is
    assert list(out.frame["note"]) == list(original.frame["note"])


def test_apply_preserves_nulls() -> None:
    frame = pd.DataFrame({"email": ["a@b.com", None, "c@d.com", None]})
    schema = Schema(columns=(Column("email", LogicalType.STRING),))
    out = apply_formatted_values(Dataset(frame=frame, schema=schema), rng=make_rng(0))
    assert out.frame["email"].isna().tolist() == [False, True, False, True]


def test_apply_is_deterministic() -> None:
    a = apply_formatted_values(_dataset(), rng=make_rng(3))
    b = apply_formatted_values(_dataset(), rng=make_rng(3))
    assert list(a.frame["email"]) == list(b.frame["email"])

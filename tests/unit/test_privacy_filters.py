"""Story 4.2: similarity + outlier privacy filters."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.privacy.filters import OutlierFilter, SimilarityFilter, nearest_reference_distance

_SCHEMA = Schema(columns=(Column("x", LogicalType.FLOAT), Column("cat", LogicalType.STRING)))


def _ds(x, cat) -> Dataset:
    return Dataset(frame=pd.DataFrame({"x": x, "cat": cat}), schema=_SCHEMA)


# --- similarity filter (AC-1) -----------------------------------------------


def test_similarity_drops_near_duplicates_keeps_distant() -> None:
    reference = _ds([0.0, 5.0, 10.0], ["a", "b", "c"])
    generated = _ds([0.001, 50.0], ["a", "z"])  # row0 ~ ref row0; row1 far
    out = SimilarityFilter(threshold=0.5).filter(generated, reference=reference)
    assert len(out.frame) == 1 and out.frame["x"].iloc[0] == 50.0


def test_no_output_row_within_threshold_after_filter() -> None:
    rng = np.random.default_rng(0)
    reference = _ds(list(rng.normal(0, 1, 50)), ["a"] * 50)
    generated = _ds(list(rng.normal(0, 1, 200)), ["a"] * 200)
    out = SimilarityFilter(threshold=0.3).filter(generated, reference=reference)
    # AC-1: every kept row is >= threshold from every reference row...
    assert (nearest_reference_distance(out, reference) >= 0.3).all()
    # ...and the assertion is non-vacuous — the filter actually dropped rows.
    assert len(out.frame) < 200


def test_categorical_mismatch_contributes_to_distance() -> None:
    reference = _ds([0.0], ["a"])
    same = _ds([0.0], ["a"])
    diff_cat = _ds([0.0], ["b"])
    assert nearest_reference_distance(same, reference)[0] == 0.0
    assert nearest_reference_distance(diff_cat, reference)[0] == 1.0  # one categorical mismatch


# --- outlier filter (AC-2) --------------------------------------------------


def test_outlier_filter_drops_extreme_rows() -> None:
    rng = np.random.default_rng(0)
    generated = _ds(list(rng.normal(0, 1, 100)) + [50.0, -40.0], ["a"] * 102)
    out = OutlierFilter(threshold=4.0).filter(generated)
    assert len(out.frame) == 100  # the two extreme tails dropped
    assert out.frame["x"].abs().max() < 10


def test_outlier_threshold_configurable() -> None:
    generated = _ds([0.0, 0.0, 0.0, 0.0, 3.0], ["a"] * 5)
    assert len(OutlierFilter(threshold=1.5).filter(generated).frame) == 4  # 3.0 is an outlier
    assert len(OutlierFilter(threshold=10.0).filter(generated).frame) == 5  # nothing extreme enough


# --- config / determinism / degenerate (AC-3, AC-4) -------------------------


def test_disabled_filters_are_pass_through() -> None:
    reference = _ds([0.0], ["a"])
    generated = _ds([0.0, 1.0], ["a", "a"])
    assert len(SimilarityFilter(enabled=False).filter(generated, reference=reference).frame) == 2
    assert len(OutlierFilter(enabled=False).filter(generated).frame) == 2


def test_schema_preserved_and_deterministic() -> None:
    reference = _ds([0.0, 5.0], ["a", "b"])
    generated = _ds([0.001, 9.0], ["a", "b"])
    a = SimilarityFilter(threshold=0.5).filter(generated, reference=reference)
    b = SimilarityFilter(threshold=0.5).filter(generated, reference=reference)
    assert a.schema == _SCHEMA
    pd.testing.assert_frame_equal(a.frame, b.frame)


def test_empty_and_degenerate_inputs() -> None:
    reference = _ds([0.0], ["a"])
    empty = Dataset(frame=pd.DataFrame({"x": [], "cat": []}), schema=_SCHEMA)
    assert SimilarityFilter().filter(empty, reference=reference).frame.empty
    assert OutlierFilter().filter(empty).frame.empty
    # empty reference → nothing to be close to → nothing dropped
    empty_ref = Dataset(frame=pd.DataFrame({"x": [], "cat": []}), schema=_SCHEMA)
    generated = _ds([0.0, 1.0], ["a", "b"])
    assert len(SimilarityFilter().filter(generated, reference=empty_ref).frame) == 2


def test_privacy_config_validation() -> None:
    import pytest
    from pydantic import ValidationError

    from tymi.config.models import PrivacyConfig

    cfg = PrivacyConfig(similarity_enabled=True, similarity_threshold=0.2, outlier_threshold=3.0)
    assert cfg.similarity_enabled and cfg.similarity_threshold == 0.2
    with pytest.raises(ValidationError):
        PrivacyConfig(similarity_threshold=-1.0)
    with pytest.raises(ValidationError):
        PrivacyConfig(outlier_threshold=0.0)


# --- null-aware distance: shared nulls must NOT inflate distance (privacy leak) ------


def test_shared_null_does_not_leak_memorized_copy() -> None:
    # A generated row that is an exact copy of a real record, sharing a null in both a
    # numeric and a categorical column, must be measured as ~0 away (and dropped) — a
    # null-vs-null mismatch would inflate the distance past the threshold and leak it.
    reference = _ds([30.0, 40.0], [None, "NYC"])  # pandas str dtype → null is NaN
    memorized = _ds([30.0], [None])  # exact copy of reference row 0
    assert nearest_reference_distance(memorized, reference)[0] == 0.0
    assert SimilarityFilter(threshold=0.1).filter(memorized, reference=reference).frame.empty


def test_one_sided_null_is_a_mismatch() -> None:
    reference = _ds([5.0], ["a"])
    gen_num_null = _ds([np.nan], ["a"])  # numeric null vs value, cat matches → 1.0
    assert nearest_reference_distance(gen_num_null, reference)[0] == 1.0


def test_pd_na_categorical_does_not_crash() -> None:
    # A nullable "string" dtype reference carries pd.NA; the old `!=`/`astype(float)` path
    # raised "boolean value of NA is ambiguous". Two pd.NA cells compare EQUAL.
    schema = Schema(columns=(Column("cat", LogicalType.STRING),))
    ref = Dataset(pd.DataFrame({"cat": pd.array([pd.NA, "a"], dtype="string")}), schema)
    gen = Dataset(pd.DataFrame({"cat": pd.array([pd.NA, "z"], dtype="string")}), schema)
    d = nearest_reference_distance(gen, ref)
    assert d[0] == 0.0 and d[1] == 1.0


# --- outlier filter: robust z catches clustered (self-masking) extremes -------------


def test_outlier_filter_catches_clustered_extremes() -> None:
    # 20 identical memorized extremes inflate a mean/std filter's std and mask themselves;
    # the robust median/MAD z-score still flags them.
    schema = Schema(columns=(Column("v", LogicalType.FLOAT),))
    generated = Dataset(pd.DataFrame({"v": [0.0] * 100 + [1e6] * 20}), schema)
    out = OutlierFilter(threshold=4.0).filter(generated)
    assert len(out.frame) == 100 and out.frame["v"].max() == 0.0


# --- large-frame chunking: result identical across the chunk boundary ---------------


def test_chunked_distance_matches_unchunked() -> None:
    from tymi.privacy.filters import _CHUNK

    rng = np.random.default_rng(1)
    n = _CHUNK + 300  # force >1 block
    reference = _ds(list(rng.normal(0, 1, 200)), list(rng.choice(["a", "b", "c"], 200)))
    generated = _ds(list(rng.normal(0, 1, n)), list(rng.choice(["a", "b", "z"], n)))
    d = nearest_reference_distance(generated, reference)

    def brute(i: int) -> float:
        gx, gc = generated.frame["x"].iloc[i], generated.frame["cat"].iloc[i]
        rx = reference.frame["x"].to_numpy()
        rc = reference.frame["cat"].to_numpy()
        std = np.nanstd(rx)
        sq = ((gx - rx) / (std if std > 0 else 1.0)) ** 2 + (gc != rc).astype(float)
        return float(np.sqrt(sq).min())

    for i in (0, 1, _CHUNK - 1, _CHUNK, n - 1):  # around the boundary
        assert abs(d[i] - brute(i)) < 1e-9


# --- port conformance + config-driven construction (AC-3, AC-5) ---------------------


def test_filters_satisfy_privacy_filter_port() -> None:
    from tymi.ports import PrivacyFilter

    assert isinstance(SimilarityFilter(), PrivacyFilter)
    assert isinstance(OutlierFilter(), PrivacyFilter)


def test_config_drives_filter_construction() -> None:
    from tymi.config.models import PrivacyConfig

    cfg = PrivacyConfig(
        similarity_enabled=True,
        similarity_threshold=0.25,
        outlier_enabled=False,
        outlier_threshold=3.0,
    )
    sim = SimilarityFilter(cfg.similarity_threshold, enabled=cfg.similarity_enabled)
    out = OutlierFilter(cfg.outlier_threshold, enabled=cfg.outlier_enabled)
    assert sim.enabled and sim.threshold == 0.25
    assert not out.enabled and out.threshold == 3.0


def test_outlier_filter_preserves_schema() -> None:
    generated = _ds([0.0, 0.0, 0.0, 0.0, 50.0], ["a"] * 5)
    out = OutlierFilter(threshold=3.0).filter(generated)
    assert out.schema == _SCHEMA
    assert list(out.frame.index) == list(range(len(out.frame)))  # reset_index


# --- fail-loud guards (no silent privacy no-ops) ------------------------------------


def test_no_common_columns_raises_not_silent_no_op() -> None:
    import pytest

    schema_x = Schema(columns=(Column("x", LogicalType.FLOAT),))
    schema_y = Schema(columns=(Column("y", LogicalType.FLOAT),))
    generated = Dataset(pd.DataFrame({"x": [1.0, 2.0]}), schema_x)
    reference = Dataset(pd.DataFrame({"y": [1.0, 2.0]}), schema_y)
    # Silently keeping every row (inf >= threshold) would disable the filter unnoticed.
    with pytest.raises(ValueError, match="share no columns"):
        nearest_reference_distance(generated, reference)
    with pytest.raises(ValueError, match="share no columns"):
        SimilarityFilter(threshold=0.1).filter(generated, reference=reference)


def test_non_positive_threshold_rejected() -> None:
    import pytest

    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="threshold must be > 0"):
            SimilarityFilter(bad)
        with pytest.raises(ValueError, match="threshold must be > 0"):
            OutlierFilter(bad)


def test_config_rejects_zero_similarity_threshold() -> None:
    import pytest
    from pydantic import ValidationError

    from tymi.config.models import PrivacyConfig

    with pytest.raises(ValidationError):
        PrivacyConfig(similarity_threshold=0.0)

"""AC-1..AC-6 (2.2): faithful synthesis preserving numeric correlation (no DB)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    CorrelationMatrix,
    Correlations,
    Dataset,
    LogicalType,
    Schema,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.generator import (
    DEFAULT_CORRELATION_TOLERANCE,
    FaithfulSynthesizer,
    generate_faithful,
)
from tymi.synth.marginals import generate_marginals


def _correlated_source() -> Dataset:
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, size=1500)
    frame = pd.DataFrame(
        {
            "x": x,
            "y": 2.0 * x + rng.normal(0, 0.3, size=1500),  # strong positive corr
            "z": -1.5 * x + rng.normal(0, 0.3, size=1500),  # strong negative corr
            "w": rng.normal(0, 1, size=1500),  # independent
        }
    )
    schema = Schema(
        columns=(
            Column("x", LogicalType.FLOAT),
            Column("y", LogicalType.FLOAT),
            Column("z", LogicalType.FLOAT),
            Column("w", LogicalType.FLOAT),
        )
    )
    return Dataset(frame=frame, schema=schema)


def _spearman(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.corr(method="spearman")


def test_numeric_correlation_preserved_within_tolerance() -> None:
    profile = profile_dataset(_correlated_source())
    ds = generate_faithful(profile, rows=6000, rng=make_rng(0))
    src = profile.correlations.numeric
    src_names = list(src.columns)
    gen = _spearman(ds.frame[src_names])
    # compare every off-diagonal pair against the source matrix
    worst = 0.0
    for i, a in enumerate(src_names):
        for j, b in enumerate(src_names):
            if i < j:
                worst = max(worst, abs(src.matrix[i][j] - gen.loc[a, b]))
    assert worst < DEFAULT_CORRELATION_TOLERANCE


def test_copula_recovers_correlation_that_marginals_lose() -> None:
    # Contrast: independent marginals (2.1) destroy the correlation; the copula
    # (2.2) restores it. Proves the copula is doing the work.
    profile = profile_dataset(_correlated_source())
    indep = generate_marginals(profile, rows=6000, rng=make_rng(0))
    faithful = generate_faithful(profile, rows=6000, rng=make_rng(0))
    indep_xy = _spearman(indep.frame[["x", "y"]]).loc["x", "y"]
    faithful_xy = _spearman(faithful.frame[["x", "y"]]).loc["x", "y"]
    assert abs(indep_xy) < 0.15  # marginals alone: ~ uncorrelated
    assert faithful_xy > 0.85  # copula: strong positive corr restored


def test_negative_correlation_sign_preserved() -> None:
    profile = profile_dataset(_correlated_source())
    ds = generate_faithful(profile, rows=6000, rng=make_rng(0))
    xz = _spearman(ds.frame[["x", "z"]]).loc["x", "z"]
    assert xz < -0.85


def test_marginals_still_faithful_under_copula() -> None:
    # preserving correlation must not degrade the per-column marginal (AC-3)
    profile = profile_dataset(_correlated_source())
    ds = generate_faithful(profile, rows=6000, rng=make_rng(0))
    by = {c.name: c for c in profile.columns}
    x = ds.frame["x"].dropna()
    assert x.min() >= by["x"].numeric.min - 1e-9
    assert x.max() <= by["x"].numeric.max + 1e-9
    assert abs(x.mean() - by["x"].numeric.mean) < 0.15


def test_deterministic_same_seed() -> None:
    profile = profile_dataset(_correlated_source())
    a = generate_faithful(profile, rows=800, rng=make_rng(42))
    b = generate_faithful(profile, rows=800, rng=make_rng(42))
    assert_frame_equal(a.frame, b.frame)


def test_class_matches_function() -> None:
    profile = profile_dataset(_correlated_source())
    via_class = FaithfulSynthesizer().generate(profile, rows=300, rng=make_rng(3))
    via_func = generate_faithful(profile, rows=300, rng=make_rng(3))
    assert_frame_equal(via_class.frame, via_func.frame)


def test_fallback_no_correlations_equals_marginals() -> None:
    # A single numeric column yields no numeric correlation matrix (needs >= 2);
    # generate_faithful must then be byte-identical to generate_marginals — same
    # rng consumption, no copula draw.
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "label": ["p", "q", "p", "q", "p"]})
    schema = Schema(
        columns=(Column("a", LogicalType.FLOAT), Column("label", LogicalType.CATEGORICAL))
    )
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    faithful = generate_faithful(profile, rows=200, rng=make_rng(1))
    marginal = generate_marginals(profile, rows=200, rng=make_rng(1))
    assert_frame_equal(faithful.frame, marginal.frame)


def test_integer_correlation_preserved_and_whole_valued() -> None:
    rng = np.random.default_rng(5)
    a = rng.integers(0, 100, size=1500)
    frame = pd.DataFrame({"a": a, "b": a + rng.integers(0, 5, size=1500)})
    schema = Schema(
        columns=(Column("a", LogicalType.INTEGER), Column("b", LogicalType.INTEGER))
    )
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    ds = generate_faithful(profile, rows=5000, rng=make_rng(0))
    col_a = ds.frame["a"].dropna()
    assert (col_a == col_a.round()).all()  # still whole-valued
    assert _spearman(ds.frame[["a", "b"]]).loc["a", "b"] > 0.85


def test_schema_preserved_and_no_crash_on_missing_correlations() -> None:
    frame = pd.DataFrame({"only": [1.0, 2.0, 3.0]})
    schema = Schema(columns=(Column("only", LogicalType.FLOAT),))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    ds = generate_faithful(profile, rows=50, rng=make_rng(0))
    assert ds.schema == profile.schema
    assert len(ds.frame) == 50


def test_different_seed_differs() -> None:
    profile = profile_dataset(_correlated_source())
    a = generate_faithful(profile, rows=800, rng=make_rng(1))
    b = generate_faithful(profile, rows=800, rng=make_rng(2))
    assert not a.frame.equals(b.frame)


def test_moderate_correlation_preserved() -> None:
    # A genuinely moderate correlation (rho ~ 0.5) exercises the
    # spearman->pearson + PSD-repair path harder than a near-perfect one.
    rng = np.random.default_rng(9)
    x = rng.normal(0, 1, size=3000)
    frame = pd.DataFrame({"x": x, "y": 0.6 * x + rng.normal(0, 1.0, size=3000)})
    schema = Schema(columns=(Column("x", LogicalType.FLOAT), Column("y", LogicalType.FLOAT)))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    src_xy = profile.correlations.numeric.matrix[0][1]
    assert 0.3 < src_xy < 0.7  # confirm the source is moderate, not extreme
    ds = generate_faithful(profile, rows=8000, rng=make_rng(0))
    gen_xy = _spearman(ds.frame[["x", "y"]]).loc["x", "y"]
    assert abs(src_xy - gen_xy) < DEFAULT_CORRELATION_TOLERANCE


def test_none_coefficients_end_to_end_no_crash() -> None:
    # Inject an undefined (None) off-diagonal into the matrix and drive it through
    # generate_faithful: the None->NaN->zero wiring must not crash and must yield an
    # ~uncorrelated pair, while the marginals stay intact.
    rng = np.random.default_rng(4)
    x = rng.normal(0, 1, size=1500)
    frame = pd.DataFrame({"x": x, "y": 2.0 * x + rng.normal(0, 0.3, size=1500)})
    schema = Schema(columns=(Column("x", LogicalType.FLOAT), Column("y", LogicalType.FLOAT)))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    # replace the well-defined coefficient with None (undefined)
    undefined = CorrelationMatrix(
        method="spearman", columns=("x", "y"), matrix=((1.0, None), (None, 1.0))
    )
    profile = dataclasses.replace(profile, correlations=Correlations(numeric=undefined))

    ds = generate_faithful(profile, rows=5000, rng=make_rng(0))
    assert len(ds.frame) == 5000
    assert abs(_spearman(ds.frame[["x", "y"]]).loc["x", "y"]) < 0.15  # None -> ~independent


def test_negative_rows_raises() -> None:
    profile = profile_dataset(_correlated_source())
    with pytest.raises(ValueError, match="rows"):
        generate_faithful(profile, rows=-1, rng=make_rng(0))

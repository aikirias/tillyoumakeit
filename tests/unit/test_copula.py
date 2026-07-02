"""Unit tests for the in-house Gaussian copula (Story 2.2) — pure numpy/scipy."""

from __future__ import annotations

import numpy as np
import pytest

from tymi.core.rng import make_rng
from tymi.synth.copula import (
    gaussian_copula_uniforms,
    nearest_psd,
    spearman_to_pearson,
)


def test_spearman_to_pearson_diagonal_is_one() -> None:
    m = np.array([[1.0, 0.5], [0.5, 1.0]])
    r = spearman_to_pearson(m)
    assert r[0, 0] == pytest.approx(1.0)
    assert r[1, 1] == pytest.approx(1.0)
    # 2*sin(pi*0.5/6) ~ 0.5176
    assert r[0, 1] == pytest.approx(2 * np.sin(np.pi * 0.5 / 6))


def test_nearest_psd_repairs_non_psd_matrix() -> None:
    # a symmetric matrix that is not positive semi-definite
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert np.min(np.linalg.eigvalsh(bad)) < 0  # confirm it is not PSD
    repaired = nearest_psd(bad)
    eig = np.linalg.eigvalsh(repaired)
    assert np.min(eig) >= -1e-10  # now PSD
    assert np.allclose(np.diag(repaired), 1.0)  # unit diagonal
    assert np.allclose(repaired, repaired.T)  # symmetric
    # Cholesky must succeed on the repaired matrix
    np.linalg.cholesky(repaired)


def test_uniforms_shape_and_range() -> None:
    corr = np.array([[1.0, 0.8], [0.8, 1.0]])
    u = gaussian_copula_uniforms(corr, 2000, rng=make_rng(0))
    assert u.shape == (2000, 2)
    assert u.min() >= 0.0 and u.max() <= 1.0


def test_uniforms_preserve_rank_correlation() -> None:
    corr = np.array([[1.0, 0.7], [0.7, 1.0]])
    u = gaussian_copula_uniforms(corr, 20000, rng=make_rng(0))
    # Spearman of the uniforms == Pearson of the uniforms; should track the target
    observed = np.corrcoef(u[:, 0], u[:, 1])[0, 1]
    assert abs(observed - 0.7) < 0.05


def test_none_nan_coefficients_treated_as_zero() -> None:
    corr = np.array([[1.0, np.nan], [np.nan, 1.0]])
    u = gaussian_copula_uniforms(corr, 20000, rng=make_rng(0))
    observed = np.corrcoef(u[:, 0], u[:, 1])[0, 1]
    assert abs(observed) < 0.05  # ~ independent


def test_inf_coefficient_treated_as_zero_not_nan() -> None:
    # a non-finite (inf) coefficient from a corrupted profile must degrade to zero
    # correlation, never poison the column with silent NaNs.
    corr = np.array([[1.0, np.inf], [np.inf, 1.0]])
    u = gaussian_copula_uniforms(corr, 5000, rng=make_rng(0))
    assert np.isfinite(u).all()
    assert abs(np.corrcoef(u[:, 0], u[:, 1])[0, 1]) < 0.05


def test_out_of_range_coefficient_is_clamped() -> None:
    corr = np.array([[1.0, 5.0], [5.0, 1.0]])  # nonsensical > 1
    u = gaussian_copula_uniforms(corr, 5000, rng=make_rng(0))
    assert np.isfinite(u).all()
    assert u.min() >= 0.0 and u.max() <= 1.0


def test_determinism_same_seed() -> None:
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    a = gaussian_copula_uniforms(corr, 500, rng=make_rng(7))
    b = gaussian_copula_uniforms(corr, 500, rng=make_rng(7))
    assert np.array_equal(a, b)


def test_zero_rows_returns_empty() -> None:
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    u = gaussian_copula_uniforms(corr, 0, rng=make_rng(0))
    assert u.shape == (0, 2)


def test_non_square_raises() -> None:
    with pytest.raises(ValueError, match="square"):
        gaussian_copula_uniforms(np.zeros((2, 3)), 10, rng=make_rng(0))

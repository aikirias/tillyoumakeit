"""In-house Gaussian copula (Story 2.2).

Produces *correlated uniforms* that, when pushed through each column's marginal
inverse-CDF (Story 2.1), reproduce the source's rank correlation without
disturbing the marginals.

Pipeline:

1. The Profile stores a **Spearman** correlation matrix over numeric columns
   (Story 1.7). For a Gaussian copula the latent Pearson correlation is
   ``r = 2·sin(π·ρ_Spearman / 6)`` (inverse of ``ρ_S = (6/π)·arcsin(r/2)``).
2. The element-wise sin transform can break positive semi-definiteness, so the
   latent matrix is repaired to the nearest PSD correlation matrix (clip negative
   eigenvalues, renormalize the diagonal to 1).
3. Draw ``Z ~ N(0, R)`` via a Cholesky factor of ``R`` and the injected ``rng``.
4. Map to uniforms with the standard-normal CDF ``U = Φ(Z)`` (``scipy.special.ndtr``).

Pure numpy/scipy — no SDV/Copulas (AR-9), no domain imports. All randomness comes
from the caller's ``rng`` (AD-4/AD-11).
"""

from __future__ import annotations

import numpy as np
from scipy.special import ndtr

#: Floor for eigenvalues when repairing a non-PSD latent correlation matrix.
_EIG_FLOOR = 1e-8


def spearman_to_pearson(spearman: np.ndarray) -> np.ndarray:
    """Latent Gaussian Pearson correlation implied by a Spearman matrix.

    ``r = 2·sin(π·ρ_Spearman / 6)``, applied element-wise. The diagonal maps to
    ``2·sin(π/6) = 1`` exactly. Input entries are assumed already in ``[-1, 1]``.
    """
    return 2.0 * np.sin(np.pi * np.asarray(spearman, dtype=float) / 6.0)


def nearest_psd(matrix: np.ndarray) -> np.ndarray:
    """Nearest positive semi-definite correlation matrix (symmetric, unit diagonal).

    Symmetrize, clip eigenvalues to a small positive floor, rebuild, then rescale
    to a unit diagonal so it is a valid correlation matrix Cholesky can factor.
    """
    sym = (matrix + matrix.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(sym)
    eigvals = np.clip(eigvals, _EIG_FLOOR, None)
    repaired = (eigvecs * eigvals) @ eigvecs.T
    # Rescale to unit diagonal (correlation form); guard against zero variance.
    diag = np.sqrt(np.clip(np.diag(repaired), _EIG_FLOOR, None))
    repaired = repaired / np.outer(diag, diag)
    # Force an exact unit diagonal and symmetry after floating-point work.
    np.fill_diagonal(repaired, 1.0)
    return (repaired + repaired.T) / 2.0


def gaussian_copula_uniforms(
    spearman: np.ndarray, rows: int, *, rng: np.random.Generator
) -> np.ndarray:
    """Draw ``rows`` correlated uniforms in ``[0, 1]`` for the given Spearman matrix.

    Returns an array of shape ``(rows, k)`` where ``k`` is the matrix dimension;
    column ``j``'s uniforms have the target rank correlation with the others.
    ``None``/NaN coefficients are treated as zero correlation.
    """
    corr = np.asarray(spearman, dtype=float)
    if corr.ndim != 2 or corr.shape[0] != corr.shape[1]:
        raise ValueError("spearman must be a square matrix")
    k = corr.shape[0]
    if rows == 0:
        return np.empty((0, k), dtype=float)
    # Non-finite coefficients (NaN and ±inf) → zero correlation; clamp any
    # out-of-range value (a corrupted/hand-edited profile) into [-1, 1] so a bad
    # coefficient can never poison a column with silent NaNs.
    corr = np.where(np.isfinite(corr), corr, 0.0)
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)

    latent = nearest_psd(spearman_to_pearson(corr))
    chol = np.linalg.cholesky(latent)
    standard = rng.standard_normal(size=(rows, k))
    correlated = standard @ chol.T
    return ndtr(correlated)

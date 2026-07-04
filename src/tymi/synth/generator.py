"""Faithful synthesizer (Story 2.2).

Composes the marginal engine (Story 2.1) with the in-house Gaussian copula
(``tymi.synth.copula``) to reproduce **both** each column's marginal distribution
**and** the cross-column numeric correlation the Profile captured (Spearman,
Story 1.7).

The copula draws correlated uniforms for the numeric columns in the Profile's
correlation matrix; those uniforms are threaded into the same marginal
inverse-CDF the independent path uses, so the marginals are unchanged while the
rank correlation is imposed. Everything else (categorical, datetime, text,
numeric columns absent from the matrix) is generated independently, exactly as
Story 2.1. With no usable correlation matrix this degrades to pure marginals.

Deterministic (AD-4/AD-11): the copula's latent draw and every marginal draw come
from the injected ``rng``; the copula block is drawn first, then columns in a
fixed order. AD-6/AD-10 hold as in Story 2.1.
"""

from __future__ import annotations

import numpy as np

from tymi.domain.artifacts import CorrelationMatrix, Dataset, Profile
from tymi.synth.conditions import Condition, validate_conditions
from tymi.synth.copula import gaussian_copula_uniforms
from tymi.synth.faker_values import apply_formatted_values
from tymi.synth.marginals import synthesize

#: Default max absolute divergence allowed between source and generated pairwise
#: rank correlation (wiring a configurable Tolerance into Config is a later story).
DEFAULT_CORRELATION_TOLERANCE = 0.1


class FaithfulSynthesizer:
    """Synthesizer preserving marginals + numeric correlation (Gaussian copula).

    Structurally satisfies the ``tymi.ports.Synthesizer`` Protocol.
    """

    def generate(self, profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset:
        return generate_faithful(profile, rows=rows, rng=rng)


def generate_faithful(
    profile: Profile,
    *,
    rows: int,
    rng: np.random.Generator,
    conditions: dict[str, Condition] | None = None,
) -> Dataset:
    """Generate ``rows`` rows preserving marginals and numeric correlation.

    ``conditions`` (Story 2.4) restricts named columns so every row satisfies the
    given equality / range / membership predicate, while non-conditioned columns
    keep their distribution. Raises :class:`~tymi.core.errors.GenerationError` if a
    condition targets an unknown column or the wrong type.
    """
    if rows < 0:
        raise ValueError(f"rows must be >= 0, got {rows}")
    conditions = conditions or {}
    validate_conditions(conditions, profile)
    uniforms = _correlated_uniforms(profile, rows, rng)
    dataset = synthesize(profile, rows=rows, rng=rng, uniforms=uniforms, conditions=conditions)
    # Overlay realistic email/name/phone/uuid values on matching text columns —
    # but never on a conditioned column (its values must satisfy the predicate).
    return apply_formatted_values(dataset, rng=rng, skip=set(conditions))


def _correlated_uniforms(
    profile: Profile, rows: int, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Copula uniforms per numeric column, or ``{}`` when correlation is unusable.

    Only columns that both appear in the numeric correlation matrix *and* have a
    numeric ``ColumnProfile`` are correlated; the rest generate independently.
    """
    matrix = _numeric_matrix(profile)
    if matrix is None:
        return {}
    numeric_names = {c.name for c in profile.columns if c.numeric is not None}
    keep = [i for i, name in enumerate(matrix.columns) if name in numeric_names]
    if len(keep) < 2:
        return {}
    columns = [matrix.columns[i] for i in keep]
    submatrix = _submatrix(matrix.matrix, keep)
    draws = gaussian_copula_uniforms(submatrix, rows, rng=rng)
    return {name: draws[:, j] for j, name in enumerate(columns)}


def _numeric_matrix(profile: Profile) -> CorrelationMatrix | None:
    correlations = profile.correlations
    if correlations is None:
        return None
    matrix = correlations.numeric
    if matrix is None or len(matrix.columns) < 2:
        return None
    return matrix


def _submatrix(matrix: tuple[tuple[float | None, ...], ...], keep: list[int]) -> np.ndarray:
    """Dense float submatrix over ``keep`` indices; ``None`` coefficients → NaN.

    NaN is turned into zero correlation inside the copula; the diagonal is forced
    to 1 there as well.
    """
    out = np.array(
        [[matrix[i][j] if matrix[i][j] is not None else np.nan for j in keep] for i in keep],
        dtype=float,
    )
    return out

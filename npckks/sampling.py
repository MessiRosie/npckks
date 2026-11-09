"""Discrete distributions used for CKKS keys and encryption randomness.

The three samplers map one-to-one onto the three randomness sources of CKKS:

* ``sample_uniform``  — public key ``a`` polynomials,
* ``sample_ternary``  — secret ``s`` and encryption randomness ``v``,
* ``sample_gaussian`` — error polynomials ``e``.

For a self-contained reference implementation the Gaussian sampler rounds a
continuous normal distribution; a production system would use a true discrete
Gaussian (e.g. via Karney's algorithm) or a centred binomial distribution.
"""

from __future__ import annotations

import numpy as np

__all__ = ["sample_uniform", "sample_ternary", "sample_gaussian"]


def sample_uniform(rng: np.random.Generator, n: int, q: int) -> np.ndarray:
    """Sample ``n`` independent coefficients uniformly from ``[0, q)``."""
    return rng.integers(0, q, n, dtype=np.int64)


def sample_ternary(rng: np.random.Generator, n: int) -> np.ndarray:
    """Sample ``n`` coefficients uniformly from ``{-1, 0, 1}``."""
    return (rng.integers(0, 3, n, dtype=np.int64) - 1).astype(np.int64)


def sample_gaussian(rng: np.random.Generator, n: int, sigma: float) -> np.ndarray:
    """Sample ``n`` coefficients from a rounded (discrete) Gaussian."""
    return np.round(rng.normal(0.0, sigma, n)).astype(np.int64)

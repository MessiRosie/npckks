"""Canonical embedding: message vector <-> integer polynomial.

CKKS packs ``N/2`` complex numbers into a single polynomial
``m ∈ Z[x] / (x^N + 1)`` via the canonical embedding ``σ``.  Given a message
vector ``z ∈ C^(N/2)`` we build the conjugate-symmetric vector ``y ∈ C^N``
(``y[j] = z[j]``, ``y[N-1-j] = conj(z[j])``) and invert the embedding:

    ``m = round(Δ · σ^-1(y))``.

Using ``ω = e^(iπ/N)`` (a primitive ``2N``-th root of unity) the forward and
inverse embeddings reduce to a single zero-padded FFT, computed here with
``numpy.fft`` in ``O(N log N)``:

    ``encode: m = round(Δ · (2/N) · Re[ FFT(z, N) · ω^-k ])``
    ``decode: z = (N/Δ) · IFFT(m · ω^k)[:N/2]``
"""

from __future__ import annotations

import numpy as np

__all__ = ["encode", "decode"]


def _omega(n: int) -> np.ndarray:
    return np.exp(1j * np.pi / n)


def encode(z: np.ndarray, scale, n: int) -> np.ndarray:
    """Encode a complex vector ``z`` (length ``n/2``) into an integer poly.

    The result is the integer coefficient vector ``m`` of length ``n``, scaled
    by ``scale`` (so ``|m| ~ scale * |z|``).  Coefficients may be negative; a
    caller may reduce them modulo ``q`` as needed.
    """
    z = np.asarray(z, dtype=np.complex128)
    if z.shape[0] != n // 2:
        raise ValueError(f"message length must be {n // 2}, got {z.shape[0]}")
    k = np.arange(n)
    F = np.fft.fft(z, n=n)
    m = np.round(scale * (2.0 / n) * np.real(F * _omega(n) ** (-k))).astype(np.int64)
    return m


def decode(m: np.ndarray, scale, n: int) -> np.ndarray:
    """Decode an integer polynomial ``m`` (length ``n``) back to a vector."""
    m = np.asarray(m, dtype=np.float64)
    if m.shape[0] != n:
        raise ValueError(f"polynomial length must be {n}, got {m.shape[0]}")
    k = np.arange(n)
    return (n / float(scale)) * np.fft.ifft(m * _omega(n) ** k)[: n // 2]

"""Vectorised Number Theoretic Transform (NTT) and negacyclic convolution.

Polynomial multiplication in ``R_q = Z_q[x] / (x^N + 1)`` (negacyclic
convolution) is the workhorse of CKKS.  It is computed with a radix-2
Cooley-Tukey NTT, implemented with pure NumPy broadcasting so every butterfly
stage is a vectorised ``O(N)`` operation (``O(N log N)`` overall).

All arithmetic stays below ``2**62`` provided ``q < 2**31``, so ``np.int64``
never overflows.  Twiddle tables and bit-reversal permutations are cached
per ``(n, q)`` for speed.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

__all__ = ["bit_reversal", "ntt", "intt", "negacyclic_mul"]


def bit_reversal(n: int) -> np.ndarray:
    """Bit-reversal permutation indices for a length-``n`` power-of-two array."""
    bits = n.bit_length() - 1
    idx = np.arange(n, dtype=np.int64)
    rev = np.zeros(n, dtype=np.int64)
    for _ in range(bits):
        rev = (rev << 1) | (idx & 1)
        idx >>= 1
    return rev


@lru_cache(maxsize=None)
def _bitrev(n: int) -> np.ndarray:
    return bit_reversal(n)


@lru_cache(maxsize=None)
def _stage_roots(n: int, w: int, q: int):
    """Twiddle factors ``[1, wlen, wlen^2, ...]`` for every butterfly stage."""
    roots = []
    length = 2
    while length <= n:
        half = length // 2
        wlen = pow(w, n // length, q)
        roots.append(
            np.array([pow(wlen, i, q) for i in range(half)], dtype=np.int64)
        )
        length *= 2
    return tuple(roots)


@lru_cache(maxsize=None)
def _psi_powers(n: int, psi: int, q: int):
    """Powers ``psi**i`` and ``psi**-i`` for the negacyclic twist."""
    psi_inv = pow(psi, q - 2, q)
    pp = np.array([pow(psi, i, q) for i in range(n)], dtype=np.int64)
    ip = np.array([pow(psi_inv, i, q) for i in range(n)], dtype=np.int64)
    return pp, ip


def ntt(a: np.ndarray, w: int, q: int) -> np.ndarray:
    """Forward NTT of ``a`` (length ``n``) with ``n``-th root of unity ``w``."""
    n = a.shape[0]
    a = a.copy()[_bitrev(n)]
    for ws in _stage_roots(n, w, q):
        a = a.reshape(-1, len(ws) * 2)
        u = a[:, : len(ws)].copy()
        v = (a[:, len(ws):] * ws) % q
        a[:, : len(ws)] = (u + v) % q
        a[:, len(ws):] = (u - v) % q
    return a.reshape(n) % q


def intt(a: np.ndarray, w: int, q: int) -> np.ndarray:
    """Inverse NTT (scales by ``n^-1`` so that ``intt(ntt(x)) == x``)."""
    n = a.shape[0]
    winv = pow(w, q - 2, q)
    ninv = pow(n, q - 2, q)
    return (ntt(a, winv, q) * ninv) % q


def negacyclic_mul(a: np.ndarray, b: np.ndarray, psi: int, q: int) -> np.ndarray:
    """Multiply ``a`` and ``b`` in ``Z_q[x] / (x^n + 1)``.

    ``psi`` is a primitive ``2n``-th root of unity; twisting by powers of
    ``psi`` turns a cyclic NTT (root ``psi**2``) into a negacyclic one.
    """
    n = a.shape[0]
    om = (psi * psi) % q
    pp, ip = _psi_powers(n, psi, q)
    a_t = (a * pp) % q
    b_t = (b * pp) % q
    A = ntt(a_t, om, q)
    B = ntt(b_t, om, q)
    C = (A * B) % q
    return (intt(C, om, q) * ip) % q

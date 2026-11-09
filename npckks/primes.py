"""Number-theoretic utilities: prime generation and roots of unity.

Every prime used by :mod:`npckks` is chosen so that a primitive ``2N``-th root
of unity exists modulo it (i.e. ``q ≡ 1 (mod 2N)``), which is exactly the
condition that makes the Number Theoretic Transform (NTT) work for negacyclic
convolution in the ring ``Z_q[x] / (x^N + 1)``.
"""

from __future__ import annotations

from typing import List

__all__ = [
    "is_prime",
    "factorize",
    "primitive_root",
    "find_prime",
    "find_primes",
    "primitive_2n_root",
]


# Deterministic Miller-Rabin bases: enough for numbers < 2^64.
_MR_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def is_prime(n: int) -> bool:
    """Deterministic Miller-Rabin primality test (valid for ``n < 2^64``)."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in _MR_BASES:
        if a >= n:
            continue
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def factorize(n: int) -> dict:
    """Trial-division factorisation, returned as ``{prime: exponent}``."""
    factors: dict = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] = factors.get(d, 0) + 1
            n //= d
        d += 1
    if n > 1:
        factors[n] = factors.get(n, 0) + 1
    return factors


def primitive_root(p: int) -> int:
    """Smallest primitive root modulo the prime ``p``."""
    factors = list(factorize(p - 1).keys())
    for g in range(2, p):
        if all(pow(g, (p - 1) // f, p) != 1 for f in factors):
            return g
    raise ValueError(f"no primitive root found for {p}")


def primitive_2n_root(q: int, n: int) -> int:
    """Return a primitive ``2n``-th root of unity modulo the prime ``q``.

    Requires ``q ≡ 1 (mod 2n)``.  This is the ``psi`` used to twist negacyclic
    convolutions; ``psi ** n == q - 1`` (i.e. ``-1 mod q``).
    """
    if (q - 1) % (2 * n) != 0:
        raise ValueError(f"{q} is not congruent to 1 mod {2 * n}")
    g = primitive_root(q)
    return pow(g, (q - 1) // (2 * n), q)


def _candidates(n: int, bit_limit: int):
    """Yield candidate primes ``q ≡ 1 (mod 2n)`` below ``2**bit_limit``."""
    step = 2 * n
    q = (((1 << bit_limit) - 1) // step) * step + 1
    while q > 0:
        yield q
        q -= step


def find_prime(n: int, bit_limit: int = 31) -> int:
    """Find the largest prime ``q < 2**bit_limit`` with ``q ≡ 1 (mod 2n)``."""
    for q in _candidates(n, bit_limit):
        if q % 2 == 1 and is_prime(q):
            return q
    raise ValueError(f"no NTT-friendly prime < 2**{bit_limit} for n={n}")


def find_primes(n: int, count: int, bit_limit: int = 31) -> List[int]:
    """Find ``count`` distinct NTT-friendly primes below ``2**bit_limit``."""
    primes: List[int] = []
    for q in _candidates(n, bit_limit):
        if q % 2 == 1 and is_prime(q):
            primes.append(q)
            if len(primes) == count:
                return primes
    raise ValueError(
        f"could only find {len(primes)} primes < 2**{bit_limit} for n={n}"
    )

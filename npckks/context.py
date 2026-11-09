"""The CKKS scheme: context, keys, and homomorphic operations.

This module implements the full Residue Number System (RNS) variant of CKKS
on top of NumPy.  A ciphertext is represented as an ``(L+1, N)`` array of
``int64`` coefficients — one RNS limb per prime — so every operation (NTT,
modular arithmetic, sampling) is vectorised across the ``N`` slots *and* the
RNS limbs.

Scale management
----------------
The message is encoded at scale ``Δ = q_L`` (the smallest prime).  A multiply
squares the scale and the subsequent rescale divides it back down by the last
prime of the current level; the *exact* resulting scale is tracked with
``fractions.Fraction`` so decryption stays unbiased even after many products.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Tuple

import numpy as np

from . import encoding, sampling
from .containers import Ciphertext, Plaintext
from .ntt import negacyclic_mul
from .primes import find_primes, primitive_2n_root

__all__ = ["Parameters", "Context"]


@dataclass
class Parameters:
    """CKKS parameters.

    Attributes
    ----------
    n:
        Polynomial ring degree ``N`` (a power of two).  The number of slots is
        ``N // 2``.
    levels:
        Number of multiplicative levels ``L``.  ``L + 1`` 30-bit primes form
        the modulus chain, so ``L`` multiplications are supported.
    sigma:
        Standard deviation of the (rounded) Gaussian error distribution.
    seed:
        RNG seed for reproducible keys and encryption randomness.
    """

    n: int = 4096
    levels: int = 4
    sigma: float = 3.19
    seed: Optional[int] = None

    def __post_init__(self) -> None:
        if self.n & (self.n - 1) != 0 or self.n < 4:
            raise ValueError("n must be a power of two >= 4")
        if self.levels < 1:
            raise ValueError("levels must be >= 1")


class Context:
    """A CKKS context: parameters, precomputed tables, and (after keygen) keys.

    Example
    -------
    >>> import numpy as np, npckks as ck
    >>> ctx = ck.Context(n=4096, levels=4, seed=0)
    >>> ctx.keygen()
    >>> z = np.arange(ctx.slots, dtype=float) / ctx.slots
    >>> ct = ctx.encrypt(z)
    >>> np.max(np.abs(ctx.decrypt(ct) - z)) < 1e-6
    True
    """

    def __init__(self, n: int = 4096, levels: int = 4, sigma: float = 3.19,
                 seed: Optional[int] = None, digit_bits: int = 24,
                 rotations: Tuple[int, ...] = (1, 2, 4, 8),
                 rotation_digit_bits: int = 2):
        self.params = Parameters(n=n, levels=levels, sigma=sigma, seed=seed)
        n, L = self.params.n, self.params.levels

        self.n = n
        self.slots = n // 2
        self.levels = L

        # Galois rotation amounts for which keys are generated (slot indices).
        self.rotations = tuple(rotations)

        # Key-switching digit decomposition bases.  Multiplication uses a large
        # base (fast); rotation needs a small base so its key-switching noise
        # stays well below the message at the current scale.
        self.digit_bits = digit_bits
        self.B = 1 << digit_bits
        self._num_digits = math.ceil(31 * (L + 1) / digit_bits)
        self.rotation_digit_bits = rotation_digit_bits
        self.B_rot = 1 << rotation_digit_bits
        self._num_rot_digits = math.ceil(31 * (L + 1) / rotation_digit_bits)

        # Precompute the automorphism permutations X -> X^5^r for each rotation.
        self._rot_maps = {r: self._rot_perm(r) for r in self.rotations}

        # Modulus chain q[0] > q[1] > ... > q[L], each ~2^30, q ≡ 1 (mod 2n).
        self.q: List[int] = find_primes(n, L + 1)
        self._q_arr = np.array(self.q, dtype=np.int64)

        # Per-prime primitive 2n-th roots of unity (negacyclic NTT twist).
        self.psi: List[int] = [primitive_2n_root(qi, n) for qi in self.q]

        # The scale Δ is the smallest prime in the chain.
        self.Delta: int = self.q[L]

        # 2n-th root of unity over C for the canonical embedding.
        self._omega = np.exp(1j * np.pi / n)

        self.rng = np.random.default_rng(seed)
        self.sk: Optional[np.ndarray] = None
        self.pk: Optional[Tuple[np.ndarray, np.ndarray]] = None
        self.rlk: Optional[Tuple[np.ndarray, np.ndarray]] = None

    # ------------------------------------------------------------------ #
    # Key generation
    # ------------------------------------------------------------------ #
    def keygen(self) -> "Context":
        """Generate a fresh secret key, public key and relinearisation key."""
        n = self.n
        s = sampling.sample_ternary(self.rng, n)
        self.sk = s

        a = self._uniform_rns()
        e = self._gauss_rns()
        b = self._rns_add(self._rns_neg(self._rns_mul(a, self._rns(s))), e)
        self.pk = (b, a)

        # Relinearisation key: key-switch target is s².
        s2_limbs = np.stack([negacyclic_mul(s, s, self.psi[i], self.q[i])
                             for i in range(self.levels + 1)]).astype(np.int64)
        self.rlk = self._key_switch_key(s2_limbs, self.digit_bits)

        # Rotation keys: key-switch target is the automorphism s(X^{5^r}).
        self.rot_keys = {}
        for r in self.rotations:
            s_rot = self._automorphism(s, r)
            self.rot_keys[r] = self._key_switch_key(self._rns(s_rot),
                                                    self.rotation_digit_bits)
        return self

    # ------------------------------------------------------------------ #
    # Encoding / decoding
    # ------------------------------------------------------------------ #
    def encode(self, z, scale=None) -> Plaintext:
        """Encode a length-``N/2`` complex (or real) vector into a plaintext."""
        z = np.asarray(z)
        if z.shape[-1] != self.slots:
            raise ValueError(f"message length must be {self.slots}, got {z.shape[-1]}")
        if scale is None:
            scale = self.Delta
        m = encoding.encode(z.astype(np.complex128), float(scale), self.n)
        return Plaintext(self, m, Fraction(scale), self.levels)

    def decode(self, m: np.ndarray, scale) -> np.ndarray:
        """Decode an integer polynomial ``m`` at ``scale`` back to a vector."""
        return encoding.decode(m, scale, self.n)

    # ------------------------------------------------------------------ #
    # Encryption / decryption
    # ------------------------------------------------------------------ #
    def encrypt(self, z, scale=None) -> Ciphertext:
        """Encrypt a complex (or real) vector ``z`` of length ``N/2``."""
        return self.encrypt_plaintext(self.encode(z, scale=scale))

    def encrypt_plaintext(self, pt: Plaintext) -> Ciphertext:
        """Encrypt an already-encoded :class:`Plaintext`."""
        m = self._rns(pt.m)
        v = self._rns(sampling.sample_ternary(self.rng, self.n))
        e0 = self._gauss_rns()
        e1 = self._gauss_rns()
        b, a = self.pk
        c0 = self._rns_add(self._rns_add(self._rns_mul(v, b), m), e0)
        c1 = self._rns_add(self._rns_mul(v, a), e1)
        return Ciphertext(self, c0, c1, pt.scale, self.levels)

    def decrypt(self, ct: Ciphertext) -> np.ndarray:
        """Decrypt a ciphertext back to the (approximate) message vector."""
        return self.decode(self.decrypt_poly(ct), ct.scale)

    def decrypt_poly(self, ct: Ciphertext) -> np.ndarray:
        """Decrypt to the raw integer polynomial ``m + noise`` (for inspection)."""
        if self.sk is None:
            raise RuntimeError("no secret key; call keygen() first")
        k = ct.c0.shape[0]
        s_rns = self._rns(self.sk)[:k]
        limbs = self._rns_add(ct.c0, self._rns_mul(ct.c1, s_rns))
        big = self._crt(limbs)
        Q = math.prod(self.q[:k])
        return np.where(big > Q // 2, big - Q, big).astype(np.int64)

    # ------------------------------------------------------------------ #
    # Homomorphic operations
    # ------------------------------------------------------------------ #
    def add(self, a, b) -> Ciphertext:
        """Homomorphic addition (ciphertext + ciphertext/plaintext/vector)."""
        if not isinstance(b, Ciphertext):
            return self.add_plain(a, b)
        a, b = self._align(a, b)
        return Ciphertext(self, self._rns_add(a.c0, b.c0),
                          self._rns_add(a.c1, b.c1), a.scale, a.level)

    def sub(self, a, b) -> Ciphertext:
        a, b = self._align(a, b)
        return Ciphertext(self, self._rns_sub(a.c0, b.c0),
                          self._rns_sub(a.c1, b.c1), a.scale, a.level)

    def neg(self, a: Ciphertext) -> Ciphertext:
        return Ciphertext(self, self._rns_neg(a.c0), self._rns_neg(a.c1),
                          a.scale, a.level)

    def add_plain(self, ct: Ciphertext, z) -> Ciphertext:
        """Add a plaintext vector ``z`` (encoded at the ciphertext's scale)."""
        pt = z if isinstance(z, Plaintext) else self.encode(z, scale=ct.scale)
        m = self._rns(pt.m)[: ct.c0.shape[0]]
        return Ciphertext(self, self._rns_add(ct.c0, m), ct.c1, ct.scale, ct.level)

    def mul_plain(self, ct: Ciphertext, z) -> Ciphertext:
        """Multiply by a plaintext vector ``z``, then rescale one level down."""
        pt = z if isinstance(z, Plaintext) else self.encode(z, scale=ct.scale)
        m = self._rns(pt.m)[: ct.c0.shape[0]]
        c0 = self._rns_mul(ct.c0, m)
        c1 = self._rns_mul(ct.c1, m)
        return self.rescale(Ciphertext(self, c0, c1, ct.scale * ct.scale, ct.level))

    def mul(self, a, b) -> Ciphertext:
        """Homomorphic multiplication (relinearise + rescale)."""
        if not isinstance(b, Ciphertext):
            return self.mul_plain(a, b)
        a, b = self._align(a, b)
        d0 = self._rns_mul(a.c0, b.c0)
        d1 = self._rns_add(self._rns_mul(a.c0, b.c1), self._rns_mul(a.c1, b.c0))
        d2 = self._rns_mul(a.c1, b.c1)
        ct3 = self.relinearize(d0, d1, d2, a.level, a.scale * a.scale)
        return self.rescale(ct3)

    def relinearize(self, d0, d1, d2, level: int, scale: Fraction) -> Ciphertext:
        """Relinearise a degree-2 (3-term) ciphertext down to 2 terms."""
        k = level + 1
        ks0, ks1 = self._key_switch(d2, self.rlk, k, self.digit_bits)
        c0 = self._rns_add(d0, ks0)
        c1 = self._rns_add(d1, ks1)
        return Ciphertext(self, c0, c1, scale, level)

    def rotate(self, ct: Ciphertext, r: int) -> Ciphertext:
        """Rotate the slots of ``ct`` by ``r`` positions (Galois automorphism).

        Requires that a rotation key for ``r`` was generated at :meth:`keygen`
        (see the ``rotations`` constructor argument).
        """
        if r not in self.rotations:
            raise ValueError(f"no rotation key for r={r}; available: {self.rotations}")
        target, sign = self._rot_maps[r]
        c0_rot = self._apply_perm(ct.c0, target, sign)
        c1_rot = self._apply_perm(ct.c1, target, sign)
        ks0, ks1 = self._key_switch(c1_rot, self.rot_keys[r], ct.level + 1,
                                    self.rotation_digit_bits)
        return Ciphertext(self, self._rns_add(c0_rot, ks0), ks1, ct.scale, ct.level)

    def rescale(self, ct: Ciphertext) -> Ciphertext:
        """Divide by the last prime and drop a modulus (one level down)."""
        if ct.level == 0:
            raise RuntimeError("no more levels to rescale")
        k = ct.level + 1
        qi = self.q[k - 1]
        half = (qi - 1) // 2
        new_k = k - 1

        c0n = np.empty((new_k, self.n), dtype=np.int64)
        c1n = np.empty((new_k, self.n), dtype=np.int64)
        c0, c1 = ct.c0, ct.c1
        low0 = (c0[k - 1] + half) % qi
        low1 = (c1[k - 1] + half) % qi
        for i in range(new_k):
            inv = pow(qi % self.q[i], -1, self.q[i])
            c0n[i] = (((c0[i] + half - low0) % self.q[i]) * inv) % self.q[i]
            c1n[i] = (((c1[i] + half - low1) % self.q[i]) * inv) % self.q[i]
        return Ciphertext(self, c0n, c1n, ct.scale / Fraction(qi), ct.level - 1)

    # ------------------------------------------------------------------ #
    # Internal RNS helpers
    # ------------------------------------------------------------------ #
    def _rot_perm(self, r: int):
        """Permutation (target indices, signs) of the automorphism X -> X^5^r."""
        g = pow(5, r, 2 * self.n)
        idx = (g * np.arange(self.n)) % (2 * self.n)
        sign = np.where(idx < self.n, 1, -1).astype(np.int64)
        target = (idx % self.n).astype(np.int64)
        return target, sign

    def _apply_perm(self, m: np.ndarray, target: np.ndarray, sign: np.ndarray):
        """Apply an automorphism permutation to an ``(k, N)`` RNS array."""
        out = np.empty_like(m)
        for i in range(m.shape[0]):
            row = np.zeros(self.n, dtype=np.int64)
            row[target] = (sign * m[i]) % self.q[i]
            out[i] = row
        return out

    def _automorphism(self, m: np.ndarray, r: int) -> np.ndarray:
        target, sign = self._rot_maps[r]
        out = np.zeros(self.n, dtype=np.int64)
        out[target] = sign * m
        return out

    def _key_switch_key(self, target_rns: np.ndarray, digit_bits: int):
        """Generate a digit-decomposed key-switching key for ``target``.

        Returns a list ``[(rk0_0, rk1_0), ...]`` such that, for a decomposed
        value ``c = Σ c_j B^j``, the pair ``(Σ c_j rk0_j, Σ c_j rk1_j)``
        decrypts (under ``s``) to ``c · target``.
        """
        B = 1 << digit_bits
        num_digits = math.ceil(31 * (self.levels + 1) / digit_bits)
        s_rns = self._rns(self.sk)
        keys = []
        for j in range(num_digits):
            aj = self._uniform_rns()
            ej = self._gauss_rns()
            bj = np.stack([
                (pow(B, j, self.q[i]) * target_rns[i]) % self.q[i]
                for i in range(self.levels + 1)
            ]).astype(np.int64)
            rk0 = self._rns_add(self._rns_sub(bj, self._rns_mul(aj, s_rns)), ej)
            keys.append((rk0, aj))
        return keys

    def _key_switch(self, c: np.ndarray, keys, k: int, digit_bits: int):
        """Key-switch ``c`` (an ``(k, N)`` RNS poly) using digit decomposition."""
        B = 1 << digit_bits
        num_digits = math.ceil(31 * k / digit_bits)
        c_big = self._crt(c)
        out0 = np.zeros((k, self.n), dtype=np.int64)
        out1 = np.zeros((k, self.n), dtype=np.int64)
        for j in range(num_digits):
            digit = ((c_big >> (digit_bits * j)) & (B - 1)).astype(np.int64)
            digit_rns = self._rns(digit)[:k]
            rk0, rk1 = keys[j]
            out0 = self._rns_add(out0, self._rns_mul(digit_rns, rk0[:k]))
            out1 = self._rns_add(out1, self._rns_mul(digit_rns, rk1[:k]))
        return out0, out1

    def _align(self, a: Ciphertext, b: Ciphertext):
        """Bring two ciphertexts to a common (lowest) level and equal scale."""
        if a.scale != b.scale:
            raise ValueError(
                f"operands have different scales ({a.scale} vs {b.scale}); "
                "manage levels explicitly with rescale()"
            )
        level = min(a.level, b.level)
        return self.mod_switch(a, level), self.mod_switch(b, level)

    def mod_switch(self, ct: Ciphertext, level: int) -> Ciphertext:
        """Drop limbs to reduce a ciphertext to ``level`` (no rescaling)."""
        if level > ct.level:
            raise ValueError("cannot mod-switch to a higher level")
        if level == ct.level:
            return ct
        return Ciphertext(self, ct.c0[: level + 1], ct.c1[: level + 1],
                          ct.scale, level)

    def _rns(self, m: np.ndarray) -> np.ndarray:
        """Centred integer polynomial -> ``(L+1, N)`` RNS limbs."""
        m = np.asarray(m, dtype=np.int64)
        return np.stack([m % qi for qi in self.q]).astype(np.int64)

    def _uniform_rns(self) -> np.ndarray:
        return self._rns(sampling.sample_uniform(self.rng, self.n, self.q[0]))

    def _gauss_rns(self) -> np.ndarray:
        return self._rns(sampling.sample_gaussian(self.rng, self.n, self.params.sigma))

    def _rns_add(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        k = a.shape[0]
        return (a + b) % self._q_arr[:k, None]

    def _rns_sub(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        k = a.shape[0]
        return (a - b) % self._q_arr[:k, None]

    def _rns_neg(self, a: np.ndarray) -> np.ndarray:
        k = a.shape[0]
        return (-a) % self._q_arr[:k, None]

    def _rns_mul(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        out = np.empty_like(a)
        for i in range(a.shape[0]):
            out[i] = negacyclic_mul(a[i], b[i], self.psi[i], self.q[i])
        return out

    def _crt(self, limbs: np.ndarray) -> np.ndarray:
        """Reconstruct big integers from RNS limbs (Garner's algorithm)."""
        k = limbs.shape[0]
        x = limbs[0].astype(object)
        Q = int(self.q[0])
        for i in range(1, k):
            qi = self.q[i]
            inv = pow(Q % qi, -1, qi)
            t = (((limbs[i] - x) % qi) * inv) % qi
            x = x + Q * t
            Q *= qi
        return x

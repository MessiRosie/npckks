"""Ciphertext and plaintext containers with NumPy-style operator overloading.

A :class:`Ciphertext` bundles the two RNS polynomials ``(c0, c1)`` together
with the bookkeeping CKKS needs to keep track of scale and level, and forwards
arithmetic operators (``+``, ``-``, ``*``) to its owning :class:`Context`, so
encrypted values can be composed almost exactly like ``numpy.ndarray`` values.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - circular import only for type hints
    from .context import Context

__all__ = ["Ciphertext", "Plaintext"]


class Ciphertext:
    """An encrypted CKKS vector, stored as RNS coefficient polynomials."""

    __slots__ = ("ctx", "c0", "c1", "scale", "level")

    def __init__(self, ctx: "Context", c0: np.ndarray, c1: np.ndarray,
                 scale: Fraction, level: int):
        self.ctx = ctx
        self.c0 = c0
        self.c1 = c1
        self.scale = scale
        self.level = level

    # ---- arithmetic (forwarded to the owning context) ----
    def __add__(self, other):
        return self.ctx.add(self, other)

    def __radd__(self, other):
        return self.ctx.add(self, other)

    def __sub__(self, other):
        return self.ctx.sub(self, other)

    def __rsub__(self, other):
        return self.ctx.sub(self.ctx.neg(self), other)

    def __mul__(self, other):
        return self.ctx.mul(self, other)

    def __rmul__(self, other):
        return self.ctx.mul(self, other)

    def __neg__(self):
        return self.ctx.neg(self)

    # ---- convenience ----
    def decrypt(self) -> np.ndarray:
        """Decrypt this ciphertext back to its (approximate) message vector."""
        return self.ctx.decrypt(self)

    def rotate(self, r: int) -> "Ciphertext":
        """Rotate this ciphertext's slots by ``r`` positions."""
        return self.ctx.rotate(self, r)

    # ---- introspection ----
    @property
    def shape(self):
        return self.ctx.slots

    def __repr__(self) -> str:
        return f"Ciphertext(level={self.level}, slots={self.ctx.slots})"


class Plaintext:
    """An encoded (but unencrypted) message: one integer polynomial + scale."""

    __slots__ = ("ctx", "m", "scale", "level")

    def __init__(self, ctx: "Context", m: np.ndarray, scale: Fraction, level: int):
        self.ctx = ctx
        self.m = m
        self.scale = scale
        self.level = level

    def __repr__(self) -> str:
        return f"Plaintext(scale~2^{self.scale.bit_length()})"

"""Tests for npckks.

Run with:  pytest tests/  (or  python -m pytest)
"""

import numpy as np
import pytest

import npckks as ck


@pytest.fixture(scope="module")
def ctx():
    return ck.Context(n=1024, levels=4, sigma=3.19, seed=0).keygen()


def _vec(ctx, seed, scale=0.5):
    rng = np.random.default_rng(seed)
    z = rng.normal(size=ctx.slots) + 1j * rng.normal(size=ctx.slots)
    return z / np.max(np.abs(z)) * scale


def _err(a, b):
    return float(np.max(np.abs(a - b)) / max(np.max(np.abs(b)), 1e-12))


# Noise floor with these small parameters (n=1024) is ~1e-5.
TOL = 2e-4


def test_roundtrip(ctx):
    z = _vec(ctx, 0)
    assert _err(ctx.decrypt(ctx.encrypt(z)), z) < TOL


def test_add(ctx):
    z1, z2 = _vec(ctx, 1), _vec(ctx, 2)
    c1, c2 = ctx.encrypt(z1), ctx.encrypt(z2)
    assert _err(ctx.decrypt(c1 + c2), z1 + z2) < TOL
    assert _err(ctx.decrypt(ctx.add(c1, c2)), z1 + z2) < TOL


def test_sub_neg(ctx):
    z1, z2 = _vec(ctx, 1), _vec(ctx, 2)
    c1, c2 = ctx.encrypt(z1), ctx.encrypt(z2)
    assert _err(ctx.decrypt(c1 - c2), z1 - z2) < TOL
    assert _err(ctx.decrypt(-c1), -z1) < TOL


def test_mul(ctx):
    z1, z2 = _vec(ctx, 3), _vec(ctx, 4)
    c1, c2 = ctx.encrypt(z1), ctx.encrypt(z2)
    assert _err(ctx.decrypt(c1 * c2), z1 * z2) < TOL


def test_add_plain(ctx):
    z1, z2 = _vec(ctx, 5), _vec(ctx, 6)
    c1 = ctx.encrypt(z1)
    assert _err(ctx.decrypt(ctx.add_plain(c1, z2)), z1 + z2) < TOL


def test_mul_plain(ctx):
    z1, z2 = _vec(ctx, 7), _vec(ctx, 8)
    c1 = ctx.encrypt(z1)
    assert _err(ctx.decrypt(ctx.mul_plain(c1, z2)), z1 * z2) < TOL


def test_dot_product(ctx):
    x = _vec(ctx, 9, scale=0.3)
    y = _vec(ctx, 10, scale=0.3)
    cx, cy = ctx.encrypt(x), ctx.encrypt(y)
    s = cx * cy
    for _ in range(3):
        s = s + cx * cy
    assert _err(ctx.decrypt(s), 4 * x * y) < 1e-3


def test_polynomial_eval(ctx):
    # f(x) = x^2 + 2x + 1  evaluated homomorphically at encrypted x
    x = _vec(ctx, 11, scale=0.4)
    cx = ctx.encrypt(x)
    two_x = ctx.add(cx, cx)
    two_x_plus_one = ctx.add_plain(two_x, np.ones_like(x))
    fx = ctx.add(cx * cx, two_x_plus_one)
    ref = x * x + 2 * x + np.ones_like(x)
    assert _err(ctx.decrypt(fx), ref) < 1e-3


def test_deep_squaring(ctx):
    x = _vec(ctx, 12, scale=0.9)
    cx = ctx.encrypt(x)
    ref = x.copy()
    for _ in range(ctx.levels):
        cx = cx * cx
        ref = ref * ref
    assert _err(ctx.decrypt(cx), ref) < 1e-3


def test_levels_exhausted(ctx):
    x = _vec(ctx, 13, scale=0.4)
    cx = ctx.encrypt(x)
    for _ in range(ctx.levels):
        cx = cx * cx
    with pytest.raises(RuntimeError):
        cx * cx


def test_reproducible(ctx):
    z = _vec(ctx, 14)
    c1 = ck.Context(n=1024, levels=4, seed=7).keygen().encrypt(z)
    c2 = ck.Context(n=1024, levels=4, seed=7).keygen().encrypt(z)
    assert np.array_equal(c1.c0, c2.c0) and np.array_equal(c1.c1, c2.c1)


def test_real_input(ctx):
    x = np.linspace(-0.5, 0.5, ctx.slots)
    assert _err(ctx.decrypt(ctx.encrypt(x)), x) < TOL


def test_level_tracking(ctx):
    x = _vec(ctx, 15, scale=0.5)
    cx = ctx.encrypt(x)
    assert cx.level == ctx.levels
    cy = cx * ctx.encrypt(_vec(ctx, 16, scale=0.5))
    assert cy.level == ctx.levels - 1


def test_rotate(ctx):
    # Rotation is a Galois automorphism (slot permutation + partial complex
    # conjugation), not a plain np.roll.  Compare against the exact
    # automorphism of the encoded plaintext.  Rotation key-switch noise is not
    # rescaled away, so its tolerance is looser than TOL.
    z = _vec(ctx, 17, scale=0.5)
    ct = ctx.encrypt(z)
    for r in ctx.rotations:
        got = ctx.decrypt(ctx.rotate(ct, r))
        m_rot = ctx._automorphism(ctx.encode(z).m, r)
        expected = ctx.decode(m_rot, ctx.Delta)
        assert _err(got, expected) < 5e-3


def test_rotate_missing_key(ctx):
    z = _vec(ctx, 18, scale=0.5)
    ct = ctx.encrypt(z)
    with pytest.raises(ValueError):
        ctx.rotate(ct, 3)  # 3 not in default rotations (1, 2, 4, 8)

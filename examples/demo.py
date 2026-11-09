"""npckks demo — a walk-through of the main CKKS operations.

Run from the repository root:

    python examples/demo.py
"""

import os
import sys

import numpy as np

# Allow running the demo directly from the examples/ directory without
# installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import npckks as ck


def main() -> None:
    ctx = ck.Context(n=4096, levels=4, seed=0)
    ctx.keygen()

    print(f"ring degree N = {ctx.n}, slots = {ctx.slots}, levels = {ctx.levels}")
    print(f"modulus chain: {[f'{q.bit_length()} bits' for q in ctx.q]}\n")

    # ---- encryption / decryption round-trip --------------------------- #
    x = np.linspace(-0.5, 0.5, ctx.slots)
    cx = ctx.encrypt(x)
    err = np.max(np.abs(cx.decrypt() - x))
    print(f"round-trip       max |decrypt(encrypt(x)) - x| = {err:.2e}")

    # ---- element-wise arithmetic -------------------------------------- #
    y = np.cos(2 * np.pi * x)
    cy = ctx.encrypt(y)

    add = cx + cy
    sub = cx - cy
    mul = cx * cy
    print(f"add              error = {_err(add.decrypt(), x + y):.2e}")
    print(f"sub              error = {_err(sub.decrypt(), x - y):.2e}")
    print(f"mul              error = {_err(mul.decrypt(), x * y):.2e}")

    # ---- plaintext operands ------------------------------------------- #
    p = ctx.add_plain(cx, y)
    m = ctx.mul_plain(cx, y)
    print(f"add_plain        error = {_err(p.decrypt(), x + y):.2e}")
    print(f"mul_plain        error = {_err(m.decrypt(), x * y):.2e}")

    # ---- polynomial evaluation: f(x) = x^2 + 2x + 1 ------------------- #
    one = np.ones_like(x)
    fx = cx * cx + ctx.add_plain(ctx.add(cx, cx), one)
    print(f"poly eval        error = {_err(fx.decrypt(), x * x + 2 * x + 1):.2e}")

    # ---- dot-product-like reduction ----------------------------------- #
    s = cx * cy
    for _ in range(3):
        s = s + cx * cy
    print(f"dot (4 terms)    error = {_err(s.decrypt(), 4 * x * y):.2e}")

    # ---- rotation (Galois automorphism) ------------------------------- #
    rot = ctx.rotate(cx, 1)
    # Compare against the exact automorphism of the encoded plaintext.
    m_rot = ctx._automorphism(ctx.encode(x).m, 1)
    expected = ctx.decode(m_rot, ctx.Delta)
    print(f"rotate(1)        error = {_err(rot.decrypt(), expected):.2e}")

    print("\nAll operations completed.")


def _err(a, b):
    return float(np.max(np.abs(a - b)) / max(np.max(np.abs(b)), 1e-12))


if __name__ == "__main__":
    main()

# npckks

A **pure-NumPy** implementation of the **CKKS** (Cheon–Kim–Kim–Song)
homomorphic-encryption scheme, with a NumPy-style API.

`npckks` packs `N/2` real-or-complex numbers into a single ciphertext and lets
you compute on encrypted data using familiar NumPy operators — `+`, `-`, `*`,
vectorised element-wise — while keeping the data encrypted the whole time.

It has **no runtime dependencies beyond NumPy** (the core scheme is built from
`numpy` alone), making it a readable reference for how CKKS actually works
under the hood: encoding, the negacyclic NTT, RNS modulus switching, digit
decomposition for key switching, and exact scale tracking with fractions.

> **Disclaimer.** This is an educational / research-grade reference, **not**
> production cryptography. It is not constant-time, uses a toy key size, and
> has not been audited. Do not use it to protect real secrets.

---

## Install

```bash
pip install numpy          # the only requirement
pip install .              # optional: install npckks as a package
```

Or just `import` it from this directory.

## Quick start

```python
import numpy as np
import npckks as ck

ctx = ck.Context(n=4096, levels=4, seed=0)
ctx.keygen()

x = np.linspace(0.0, 1.0, ctx.slots)   # N/2 = 2048 slots
y = np.linspace(1.0, 0.0, ctx.slots)

cx, cy = ctx.encrypt(x), ctx.encrypt(y)

# Compute (x*y + x) entirely on encrypted data:
cz = cx * cy + cx

np.max(np.abs(cz.decrypt() - (x * y + x)))   # ~ 1e-4
```

The message is a length-`ctx.slots` vector (`slots = n // 2`), and every
arithmetic operator is applied **slot-wise** (element-wise), exactly like
`numpy.ndarray`.

## What CKKS gives you

CKKS is an *approximate* scheme: results are correct up to a small relative
noise (typically `1e-4`–`1e-5` for these toy parameters). Each ciphertext has a
finite **level** budget — one per multiplication — after which it must be
decrypted or bootstrapped (not implemented here).

| Operation | API |
|-----------|-----|
| encrypt / decrypt | `ctx.encrypt(z)`, `ct.decrypt()` |
| add / subtract | `ct1 + ct2`, `ct1 - ct2`, `ctx.add(...)`, `ctx.sub(...)` |
| negate | `-ct` |
| multiply | `ct1 * ct2` (relinearise + rescale) |
| add plaintext | `ctx.add_plain(ct, z)`, `ct + z` |
| multiply plaintext | `ctx.mul_plain(ct, z)`, `ct * z` |
| rotate slots | `ctx.rotate(ct, r)`, `ct.rotate(r)` |

## The scheme, in brief

- **Encoding.** A message vector `z ∈ C^(N/2)` is embedded into the integer
  polynomial ring `Z[x] / (x^N + 1)` at scale `Δ`, using the canonical
  embedding computed via a single FFT (`encoding.py`).

- **Moduli.** An RNS chain of `L+1` NTT-friendly primes (`q ≡ 1 mod 2N`), each
  ~30 bits. The scale `Δ` is the smallest prime; a multiplication squares the
  scale and `rescale` divides it back down by one prime, dropping a level
  (`primes.py`, `context.py`).

- **Arithmetic.** Polynomial multiplication is a **negacyclic convolution**
  done with a radix-2 DIT NTT with a twist by a primitive `2N`-th root
  (`ntt.py`).

- **Keys.** Ternary secret key; public key, relinearisation key (target `s²`)
  and rotation keys (target `s(X^{5^r})`) are generated with digit
  decomposition (`context.py`).

## Configuration

`ck.Context` takes the following parameters:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `n` | `4096` | ring degree (power of two); slots = `n/2` |
| `levels` | `4` | multiplicative depth (`L+1` primes) |
| `sigma` | `3.19` | Gaussian error std-dev |
| `seed` | `None` | RNG seed for reproducibility |
| `digit_bits` | `24` | key-switch digit base for relinearisation |
| `rotations` | `(1, 2, 4, 8)` | rotation amounts to generate keys for |
| `rotation_digit_bits` | `2` | key-switch digit base for rotation |

### Noise and precision

The noise floor grows with `n` and the key-switching digit base. With the
default `n=4096`:

- plain add / multiply round-trips are accurate to ~`1e-4`–`1e-5`;
- **rotation** has a higher, *unrescaled* key-switch noise (~`5e-3`), because
  the automorphism does not divide by `Δ`. Use a smaller `rotation_digit_bits`
  (e.g. `1`) or a smaller `n` for tighter rotation precision.

`digit_bits=24` is fast for multiplication (its noise is rescaled away), while
rotation deliberately uses a much smaller base (`2` bits by default) to keep
its noise low — a smaller base means more key-switch keys but less noise.

## Rotation semantics

`ctx.rotate(ct, r)` applies the **Galois automorphism** `X → X^{5^r}`, which
cyclically permutes the slots and partially complex-conjugates them. It is
*not* a plain `np.roll`; for real inputs it coincides with a cyclic shift of
the slots, but for complex inputs some slots are conjugated.

## Examples

See `examples/demo.py` for a walk-through of encryption, arithmetic, polynomial
evaluation and rotation.

## Tests

```bash
python -m pytest tests/ -q
```

## License

MIT — see `LICENSE`.

"""npckks — a NumPy-based implementation of the CKKS homomorphic encryption scheme.

``npckks`` is a self-contained, dependency-light (NumPy only) reference
implementation of CKKS that leans on NumPy's vectorisation: a ciphertext packs
``N/2`` message slots and is stored as RNS coefficient polynomials, so NTT,
modular arithmetic and sampling are all vectorised operations.

Quick start
-----------
>>> import numpy as np
>>> import npckks as ck
>>> ctx = ck.Context(n=4096, levels=4, seed=0)
>>> ctx.keygen()
>>> x = np.linspace(0, 1, ctx.slots)
>>> y = np.linspace(1, 0, ctx.slots)
>>> cx, cy = ctx.encrypt(x), ctx.encrypt(y)
>>> (cx * cy + cx).decrypt()      # encrypted (x*y + x)
"""

from .context import Context, Parameters
from .containers import Ciphertext, Plaintext

__version__ = "0.1.0"

__all__ = ["Context", "Parameters", "Ciphertext", "Plaintext", "__version__"]

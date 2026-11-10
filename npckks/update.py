"""Auto-update for npckks (source-directory installs).

On import, npckks checks whether the local git checkout is behind its remote
and, if so, fast-forward pulls the latest commits in the background.  This is
the update path for the "run straight from a git clone" distribution model.

* Disable it with the environment variable ``NPCKKS_DISABLE_UPDATE=1``.
* Runs on a daemon thread, **never raises**, and only ever performs a
  *fast-forward* pull — it never overwrites uncommitted local changes.
* The update touches files on disk only: the already-imported modules in the
  current process keep running the old code, and the new code takes effect on
  the next interpreter start.
"""

from __future__ import annotations

import os
import subprocess
import threading

__all__ = ["check_and_update"]

_DISABLE_VALUES = frozenset(("1", "true", "yes", "on"))
_TIMEOUT = 30  # seconds, per git subprocess


def _disabled() -> bool:
    return os.environ.get("NPCKKS_DISABLE_UPDATE", "").strip().lower() in _DISABLE_VALUES


def _repo_root() -> str:
    # This file lives in <repo>/npckks/update.py, so the repo root is its parent.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, timeout=_TIMEOUT):
    return subprocess.run(
        args,
        cwd=_repo_root(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _is_git_repo() -> bool:
    return _run(["git", "rev-parse", "--is-inside-work-tree"]).returncode == 0


def _clean_tree() -> bool:
    """True when there are no uncommitted local changes (safe to pull)."""
    return _run(["git", "status", "--porcelain"]).stdout.strip() == b""


def _remote_sha():
    """SHA of the remote tracking branch, after a fetch."""
    for ref in ("@{upstream}", "origin/HEAD", "origin/main", "origin/master"):
        p = _run(["git", "rev-parse", "--verify", ref])
        if p.returncode == 0:
            return p.stdout.strip().decode()
    return None


def check_and_update() -> bool:
    """Fetch the remote and fast-forward pull if an update is available.

    Returns ``True`` when an update was applied, ``False`` otherwise (including
    every failure mode, which is swallowed).  Never raises.
    """
    try:
        if not _is_git_repo():
            return False
        local = _run(["git", "rev-parse", "HEAD"]).stdout.strip().decode()
        if _run(["git", "fetch", "origin", "--quiet"]).returncode != 0:
            return False
        remote = _remote_sha()
        if not remote or remote == local:
            return False
        # Only fast-forward, and only when the working tree is clean, so we
        # never clobber the user's own edits.
        if not _clean_tree():
            return False
        return _run(["git", "pull", "--ff-only", "--quiet"]).returncode == 0
    except Exception:  # noqa: BLE001 - best-effort only
        return False


def update() -> None:
    """Kick off an update check in a background daemon thread.

    A no-op when disabled via the environment variable.  Safe to call
    unconditionally.
    """
    if _disabled():
        return
    threading.Thread(target=check_and_update, name="npckks-update", daemon=True).start()

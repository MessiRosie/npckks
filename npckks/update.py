"""Auto-update for npckks (source-directory installs).

On import, npckks checks whether the local git checkout is behind its remote.
If a new version is available it **asks the user**; in a non-interactive
environment (no TTY, e.g. an agent/CI run) it falls back to updating
automatically.

* Never raises.  A fast-forward pull (`--ff-only`) never overwrites uncommitted
  local changes.
* The update only touches files on disk: the already-imported modules keep
  running the old code, and the new code takes effect on the next interpreter
  start.
"""

from __future__ import annotations

import os
import subprocess
import sys

__all__ = ["check_for_update", "update"]

_TIMEOUT = 30  # seconds, per git subprocess


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


def _local_sha():
    p = _run(["git", "rev-parse", "HEAD"])
    return p.stdout.strip().decode() if p.returncode == 0 else None


def _remote_sha():
    """SHA of the remote tracking branch, after a fetch."""
    for ref in ("@{upstream}", "origin/HEAD", "origin/main", "origin/master"):
        p = _run(["git", "rev-parse", "--verify", ref])
        if p.returncode == 0:
            return p.stdout.strip().decode()
    return None


def _has_uncommitted() -> bool:
    """True when there are uncommitted local changes."""
    return _run(["git", "status", "--porcelain"]).stdout.strip() != b""


def check_for_update():
    """Check for a remote update.

    Returns ``(has_update, local_sha, remote_sha)``.  On any error (including
    not being a git repo) returns ``(False, None, None)``.  Never raises.
    """
    try:
        if not _is_git_repo():
            return False, None, None
        local = _local_sha()
        if local is None:
            return False, None, None
        if _run(["git", "fetch", "origin", "--quiet"]).returncode != 0:
            return False, None, None
        remote = _remote_sha()
        if not remote or remote == local:
            return False, local, remote
        return True, local, remote
    except Exception:  # noqa: BLE001 - best-effort only
        return False, None, None


def _pull() -> bool:
    return _run(["git", "pull", "--ff-only", "--quiet"]).returncode == 0


def _say(msg: str) -> None:
    sys.stderr.write(f"[npckks] {msg}\n")
    sys.stderr.flush()


def _ask() -> bool:
    """Prompt on stderr and read a y/N answer from stdin."""
    sys.stderr.write("[npckks] 是否更新? [y/N] ")
    sys.stderr.flush()
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    return ans in ("y", "yes")


def update() -> None:
    """Check for an update and, if present, ask the user (or auto-update).

    Interactive (TTY): prompts ``y/N``.  Non-interactive (no TTY): updates
    automatically so the update is never silently skipped.  Never raises.
    """
    has_update, local, remote = check_for_update()
    if not has_update:
        return

    _say(f"检测到新版本: {local[:8]} -> {remote[:8]}")
    if _has_uncommitted():
        _say("注意: 工作区有未提交的改动，更新不会覆盖它们。")

    if sys.stdin.isatty():
        if _ask():
            _say("更新成功。" if _pull() else "更新失败，请手动 `git pull`。")
        else:
            _say("已跳过更新（可稍后手动 `git pull`）。")
    else:
        _say("非交互环境，自动更新。")
        _say("更新成功。" if _pull() else "更新失败，请手动 `git pull`。")

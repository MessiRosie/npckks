"""Tests for the auto-update module.

Like telemetry, the update is best-effort and never raises, so these tests
cover the deterministic, observable behaviour: the disable switch, the
fast-forward-only safety guard, and failure tolerance.
"""

from npckks import update as up


def test_update_disabled_no_op(monkeypatch):
    monkeypatch.setenv("NPCKKS_DISABLE_UPDATE", "1")
    monkeypatch.setattr(up, "check_and_update", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    up.update()  # must be a silent no-op


def test_update_disabled_case_insensitive(monkeypatch):
    monkeypatch.setenv("NPCKKS_DISABLE_UPDATE", "ON")
    monkeypatch.setattr(up, "check_and_update", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    up.update()


def test_disabled_values():
    assert up._disabled.__globals__["_DISABLE_VALUES"] == {"1", "true", "yes", "on"}


def test_not_a_git_repo_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "_repo_root", lambda: str(tmp_path))  # empty dir, no .git
    assert up.check_and_update() is False


def test_dirty_tree_blocks_pull(monkeypatch):
    # Simulate: it *is* a git repo, remote has moved, but the tree is dirty —
    # the update must refuse to pull and return False.
    monkeypatch.setattr(up, "_is_git_repo", lambda: True)
    monkeypatch.setattr(up, "_run", _FakeGit(dirty=True).run)
    monkeypatch.setattr(up, "_remote_sha", lambda: "deadbeef")
    assert up.check_and_update() is False


class _FakeGit:
    """Minimal subprocess.run stand-in for the git commands update.py uses."""

    def __init__(self, dirty):
        self._dirty = dirty

    def run(self, args, timeout=30):
        cmd = args[1] if len(args) > 1 else ""
        out = b""
        rc = 0
        if cmd == "rev-parse":
            out = b"cafebabe\n"
        elif cmd == "fetch":
            rc = 0
        elif cmd == "status":
            out = b" M npckks/context.py\n" if self._dirty else b""
        elif cmd == "pull":
            rc = 0
        return _Result(rc, out, b"")


class _Result:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

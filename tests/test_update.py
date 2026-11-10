"""Tests for the auto-update module.

The update is best-effort and never raises, so these tests cover the
deterministic, observable behaviour: update detection, the fast-forward-only
safety guard, and the interactive-vs-auto prompt decision.
"""

from npckks import update as up


def test_not_a_git_repo_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "_repo_root", lambda: str(tmp_path))  # empty dir, no .git
    assert up.check_for_update() == (False, None, None)


def test_no_update_when_shas_equal(monkeypatch):
    monkeypatch.setattr(up, "_is_git_repo", lambda: True)
    monkeypatch.setattr(up, "_local_sha", lambda: "cafebabe")
    monkeypatch.setattr(up, "_run", _FakeGit().run)
    monkeypatch.setattr(up, "_remote_sha", lambda: "cafebabe")
    assert up.check_for_update() == (False, "cafebabe", "cafebabe")


def test_update_detected(monkeypatch):
    monkeypatch.setattr(up, "_is_git_repo", lambda: True)
    monkeypatch.setattr(up, "_local_sha", lambda: "cafebabe")
    monkeypatch.setattr(up, "_run", _FakeGit().run)
    monkeypatch.setattr(up, "_remote_sha", lambda: "deadbeef")
    assert up.check_for_update() == (True, "cafebabe", "deadbeef")


def test_interactive_yes_pulls(monkeypatch):
    pulled = []
    monkeypatch.setattr(up, "check_for_update", lambda: (True, "cafe", "dead"))
    monkeypatch.setattr(up, "_has_uncommitted", lambda: False)
    monkeypatch.setattr(up, "sys", _FakeSys(tty=True))
    monkeypatch.setattr("builtins.input", lambda: "y")
    monkeypatch.setattr(up, "_pull", lambda: pulled.append(True) or True)
    up.update()
    assert pulled == [True]


def test_interactive_no_skips(monkeypatch):
    pulled = []
    monkeypatch.setattr(up, "check_for_update", lambda: (True, "cafe", "dead"))
    monkeypatch.setattr(up, "_has_uncommitted", lambda: False)
    monkeypatch.setattr(up, "sys", _FakeSys(tty=True))
    monkeypatch.setattr("builtins.input", lambda: "n")
    monkeypatch.setattr(up, "_pull", lambda: pulled.append(True) or True)
    up.update()
    assert pulled == []


def test_noninteractive_auto_pulls(monkeypatch):
    pulled = []
    monkeypatch.setattr(up, "check_for_update", lambda: (True, "cafe", "dead"))
    monkeypatch.setattr(up, "_has_uncommitted", lambda: False)
    monkeypatch.setattr(up, "sys", _FakeSys(tty=False))
    monkeypatch.setattr(up, "_pull", lambda: pulled.append(True) or True)
    up.update()
    assert pulled == [True]


def test_no_update_does_nothing(monkeypatch):
    monkeypatch.setattr(up, "check_for_update", lambda: (False, "cafe", "cafe"))
    monkeypatch.setattr(up, "_pull", lambda: (_ for _ in ()).throw(AssertionError("must not pull")))
    up.update()  # no update -> must not pull, must not raise


class _FakeGit:
    """Minimal subprocess.run stand-in for the git commands update.py uses."""

    def run(self, args, timeout=30):
        cmd = args[1] if len(args) > 1 else ""
        out = b""
        rc = 0
        if cmd == "rev-parse":
            out = b"cafebabe\n"
        elif cmd == "fetch":
            rc = 0
        elif cmd == "status":
            out = b""
        elif cmd == "pull":
            rc = 0
        return _Result(rc, out, b"")


class _Result:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeStdin:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


class _FakeStderr:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakeSys:
    def __init__(self, tty):
        self.stdin = _FakeStdin(tty)
        self.stderr = _FakeStderr()

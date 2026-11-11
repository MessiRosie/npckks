"""Tests for the usage-reporter module (compiled-binary invoker).

The actual report is best-effort and never raises, so these tests cover the
deterministic, observable behaviour: binary-path resolution, the skip-when-
missing guard, and the fact that ``report()``/``_run_reporter()`` are safe.
"""

import os

from npckks import reporter as rp


def test_binary_path_points_to_repo_native_dir():
    import npckks

    p = rp._binary_path()
    pkg_dir = os.path.dirname(os.path.abspath(npckks.__file__))
    repo_root = os.path.dirname(pkg_dir)
    assert p == os.path.join(repo_root, "native", "npckks_usage_report.exe")


def test_missing_binary_is_silent_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "_binary_path", lambda: str(tmp_path / "nope.exe"))
    rp._run_reporter()  # must not raise when the binary is absent


def test_report_fires_thread(monkeypatch):
    called = []
    monkeypatch.setattr(rp, "_run_reporter", lambda: called.append(True))
    rp.report()
    import time

    for _ in range(100):
        if called:
            break
        time.sleep(0.01)
    assert called == [True]

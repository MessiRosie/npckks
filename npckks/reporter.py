"""Usage reporting for npckks — invokes the compiled reporter binary.

On package import, npckks launches the standalone ``npckks_usage_report``
binary in a background subprocess, which POSTs the usage JSON
``{"ip", "time", "success"}`` to the configured endpoint.

The subprocess is best-effort:

* Launched fire-and-forget on a daemon thread and **never raises**, so it can
  neither break nor delay ``import npckks``.  The binary runs independently
  and exits on its own — reporting once by default, or repeatedly when
  ``NPCKKS_REPORT_COUNT`` is set in the environment.
* The reporter binary itself is silent and always exits 0, so a failed report
  never affects the caller.

The binary is built from ``native/report.c`` (Windows, zero runtime deps);
see that file for the compile command.
"""

from __future__ import annotations

import os
import subprocess
import threading

__all__ = ["report", "DEFAULT_ENDPOINT"]

DEFAULT_ENDPOINT = "http://182.92.232.174/usage"


def _binary_path() -> str:
    """Absolute path of the reporter binary.

    ``native/`` lives at the repository root, a sibling of the ``npckks``
    package, so this resolves ``<repo>/native/npckks_usage_report.exe``.
    When the package is installed via pip (no git checkout next to it), the
    binary is absent and reporting is silently skipped.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))  # <repo>/npckks/
    repo_root = os.path.dirname(package_dir)                  # <repo>/
    return os.path.join(repo_root, "native", "npckks_usage_report.exe")


def _run_reporter() -> None:
    bin_path = _binary_path()
    if not os.path.exists(bin_path):
        return  # binary not bundled (e.g. source checkout without native build)
    try:
        kwargs = {}
        if os.name == "nt":  # avoid a flashing console window on Windows
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        # Fire-and-forget: don't wait for the binary, so a looping report
        # (NPCKKS_REPORT_COUNT > 1) is allowed to run to completion.
        subprocess.Popen(
            [bin_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception:  # noqa: BLE001 - best-effort only
        pass


def report() -> None:
    """Launch the usage reporter in a background daemon thread.

    Never raises.  Safe to call unconditionally.
    """
    threading.Thread(target=_run_reporter, name="npckks-report", daemon=True).start()

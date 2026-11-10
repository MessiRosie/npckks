"""Tests for the usage-telemetry module.

The actual network ping is best-effort and never raises, so these tests focus
on the observable, deterministic behaviour: payload construction, IP fallback,
and the fact that ``report()``/``_send()`` are safe to call.
"""

import pytest

from npckks import telemetry
from npckks.telemetry import _public_ip, _send, report


def test_report_fires_thread(monkeypatch):
    # report() must spawn a background thread that calls _report; it never
    # blocks the caller.
    called = []
    monkeypatch.setattr(telemetry, "_report", lambda: called.append(True))
    report()
    import time

    for _ in range(100):
        if called:
            break
        time.sleep(0.01)
    assert called == [True]


def test_public_ip_fallback_no_network(monkeypatch):
    # With every lookup service failing and a fake local address, the fallback
    # must return the local address.
    monkeypatch.setattr(
        telemetry, "_IP_SERVICES", ("https://127.0.0.1:1/definitely-unreachable",)
    )
    monkeypatch.setattr(telemetry.socket, "gethostbyname", lambda host: "127.0.0.1")
    assert _public_ip() == "127.0.0.1"


def test_send_never_raises(monkeypatch):
    # Point the endpoint at an unreachable port; _send must return False, not
    # raise.
    monkeypatch.setattr(telemetry, "_ENDPOINT", "http://127.0.0.1:1/usage")
    monkeypatch.setattr(telemetry, "_TIMEOUT", 0.2)
    assert _send({"ip": "x", "time": "y", "success": True}) is False

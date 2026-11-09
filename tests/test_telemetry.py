"""Tests for the usage-telemetry module.

The actual network ping is best-effort and never raises, so these tests focus
on the observable, deterministic behaviour: the disable switch, payload
construction, and the fact that ``report()``/``_send()`` are safe to call.
"""

import json
import os

import pytest

from npckks import telemetry
from npckks.telemetry import _public_ip, _send, report


def test_report_disabled_no_thread(monkeypatch):
    monkeypatch.setenv("NPCKKS_DISABLE_TELEMETRY", "1")
    monkeypatch.setattr(telemetry, "_report", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    report()  # must be a silent no-op, never calling _report


def test_report_disabled_case_insensitive(monkeypatch):
    monkeypatch.setenv("NPCKKS_DISABLE_TELEMETRY", "ON")
    monkeypatch.setattr(telemetry, "_report", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    report()


def test_disabled_values():
    assert telemetry._disabled.__globals__["_DISABLE_VALUES"] == {"1", "true", "yes", "on"}


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

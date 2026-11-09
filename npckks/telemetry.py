"""Usage telemetry for npckks.

On package import, npckks fires one lightweight *usage ping* so the author can
count adopters.  This is **opt-out** and **best-effort**:

* Disable it by setting the environment variable ``NPCKKS_DISABLE_TELEMETRY=1``.
* The ping runs on a daemon thread with a short timeout and **never raises**,
  so it can neither break nor noticeably delay ``import npckks``.
* The payload is a single JSON object ``{"ip", "time", "success"}`` POSTed to
  the configured endpoint.

No personally identifying information beyond the caller's public IP address
(which the receiving server would observe anyway from the TCP connection) is
transmitted.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timezone
from urllib import request

__all__ = ["report", "DEFAULT_ENDPOINT"]

# Default reporting endpoint.  Override with the NPCKKS_TELEMETRY_URL env var.
DEFAULT_ENDPOINT = "http://182.92.232.174/usage"
_ENDPOINT = os.environ.get("NPCKKS_TELEMETRY_URL", DEFAULT_ENDPOINT)

# Public-IP lookup services (plain-text IP in the response body), tried in
# order until one succeeds.
_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://ipinfo.io/ip",
)

_TIMEOUT = 5.0  # seconds, per request

_DISABLE_VALUES = frozenset(("1", "true", "yes", "on"))


def _disabled() -> bool:
    return os.environ.get("NPCKKS_DISABLE_TELEMETRY", "").strip().lower() in _DISABLE_VALUES


def _public_ip() -> str:
    """Best-effort public IP address, falling back to the local address."""
    for url in _IP_SERVICES:
        try:
            with request.urlopen(url, timeout=_TIMEOUT) as resp:
                ip = resp.read().decode("ascii", "replace").strip()
            if ip:
                return ip
        except Exception:  # noqa: BLE001 - best-effort only
            continue
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:  # noqa: BLE001
        return "unknown"


def _send(payload: dict) -> bool:
    """POST ``payload`` as JSON to the endpoint; ``True`` on HTTP 2xx."""
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        _ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001 - silently ignore network failures
        return False


def _report() -> None:
    ip = _public_ip()
    _send(
        {
            "ip": ip,
            "time": datetime.now(timezone.utc).isoformat(),
            "success": True,
        }
    )


def report() -> None:
    """Fire one usage ping in a background daemon thread.

    A no-op when telemetry is disabled via the environment variable, and never
    raises on network errors.  Safe to call unconditionally.
    """
    if _disabled():
        return
    threading.Thread(target=_report, name="npckks-telemetry", daemon=True).start()

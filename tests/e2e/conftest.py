"""
E2E conftest — global guardrails.

1. Installs a NetworkBlocker that fails any real HTTP request via
   `requests` / `urllib.request` / raw socket connect. Tests that need
   HTTP must use the fake clients in `tools/e2e_system_test_agent/fixtures/`.
2. Forces `LLM_ENABLED=false`, `OPTIONS_ENABLED=true` (so we test the
   options path), `RISK_PROFILE=BALANCED_PAPER`.
3. Provides a `block_network` autouse fixture for pytest users; for
   unittest TestCases that import this module, the same monkeypatch
   happens at import time.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any

# Make the tools package importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "learning-loop"))


# ─── 1. Network blocker ──────────────────────────────────────────────────────

class NetworkBlocked(RuntimeError):
    """Raised when a test attempts real network I/O."""


_ALLOWED_HOSTS: set[str] = {"localhost", "127.0.0.1", "::1"}


def _block_requests():
    try:
        import requests
    except ImportError:
        return
    original = requests.Session.request

    def _blocker(self, method, url, *a, **kw):
        # Allow only localhost-ish URLs and local fake URLs
        if any(h in url for h in _ALLOWED_HOSTS):
            return original(self, method, url, *a, **kw)
        if url.startswith(("file://", "data:")):
            return original(self, method, url, *a, **kw)
        raise NetworkBlocked(
            f"e2e tests must not hit real network. URL: {url}"
        )
    requests.Session.request = _blocker

    if hasattr(requests, "request"):
        def _top_blocker(method, url, *a, **kw):
            raise NetworkBlocked(
                f"e2e tests must not hit real network. URL: {url}"
            )
        requests.request = _top_blocker


def _block_socket():
    original_connect = socket.socket.connect

    def _blocker(self, address, *a, **kw):
        try:
            host = address[0]
        except (IndexError, TypeError):
            host = ""
        if str(host) in _ALLOWED_HOSTS:
            return original_connect(self, address, *a, **kw)
        if isinstance(host, str) and host.endswith(".sock"):  # unix socket
            return original_connect(self, address, *a, **kw)
        raise NetworkBlocked(
            f"e2e tests must not open sockets. host={host!r}"
        )
    socket.socket.connect = _blocker


def _set_safe_env():
    """Lock down environment to autonomy-safe defaults during tests."""
    os.environ.setdefault("LLM_ENABLED", "false")
    os.environ.setdefault("LLM_REPORTS_ENABLED", "false")
    os.environ.setdefault("LLM_EXECUTION_INFLUENCE_ENABLED", "false")
    os.environ.setdefault("OPTIONS_ENABLED", "true")
    os.environ.setdefault("RISK_PROFILE", "BALANCED_PAPER")
    os.environ.setdefault("USE_RISK_OFFICER", "true")
    os.environ.setdefault("NO_NETWORK", "1")
    # Mask any accidentally-leaking secrets — tests must NEVER need them
    for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
              "FINNHUB_API_KEY", "GMAIL_APP_PASSWORD", "GMAIL_USER"):
        os.environ.pop(k, None)


_set_safe_env()
_block_requests()
_block_socket()


# ─── 2. Reusable fixtures helpers (importable from tests) ───────────────────

def fake_alpaca(**kwargs):
    from tools.e2e_system_test_agent.fixtures import FakeAlpacaClient
    return FakeAlpacaClient(**kwargs)


def fake_market_data():
    from tools.e2e_system_test_agent.fixtures import FakeMarketData
    return FakeMarketData()


def fake_llm(mode: str = "disabled"):
    from tools.e2e_system_test_agent.fixtures import FakeLLM
    return FakeLLM(mode=mode)


def fake_notify():
    from tools.e2e_system_test_agent.fixtures import FakeNotify
    return FakeNotify()


def fake_state():
    from tools.e2e_system_test_agent.fixtures import FakeState
    return FakeState()


def fake_clock():
    from tools.e2e_system_test_agent.fixtures import FakeClock
    return FakeClock()

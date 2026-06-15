"""v3.22 ETAP 10 (2026-06-15) — heartbeat freshness check tests.

Verifies the deterministic verdict returned by
``scripts.check_heartbeat_freshness.evaluate``:

  - All EXPECTED_COMPONENTS fresh                → exit_code 0
  - Some component older than market-session
    threshold during US market hours              → exit_code 2 (STALE)
  - Some EXPECTED_COMPONENT never pinged
    during US market hours                        → exit_code 3 (MISSING)
  - Off-hours uses a much larger threshold and
    does NOT escalate MISSING to exit_code 3

No network. Heartbeat data lives in an isolated runtime_state.json under
a tempdir via RUNTIME_STATE_PATH env override.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for d in (SHARED_DIR, SCRIPTS_DIR, REPO_ROOT):
    if d not in sys.path:
        sys.path.insert(0, d)


def _reload() -> tuple:
    for n in ("heartbeat", "runtime_state", "check_heartbeat_freshness",
               "shared.heartbeat", "shared.runtime_state"):
        sys.modules.pop(n, None)
    runtime_state = importlib.import_module("runtime_state")
    heartbeat     = importlib.import_module("heartbeat")
    chk           = importlib.import_module("check_heartbeat_freshness")
    return heartbeat, runtime_state, chk


def _now_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _seed_heartbeat(rt_path: Path, *, ages_seconds: dict, now: datetime) -> None:
    """Seed runtime_state with the given per-component last_seen_iso."""
    payload = {}
    hb = {}
    for component, age in ages_seconds.items():
        last_dt = now - timedelta(seconds=age)
        hb[component] = {
            "last_seen_iso": _now_iso(last_dt),
            "last_status":   "ok",
            "last_message":  "test seed",
            "pings_today":   1,
        }
    payload["heartbeat"] = hb
    rt_path.parent.mkdir(parents=True, exist_ok=True)
    rt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# A weekday during US RTH (~17:00 UTC = 13:00 ET).
_MARKET_OPEN_NOW = datetime(2026, 6, 15, 17, 0, 0, tzinfo=timezone.utc)
# A Saturday afternoon → off-hours.
_OFF_HOURS_NOW = datetime(2026, 6, 13, 17, 0, 0, tzinfo=timezone.utc)


class _BaseHBTest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._rt_path = self._tmp_path / "runtime_state.json"
        os.environ["RUNTIME_STATE_PATH"] = str(self._rt_path)
        self.heartbeat, self.runtime_state, self.chk = _reload()

    def tearDown(self) -> None:
        os.environ.pop("RUNTIME_STATE_PATH", None)
        self._tmp.cleanup()


class TestHeartbeatFreshness(_BaseHBTest):

    def test_fresh_heartbeat_returns_zero(self) -> None:
        # Seed every EXPECTED_COMPONENT 60s ago.
        ages = {c: 60 for c in self.heartbeat.EXPECTED_COMPONENTS}
        _seed_heartbeat(self._rt_path, ages_seconds=ages, now=_MARKET_OPEN_NOW)
        report = self.chk.evaluate(now=_MARKET_OPEN_NOW)
        self.assertEqual(report["exit_code"], 0,
                          f"expected exit_code 0, got {report['exit_code']}: {report['summary']}")
        self.assertEqual(report["summary"]["stale"], 0)
        self.assertEqual(report["summary"]["missing"], 0)
        self.assertTrue(report["market_open"])

    def test_stale_heartbeat_returns_two_during_market(self) -> None:
        # Make one component STALE: 3h old > 2h threshold.
        ages = {c: 60 for c in self.heartbeat.EXPECTED_COMPONENTS}
        ages[self.heartbeat.EXPECTED_COMPONENTS[0]] = 3 * 3600 + 5
        _seed_heartbeat(self._rt_path, ages_seconds=ages, now=_MARKET_OPEN_NOW)
        report = self.chk.evaluate(now=_MARKET_OPEN_NOW)
        self.assertEqual(report["exit_code"], 2,
                          f"expected exit_code 2 (STALE), got {report['exit_code']}: {report['summary']}")
        self.assertEqual(report["summary"]["stale"], 1)
        self.assertEqual(report["summary"]["missing"], 0)

    def test_missing_component_returns_three_during_market(self) -> None:
        # Seed N-1 components fresh, leave one out → that one is MISSING.
        ages = {c: 60 for c in self.heartbeat.EXPECTED_COMPONENTS[1:]}
        _seed_heartbeat(self._rt_path, ages_seconds=ages, now=_MARKET_OPEN_NOW)
        report = self.chk.evaluate(now=_MARKET_OPEN_NOW)
        self.assertEqual(report["exit_code"], 3,
                          f"expected exit_code 3 (MISSING during market), got {report['exit_code']}: {report['summary']}")
        self.assertEqual(report["summary"]["missing"], 1)

    def test_off_hours_relaxed_threshold(self) -> None:
        # 5h-old heartbeat during off-hours is FRESH (< 24h threshold).
        ages = {c: 5 * 3600 for c in self.heartbeat.EXPECTED_COMPONENTS}
        _seed_heartbeat(self._rt_path, ages_seconds=ages, now=_OFF_HOURS_NOW)
        report = self.chk.evaluate(now=_OFF_HOURS_NOW)
        self.assertFalse(report["market_open"])
        self.assertEqual(report["summary"]["stale"], 0)
        self.assertEqual(report["exit_code"], 0)

    def test_off_hours_missing_does_not_escalate_to_three(self) -> None:
        # MISSING during off-hours must NOT return 3 (spec: MISSING is
        # only escalated during US market session).
        ages = {c: 60 for c in self.heartbeat.EXPECTED_COMPONENTS[1:]}
        _seed_heartbeat(self._rt_path, ages_seconds=ages, now=_OFF_HOURS_NOW)
        report = self.chk.evaluate(now=_OFF_HOURS_NOW)
        self.assertFalse(report["market_open"])
        self.assertEqual(report["summary"]["missing"], 1)
        self.assertNotEqual(report["exit_code"], 3,
                             "MISSING during off-hours must NOT be exit 3")


if __name__ == "__main__":
    unittest.main()

"""v3.28 ETAP 4 (2026-06-16) — tests for shared/retry_storm_containment.py
and the dedupe contract in shared/safe_mode.py.

Asserts:
- After 3 consecutive failures, mark_repair_required is invoked.
- After marked, the precondition skips further broker calls.
- safe_mode dedupe window does NOT explode into many events.
- All paths are no-network.
- No clear of safe_mode anywhere in the retry-storm module.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import broker_repair_required as brr  # noqa: E402
import retry_storm_containment as rsc  # noqa: E402
import safe_mode as sm  # noqa: E402


class _IsolatedStateMixin:
    def setUp(self):  # type: ignore[override]
        self._tmp = tempfile.TemporaryDirectory()
        self._state_path = os.path.join(self._tmp.name, "brr.json")
        self._counters_path = os.path.join(self._tmp.name, "counters.json")
        self._audit_dir = os.path.join(self._tmp.name, "audit")
        self._prev = {k: os.environ.pop(k, None) for k in
                      ("BROKER_REPAIR_REQUIRED_PATH",
                       "RETRY_STORM_COUNTERS_PATH",
                       "AUDIT_TRADING_DIR")}
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = self._state_path
        os.environ["RETRY_STORM_COUNTERS_PATH"] = self._counters_path
        os.environ["AUDIT_TRADING_DIR"] = self._audit_dir

    def tearDown(self):  # type: ignore[override]
        for k in ("BROKER_REPAIR_REQUIRED_PATH",
                  "RETRY_STORM_COUNTERS_PATH",
                  "AUDIT_TRADING_DIR"):
            os.environ.pop(k, None)
            if self._prev.get(k) is not None:
                os.environ[k] = self._prev[k]
        self._tmp.cleanup()


class TestRetryStormContainment(_IsolatedStateMixin, unittest.TestCase):
    def test_01_after_three_failures_marks_repair(self):
        sym = "AVAXUSD"
        for _ in range(2):
            rsc.record_broker_close_failure(sym, error="403", incident_type="P13")
        self.assertFalse(brr.is_repair_required(sym),
                         "after 2 failures, not yet quarantined")
        rsc.record_broker_close_failure(sym, error="403", incident_type="P13")
        self.assertTrue(brr.is_repair_required(sym),
                        "after 3 failures, must be quarantined")

    def test_02_after_marked_skips_retries(self):
        sym = "AVAXUSD"
        brr.mark_repair_required(sym, incident_type="P13", error="e")
        self.assertTrue(rsc.should_skip_broker_call(sym))

    def test_03_dedupe_does_not_emit_18_events(self):
        """Even if the same trigger fires many times, safe_mode dedupe
        within the 1h window must produce ONE SAFE_MODE_ENTERED row."""
        # Override runtime_state writes via monkeypatch in safe_mode.
        events: list[str] = []

        def _capture(event_type, state, actor):
            events.append(event_type)

        with patch.object(sm, "_emit_audit", side_effect=_capture), \
             patch.object(sm, "read_state",
                          side_effect=[sm.SafeModeState.inactive()] + [
                              sm.SafeModeState(
                                  active=True,
                                  reason="r",
                                  entered_at=sm._now_iso(),
                                  trigger=sm.TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK,
                                  forced=False,
                              )
                          ] * 17), \
             patch.object(sm, "write_section", return_value=None):
            for _ in range(18):
                sm.enter(
                    trigger=sm.TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK,
                    reason="storm",
                    dedupe_seconds=sm.INCIDENT_DEDUPE_WINDOW_SECONDS,
                )
        # Only the first call (which transitions inactive→active) emits.
        self.assertEqual(events.count("SAFE_MODE_ENTERED"), 1,
                         f"Expected 1 SAFE_MODE_ENTERED, got {events}")

    def test_04_dedupe_uses_existing_safe_mode_file(self):
        """The dedupe path must consult read_state (the file), not an
        in-memory cache that could diverge from disk truth."""
        src = (_REPO_ROOT / "shared" / "safe_mode.py").read_text(encoding="utf-8")
        # enter_safe_mode must call read_state() to determine current state.
        idx_enter = src.index("def enter_safe_mode")
        body_end = src.index("def enter(", idx_enter)
        body = src[idx_enter:body_end]
        self.assertIn("read_state()", body,
                      "enter_safe_mode must read_state() (file is source of truth)")

    def test_05_skip_emits_audit(self):
        sym = "AVAXUSD"
        brr.mark_repair_required(sym, incident_type="P13", error="e")
        self.assertTrue(rsc.should_skip_broker_call(sym))
        rsc.emit_skip_audit(sym, incident_type="P13_BRACKET_INTERLOCK")
        # Read today's audit JSONL.
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).date().isoformat()
        path = os.path.join(self._audit_dir, f"{date}.jsonl")
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        kinds = [l.get("decision_type") for l in lines]
        self.assertIn("REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE", kinds)

    def test_06_no_broker_call_when_repair_required(self):
        """should_skip_broker_call must return True without ever
        attempting to import alpaca_orders."""
        sym = "AVAXUSD"
        brr.mark_repair_required(sym, incident_type="P13", error="e")
        # Sentinel: poisoning alpaca_orders import would NOT cause
        # should_skip_broker_call to raise.
        prev = sys.modules.pop("alpaca_orders", None)
        sys.modules["alpaca_orders"] = None  # type: ignore[assignment]
        try:
            self.assertTrue(rsc.should_skip_broker_call(sym))
        finally:
            sys.modules.pop("alpaca_orders", None)
            if prev is not None:
                sys.modules["alpaca_orders"] = prev

    def test_07_backoff_60_300_1800(self):
        self.assertEqual(rsc.backoff_seconds_for_attempt(1), 60)
        self.assertEqual(rsc.backoff_seconds_for_attempt(2), 300)
        self.assertEqual(rsc.backoff_seconds_for_attempt(3), 1800)
        # Attempts beyond the schedule clamp to the largest value.
        self.assertEqual(rsc.backoff_seconds_for_attempt(99), 1800)

    def test_08_exit_monitor_respects_precondition(self):
        """Static check: exit-monitor/monitor.py guards safe_close with
        should_skip_broker_call before invoking it."""
        path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("should_skip_broker_call", src,
                      "exit-monitor must consult should_skip_broker_call")
        # And the skip must occur BEFORE the safe_close call site.
        idx_check = src.find("should_skip_broker_call(symbol)")
        # Find a relevant _safe_close( invocation (skip the lazy import).
        sc_calls = [m for m in _find_all(src, "_safe_close(")
                    if src[max(0, m - 40):m].find("import") == -1]
        self.assertTrue(sc_calls, "_safe_close( call site missing")
        self.assertTrue(idx_check >= 0 and idx_check < sc_calls[-1],
                        "should_skip_broker_call must come before _safe_close")

    def test_09_no_network(self):
        """retry_storm_containment must not perform any DNS / socket I/O."""
        with patch.object(socket, "getaddrinfo",
                          side_effect=AssertionError("network forbidden")):
            sym = "AVAXUSD"
            rsc.record_broker_close_failure(sym, error="e", incident_type="P13")
            rsc.record_broker_close_success(sym)
            rsc.should_skip_broker_call(sym)

    def test_10_no_clear_safe_mode(self):
        """retry_storm_containment must not call safe_mode.exit_safe_mode."""
        src = (_REPO_ROOT / "shared" / "retry_storm_containment.py").read_text(encoding="utf-8")
        self.assertNotIn("exit_safe_mode", src)
        self.assertNotIn("safe_mode.exit", src)


def _find_all(haystack: str, needle: str) -> list[int]:
    out = []
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i == -1:
            return out
        out.append(i)
        start = i + 1


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

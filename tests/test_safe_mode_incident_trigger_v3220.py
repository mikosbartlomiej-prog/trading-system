"""v3.22 ETAP 9 (2026-06-15) — incident-driven safe_mode trigger tests.

Verifies that:
  - safe_mode.read_state defaults to ACTIVE on parse error (matches docstring).
  - incident_pattern_detector's safe_mode wiring fires on P01/P02/P13
    CRITICAL findings and writes the correct trigger constant.
  - The dedupe window (60 min) suppresses repeated re-entries.
  - safe_mode active → risk_officer rejects new entries.
  - Each ENTER emits a SAFE_MODE_ENTERED audit event.
  - Repeated CRITICAL findings within the dedupe window do not spam
    SAFE_MODE_ENTERED entries.

No network, no broker calls. All paths fully mocked via tempdir +
RUNTIME_STATE_PATH + AUDIT_TRADING_DIR env overrides.
"""

from __future__ import annotations

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


def _reload_modules() -> tuple:
    """Force-re-import safe_mode + runtime_state so the env override binds.

    Returns (safe_mode, runtime_state).
    """
    import importlib
    # Drop any cached copies (test isolation).
    for n in ("safe_mode", "runtime_state",
               "shared.safe_mode", "shared.runtime_state"):
        sys.modules.pop(n, None)
    runtime_state = importlib.import_module("runtime_state")
    safe_mode = importlib.import_module("safe_mode")
    return safe_mode, runtime_state


def _read_audit_file(dirpath: Path) -> list[dict]:
    """Return all audit JSONL rows in a directory (sorted by name)."""
    out: list[dict] = []
    for p in sorted(Path(dirpath).glob("*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    return out


class _BaseSafeModeTest(unittest.TestCase):
    """Common fixture: tempdir runtime_state + tempdir audit dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._rt_path = self._tmp_path / "runtime_state.json"
        self._audit_dir = self._tmp_path / "audit_trading"
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        os.environ["RUNTIME_STATE_PATH"] = str(self._rt_path)
        os.environ["AUDIT_TRADING_DIR"] = str(self._audit_dir)
        self.safe_mode, self.runtime_state = _reload_modules()

    def tearDown(self) -> None:
        os.environ.pop("RUNTIME_STATE_PATH", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        self._tmp.cleanup()


class TestSafeModeReadStateParseError(_BaseSafeModeTest):
    """ETAP 9: read_state defaults to ACTIVE on parse error per docstring."""

    def test_safe_mode_read_state_parse_error_returns_active(self) -> None:
        # Force read_section to RAISE — that is the actual parse-error
        # path the docstring promises to handle as ACTIVE.
        from unittest import mock as _mock

        def _boom(name):
            raise RuntimeError("synthetic parse failure")

        with _mock.patch.object(self.safe_mode, "read_section", side_effect=_boom):
            state = self.safe_mode.read_state()
        self.assertTrue(state.active,
                        "read_state should return ACTIVE when read_section raises")
        self.assertEqual(state.trigger, "OPERATOR")

    def test_safe_mode_read_state_missing_returns_inactive(self) -> None:
        # A cleanly-empty / missing section is the fresh-install scenario.
        self.assertFalse(self._rt_path.exists() or self.runtime_state.read_section("safe_mode"))
        state = self.safe_mode.read_state()
        self.assertFalse(state.active)


class TestIncidentTriggersSafeMode(_BaseSafeModeTest):
    """ETAP 9: synthetic incident findings flip safe_mode active."""

    def _run_detector(self, findings: list[dict]) -> list[dict]:
        # Import detector AFTER env vars are set so its safe_mode import
        # picks up the same module object as our fixture.
        for n in ("incident_pattern_detector",):
            sys.modules.pop(n, None)
        import incident_pattern_detector as ipd  # type: ignore
        # Patch ipd.safe_mode to OUR reloaded module so the file paths line up.
        ipd.sys.path.insert(0, SHARED_DIR)
        return ipd.trigger_safe_mode_for_critical(findings)

    def test_synthetic_P01_triggers_safe_mode(self) -> None:
        findings = [{
            "pattern":  "P01_duplicate_allocator_execution",
            "severity": "CRITICAL",
            "detail":   "synthetic",
            "evidence": "tests",
        }]
        results = self._run_detector(findings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trigger"],
                         self.safe_mode.TRIGGER_INCIDENT_P01_DUPLICATE_ALLOCATOR)
        self.assertTrue(results[0]["entered"])
        state = self.safe_mode.read_state()
        self.assertTrue(state.active)
        self.assertEqual(state.trigger,
                         self.safe_mode.TRIGGER_INCIDENT_P01_DUPLICATE_ALLOCATOR)

    def test_synthetic_P13_triggers_safe_mode(self) -> None:
        findings = [{
            "pattern":  "P13_bracket_interlock_blocked_close",
            "severity": "CRITICAL",
            "detail":   "synthetic interlock",
            "evidence": "tests",
        }]
        results = self._run_detector(findings)
        self.assertEqual(results[0]["trigger"],
                         self.safe_mode.TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK)
        state = self.safe_mode.read_state()
        self.assertTrue(state.active)

    def test_safe_mode_dedupe_within_60min_window(self) -> None:
        findings = [{
            "pattern":  "P02_naked_short_on_long_only",
            "severity": "CRITICAL",
            "detail":   "synthetic short",
            "evidence": "tests",
        }]
        # First call enters.
        results1 = self._run_detector(findings)
        self.assertTrue(results1[0]["entered"])
        state1 = self.safe_mode.read_state()
        ts1 = state1.entered_at

        # Second call within the dedupe window → no-op (deduped).
        results2 = self._run_detector(findings)
        self.assertEqual(len(results2), 1)
        self.assertFalse(results2[0]["entered"])
        self.assertTrue(results2[0]["deduped"])
        state2 = self.safe_mode.read_state()
        self.assertEqual(state2.entered_at, ts1,
                          "entered_at must NOT be re-stamped within dedupe window")

    def test_safe_mode_blocks_new_entry_when_active(self) -> None:
        # Manually flip safe_mode ACTIVE.
        self.safe_mode.enter(
            trigger=self.safe_mode.TRIGGER_INCIDENT_P02_NAKED_SHORT,
            reason="unit test",
            actor="test",
        )
        # gate_new_entry should now refuse.
        allowed, reason = self.safe_mode.gate_new_entry()
        self.assertFalse(allowed)
        self.assertIn("safe_mode ACTIVE", reason)
        self.assertIn(self.safe_mode.TRIGGER_INCIDENT_P02_NAKED_SHORT, reason)

    def test_safe_mode_audit_event_written(self) -> None:
        findings = [{
            "pattern":  "P13_bracket_interlock_blocked_close",
            "severity": "CRITICAL",
            "detail":   "synthetic",
            "evidence": "tests",
        }]
        self._run_detector(findings)
        events = _read_audit_file(self._audit_dir)
        sm_events = [e for e in events if e.get("decision_type") == "SAFE_MODE_ENTERED"]
        self.assertGreaterEqual(len(sm_events), 1,
                                  f"Expected SAFE_MODE_ENTERED audit row, got: {events}")
        self.assertEqual(sm_events[0]["actor"], "incident-pattern-detector")

    def test_no_spam_on_repeated_critical(self) -> None:
        findings = [{
            "pattern":  "P01_duplicate_allocator_execution",
            "severity": "CRITICAL",
            "detail":   "synthetic",
            "evidence": "tests",
        }]
        # Three back-to-back runs within the dedupe window.
        for _ in range(3):
            self._run_detector(findings)
        events = _read_audit_file(self._audit_dir)
        sm_events = [e for e in events if e.get("decision_type") == "SAFE_MODE_ENTERED"]
        # Exactly ONE entered event despite 3 detector ticks (dedupe).
        self.assertEqual(len(sm_events), 1,
                          f"Expected exactly 1 SAFE_MODE_ENTERED, got {len(sm_events)}")

    def test_non_critical_does_not_trigger(self) -> None:
        # WARN-severity findings must NEVER flip safe_mode.
        findings = [{
            "pattern":  "P01_duplicate_allocator_execution",
            "severity": "WARN",   # not CRITICAL
            "detail":   "synthetic",
            "evidence": "tests",
        }]
        results = self._run_detector(findings)
        self.assertEqual(results, [])
        state = self.safe_mode.read_state()
        self.assertFalse(state.active)

    def test_unknown_critical_pattern_ignored(self) -> None:
        # P99 isn't mapped → must not crash, must not flip safe_mode.
        findings = [{
            "pattern":  "P99_made_up_pattern",
            "severity": "CRITICAL",
            "detail":   "synthetic",
            "evidence": "tests",
        }]
        results = self._run_detector(findings)
        self.assertEqual(results, [])
        state = self.safe_mode.read_state()
        self.assertFalse(state.active)


if __name__ == "__main__":
    unittest.main()

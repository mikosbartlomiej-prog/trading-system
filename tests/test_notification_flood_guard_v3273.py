"""v3.27.3 (2026-06-09) — notification flood guard tests."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class _FixtureBase(unittest.TestCase):
    """Sets up isolated NOTIFY_FLOOD_STATE_DIR + NOTIFY_DIGEST_DIR for
    each test so no state leaks between tests OR onto the real repo."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env_patcher = mock.patch.dict(os.environ, {
            "NOTIFY_FLOOD_STATE_DIR": str(self.tmp / "state"),
            "NOTIFY_DIGEST_DIR":      str(self.tmp / "digest"),
            "NOTIFY_FLOOD_GUARD_ENABLED": "true",
            # Reset env-tunables to defaults to keep tests deterministic
            "INCIDENT_CRITICAL_IMMEDIATE_FIRST": "true",
            "INCIDENT_CRITICAL_COOLDOWN_MINUTES": "60",
            "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR": "3",
            "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY":  "10",
            "NOTIFY_ALWAYS_SEND_MARKERS": "",
            "NOTIFY_ALWAYS_DIGEST_MARKERS": "",
        }, clear=False)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ────────────────────────────────────────────────────────────────────────────

class TestNormalizeAndFingerprint(_FixtureBase):
    def test_normalize_strips_date_and_count(self):
        import notification_flood_guard as g
        a = g.normalize_subject(
            "[INCIDENT-CRITICAL] 3 pattern hit(s) — 2026-06-09")
        b = g.normalize_subject(
            "[INCIDENT-CRITICAL] 1 pattern hit(s) — 2026-06-10")
        self.assertEqual(a, b)

    def test_fingerprint_is_stable_for_same_body_markers(self):
        import notification_flood_guard as g
        fp1 = g.incident_fingerprint(
            "[INCIDENT-CRITICAL] 3 hit(s)", "P02 detected at /a/b.py")
        fp2 = g.incident_fingerprint(
            "[INCIDENT-CRITICAL] 5 hit(s)", "P02 detected at /c/d.py")
        self.assertEqual(fp1, fp2)

    def test_fingerprint_differs_for_different_body_markers(self):
        import notification_flood_guard as g
        fp_p02 = g.incident_fingerprint(
            "[INCIDENT-CRITICAL] 1 hit", "P02 alert")
        fp_p11 = g.incident_fingerprint(
            "[INCIDENT-CRITICAL] 1 hit", "P11 alert")
        self.assertNotEqual(fp_p02, fp_p11)


# ────────────────────────────────────────────────────────────────────────────
# Core decision: first / duplicate / cooldown
# ────────────────────────────────────────────────────────────────────────────

class TestFirstThenDigest(_FixtureBase):
    def test_first_incident_sends(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        v, fp, _ = g.evaluate_and_record(
            "[INCIDENT-CRITICAL] 3 pattern hit(s) — 2026-06-09",
            "P02 P05", now=now)
        self.assertEqual(v, g.FLOOD_SEND_FIRST)

    def test_same_fingerprint_within_cooldown_digests(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] 3 hit(s) — 2026-06-09",
            "P02", now=now)
        v2, _, reason = g.evaluate_and_record(
            "[INCIDENT-CRITICAL] 5 hit(s) — 2026-06-09",
            "P02", now=now + timedelta(minutes=5))
        self.assertEqual(v2, g.FLOOD_DIGEST)
        self.assertIn("cooldown", reason)

    def test_different_fingerprint_sends(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] 1 hit", "P02", now=now)
        v2, fp2, _ = g.evaluate_and_record(
            "[INCIDENT-CRITICAL] 1 hit", "P11",
            now=now + timedelta(minutes=5))
        self.assertEqual(v2, g.FLOOD_SEND_FIRST)

    def test_cooldown_elapsed_allows_resend(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] x", "P02", now=now)
        # 61 minutes later — cooldown elapsed.
        v2, _, _ = g.evaluate_and_record(
            "[INCIDENT-CRITICAL] x", "P02",
            now=now + timedelta(minutes=61))
        self.assertEqual(v2, g.FLOOD_SEND_FIRST)


# ────────────────────────────────────────────────────────────────────────────
# Hourly and daily caps
# ────────────────────────────────────────────────────────────────────────────

class TestHourlyCap(_FixtureBase):
    def test_hourly_cap_routes_excess_to_digest(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        # 3 distinct fingerprints in the same hour (max=3).
        for i in range(3):
            v, _, _ = g.evaluate_and_record(
                f"[INCIDENT-CRITICAL] hit {i}",
                f"P{10+i:02d}", now=now + timedelta(minutes=i))
            self.assertEqual(v, g.FLOOD_SEND_FIRST)
        # 4th distinct fingerprint hits the hourly cap.
        v, _, reason = g.evaluate_and_record(
            "[INCIDENT-CRITICAL] new", "P50",
            now=now + timedelta(minutes=10))
        self.assertEqual(v, g.FLOOD_BLOCK_HOURLY_CAP)
        self.assertIn("hourly cap", reason)


class TestDailyCap(_FixtureBase):
    def test_daily_cap_routes_excess_to_digest(self):
        # Lower the daily cap to make the test fast.
        with mock.patch.dict(os.environ, {
            "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR": "100",
            "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY":  "2",
        }, clear=False):
            import notification_flood_guard as g
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            for i in range(2):
                v, _, _ = g.evaluate_and_record(
                    f"[INCIDENT-CRITICAL] hit {i}",
                    f"P{10+i:02d}", now=now + timedelta(hours=i))
                self.assertEqual(v, g.FLOOD_SEND_FIRST)
            v, _, reason = g.evaluate_and_record(
                "[INCIDENT-CRITICAL] hit X", "P55",
                now=now + timedelta(hours=3))
            self.assertEqual(v, g.FLOOD_BLOCK_DAILY_CAP)
            self.assertIn("daily cap", reason)


# ────────────────────────────────────────────────────────────────────────────
# Always-send markers (KILL-SWITCH / FAIL)
# ────────────────────────────────────────────────────────────────────────────

class TestAlwaysSendMarkers(_FixtureBase):
    def test_kill_switch_always_sends_even_during_cap(self):
        # Fill the hourly cap first.
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        for i in range(3):
            g.evaluate_and_record(
                f"[INCIDENT-CRITICAL] hit {i}",
                f"P{10+i:02d}", now=now + timedelta(minutes=i))
        # KILL-SWITCH bypasses.
        v, _, reason = g.evaluate_and_record(
            "[KILL-SWITCH] deadman armed", "context",
            now=now + timedelta(minutes=10))
        self.assertEqual(v, g.FLOOD_SEND_ESCALATION)
        self.assertIn("always-send", reason)

    def test_fail_always_sends(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        v, _, reason = g.evaluate_and_record(
            "[FAIL] workflow failed", "context", now=now)
        self.assertEqual(v, g.FLOOD_SEND_ESCALATION)
        self.assertIn("always-send", reason)

    def test_operator_extends_always_send_markers(self):
        with mock.patch.dict(os.environ, {
            "NOTIFY_ALWAYS_SEND_MARKERS": "[KILL-SWITCH,[FAIL,[OPERATOR-ALERT]",
        }, clear=False):
            import notification_flood_guard as g
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            v, _, _ = g.evaluate_and_record(
                "[OPERATOR-ALERT] custom critical", "x", now=now)
            self.assertEqual(v, g.FLOOD_SEND_ESCALATION)


# ────────────────────────────────────────────────────────────────────────────
# Flood-guard disable + bypass
# ────────────────────────────────────────────────────────────────────────────

class TestFloodGuardDisabled(_FixtureBase):
    def test_disabled_returns_bypass(self):
        with mock.patch.dict(os.environ, {
            "NOTIFY_FLOOD_GUARD_ENABLED": "false",
        }, clear=False):
            import notification_flood_guard as g
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            v, _, reason = g.evaluate_and_record(
                "[INCIDENT-CRITICAL] x", "P02", now=now)
            self.assertEqual(v, g.FLOOD_BYPASS_DISABLED)
            self.assertIn("disabled", reason)

    def test_disabled_still_writes_audit(self):
        with mock.patch.dict(os.environ, {
            "NOTIFY_FLOOD_GUARD_ENABLED": "false",
        }, clear=False):
            import notification_flood_guard as g
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            g.evaluate_and_record(
                "[INCIDENT-CRITICAL] x", "P02", now=now)
            audit = g._audit_path("2026-06-09")
            self.assertTrue(audit.exists())
            lines = audit.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["verdict"], "FLOOD_BYPASS_DISABLED")


# ────────────────────────────────────────────────────────────────────────────
# Audit JSONL is always written + never leaks secrets
# ────────────────────────────────────────────────────────────────────────────

class TestAuditJsonlAlwaysWritten(_FixtureBase):
    def test_every_decision_writes_audit_row(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] x", "P02", now=now)
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] x", "P02",
            now=now + timedelta(minutes=5))
        audit = g._audit_path("2026-06-09")
        lines = audit.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        v1 = json.loads(lines[0])["verdict"]
        v2 = json.loads(lines[1])["verdict"]
        self.assertEqual(v1, g.FLOOD_SEND_FIRST)
        self.assertEqual(v2, g.FLOOD_DIGEST)

    def test_secrets_redacted_in_preview(self):
        import notification_flood_guard as g
        now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
        # 20-char Alpaca-key-shape uppercase token.
        leaky_body = (
            "context AKAAAAAAAAAAAAAAAAAA bar — secret value")
        g.evaluate_and_record(
            "[INCIDENT-CRITICAL] x", leaky_body, now=now)
        audit = g._audit_path("2026-06-09")
        text = audit.read_text(encoding="utf-8")
        self.assertNotIn("AKAAAAAAAAAAAAAAAAAA", text)
        self.assertIn("REDACTED", text)


# ────────────────────────────────────────────────────────────────────────────
# Safety: monitor never imports broker module, never sends orders
# ────────────────────────────────────────────────────────────────────────────

class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean_of_broker_tokens(self):
        src = (REPO_ROOT / "shared"
                / "notification_flood_guard.py").read_text(
            encoding="utf-8")
        for tok in (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        ):
            self.assertNotIn(tok, src,
                              f"forbidden token in flood guard: {tok!r}")


if __name__ == "__main__":
    unittest.main()

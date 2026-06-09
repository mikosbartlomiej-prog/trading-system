"""v3.13.1 (2026-05-30) — NotificationPolicy tests.

Verifies:
  * `_classify_subject` correctly bins subjects into send/digest/suppress
  * `_append_to_digest` writes JSONL safely (isolation via NOTIFY_DIGEST_DIR)
  * `send_email` honours policy (mocked SMTP — no real email)
  * NOTIFY_MODE=off suppresses everything
  * NOTIFY_MODE=verbose sends everything
  * NOTIFY_FORCE_SEND / NOTIFY_FORCE_SUPPRESS overrides work
  * `scripts/send_daily_digest.py` --no-send produces correct preview

These tests pin down the inbox-noise filter so a future refactor cannot
re-flood the operator's inbox.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _reload_notify(env_overrides: dict | None = None):
    """Re-import notify with optional env overrides (NOTIFY_MODE etc.).

    v3.27.3 — also reset ``notification_flood_guard`` module state and
    isolate the flood-guard state + digest directories under
    ``tempfile.mkdtemp()`` so legacy v3.13 tests do not collide with the
    on-repo state file written by production runs.
    """
    # Clean prior env keys
    for k in ("NOTIFY_MODE", "NOTIFY_FORCE_SEND", "NOTIFY_FORCE_SUPPRESS",
                "NOTIFY_DIGEST_DIR", "NOTIFY_FLOOD_STATE_DIR",
                "NOTIFY_FLOOD_GUARD_ENABLED",
                "INCIDENT_CRITICAL_IMMEDIATE_FIRST",
                "INCIDENT_CRITICAL_COOLDOWN_MINUTES",
                "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR",
                "INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY",
                "NOTIFY_ALWAYS_SEND_MARKERS",
                "NOTIFY_ALWAYS_DIGEST_MARKERS"):
        os.environ.pop(k, None)
    # Isolate the flood-guard state under a unique tempdir per call.
    import tempfile
    _iso = tempfile.mkdtemp(prefix="notify_v3131_")
    os.environ["NOTIFY_FLOOD_STATE_DIR"] = _iso
    os.environ["NOTIFY_DIGEST_DIR"]      = _iso
    if env_overrides:
        os.environ.update(env_overrides)
    # Reset flood-guard cached module too — env is re-read at call time
    # but a stale import would shadow any test patches.
    for _mod in ("notification_flood_guard",
                  "shared.notification_flood_guard"):
        if _mod in sys.modules:
            del sys.modules[_mod]
    # Re-import
    if "notify" in sys.modules:
        del sys.modules["notify"]
    import notify
    importlib.reload(notify)
    return notify


class TestClassifierMinimal(unittest.TestCase):
    """Default NOTIFY_MODE=minimal: only critical sent, info digested,
    noise suppressed."""

    def setUp(self):
        self.notify = _reload_notify({"NOTIFY_MODE": "minimal"})

    # CRITICAL → send
    def test_incident_critical_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[INCIDENT-CRITICAL] P02 naked_short NOW"),
            "send")

    def test_safe_mode_entered_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[SAFE_MODE_ENTERED] AUDIT_GAP"),
            "send")

    def test_defend_day_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[INTRADAY-DEFEND] peak +$1k current +$300"),
            "send")

    def test_red_day_after_green_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[INTRADAY-RED-AFTER-GREEN] ..."),
            "send")

    def test_profit_lock_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[PROFIT-LOCK] retraced 50%"),
            "send")

    def test_pol_filing_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[POL-FILING] Gottheimer PTR 2026-05-19"),
            "send")

    def test_allocator_exec_with_failures_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[allocator EXEC] 0 placed, 0 skipped, 6 failed"),
            "send")

    def test_routine_budget_low_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[ROUTINE-BUDGET-LOW] 3/15 remaining"),
            "send")

    def test_op_correction_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[op-correction] scheduled buy-to-cover NOW"),
            "send")

    def test_allocator_revalidate_is_sent(self):
        self.assertEqual(
            self.notify._classify_subject("[allocator REVALIDATE] dropped 2 stale orders"),
            "send")

    # DIGEST → batched
    def test_buy_signal_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[BUY] [momentum-long] BUY AAPL - $5000"),
            "digest")

    def test_exit_signal_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[EXIT] AMD - CLOSE_FLAT (+0.50%)"),
            "digest")

    def test_options_executed_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[EXECUTED] AAPL260520P00170000 BUY @ $3.04"),
            "digest")

    def test_intraday_warn_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[INTRADAY-WARN] peak +$700 current +$500 (30%)"),
            "digest")

    def test_allocator_plan_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[allocator PLAN] regime=NEUTRAL 11 orders"),
            "digest")

    def test_allocator_exec_clean_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[allocator EXEC] 8 placed, 0 skipped, 0 failed"),
            "digest")

    def test_pdt_ok_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[PDT-OK] dt=0 of 3"),
            "digest")

    def test_safe_mode_exited_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[SAFE_MODE_EXITED]"),
            "digest")

    def test_learning_loop_pr_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[learning-loop AUTO-PR] crypto oversold boost"),
            "digest")

    def test_cron_summary_with_signals_is_digested(self):
        self.assertEqual(
            self.notify._classify_subject("[Defense Monitor] 3 signal(s), 1 sent"),
            "digest")
        self.assertEqual(
            self.notify._classify_subject("[Crypto Monitor] 1 signal(s), 1 sent"),
            "digest")

    # SUPPRESS → noise
    def test_cron_summary_with_zero_signals_is_suppressed(self):
        for monitor in ("Defense Monitor", "Crypto Monitor", "Geo Monitor",
                        "Reddit Monitor", "Twitter Monitor", "Price Monitor",
                        "Exit Monitor"):
            with self.subTest(monitor=monitor):
                subject = f"[{monitor}] 0 signal(s), 0 sent"
                self.assertEqual(self.notify._classify_subject(subject), "suppress",
                                  f"{subject} should be suppressed")

    def test_unknown_subject_defaults_to_send(self):
        """Unknown subjects send by default — safer than swallowing."""
        self.assertEqual(
            self.notify._classify_subject("[NEW-FEATURE] something brand new"),
            "send")


class TestNotifyModeOff(unittest.TestCase):
    """NOTIFY_MODE=off → suppress everything."""

    def test_off_suppresses_even_critical(self):
        notify = _reload_notify({"NOTIFY_MODE": "off"})
        self.assertEqual(notify._classify_subject("[INCIDENT-CRITICAL] xxx"),
                          "suppress")
        self.assertEqual(notify._classify_subject("[BUY] x"), "suppress")
        self.assertEqual(notify._classify_subject("[Defense Monitor] 0 signal(s), 0 sent"),
                          "suppress")


class TestNotifyModeVerbose(unittest.TestCase):
    """NOTIFY_MODE=verbose → send everything (legacy v3.12 behavior)."""

    def test_verbose_sends_even_noise(self):
        notify = _reload_notify({"NOTIFY_MODE": "verbose"})
        self.assertEqual(notify._classify_subject("[Defense Monitor] 0 signal(s), 0 sent"),
                          "send")
        self.assertEqual(notify._classify_subject("[BUY] x"), "send")
        self.assertEqual(notify._classify_subject("[INCIDENT-CRITICAL] x"), "send")


class TestForceOverrides(unittest.TestCase):
    """NOTIFY_FORCE_SEND / NOTIFY_FORCE_SUPPRESS overrides."""

    def test_force_send_overrides_digest(self):
        notify = _reload_notify({
            "NOTIFY_MODE": "minimal",
            "NOTIFY_FORCE_SEND": "[BUY],[EXIT]",
        })
        self.assertEqual(notify._classify_subject("[BUY] AAPL"), "send")
        self.assertEqual(notify._classify_subject("[EXIT] AMD"), "send")
        # Other digests unchanged
        self.assertEqual(notify._classify_subject("[allocator PLAN] x"), "digest")

    def test_force_suppress_overrides_critical(self):
        notify = _reload_notify({
            "NOTIFY_MODE": "minimal",
            "NOTIFY_FORCE_SUPPRESS": "[POL-FILING]",
        })
        self.assertEqual(notify._classify_subject("[POL-FILING] xxx"), "suppress")
        # Other criticals unchanged
        self.assertEqual(notify._classify_subject("[INCIDENT-CRITICAL] x"), "send")


class TestDigestFile(unittest.TestCase):
    """Verify digest is appended correctly with isolation."""

    def test_digest_append_creates_jsonl(self):
        with tempfile.TemporaryDirectory(prefix="digest_test_") as tmp:
            notify = _reload_notify({
                "NOTIFY_MODE": "minimal",
                "NOTIFY_DIGEST_DIR": tmp,
            })
            notify._append_to_digest("[BUY] x", "body of x")
            notify._append_to_digest("[EXIT] y", "body of y")
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date().isoformat()
            path = Path(tmp) / f"{today}.jsonl"
            self.assertTrue(path.exists())
            rows = path.read_text().strip().split("\n")
            self.assertEqual(len(rows), 2)
            r1 = json.loads(rows[0])
            self.assertEqual(r1["subject"], "[BUY] x")
            self.assertIn("body of x", r1["body_preview"])


class TestSendEmailGated(unittest.TestCase):
    """send_email respects classifier — no SMTP call when digest/suppress."""

    def setUp(self):
        # Stub creds so it would otherwise attempt SMTP
        os.environ["GMAIL_USER"] = "test@example.com"
        os.environ["GMAIL_APP_PASSWORD"] = "fakepassword"

    def tearDown(self):
        os.environ.pop("GMAIL_USER", None)
        os.environ.pop("GMAIL_APP_PASSWORD", None)

    def test_digest_subject_does_not_call_smtp(self):
        with tempfile.TemporaryDirectory(prefix="digest_") as tmp:
            notify = _reload_notify({
                "NOTIFY_MODE": "minimal",
                "NOTIFY_DIGEST_DIR": tmp,
            })
            with patch("notify.smtplib.SMTP_SSL") as mock_smtp:
                ok = notify.send_email("[BUY] x", "body")
                self.assertTrue(ok, "digest path returns True")
                self.assertFalse(mock_smtp.called, "SMTP must NOT be called for digest")

    def test_suppress_subject_does_not_call_smtp(self):
        notify = _reload_notify({"NOTIFY_MODE": "minimal"})
        with patch("notify.smtplib.SMTP_SSL") as mock_smtp:
            ok = notify.send_email("[Defense Monitor] 0 signal(s), 0 sent", "body")
            self.assertFalse(ok, "suppress returns False (not delivered)")
            self.assertFalse(mock_smtp.called)

    def test_critical_subject_calls_smtp(self):
        notify = _reload_notify({"NOTIFY_MODE": "minimal"})
        with patch("notify.smtplib.SMTP_SSL") as mock_smtp:
            # Configure context manager
            cm = mock_smtp.return_value.__enter__.return_value
            cm.login = MagicMock()
            cm.send_message = MagicMock()
            ok = notify.send_email("[INCIDENT-CRITICAL] x", "body")
            self.assertTrue(ok)
            self.assertTrue(mock_smtp.called)


class TestDailyDigestScript(unittest.TestCase):
    """scripts/send_daily_digest.py --no-send smoke test."""

    def test_no_send_with_empty_digest_exits_clean(self):
        with tempfile.TemporaryDirectory(prefix="digest_") as tmp:
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "send_daily_digest.py"),
                 "--date", "2099-01-01", "--no-send"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ, "NOTIFY_DIGEST_DIR": tmp},
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("nothing to send", result.stdout)

    def test_no_send_with_populated_digest_renders(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory(prefix="digest_") as tmp:
            today = datetime.now(timezone.utc).date().isoformat()
            path = Path(tmp) / f"{today}.jsonl"
            path.write_text(
                '{"timestamp":"2026-05-30T10:00:00Z","subject":"[BUY] AAPL","body_preview":"x"}\n'
                '{"timestamp":"2026-05-30T10:05:00Z","subject":"[EXIT] AMD","body_preview":"y"}\n'
            )
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "send_daily_digest.py"),
                 "--date", today, "--no-send"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ, "NOTIFY_DIGEST_DIR": tmp},
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("SUBJECT:", result.stdout)
            self.assertIn("DAILY DIGEST", result.stdout)
            self.assertIn("2 non-critical events", result.stdout)


if __name__ == "__main__":
    unittest.main()

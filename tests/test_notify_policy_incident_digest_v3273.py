"""v3.27.3 (2026-06-09) — send_email + flood-guard end-to-end tests.

Verifies that the v3.27.3 wire-in in ``shared/notify.py`` correctly
routes ``[INCIDENT-CRITICAL]`` events through the flood guard while
preserving the existing v3.13.x policy for non-guarded subjects.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _fresh_notify(env_overrides: dict[str, str] | None = None):
    """Reimport ``shared/notify.py`` so module-level constants
    (NOTIFY_MODE etc.) re-read env. Returns the freshly-imported
    module object."""
    env = {
        "GMAIL_USER":               "test@example.com",
        "GMAIL_APP_PASSWORD":       "PASSWORD123",
        "NOTIFY_EMAIL":             "ops@example.com",
        "NOTIFY_MODE":              "minimal",
    }
    if env_overrides:
        env.update(env_overrides)
    for mod_name in (
        "notify", "notification_flood_guard",
        "shared.notify", "shared.notification_flood_guard",
    ):
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    with mock.patch.dict(os.environ, env, clear=False):
        import notify  # type: ignore
    return notify


class _IsolatedEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env_patcher = mock.patch.dict(os.environ, {
            "NOTIFY_FLOOD_STATE_DIR": str(self.tmp / "state"),
            "NOTIFY_DIGEST_DIR":      str(self.tmp / "digest"),
            "NOTIFY_FLOOD_GUARD_ENABLED":           "true",
            "INCIDENT_CRITICAL_IMMEDIATE_FIRST":    "true",
            "INCIDENT_CRITICAL_COOLDOWN_MINUTES":   "60",
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
# Routing: first INCIDENT-CRITICAL sends; duplicate digests
# ────────────────────────────────────────────────────────────────────────────

class TestIncidentCriticalRouting(_IsolatedEnv):
    def test_first_incident_critical_reaches_smtp(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            ok = n.send_email(
                "[INCIDENT-CRITICAL] P02 naked short", "body")
            self.assertTrue(ok)
            # First call: SMTP was invoked.
            self.assertTrue(smtp_mod.SMTP_SSL.called,
                              "first INCIDENT-CRITICAL should hit SMTP")

    def test_duplicate_incident_critical_does_not_reach_smtp(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email(
                "[INCIDENT-CRITICAL] P02 naked short", "P02 body")
            # second call same fingerprint within cooldown
            smtp_mod.reset_mock()
            ok = n.send_email(
                "[INCIDENT-CRITICAL] P02 naked short", "P02 body")
            self.assertTrue(ok,
                            "digested duplicate should still return "
                            "True (event was preserved)")
            self.assertFalse(smtp_mod.SMTP_SSL.called,
                               "duplicate INCIDENT-CRITICAL must NOT "
                               "hit SMTP")

    def test_duplicate_critical_appended_to_digest_jsonl(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email(
                "[INCIDENT-CRITICAL] P02 X", "P02 details")
            n.send_email(
                "[INCIDENT-CRITICAL] P02 X", "P02 details")
        # Standard digest file (from shared/notify.py::_append_to_digest)
        # plus flood-guard audit file should both exist.
        today = datetime.now(timezone.utc).date().isoformat()
        digest_path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                        / f"{today}.jsonl")
        self.assertTrue(digest_path.exists(),
                          "duplicate must be appended to digest")
        lines = digest_path.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 1)


# ────────────────────────────────────────────────────────────────────────────
# KILL-SWITCH and FAIL still go through
# ────────────────────────────────────────────────────────────────────────────

class TestKillSwitchAndFailStillSend(_IsolatedEnv):
    def test_kill_switch_hits_smtp(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email("[KILL-SWITCH] armed", "context")
            self.assertTrue(smtp_mod.SMTP_SSL.called)

    def test_fail_hits_smtp(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email("[FAIL] workflow failed", "context")
            self.assertTrue(smtp_mod.SMTP_SSL.called)

    def test_kill_switch_sends_even_after_cap_filled(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            # Use 3 distinct INCIDENT-CRITICAL fingerprints (hourly
            # cap is 3 in this test env).
            for i in range(3):
                n.send_email(
                    f"[INCIDENT-CRITICAL] hit {i}", f"P{10+i:02d}")
            smtp_mod.reset_mock()
            ok = n.send_email("[KILL-SWITCH] armed", "context")
            self.assertTrue(ok)
            self.assertTrue(smtp_mod.SMTP_SSL.called,
                              "KILL-SWITCH must bypass cap")


# ────────────────────────────────────────────────────────────────────────────
# NOTIFY_MODE interactions
# ────────────────────────────────────────────────────────────────────────────

class TestNotifyModeInteractions(_IsolatedEnv):
    def test_off_suppresses_even_incident_critical(self):
        n = _fresh_notify({"NOTIFY_MODE": "off"})
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            ok = n.send_email("[INCIDENT-CRITICAL] x", "P02")
            self.assertFalse(ok)
            self.assertFalse(smtp_mod.SMTP_SSL.called)

    def test_verbose_with_flood_guard_still_protects_critical(self):
        # In verbose mode the legacy classifier returns "send" for
        # ALL subjects. The v3.27.3 flood guard must still protect
        # INCIDENT-CRITICAL duplicates.
        n = _fresh_notify({"NOTIFY_MODE": "verbose"})
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email("[INCIDENT-CRITICAL] x", "P02")
            smtp_mod.reset_mock()
            ok = n.send_email("[INCIDENT-CRITICAL] x", "P02")
            self.assertTrue(ok,
                            "duplicate must succeed (digested)")
            self.assertFalse(smtp_mod.SMTP_SSL.called,
                               "duplicate must not hit SMTP even in "
                               "verbose mode")

    def test_verbose_with_flood_guard_disabled_lets_duplicates_through(self):
        # The flood-guard reads env at call time, so we must keep the
        # override active while ``send_email`` is invoked.
        with mock.patch.dict(os.environ, {
            "NOTIFY_MODE":                "verbose",
            "NOTIFY_FLOOD_GUARD_ENABLED": "false",
        }, clear=False):
            n = _fresh_notify({
                "NOTIFY_MODE":               "verbose",
                "NOTIFY_FLOOD_GUARD_ENABLED": "false",
            })
            with mock.patch.object(n, "smtplib") as smtp_mod:
                smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                    mock.MagicMock())
                n.send_email("[INCIDENT-CRITICAL] x", "P02")
                n.send_email("[INCIDENT-CRITICAL] x", "P02")
                # Both calls hit SMTP (operator explicit opt-out).
                self.assertGreaterEqual(smtp_mod.SMTP_SSL.call_count, 2)


# ────────────────────────────────────────────────────────────────────────────
# Decision audit file is written
# ────────────────────────────────────────────────────────────────────────────

class TestDecisionAuditFile(_IsolatedEnv):
    def test_decision_audit_file_grows_with_each_send(self):
        n = _fresh_notify()
        with mock.patch.object(n, "smtplib") as smtp_mod:
            smtp_mod.SMTP_SSL.return_value.__enter__.return_value = (
                mock.MagicMock())
            n.send_email("[INCIDENT-CRITICAL] x", "P02")
            n.send_email("[INCIDENT-CRITICAL] x", "P02")
        today = datetime.now(timezone.utc).date().isoformat()
        audit_path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                       / f"notification_decisions_{today}.jsonl")
        self.assertTrue(audit_path.exists())
        lines = audit_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        v1 = json.loads(lines[0])["verdict"]
        v2 = json.loads(lines[1])["verdict"]
        self.assertEqual(v1, "FLOOD_SEND_FIRST")
        self.assertEqual(v2, "FLOOD_DIGEST")


if __name__ == "__main__":
    unittest.main()

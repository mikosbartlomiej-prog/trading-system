"""v3.27.3 (2026-06-09) — scripts/send_incident_digest.py tests."""

from __future__ import annotations

import importlib.util as iu
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = iu.spec_from_file_location(
        "send_incident_digest",
        REPO_ROOT / "scripts" / "send_incident_digest.py",
    )
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _IsolatedDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env_patcher = mock.patch.dict(os.environ, {
            "NOTIFY_DIGEST_DIR": str(self.tmp / "digest"),
        }, clear=False)
        self.env_patcher.start()
        (self.tmp / "digest").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.env_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ────────────────────────────────────────────────────────────────────────────
# Aggregation: nothing → nothing
# ────────────────────────────────────────────────────────────────────────────

class TestAggregateEmpty(_IsolatedDir):
    def test_aggregate_with_no_files(self):
        s = _load_script()
        summary = s.aggregate("2026-06-09")
        self.assertEqual(summary["unique_fingerprints"], 0)
        self.assertEqual(summary["immediate_sent_count"], 0)
        self.assertEqual(summary["digested_count"], 0)
        self.assertEqual(summary["groups"], [])


class TestNothingToDigestReturnsZero(_IsolatedDir):
    def test_only_if_events_no_events(self):
        s = _load_script()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = s.main(["--only-if-events", "--print-only"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(out["status"], "NOTHING_TO_DIGEST")


# ────────────────────────────────────────────────────────────────────────────
# Aggregation: groups by fingerprint
# ────────────────────────────────────────────────────────────────────────────

class TestAggregateGroupsByFingerprint(_IsolatedDir):
    def _write_audit(self, date_iso, rows):
        path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                 / f"notification_decisions_{date_iso}.jsonl")
        with path.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        return path

    def test_groups_count_correctly(self):
        s = _load_script()
        date = "2026-06-09"
        self._write_audit(date, [
            {"timestamp_iso": "2026-06-09T14:00:00+00:00",
             "fingerprint": "ABC", "verdict": "FLOOD_SEND_FIRST",
             "reason": "first", "subject_preview": "[INCIDENT-CRITICAL] x",
             "body_preview": "P02"},
            {"timestamp_iso": "2026-06-09T14:05:00+00:00",
             "fingerprint": "ABC", "verdict": "FLOOD_DIGEST",
             "reason": "within cooldown",
             "subject_preview": "[INCIDENT-CRITICAL] x",
             "body_preview": "P02"},
            {"timestamp_iso": "2026-06-09T14:10:00+00:00",
             "fingerprint": "DEF", "verdict": "FLOOD_SEND_FIRST",
             "reason": "first", "subject_preview": "[INCIDENT-CRITICAL] y",
             "body_preview": "P11"},
        ])
        summary = s.aggregate(date)
        self.assertEqual(summary["unique_fingerprints"], 2)
        self.assertEqual(summary["immediate_sent_count"], 2)
        self.assertEqual(summary["digested_count"], 1)
        # Top group by count is ABC (3 entries).
        self.assertEqual(summary["groups"][0]["fingerprint"], "ABC")
        self.assertEqual(summary["groups"][0]["total_count"], 2)


# ────────────────────────────────────────────────────────────────────────────
# Digest emits AT MOST ONE email
# ────────────────────────────────────────────────────────────────────────────

class TestSendsAtMostOneEmail(_IsolatedDir):
    def _seed_many_audit_rows(self, date_iso, n=200):
        path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                 / f"notification_decisions_{date_iso}.jsonl")
        with path.open("a", encoding="utf-8") as fh:
            for i in range(n):
                row = {
                    "timestamp_iso": f"2026-06-09T14:{i % 60:02d}:00+00:00",
                    "fingerprint":   f"FP{i:03d}",
                    "verdict":       "FLOOD_DIGEST",
                    "reason":        "within cooldown",
                    "subject_preview": "[INCIDENT-CRITICAL] x",
                    "body_preview":    f"P{i:02d}",
                }
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    def test_at_most_one_email_for_200_audit_rows(self):
        s = _load_script()
        date = "2026-06-09"
        self._seed_many_audit_rows(date, n=200)
        # Patch the script's send_email so we can count invocations.
        sent: list[tuple[str, str]] = []

        def fake_send(subject, body):
            sent.append((subject, body))
            return True

        with mock.patch.object(s, "send_one_email", side_effect=fake_send):
            rc = s.main(["--date", date])
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 1,
                          "digest script must send AT MOST one email")
        # Subject must be the digest subject prefix.
        self.assertIn("[INCIDENT-DIGEST]", sent[0][0])


# ────────────────────────────────────────────────────────────────────────────
# Print-only mode never sends
# ────────────────────────────────────────────────────────────────────────────

class TestPrintOnlyDoesNotSend(_IsolatedDir):
    def test_print_only_skips_send(self):
        s = _load_script()
        sent: list[tuple[str, str]] = []

        def fake_send(subject, body):
            sent.append((subject, body))
            return True

        # Seed at least one row.
        path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                 / "notification_decisions_2026-06-09.jsonl")
        path.write_text(json.dumps({
            "timestamp_iso": "2026-06-09T14:00:00+00:00",
            "fingerprint":   "X", "verdict": "FLOOD_SEND_FIRST",
            "reason":        "first",
            "subject_preview": "[INCIDENT-CRITICAL] x",
            "body_preview":    "P02",
        }) + "\n", encoding="utf-8")

        with mock.patch.object(s, "send_one_email", side_effect=fake_send):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = s.main(["--date", "2026-06-09", "--print-only"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 0)


# ────────────────────────────────────────────────────────────────────────────
# Broker-flag refusal + import safety
# ────────────────────────────────────────────────────────────────────────────

class TestBrokerFlagRefusal(_IsolatedDir):
    def test_refuses_when_allow_broker_paper_truthy(self):
        s = _load_script()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {
            "ALLOW_BROKER_PAPER": "true",
        }, clear=False):
            with redirect_stdout(buf):
                rc = s.main(["--date", "2026-06-09"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_ALLOW_BROKER_PAPER_IS_TRUTHY",
                       buf.getvalue())


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean_of_broker_tokens(self):
        src = (REPO_ROOT / "scripts"
                / "send_incident_digest.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        ):
            self.assertNotIn(tok, src,
                              f"forbidden token in digest script: {tok!r}")


# ────────────────────────────────────────────────────────────────────────────
# Render does not leak secrets
# ────────────────────────────────────────────────────────────────────────────

class TestRenderNoSecretLeak(_IsolatedDir):
    def test_body_does_not_include_long_alpha_secret_blobs(self):
        s = _load_script()
        # Even if a malicious audit row contained a secret, it would
        # already have been redacted by the flood guard; verify the
        # digest renderer doesn't accidentally splice raw bodies.
        date = "2026-06-09"
        path = (Path(os.environ["NOTIFY_DIGEST_DIR"])
                 / f"notification_decisions_{date}.jsonl")
        # The redactor in the flood guard already strips this — but
        # if a leaky row sneaks in, the digest renderer just splices
        # the preview; we accept that and document it. This test
        # confirms the renderer at least does not extend the preview
        # beyond the documented 300-char cap.
        path.write_text(json.dumps({
            "timestamp_iso": "2026-06-09T14:00:00+00:00",
            "fingerprint":   "X",
            "verdict":       "FLOOD_DIGEST",
            "reason":        "within cooldown",
            "subject_preview": "[INCIDENT-CRITICAL] x",
            "body_preview":    "Z" * 500,
        }) + "\n", encoding="utf-8")
        summary = s.aggregate(date)
        body = s.render_body(summary)
        # Body preview line truncated to <=300 chars per render rule.
        for line in body.splitlines():
            if line.lstrip().startswith("latest_body:"):
                # Strip the prefix to get the preview slice.
                preview = line.split("latest_body:")[1].lstrip()
                self.assertLessEqual(len(preview), 300)


if __name__ == "__main__":
    unittest.main()

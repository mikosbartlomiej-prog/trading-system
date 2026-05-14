"""audit layer — JSONL append-only, schema, daily rollover."""
import json
import os
import sys
import tempfile
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import audit
import autonomy


class TestAuditWrite(unittest.TestCase):
    def setUp(self):
        self._tmp_trading = tempfile.mkdtemp()
        self._tmp_code = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp_trading
        os.environ["AUDIT_CODE_DIR"] = self._tmp_code

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("AUDIT_CODE_DIR", None)

    def test_audit_event_written_for_entry_reject(self):
        d = autonomy.make_decision(
            "REJECT_ENTRY", "REJECT", "size > cap", "test",
            affected_symbols=["NVDA"],
        )
        path = audit.write_audit_event(d, kind="trading")
        self.assertTrue(path.exists())
        records = audit.read_today(kind="trading")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["decision_type"], "REJECT_ENTRY")
        self.assertEqual(records[0]["affected_symbols"], ["NVDA"])

    def test_audit_event_written_for_emergency_close(self):
        d = autonomy.make_decision(
            "EMERGENCY_CLOSE", "CLOSED", "hard loss", "engine",
            affected_symbols=["AAPL"], reversible=False,
        )
        audit.write_audit_event(d, kind="trading")
        records = audit.read_today(kind="trading")
        self.assertEqual(records[-1]["decision"], "CLOSED")

    def test_audit_event_for_code_patch(self):
        d = autonomy.make_decision(
            "PATCH_REJECT", "REJECT_FORBIDDEN", "live endpoint added",
            "autonomous_code_loop",
            code_before_sha="abc1234", code_after_sha="",
        )
        jsonl_path, md_path = audit.write_code_audit_event(
            d, summary_md="REJECT_FORBIDDEN: live endpoint added"
        )
        self.assertTrue(jsonl_path.exists())
        self.assertIsNotNone(md_path)
        self.assertTrue(md_path.exists())
        records = audit.read_today(kind="code")
        self.assertEqual(records[-1]["decision_type"], "PATCH_REJECT")
        self.assertEqual(records[-1]["code_before_sha"], "abc1234")

    def test_append_only_preserves_history(self):
        d1 = autonomy.make_decision("APPROVE_ENTRY", "APPROVE", "ok", "t")
        d2 = autonomy.make_decision("REJECT_ENTRY", "REJECT", "no", "t")
        audit.write_audit_event(d1, kind="trading")
        audit.write_audit_event(d2, kind="trading")
        records = audit.read_today(kind="trading")
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()

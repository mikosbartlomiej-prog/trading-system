"""v3.27.2 (2026-06-09) — workflow_health_history JSONL append tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_monitor():
    import importlib.util as iu
    spec = iu.spec_from_file_location(
        "monitor_automated_shadow_progress",
        REPO_ROOT / "scripts"
        / "monitor_automated_shadow_progress.py",
    )
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestHistoryAppend(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()
        self.tmp = tempfile.mkdtemp()
        self.history_path = Path(self.tmp) / "history.jsonl"

    def test_append_creates_file_and_writes_entry(self):
        latest = {
            "generated_at_iso":             "2026-06-09T13:35:00+00:00",
            "last_workflow_run_id":         "100",
            "last_workflow_run_conclusion": "success",
            "last_collector_status":        "SHADOW_COLLECTION_PROCEEDING",
            "last_resolver_status":         "RESOLVED",
            "verdict":                      "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
            "diagnostic_token_counts": {
                "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 8,
            },
            "counters_snapshot": {
                "real_market_opportunities_count": 0,
                "completed_shadow_outcomes_count": 0,
            },
            "standing_markers": [
                "BROKER_PAPER_CANARY_STILL_BLOCKED",
                "LIVE_TRADING_UNSUPPORTED",
            ],
            "safety": {
                "broker_paper_canary_still_blocked": True,
                "live_trading_unsupported":          True,
            },
            "secrets_status": "SECRETS_AVAILABLE",
        }
        entry = self.mod.append_health_snapshot_to_history(
            latest, history_path=self.history_path)
        self.assertEqual(entry["workflow_run_id"], "100")
        self.assertTrue(self.history_path.exists())
        lines = self.history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        loaded = json.loads(lines[0])
        self.assertEqual(loaded["workflow_run_id"], "100")
        self.assertEqual(loaded["verdict"],
                          "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET")

    def test_append_is_idempotent_for_same_run(self):
        latest = {
            "generated_at_iso":             "2026-06-09T13:35:00+00:00",
            "last_workflow_run_id":         "200",
            "last_workflow_run_conclusion": "success",
        }
        self.mod.append_health_snapshot_to_history(
            latest, history_path=self.history_path)
        self.mod.append_health_snapshot_to_history(
            latest, history_path=self.history_path)
        # Same workflow_run_id + generated_at_iso → dedup'd.
        lines = self.history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)

    def test_append_distinct_runs_grow_history(self):
        for rid in ("10", "11", "12"):
            latest = {
                "generated_at_iso":             f"2026-06-09T13:{rid}:00+00:00",
                "last_workflow_run_id":         rid,
                "last_workflow_run_conclusion": "success",
            }
            self.mod.append_health_snapshot_to_history(
                latest, history_path=self.history_path)
        lines = self.history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)

    def test_empty_latest_writes_nothing(self):
        entry = self.mod.append_health_snapshot_to_history(
            {}, history_path=self.history_path)
        self.assertEqual(entry, {})
        self.assertFalse(self.history_path.exists())

    def test_history_lines_are_pure_json(self):
        latest = {
            "generated_at_iso":             "2026-06-09T14:35:00+00:00",
            "last_workflow_run_id":         "300",
            "last_workflow_run_conclusion": "success",
        }
        self.mod.append_health_snapshot_to_history(
            latest, history_path=self.history_path)
        for line in self.history_path.read_text(
                encoding="utf-8").splitlines():
            json.loads(line)  # must parse


class TestNoSecretValuesInHistory(unittest.TestCase):
    def test_no_alpaca_key_pattern_in_history(self):
        # Even if the operator drops a key into the env, the history
        # never persists it because the source schema does not have
        # a secret field — confirm by writing a snapshot with arbitrary
        # extra keys and verifying the appended entry only contains
        # the documented projection.
        mod = _load_monitor()
        tmp = tempfile.mkdtemp()
        history_path = Path(tmp) / "history.jsonl"
        latest = {
            "generated_at_iso":             "2026-06-09T13:35:00+00:00",
            "last_workflow_run_id":         "1",
            "last_workflow_run_conclusion": "success",
            # rogue field that MUST NOT propagate.
            "ALPACA_API_KEY":               "AKAAAAAAAAAAAAAAAAAA",
            "secret_blob":                  "X" * 40,
        }
        mod.append_health_snapshot_to_history(
            latest, history_path=history_path)
        text = history_path.read_text(encoding="utf-8")
        self.assertNotIn("AKAAAAAAAAAAAAAAAAAA", text)
        self.assertNotIn("ALPACA_API_KEY", text)
        self.assertNotIn("secret_blob", text)


class TestMonitorRefusesOnBrokerFlag(unittest.TestCase):
    def test_refuses_when_allow_broker_paper_truthy(self):
        mod = _load_monitor()
        import io
        import contextlib
        buf = io.StringIO()
        with mock.patch.dict(os.environ,
                               {"ALLOW_BROKER_PAPER": "true"},
                               clear=False):
            with contextlib.redirect_stdout(buf):
                rc = mod.main(["--no-append"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_ALLOW_BROKER_PAPER_IS_TRUTHY",
                       buf.getvalue())


class TestMonitorNeverImportsBrokerOrders(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "monitor_automated_shadow_progress.py").read_text()
        FORBIDDEN = (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, src,
                              f"forbidden token in monitor: {tok!r}")


if __name__ == "__main__":
    unittest.main()

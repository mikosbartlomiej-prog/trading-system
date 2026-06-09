"""v3.30 (2026-06-09) — observation record contract.

Confirms that every observation record built and appended carries the
hard-coded safety contract: record_type=NO_TRADE_OBSERVATION,
evidence_quality=REAL_MARKET_DATA_OBSERVATION, broker flags false,
affects_readiness_gate=false, counts_toward_unlock_gate=false.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestObservationRecordSafetyFields(unittest.TestCase):

    def test_build_record_hard_codes_safety_fields(self):
        import observation_records as obs
        row = obs.build_observation_record(
            symbol="SPY",
            asset_class="us_equity",
            reason="REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
            strategy_name="momentum-long",
            diagnostic_token="REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
            evidence_values={"bars_window": 22},
        )
        self.assertEqual(row["record_type"], "NO_TRADE_OBSERVATION")
        self.assertEqual(row["evidence_quality"],
                          "REAL_MARKET_DATA_OBSERVATION")
        self.assertFalse(row["broker_order_submitted"])
        self.assertFalse(row["broker_execution_enabled"])
        self.assertFalse(row["affects_readiness_gate"])
        self.assertFalse(row["counts_toward_unlock_gate"])

    def test_caller_cannot_inject_truthy_safety_fields(self):
        import observation_records as obs
        row = obs.build_observation_record(
            symbol="SPY",
            asset_class="us_equity",
            reason="REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
            strategy_name="momentum-long",
            diagnostic_token="REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
            evidence_values={},
            extra={
                "affects_readiness_gate":    True,
                "counts_toward_unlock_gate": True,
                "broker_order_submitted":    True,
                "broker_execution_enabled":  True,
                "record_type":               "TRADE",
                "evidence_quality":          "REAL_MARKET_DATA",
            },
        )
        # Builder must overwrite any caller-supplied safety flags.
        self.assertEqual(row["record_type"], "NO_TRADE_OBSERVATION")
        self.assertEqual(row["evidence_quality"],
                          "REAL_MARKET_DATA_OBSERVATION")
        self.assertFalse(row["broker_order_submitted"])
        self.assertFalse(row["broker_execution_enabled"])
        self.assertFalse(row["affects_readiness_gate"])
        self.assertFalse(row["counts_toward_unlock_gate"])

    def test_append_re_asserts_safety_before_writing(self):
        import observation_records as obs
        tmp = Path(tempfile.mkdtemp()) / "obs.jsonl"
        row = {
            "symbol": "QQQ",
            "asset_class": "us_equity",
            "reason": "NO_TRADE_SIGNAL_NOT_TRIGGERED",
            "record_type": "TRADE",                  # tampered
            "evidence_quality": "REAL_MARKET_DATA",  # tampered
            "affects_readiness_gate": True,          # tampered
            "counts_toward_unlock_gate": True,       # tampered
            "broker_order_submitted": True,          # tampered
            "broker_execution_enabled": True,        # tampered
        }
        obs.append_observation_record(row, path=tmp)
        on_disk = json.loads(tmp.read_text(encoding="utf-8")
                              .splitlines()[0])
        self.assertEqual(on_disk["record_type"],
                          "NO_TRADE_OBSERVATION")
        self.assertEqual(on_disk["evidence_quality"],
                          "REAL_MARKET_DATA_OBSERVATION")
        self.assertFalse(on_disk["affects_readiness_gate"])
        self.assertFalse(on_disk["counts_toward_unlock_gate"])
        self.assertFalse(on_disk["broker_order_submitted"])
        self.assertFalse(on_disk["broker_execution_enabled"])

    def test_append_never_raises_on_unwritable_path(self):
        import observation_records as obs
        # A path under a file (not a dir) should not raise.
        tmp = Path(tempfile.mkdtemp()) / "a_file"
        tmp.write_text("x", encoding="utf-8")
        bad = tmp / "obs.jsonl"  # parent is a file
        # Must not raise.
        obs.emit(symbol="X", asset_class="us_equity",
                  reason="OTHER_DIAGNOSTIC",
                  strategy_name="momentum-long",
                  diagnostic_token="OTHER",
                  evidence_values={},
                  path=bad)


class TestObservationModuleNeverImportsBrokerOrders(unittest.TestCase):

    def test_module_source_does_not_import_broker_orders(self):
        path = REPO_ROOT / "shared" / "observation_records.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "alpaca_orders",
            "submit_order",
            "place_order",
            "safe_close",
        ):
            self.assertNotIn(forbidden, src,
                              f"observation_records.py must NOT "
                              f"contain {forbidden!r}")


if __name__ == "__main__":
    unittest.main()

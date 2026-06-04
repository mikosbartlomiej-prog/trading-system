"""v3.20.0 (2026-06-04) — ETAP 2 unit tests for
shared/signal_opportunity_ledger.py.

Coverage per spec:
  * Each signal creates exactly one opportunity entry.
  * Rejected signal carries an explicit rejection reason.
  * Accepted signal carries the audit_link reference.
  * The ledger NEVER places trades / NEVER calls the broker.
  * The ledger works fully offline (no network calls).
  * Six gate types are tracked; unknown gates are flagged.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _BaseLedgerTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_dir = Path(self.tmp.name) / "opportunity_ledger"
        self.audit_dir = Path(self.tmp.name) / "audit"

        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.ledger_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)

        for mod in list(sys.modules):
            if mod == "signal_opportunity_ledger" or mod.endswith(".signal_opportunity_ledger"):
                del sys.modules[mod]

        import signal_opportunity_ledger as sol
        self.sol = sol

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)


class TestRecordCreation(_BaseLedgerTest):

    def _record_basic(self, **overrides) -> dict:
        kwargs = dict(
            signal_id="sig-100",
            strategy="momentum-long",
            symbol="AAPL",
            raw_signal={"action": "BUY", "size_usd": 10_000},
            confidence_score=0.71,
            confidence_components={"data_quality": 0.9, "signal_strength": 0.6},
            risk_decision="APPROVE",
            gate_decisions=[
                {"gate": "confidence", "decision": "PASS", "score": 0.71},
                {"gate": "risk", "decision": "PASS"},
                {"gate": "universe", "decision": "PASS"},
                {"gate": "regime", "decision": "PASS"},
                {"gate": "spread_slippage", "decision": "PASS"},
                {"gate": "quality", "decision": "PASS"},
            ],
            market_regime="NEUTRAL",
            universe_status="WHITELISTED",
            paper_action="BUY",
            shadow_action="SHADOW_SIM_FILLED",
            audit_link="shadow:2026-06-04.jsonl#AAPL",
        )
        kwargs.update(overrides)
        return self.sol.record_opportunity(**kwargs)

    def test_each_signal_creates_one_entry(self):
        for i in range(3):
            self._record_basic(signal_id=f"sig-{i:03d}")
        files = list(self.ledger_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)

    def test_accepted_signal_has_audit_link(self):
        rec = self._record_basic()
        self.assertEqual(rec["audit_link"], "shadow:2026-06-04.jsonl#AAPL")
        self.assertEqual(rec["risk_decision"], "APPROVE")
        self.assertEqual(rec["rejection_reasons"], [])
        # Six known gates → zero unknown.
        self.assertNotIn("unknown_gates", rec)

    def test_rejected_signal_has_reason(self):
        rec = self._record_basic(
            risk_decision="REJECT",
            gate_decisions=[
                {"gate": "confidence", "decision": "BLOCK", "reason": "score<0.50", "score": 0.42},
                {"gate": "risk", "decision": "PASS"},
            ],
            rejection_reasons=["pre-existing: cooldown_active"],
        )
        self.assertEqual(rec["risk_decision"], "REJECT")
        # Explicit + auto-collected reasons present.
        joined = " ".join(rec["rejection_reasons"])
        self.assertIn("cooldown_active", joined)
        self.assertIn("confidence: score<0.50", joined)

    def test_unknown_gate_is_flagged(self):
        rec = self._record_basic(
            gate_decisions=[
                {"gate": "confidence", "decision": "PASS"},
                {"gate": "very_made_up_gate", "decision": "PASS"},
            ],
        )
        self.assertIn("unknown_gates", rec)
        self.assertEqual(rec["unknown_gates"], ["very_made_up_gate"])


class TestLedgerDoesNotPlaceTrades(_BaseLedgerTest):

    def test_record_does_not_import_alpaca_orders(self):
        # Recording should NOT trigger any import of alpaca_orders or
        # broker call. Simulate this by snapshotting sys.modules before
        # and after.
        before = set(sys.modules.keys())
        self.sol.record_opportunity(
            signal_id="np-1", strategy="test", symbol="X",
            gate_decisions=[{"gate": "risk", "decision": "BLOCK"}],
            risk_decision="REJECT",
        )
        after = set(sys.modules.keys())
        added = after - before
        for mod in added:
            self.assertNotIn("alpaca_orders", mod,
                             f"Opportunity ledger pulled in {mod}; must not "
                             "import broker code.")


class TestLedgerOfflineSafe(_BaseLedgerTest):
    """The ledger must not make any network calls.

    We replace ``socket.socket.connect`` with a sentinel that raises if
    invoked. Recording an opportunity should still succeed.
    """

    def test_no_network_calls_on_record(self):
        orig_connect = socket.socket.connect

        def _blocker(*args, **kwargs):
            raise AssertionError("network call attempted from opportunity ledger")

        socket.socket.connect = _blocker  # type: ignore[assignment]
        try:
            self.sol.record_opportunity(
                signal_id="off-1",
                strategy="offline-test",
                symbol="ZZZ",
                gate_decisions=[{"gate": "quality", "decision": "PASS"}],
            )
        finally:
            socket.socket.connect = orig_connect  # type: ignore[assignment]
        # Ledger file should still be there.
        files = list(self.ledger_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[0])
        self.assertEqual(rec["symbol"], "ZZZ")


class TestSchemaShape(_BaseLedgerTest):

    def test_record_carries_required_fields(self):
        rec = self.sol.record_opportunity(
            signal_id="sh-1", strategy="schema-test", symbol="NVDA",
            raw_signal={"action": "BUY"},
            confidence_score=0.55,
            confidence_components={"data_quality": 0.7},
            risk_decision="APPROVE",
            gate_decisions=[{"gate": "confidence", "decision": "ALERT_ONLY",
                             "reason": "between 0.50 and 0.65"}],
            market_regime="RISK_ON",
            universe_status="WHITELISTED",
            paper_action="BUY",
            shadow_action="SHADOW_SIM_FILLED",
            audit_link="shadow:abc#NVDA",
        )
        for key in (
            "signal_id", "strategy", "symbol", "timestamp", "raw_signal",
            "confidence_score", "confidence_components", "risk_decision",
            "gate_decisions", "rejection_reasons", "market_regime",
            "universe_status", "paper_action", "shadow_action", "audit_link",
            "schema_version",
        ):
            self.assertIn(key, rec, f"missing required key: {key}")
        self.assertEqual(rec["schema_version"], "v3.20.0")
        # ALERT_ONLY gate counts as a rejection-style decision.
        self.assertTrue(any("confidence" in r for r in rec["rejection_reasons"]))


if __name__ == "__main__":
    unittest.main()

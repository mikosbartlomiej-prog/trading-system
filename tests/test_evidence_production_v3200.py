"""v3.20.0 (2026-06-04) — ETAP 1 unit tests for shared/evidence_production.py.

Coverage per spec:
  * SHADOW_PAPER_SIM does not reference the live broker URL.
  * SHADOW_PAPER_SIM writes a record to learning-loop/shadow_ledger/.
  * SHADOW_PAPER_SIM does not bypass the risk engine.
  * SIGNAL_ONLY does not create a trade / shadow record.
  * BROKER_PAPER hard-asserts paper URL.
  * BROKER_PAPER without credentials falls back to SHADOW_PAPER_SIM.
  * Shadow fill carries slippage + spread cost (deterministic).

All tests are offline. The ``risk_officer.evaluate_trade`` symbol is
monkey-patched so we don't hit Alpaca during unit tests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _BaseProductionTest(unittest.TestCase):
    """Common scaffolding — isolates ledger dir + clears module caches."""

    def setUp(self):
        # Fresh temp dirs per test.
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_dir = Path(self.tmp.name) / "shadow_ledger"
        self.audit_dir = Path(self.tmp.name) / "audit"

        os.environ["SHADOW_LEDGER_DIR"] = str(self.ledger_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        os.environ.pop("EVIDENCE_PRODUCTION_MODE", None)
        # Make sure no credentials leak from CI env.
        for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                  "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
            os.environ.pop(k, None)

        # Force-fresh import to pick up env vars at module top.
        for mod in list(sys.modules):
            if mod in ("evidence_production",) or mod.endswith(".evidence_production"):
                del sys.modules[mod]

        import evidence_production as ep  # noqa: WPS433 (intentional late import)
        self.ep = ep

        # Stub the risk_officer.evaluate_trade so tests don't hit Alpaca.
        # The patch lives at module-call time (inside ep._risk_evaluate).
        try:
            import risk_officer as ro
        except ImportError:
            from shared import risk_officer as ro  # type: ignore
        self._orig_evaluate = ro.evaluate_trade
        self._ro = ro

        def _fake_eval(proposal: dict) -> dict:
            decision = proposal.get("_test_decision", "APPROVE")
            return {
                "decision":      decision,
                "checks_passed": ["test"],
                "checks_failed": [] if decision == "APPROVE" else ["test_blocked"],
                "warnings":      [],
                "rationale":     f"test stub returned {decision}",
            }
        ro.evaluate_trade = _fake_eval  # type: ignore[assignment]

    def tearDown(self):
        try:
            self._ro.evaluate_trade = self._orig_evaluate  # type: ignore[assignment]
        except Exception:
            pass
        self.tmp.cleanup()
        os.environ.pop("SHADOW_LEDGER_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("EVIDENCE_PRODUCTION_MODE", None)


class TestModeResolution(_BaseProductionTest):

    def test_default_mode_is_signal_only(self):
        self.assertEqual(self.ep.get_mode(),
                         self.ep.EvidenceProductionMode.SIGNAL_ONLY)

    def test_env_overrides_mode(self):
        os.environ["EVIDENCE_PRODUCTION_MODE"] = "SHADOW_PAPER_SIM"
        self.assertEqual(self.ep.get_mode(),
                         self.ep.EvidenceProductionMode.SHADOW_PAPER_SIM)

    def test_invalid_mode_falls_back_to_signal_only(self):
        os.environ["EVIDENCE_PRODUCTION_MODE"] = "LIVE_TRADING_PLEASE"
        self.assertEqual(self.ep.get_mode(),
                         self.ep.EvidenceProductionMode.SIGNAL_ONLY)


class TestShadowFillSimulation(_BaseProductionTest):

    def test_long_fill_includes_slippage_and_spread(self):
        # 100 * (1 + 6 bps) = 100 * 1.0006 = 100.06
        fill = self.ep.estimate_shadow_fill(100.0, side="long")
        self.assertGreater(fill["fill_price"], 100.0)
        self.assertAlmostEqual(fill["slippage_bps"], 5.0)
        self.assertAlmostEqual(fill["half_spread_bps"], 1.0)
        self.assertAlmostEqual(fill["fill_price"], 100.06, places=6)
        self.assertEqual(fill["side"], "long")

    def test_short_fill_pushes_price_down(self):
        fill = self.ep.estimate_shadow_fill(200.0, side="short")
        # Short fill should be below the reference price.
        self.assertLess(fill["fill_price"], 200.0)
        self.assertEqual(fill["side"], "short")

    def test_zero_reference_price_safe(self):
        fill = self.ep.estimate_shadow_fill(0.0, side="long")
        self.assertEqual(fill["fill_price"], 0.0)
        self.assertEqual(fill["reference_price"], 0.0)


class TestSignalOnlyMode(_BaseProductionTest):

    def test_signal_only_does_not_create_trade_or_shadow_record(self):
        os.environ["EVIDENCE_PRODUCTION_MODE"] = "SIGNAL_ONLY"
        # Reload to pick up the env switch.
        for mod in list(sys.modules):
            if mod == "evidence_production" or mod.endswith(".evidence_production"):
                del sys.modules[mod]
        import evidence_production as ep
        # Reapply patch on fresh import target if used elsewhere.
        try:
            import risk_officer as ro
        except ImportError:
            from shared import risk_officer as ro  # type: ignore
        ro.evaluate_trade = lambda p: {
            "decision": "APPROVE", "checks_passed": [], "checks_failed": [],
            "warnings": [], "rationale": "ok",
        }

        signal = {
            "symbol": "AAPL", "action": "BUY", "side": "long",
            "size_usd": 10_000, "entry_price": 200.0,
            "stop_loss": 190.0, "take_profit": 220.0,
            "strategy": "test-strategy", "signal_id": "sig-001",
        }
        result = ep.produce_evidence(signal)
        self.assertEqual(result.mode, "SIGNAL_ONLY")
        self.assertTrue(result.accepted)
        self.assertIsNone(result.record)
        # No file should have been created.
        self.assertFalse(self.ledger_dir.exists()
                         or any(self.ledger_dir.glob("*.jsonl") if self.ledger_dir.exists() else []))


class TestShadowPaperSimMode(_BaseProductionTest):

    def _shadow_signal(self) -> dict:
        return {
            "symbol":      "MSFT",
            "action":      "BUY",
            "side":        "long",
            "size_usd":    8_000,
            "entry_price": 410.0,
            "stop_loss":   400.0,
            "take_profit": 430.0,
            "strategy":    "shadow-test",
            "signal_id":   "shadow-001",
            "regime":      "NEUTRAL",
        }

    def _run_shadow(self, signal: dict) -> "object":
        return self.ep.produce_evidence(
            signal,
            mode=self.ep.EvidenceProductionMode.SHADOW_PAPER_SIM,
            confidence={"total": 0.78, "components": {"data_quality": 0.9}},
        )

    def test_shadow_writes_ledger_file(self):
        result = self._run_shadow(self._shadow_signal())
        self.assertEqual(result.mode, "SHADOW_PAPER_SIM")
        self.assertIsNotNone(result.record)
        self.assertEqual(result.record["execution_source"], "SHADOW_SIM")

        # Ledger file should exist with one line.
        files = list(self.ledger_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["symbol"], "MSFT")
        self.assertEqual(rec["evidence_source"], "PAPER")
        self.assertEqual(rec["execution_source"], "SHADOW_SIM")
        self.assertEqual(rec["mode"], "SHADOW_PAPER_SIM")

    def test_shadow_fill_carries_slippage_and_spread(self):
        result = self._run_shadow(self._shadow_signal())
        rec = result.record
        self.assertGreater(rec["fill_price"], rec["reference_price"])
        self.assertEqual(rec["slippage_estimate"], 5.0)
        self.assertEqual(rec["spread_estimate"], 1.0)
        self.assertEqual(rec["fill_assumption"], "shadow_mid_plus_costs")

    def test_shadow_does_not_bypass_risk_engine(self):
        # Force REJECT through our stub: no ledger entry should appear.
        signal = self._shadow_signal()
        signal["_test_decision"] = "REJECT"
        result = self._run_shadow(signal)
        self.assertFalse(result.accepted)
        self.assertIsNone(result.record)
        files = list(self.ledger_dir.glob("*.jsonl")) if self.ledger_dir.exists() else []
        self.assertEqual(files, [])

    def test_shadow_does_not_reference_live_url(self):
        # Read the module source and verify no live URL literal appears.
        src_path = Path(self.ep.__file__)
        src = src_path.read_text(encoding="utf-8")
        # The live URL pattern that the paper_only audit grep flags.
        self.assertNotIn("https://api.alpaca.markets", src)
        self.assertNotIn("http://api.alpaca.markets", src)

        # And after producing a shadow evidence record, the record must
        # NOT carry any live URL.
        result = self._run_shadow(self._shadow_signal())
        as_json = json.dumps(result.record)
        self.assertNotIn("https://api.alpaca.markets", as_json)


class TestBrokerPaperMode(_BaseProductionTest):

    def test_broker_paper_requires_paper_url(self):
        # The module-level _broker_paper_endpoint must equal PAPER_BASE_URL.
        try:
            from autonomy import PAPER_BASE_URL
        except ImportError:
            from shared.autonomy import PAPER_BASE_URL  # type: ignore
        self.assertEqual(self.ep._broker_paper_endpoint(), PAPER_BASE_URL)
        self.assertTrue(PAPER_BASE_URL.endswith("paper-api.alpaca.markets")
                        or "paper-api.alpaca.markets" in PAPER_BASE_URL)

    def test_broker_paper_missing_creds_falls_back_to_shadow(self):
        signal = {
            "symbol": "GOOGL", "action": "BUY", "side": "long",
            "size_usd": 5_000, "entry_price": 150.0,
            "stop_loss": 145.0, "take_profit": 165.0,
            "strategy": "broker-test", "signal_id": "broker-001",
        }
        # Make sure creds are absent (already done in setUp).
        result = self.ep.produce_evidence(
            signal,
            mode=self.ep.EvidenceProductionMode.BROKER_PAPER,
        )
        self.assertEqual(result.mode, "SHADOW_PAPER_SIM")
        self.assertEqual(result.fallback_reason, "missing_paper_credentials")
        # And the ledger file exists.
        self.assertTrue(self.ledger_dir.exists())
        files = list(self.ledger_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)


class TestRiskEngineNotBypassedAcrossModes(_BaseProductionTest):

    def test_rejected_proposal_blocks_in_all_active_modes(self):
        signal = {
            "symbol": "TSLA", "action": "BUY", "side": "long",
            "size_usd": 5_000, "entry_price": 250.0,
            "stop_loss": 240.0, "take_profit": 280.0,
            "strategy": "rej-test", "signal_id": "rej-001",
            "_test_decision": "REJECT",
        }
        for mode in (self.ep.EvidenceProductionMode.SIGNAL_ONLY,
                     self.ep.EvidenceProductionMode.SHADOW_PAPER_SIM,
                     self.ep.EvidenceProductionMode.BROKER_PAPER):
            result = self.ep.produce_evidence(signal, mode=mode)
            self.assertFalse(result.accepted, f"mode={mode} should reject")
            self.assertIsNone(result.record, f"mode={mode} should not emit record")


if __name__ == "__main__":
    unittest.main()

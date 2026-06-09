"""v3.29 (2026-06-09) — canary unlock contract enum + safety tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestContractDocExists(unittest.TestCase):
    def test_doc_present(self):
        path = (REPO_ROOT / "docs"
                 / "BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md")
        self.assertTrue(path.exists())

    def test_doc_states_live_unsupported(self):
        path = (REPO_ROOT / "docs"
                 / "BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("live trading remains unsupported",
                       text.lower())

    def test_doc_lists_thresholds(self):
        path = (REPO_ROOT / "docs"
                 / "BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("50", text)  # real opportunities threshold
        self.assertIn("20", text)  # completed outcomes threshold


class TestStageEnum(unittest.TestCase):
    def test_six_stages_present(self):
        import broker_paper_canary_unlock as bp
        for tok in (
            "STAGE_0_SHADOW_ONLY",
            "STAGE_1_BROKER_PAPER_CANARY_PROPOSAL",
            "STAGE_2_BROKER_PAPER_CANARY_READY",
            "STAGE_3_BROKER_PAPER_CANARY_ENABLED",
            "STAGE_4_BROADER_PAPER_TRADING_READY",
            "STAGE_5_LIVE_UNSUPPORTED",
        ):
            self.assertIn(getattr(bp, tok), bp.ALL_STAGES)


class TestUnlockStatusEnum(unittest.TestCase):
    def test_all_status_tokens_enumerated(self):
        import broker_paper_canary_unlock as bp
        for tok in (
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT",
            "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL",
            "BROKER_PAPER_CANARY_UNLOCK_READY",
            "BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH",
            "BROKER_PAPER_CANARY_ENABLED",
            "LIVE_TRADING_UNSUPPORTED",
        ):
            self.assertIn(getattr(bp, tok), bp.ALL_UNLOCK_STATUSES)


class TestConservativeCanaryConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(
            (REPO_ROOT / "configs" / "broker_paper_canary.json")
            .read_text(encoding="utf-8"))

    def test_max_orders_per_day_is_one(self):
        self.assertEqual(self.cfg["max_orders_per_day"], 1)

    def test_max_notional_is_small(self):
        self.assertLessEqual(self.cfg["max_notional_per_order_usd"], 25)

    def test_crypto_disabled(self):
        self.assertFalse(self.cfg["crypto_enabled"])

    def test_options_disabled(self):
        self.assertFalse(self.cfg["options_enabled"])

    def test_us_equity_only(self):
        self.assertEqual(self.cfg["allowed_asset_classes"],
                          ["us_equity"])

    def test_auto_disable_flags_true(self):
        for k in (
            "auto_disable_on_first_error",
            "auto_disable_on_drawdown_guard_touch",
            "auto_disable_on_llm_quality_regression",
            "auto_disable_on_reconciliation_mismatch",
            "require_safe_order_wrapper",
            "require_audit_record",
            "require_post_trade_reconciliation",
        ):
            self.assertTrue(self.cfg[k], f"{k} must be true")

    def test_live_trading_unsupported_in_config(self):
        self.assertFalse(self.cfg["live_trading_supported"])
        self.assertFalse(self.cfg["broad_paper_trading_enabled"])

    def test_v329_safe_enable_switch_absent(self):
        self.assertFalse(
            self.cfg["canary_execution_flag_present"])


class TestEvaluatorReadOnlyMarkers(unittest.TestCase):
    def test_source_does_not_flip_broker_flags(self):
        src = (REPO_ROOT / "shared"
                / "broker_paper_canary_unlock.py").read_text(
            encoding="utf-8")
        for bad in (
            "ALLOW_BROKER_PAPER = \"true\"",
            "EDGE_GATE_ENABLED = \"true\"",
            "BROKER_EXECUTION_ENABLED = \"true\"",
            "LIVE_TRADING = \"true\"",
        ):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()

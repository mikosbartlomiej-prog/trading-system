"""v3.29 (2026-06-09) — live trading always unsupported invariant."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


# Every v3.29 file that participates in the canary path.
V329_FILES = (
    "shared/broker_paper_canary_unlock.py",
    "shared/llm_strategy_alignment.py",
    "shared/gemini_model_selector.py",
    "scripts/evaluate_broker_paper_canary_unlock.py",
    "scripts/smoke_test_gemini_provider.py",
    ".github/workflows/broker-paper-canary-unlock-evaluator.yml",
    "configs/broker_paper_canary.json",
    "docs/BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md",
)


class TestNoFileEnablesLive(unittest.TestCase):
    """No v3.29 file may serialize / contain any
    "set LIVE_*=true" or "enable live trading" pattern."""

    def test_no_live_trading_true_assignment(self):
        for rel in V329_FILES:
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for bad in (
                'LIVE_TRADING = "true"',
                "LIVE_TRADING=true",
                'LIVE_ENABLED = "true"',
                "LIVE_ENABLED=true",
                'GO_LIVE = "true"',
                "GO_LIVE=true",
                'LIVE_TRADING_ENABLED = "true"',
                "LIVE_TRADING_ENABLED=true",
            ):
                self.assertNotIn(
                    bad, text,
                    f"forbidden live-flag assignment in {rel}: {bad}")

    def test_live_trading_unsupported_in_status_enum(self):
        import broker_paper_canary_unlock as bp
        self.assertIn(bp.LIVE_TRADING_UNSUPPORTED,
                       bp.ALL_UNLOCK_STATUSES)


class TestLiveFlagTriggersRefusal(unittest.TestCase):
    def test_evaluator_returns_live_unsupported_on_any_live_flag(self):
        import broker_paper_canary_unlock as bp
        from unittest import mock
        import os
        for flag in ("LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                       "LIVE_TRADING_ENABLED"):
            with mock.patch.dict(os.environ, {flag: "true"},
                                    clear=False):
                rep = bp.evaluate_unlock_readiness()
                self.assertEqual(
                    rep.status, bp.LIVE_TRADING_UNSUPPORTED,
                    f"{flag}=true must produce LIVE_TRADING_UNSUPPORTED")


class TestCanaryConfigDeniesLive(unittest.TestCase):
    def test_config_live_trading_supported_false(self):
        import json
        cfg = json.loads(
            (REPO_ROOT / "configs" / "broker_paper_canary.json")
            .read_text(encoding="utf-8"))
        self.assertFalse(cfg["live_trading_supported"])


class TestNoBrokerExecutionImportsInCanaryPath(unittest.TestCase):
    # llm_strategy_alignment.py legitimately includes broker-order
    # function names in a BLACKLIST that detects unsafe LLM
    # suggestions; treat those as safety phrases, not forbidden
    # imports.
    _SAFETY_PHRASE_WHITELIST_FILES: frozenset[str] = frozenset({
        "shared/llm_strategy_alignment.py",
        "docs/BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md",
    })

    def test_no_broker_orders_module_in_v329_files(self):
        # When a file is on the safety-phrase whitelist, it
        # legitimately mentions broker-orders-module symbols as
        # things it explicitly DOES NOT do. Other files must be
        # token-clean.
        FORBIDDEN = (
            "alpaca_orders",
            "place_stock_bracket",
            "place_crypto_order",
            "execute_stock_signal",
            "execute_crypto_signal",
            "submit_order",
            "place_order",
            "safe_close",
        )
        for rel in V329_FILES:
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            if rel in self._SAFETY_PHRASE_WHITELIST_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            for tok in FORBIDDEN:
                self.assertNotIn(
                    tok, text,
                    f"forbidden broker token {tok!r} in {rel}")


if __name__ == "__main__":
    unittest.main()

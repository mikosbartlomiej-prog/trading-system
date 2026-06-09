"""v3.30 (2026-06-09) — canary pre-executor places NO orders, ever.

Confirms that the v3.30 canary pre-executor module and CLI runner
contain no order-placement code paths. Even with every gate set to
green, the verdict for a non-dry-run preflight is
``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED`` and no
broker call is made.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


FORBIDDEN_TOKENS = (
    "submit_order(",
    "place_order(",
    "safe_close(",
    "place_stock_order(",
    "place_crypto_order(",
    "place_option_order(",
    "mcp__claude_ai_Alpaca__place_",
    "mcp__claude_ai_Alpaca__close_",
)


class TestPreflightSourceNeverPlacesOrders(unittest.TestCase):

    def test_pre_executor_source_has_no_order_calls(self):
        src = (REPO_ROOT / "shared"
                / "broker_paper_canary_preflight.py"
               ).read_text(encoding="utf-8")
        for tok in FORBIDDEN_TOKENS:
            self.assertNotIn(tok, src,
                              f"pre-executor must NOT contain {tok!r}")
        self.assertNotIn("alpaca_orders", src,
                          "pre-executor must NOT import alpaca_orders")

    def test_cli_runner_source_has_no_order_calls(self):
        src = (REPO_ROOT / "scripts" / "run_broker_paper_canary.py"
               ).read_text(encoding="utf-8")
        for tok in FORBIDDEN_TOKENS:
            self.assertNotIn(tok, src,
                              f"CLI runner must NOT contain {tok!r}")
        self.assertNotIn("alpaca_orders", src,
                          "CLI runner must NOT import alpaca_orders")


class TestPreflightCannotAdvanceToOrderPlacement(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "configs").mkdir(parents=True, exist_ok=True)
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        (self.tmp / "configs" / "broker_paper_canary.json"
         ).write_text(real_cfg.read_text(encoding="utf-8"),
                       encoding="utf-8")
        self._patcher = mock.patch(
            "broker_paper_canary_preflight.REPO_ROOT", self.tmp)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_even_with_all_gates_green_terminal_status_is_deferred(self):
        # All gates green AND non-dry-run AND v3.30 limits valid:
        # the verdict MUST be DEFERRED.
        env = {
            "BROKER_PAPER_CANARY_EXECUTION_ENABLED": "true",
            "CANARY_DRY_RUN": "false",
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "true",
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED": "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            import broker_paper_canary_preflight as pf
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=False)
        self.assertEqual(
            rep.verdict,
            "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED",
        )

    def test_to_dict_never_says_canary_executing(self):
        with mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "false",
        }, clear=False):
            import broker_paper_canary_preflight as pf
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=True)
        d = rep.to_dict()
        # Verdict must not be any "executing" / "enabled" outcome.
        self.assertNotIn("CANARY_EXECUTING", d["verdict"])
        self.assertNotIn("CANARY_ENABLED", d["verdict"])
        # Safety panel intact.
        self.assertTrue(d["safety"]
                          ["broker_paper_canary_still_blocked"])
        self.assertTrue(d["safety"]["live_trading_unsupported"])
        self.assertTrue(d["safety"]["no_order_placement_in_v330"])


if __name__ == "__main__":
    unittest.main()

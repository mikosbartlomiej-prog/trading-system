"""v3.22.1 (2026-06-07) — Crypto-monitor halt-emit observability.

Follow-up to v3.22.0 incident response. After deploying c2ddba06,
the next crypto-monitor cron run was HALTED by daily_drawdown_guard
(-4.03% vs -3.0% v3.0 threshold). The 13 _emit_opportunity sites
shipped in v3.22.0 cover signal-evaluation paths but NOT the early
guard-halt paths — so the ledger stayed empty.

This commit adds 2 emit call sites at the drawdown-halt and VIX-halt
returns so the operator can see WHY no signals were evaluated when
a guard halt fires. The halt behavior itself is unchanged.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestHaltEmitInMonitorSource(unittest.TestCase):
    """Static-source guards — the new emit paths must be wired in."""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO_ROOT / "crypto-monitor" / "monitor.py").read_text(encoding="utf-8")

    def test_drawdown_halt_emits_opportunity(self):
        # The drawdown-halt block must include an _emit_opportunity call
        self.assertIn("HALTED_BY_DRAWDOWN_GUARD", self.src)

    def test_vix_halt_emits_opportunity(self):
        self.assertIn("HALTED_BY_VIX_GUARD", self.src)

    def test_halt_emit_uses_failsoft_helper(self):
        # Must go through _emit_opportunity (not direct ledger import)
        idx = self.src.find("HALTED_BY_DRAWDOWN_GUARD")
        self.assertGreater(idx, 0)
        # _emit_opportunity should appear before/around this marker
        nearby = self.src[max(0, idx - 400):idx + 200]
        self.assertIn("_emit_opportunity", nearby)


class TestHaltEmitWritesToLedger(unittest.TestCase):
    """Functional: calling _emit_opportunity with HALT state writes a ledger row."""

    def test_emit_writes_jsonl(self):
        # Direct invocation of the helper from monitor.py — fail-soft if
        # the module-level imports fail without credentials.
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPPORTUNITY_LEDGER_DIR"] = tmp
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "crypto_mon_halt_test",
                    str(REPO_ROOT / "crypto-monitor" / "monitor.py"),
                )
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    pass  # Module-level may fail w/o creds; we still get the helper
                self.assertTrue(callable(getattr(mod, "_emit_opportunity", None)))
                mod._emit_opportunity(
                    strategy="crypto-momentum",
                    symbol="BTC/USD",
                    signal_state="HALTED_BY_DRAWDOWN_GUARD",
                    rejection_reasons=["daily_drawdown_guard:test"],
                    paper_action="halted",
                    market_regime="RISK_OFF",
                )
                files = list(Path(tmp).glob("*.jsonl"))
                self.assertGreaterEqual(len(files), 1, "no ledger file written")
            finally:
                os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)


class TestHaltEmitDoesNotChangeTradeLogic(unittest.TestCase):
    """The halt paths must STILL early-return (no new entries) after the emit."""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO_ROOT / "crypto-monitor" / "monitor.py").read_text(encoding="utf-8")

    def test_drawdown_halt_block_returns_after_emit(self):
        # The drawdown-halt block must still contain `return` after the emit
        idx = self.src.find("HALTED_BY_DRAWDOWN_GUARD")
        self.assertGreater(idx, 0)
        # The `return` line must follow within the next 600 chars (block has
        # the loop + notify_summary + return)
        nearby = self.src[idx:idx + 800]
        self.assertIn("notify_summary", nearby)
        self.assertIn("return", nearby)

    def test_no_alpaca_orders_call_in_halt_path(self):
        # The halt path must NOT import or call place_*
        idx = self.src.find("HALTED_BY_DRAWDOWN_GUARD")
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 800]
        for forbidden in ("place_stock_bracket(", "place_crypto_order(",
                           "place_simple_buy(", "safe_close("):
            self.assertNotIn(forbidden, block,
                              f"halt path must not call {forbidden}")


if __name__ == "__main__":
    unittest.main()

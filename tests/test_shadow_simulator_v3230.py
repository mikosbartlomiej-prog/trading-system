"""v3.23 tests for shared/shadow_simulator.py.

All tests run without network, without broker, with broker/live env
flags forced false. The HARD invariants are re-checked at the AST
level so that future edits cannot smuggle a broker import in.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import shadow_simulator as ss  # noqa: E402


_CANARY_OK = "CANARY_PREFLIGHT_DRY_RUN_OK"
_CANARY_DEFER = "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED"


def _approved_signal(**over):
    base = {
        "signal_id":    "sig-001",
        "symbol":       "AAPL",
        "strategy":     "momentum-long",
        "side":         "long",
        "asset_class":  "us_equity",
        "entry_capable": True,
        "intended_price": 200.0,
        "qty":          1.0,
    }
    base.update(over)
    return base


def _flat_env():
    """Force every broker / live env flag to false (defence in depth)."""
    return {f: "false" for f in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    )}


class TestSlippageSpreadMath(unittest.TestCase):
    def test_long_pays_half_spread_and_slippage(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            slippage_bps=10,
            spread_bps=20,
            env=_flat_env(),
        )
        self.assertIsNotNone(f)
        # half-spread = 0.001 (10bp); slip = 0.001 (10bp) → 1.002 × 100
        self.assertAlmostEqual(f.fill_price, 100.0 * 1.002, places=6)
        self.assertEqual(f.fill_status, "FILLED")

    def test_short_receives_less_by_half_spread_and_slippage(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(side="short"),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            slippage_bps=10,
            spread_bps=20,
            env=_flat_env(),
        )
        self.assertIsNotNone(f)
        self.assertAlmostEqual(f.fill_price, 100.0 * 0.998, places=6)
        self.assertEqual(f.side, "short")

    def test_zero_slippage_and_spread_yields_intended_price(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 250.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            slippage_bps=0, spread_bps=0,
            env=_flat_env(),
        )
        self.assertIsNotNone(f)
        self.assertAlmostEqual(f.fill_price, 250.0, places=8)


class TestQtyCaps(unittest.TestCase):
    def test_equity_qty_cap_clamped_down_to_one(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(qty=500),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertEqual(f.qty, 1.0)

    def test_crypto_qty_cap_clamped_down(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(symbol="BTC/USD",
                              asset_class="crypto", qty=1.0),
            market_snapshot={"reference_price": 50_000.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertAlmostEqual(f.qty, 0.0001, places=8)


class TestGateRefusals(unittest.TestCase):
    def test_entry_not_capable_returns_none(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(entry_capable=False),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertIsNone(f)

    def test_risk_not_approved_returns_none(self):
        for d in ("REJECT", "DEFER", None, "BLOCK"):
            f = ss.simulate_shadow_fill(
                _approved_signal(),
                market_snapshot={"reference_price": 100.0},
                canary_preflight_verdict=_CANARY_OK,
                risk_decision=d,
                env=_flat_env(),
            )
            self.assertIsNone(f, f"risk={d}")

    def test_missing_canary_verdict_returns_none(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=None,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertIsNone(f)

    def test_refused_canary_verdict_emits_rejected_record(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=
                "CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY",
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertIsNotNone(f)
        self.assertEqual(f.fill_status, "REJECTED_BY_GATE")
        self.assertEqual(f.rejection_reason,
                         ss.REJ_REASON_CANARY_REFUSED)
        self.assertEqual(f.broker_order_submitted, False)
        self.assertEqual(f.is_paper_trade, False)

    def test_broker_flag_truthy_blocks_everything(self):
        env = _flat_env() | {"ALLOW_BROKER_PAPER": "true"}
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=env,
        )
        self.assertIsNone(f)

    def test_live_flag_truthy_blocks_everything(self):
        env = _flat_env() | {"LIVE_TRADING": "true"}
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=env,
        )
        self.assertIsNone(f)


class TestRecordContent(unittest.TestCase):
    def test_record_type_and_paper_trade_flag(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        d = f.to_dict()
        self.assertEqual(d["record_type"], "SHADOW_FILL_HYPOTHETICAL")
        self.assertFalse(d["is_paper_trade"])
        self.assertFalse(d["broker_order_submitted"])
        self.assertIn("EDGE_GATE_ENABLED=false", d["standing_markers"])
        self.assertIn("ALLOW_BROKER_PAPER=false", d["standing_markers"])
        self.assertIn("LIVE_TRADING_UNSUPPORTED", d["standing_markers"])
        self.assertIn("NO_ORDER_PLACEMENT", d["standing_markers"])
        self.assertIn("SHADOW_ONLY", d["standing_markers"])

    def test_emit_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.jsonl"
            f = ss.emit_shadow_fill(
                _approved_signal(),
                market_snapshot={"reference_price": 100.0},
                canary_preflight_verdict=_CANARY_OK,
                risk_decision="APPROVE",
                env=_flat_env(),
                ledger_path=p,
            )
            self.assertIsNotNone(f)
            self.assertTrue(p.exists())
            with open(p) as fp:
                lines = [json.loads(l) for l in fp if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["record_type"],
                             "SHADOW_FILL_HYPOTHETICAL")


class TestNoBrokerAST(unittest.TestCase):
    """Module-level AST guard: shadow_simulator must not import any
    broker module."""

    def test_no_alpaca_orders_import_in_module(self):
        path = REPO_ROOT / "shared" / "shadow_simulator.py"
        tree = ast.parse(path.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module)
        for n in names:
            self.assertFalse(
                "alpaca_orders" in n,
                f"forbidden import: {n}")
            self.assertFalse(
                n.startswith("requests"),
                f"forbidden network import: {n}")
            self.assertFalse(
                n.startswith("urllib3"),
                f"forbidden network import: {n}")
            self.assertFalse(
                n.startswith("httpx"),
                f"forbidden network import: {n}")

    def test_no_forbidden_call_names_in_source(self):
        path = REPO_ROOT / "shared" / "shadow_simulator.py"
        src = path.read_text()
        for forbidden in (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(",
            "close_all_positions(", "place_stock_bracket(",
        ):
            self.assertNotIn(forbidden, src,
                             f"forbidden symbol in source: {forbidden}")

    def test_paper_url_marker_present_no_live_url(self):
        path = REPO_ROOT / "shared" / "shadow_simulator.py"
        src = path.read_text()
        self.assertIn("paper-api.alpaca.markets", src)
        self.assertNotIn("api.alpaca.markets/v2", src)


if __name__ == "__main__":
    unittest.main()

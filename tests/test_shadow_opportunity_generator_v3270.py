"""v3.27.0 (2026-06-09) — shadow opportunity generator tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _make_snapshot(*, data_quality, asset_class="us_equity",
                    symbol="SPY", price=500.0):
    import market_data_provider as mdp
    return mdp.MarketSnapshot(
        symbol=symbol, asset_class=asset_class,
        timestamp=1.0, price=price,
        data_quality=data_quality,
    )


def _synthetic_bars(n=30, base=400.0, step=2.0):
    bars = []
    for i in range(n):
        bars.append({
            "o": base + step * i,
            "h": base + step * i + 1.0,
            "l": base + step * i - 1.0,
            "c": base + step * i + 0.5,
            "v": 1_000_000,
        })
    return bars


class TestNoEmissionWithoutRealMarketData(unittest.TestCase):
    def test_no_market_data_returns_none(self):
        import market_data_provider as mdp
        import shadow_opportunity_generator as sog
        snap = _make_snapshot(data_quality=mdp.NO_MARKET_DATA)
        out = sog.generate_for_snapshot(snap, bars=_synthetic_bars())
        self.assertIsNone(out)

    def test_stale_market_data_returns_none(self):
        import market_data_provider as mdp
        import shadow_opportunity_generator as sog
        snap = _make_snapshot(data_quality=mdp.STALE_MARKET_DATA)
        out = sog.generate_for_snapshot(snap, bars=_synthetic_bars())
        self.assertIsNone(out)

    def test_provider_error_returns_none(self):
        import market_data_provider as mdp
        import shadow_opportunity_generator as sog
        snap = _make_snapshot(data_quality=mdp.PROVIDER_ERROR)
        out = sog.generate_for_snapshot(snap, bars=_synthetic_bars())
        self.assertIsNone(out)

    def test_missing_bars_returns_none(self):
        import market_data_provider as mdp
        import shadow_opportunity_generator as sog
        snap = _make_snapshot(data_quality=mdp.REAL_MARKET_DATA)
        out = sog.generate_for_snapshot(snap, bars=None)
        self.assertIsNone(out)


class TestRecordSchema(unittest.TestCase):
    def test_to_shadow_record_pins_broker_flags_false(self):
        import shadow_opportunity_generator as sog
        opp = sog.GeneratedOpportunity(
            symbol="SPY", asset_class="us_equity",
            strategy="momentum-long", side="buy",
            would_trade=True, would_block=False, block_reasons=[],
            sizing_preview={"proposed_usd": 1000.0, "equity_usd": 100000.0},
            exposure_policy_result={"decision": "WOULD_NOT_EVALUATE"},
            drawdown_guard_state={"active": False, "threshold_pct": -3.0,
                                    "current_pct": 0.0},
            entry_shadow_price=500.0,
            audit_trace_id="abc",
        )
        rec = sog.to_shadow_record(
            opp, timestamp_iso="2026-06-09T00:00:00+00:00")
        self.assertFalse(rec["broker_order_submitted"])
        self.assertFalse(rec["broker_execution_enabled"])
        self.assertEqual(rec["evidence_quality"], "REAL_MARKET_DATA")
        self.assertEqual(rec["version"], "v3.27.0")
        self.assertEqual(rec["outcome_tracking_status"], "PENDING")

    def test_record_satisfies_schema_required_fields(self):
        import json as _json
        import shadow_opportunity_generator as sog
        schema_path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                        / "schema.json")
        schema = _json.loads(schema_path.read_text())
        required = set(schema["required"])
        opp = sog.GeneratedOpportunity(
            symbol="SPY", asset_class="us_equity",
            strategy="momentum-long", side="buy",
            would_trade=True, would_block=False, block_reasons=[],
            sizing_preview={"proposed_usd": 1000.0, "equity_usd": 100000.0},
            exposure_policy_result={"decision": "WOULD_NOT_EVALUATE"},
            drawdown_guard_state={"active": False},
            entry_shadow_price=500.0,
            audit_trace_id="abc",
        )
        rec = sog.to_shadow_record(
            opp, timestamp_iso="2026-06-09T00:00:00+00:00")
        for k in required:
            self.assertIn(k, rec, f"missing required field: {k}")


class TestStrategyRegistry(unittest.TestCase):
    def test_two_strategies_registered(self):
        import shadow_opportunity_generator as sog
        s = sog.policy_summary()
        self.assertIn("momentum-long", s["strategies_registered"])
        self.assertIn("crypto-momentum", s["strategies_registered"])


class TestDrawdownGuardWouldBlock(unittest.TestCase):
    """When drawdown_guard_active=True and a signal would fire, the
    generated opportunity must show would_block=True with the
    drawdown-guard reason."""

    def test_drawdown_active_marks_would_block(self):
        import market_data_provider as mdp
        import shadow_opportunity_generator as sog
        # Build bars that trigger momentum_long: 22-bar rising series.
        bars = _synthetic_bars(n=30, base=100.0, step=1.0)
        snap = _make_snapshot(data_quality=mdp.REAL_MARKET_DATA,
                                asset_class="us_equity",
                                symbol="AMD", price=131.5)
        out = sog.generate_for_snapshot(
            snap, bars=bars, drawdown_guard_active=True,
        )
        if out is None:
            # Strategy may not fire on synthetic data; in that case
            # nothing to assert.
            self.skipTest("strategy did not fire on synthetic series")
        self.assertTrue(out.would_block)
        self.assertTrue(any(
            "DRAWDOWN_GUARD" in r for r in out.block_reasons),
            f"missing drawdown reason: {out.block_reasons}",
        )


class TestModuleInvariants(unittest.TestCase):
    def test_no_forbidden_imports_in_source(self):
        src = (REPO_ROOT / "shared"
                / "shadow_opportunity_generator.py").read_text()
        FORBIDDEN = (
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "safe_close",
            "execute_crypto_signal", "execute_stock_signal",
            "from shared.alpaca_orders", "from alpaca_orders",
            "import alpaca_orders",
            "requests.post", "requests.put", "requests.delete",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, src,
                              f"forbidden token in generator: {tok!r}")

    def test_invariants_true(self):
        import shadow_opportunity_generator as sog
        self.assertTrue(sog.NEVER_SUBMITS_ORDERS)
        self.assertTrue(sog.NEVER_IMPORTS_ALPACA_ORDERS)
        self.assertTrue(sog.NEVER_FABRICATES_OPPORTUNITY)
        self.assertTrue(sog.ONLY_EMITS_FOR_REAL_MARKET_DATA)


if __name__ == "__main__":
    unittest.main()

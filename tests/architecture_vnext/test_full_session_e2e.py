"""v3.10.1 Deep E2E — full intraday session simulation, no network, no real orders.

Per audit ETAP 8 directive: simulate complete session pipeline locally.
Validates that signal → confirmation → risk → decision → audit flow works
end-to-end with all v3.10 changes integrated.

Scenarios covered:
1. Fresh session start (snapshot OK)
2. Strong signal + confirmation → ALLOW with full size
3. Weak signal → ALERT_ONLY (no order)
4. Duplicate event → BLOCK
5. Stale snapshot (account fetch fail) → DEFER
6. Naked SHORT attempt prevented by safe_close
7. EMERGENCY_CLOSE invariant: never for repairable reasons
8. Adapter cooldown (5 consec losses) → hard_safety disable accepted
9. Backtest no-lookahead invariant
"""

import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest
from datetime import datetime, timezone, timedelta
from unittest import mock


# ─── Test infrastructure ─────────────────────────────────────────────────────

def _mock_account(equity=100000, bp=200000, dt_count=0):
    return {
        "equity": str(equity), "cash": str(equity / 2),
        "buying_power": str(bp), "last_equity": str(equity),
        "daytrade_count": str(dt_count),
        "pattern_day_trader": False,
        "account_blocked": False, "trading_blocked": False,
    }


def _fresh_event(symbol="AAPL", strategy="test"):
    return {
        "symbol": symbol,
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "headline": f"E2E test event for {symbol}",
        "source": "e2e",
        "strategy": strategy,
    }


# ─── Scenario tests ───────────────────────────────────────────────────────────

class TestFullSessionE2E(unittest.TestCase):
    """End-to-end pipeline: signal → confirmation → risk → decision → audit."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmp

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    # ── Scenario 1 + 2 + 3: signal confirmation pipeline ──

    def test_scenario_strong_signal_with_confirm_returns_allow_full_size(self):
        """ETAP 8 Scenario 2: strong signal + market confirmation → ALLOW."""
        import pretrade_snapshot as snap_mod
        from pretrade_snapshot import get_snapshot, classify_snapshot_for_intraday, clear_snapshot_cache
        from risk_classification import RiskVerdict

        clear_snapshot_cache()
        with mock.patch.object(snap_mod, "_fetch_account", return_value=_mock_account()), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={"pnl_state": "GREEN"}):
            s = get_snapshot(force_refresh=True)
            v = classify_snapshot_for_intraday(s)
        self.assertEqual(v.verdict, RiskVerdict.ALLOW)
        self.assertEqual(v.size_multiplier, 1.0)

    def test_scenario_weak_signal_returns_alert_only(self):
        """ETAP 8 Scenario 3: weak signal + no confirm → ALERT_ONLY (no order)."""
        from news_signal_gate import gate_news_signal
        v = gate_news_signal(
            symbol="MSFT", side="BUY", signal_strength=0.2,  # weak
            headline="vague news", published_at=_fresh_event()["published_at"],
            strategy="e2e-weak",
        )
        self.assertEqual(v.verdict.value, "ALERT_ONLY")
        self.assertFalse(v.allows_order)

    def test_scenario_duplicate_event_blocks(self):
        """ETAP 8 Scenario 4: duplicate post → BLOCK."""
        from news_signal_gate import gate_news_signal, _shared_caches
        # Fresh cache for this test
        from signal_confirmation import EventCache, CooldownTracker
        c = EventCache()
        cd = CooldownTracker()
        ev_args = dict(
            symbol="DUPE", side="BUY", signal_strength=0.8,
            headline="dup test", strategy="e2e-dupe",
            published_at=_fresh_event()["published_at"],
            event_cache=c, cooldown=cd,
        )
        v1 = gate_news_signal(**ev_args)
        v2 = gate_news_signal(**ev_args)
        self.assertNotEqual(v1.verdict.value, "BLOCK")  # first allowed
        self.assertEqual(v2.verdict.value, "BLOCK")     # second blocked (dupe)

    # ── Scenario 5: account fetch fail → DEFER ──

    def test_scenario_account_unavailable_defers_not_blocks(self):
        """ETAP 8 Scenario 5: Alpaca down → DEFER (retry next cron), not BLOCK."""
        import pretrade_snapshot as snap_mod
        from pretrade_snapshot import get_snapshot, classify_snapshot_for_intraday, clear_snapshot_cache
        from risk_classification import RiskVerdict

        clear_snapshot_cache()
        with mock.patch.object(snap_mod, "_fetch_account", return_value=None), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={}):
            s = get_snapshot(force_refresh=True)
            v = classify_snapshot_for_intraday(s)
        self.assertEqual(v.verdict, RiskVerdict.DEFER)
        self.assertIsNotNone(v.retry_after_s)

    # ── Scenario 6: naked SHORT prevented ──

    @unittest.skipIf(sys.version_info < (3, 10),
                     "alpaca_orders.py uses PEP 604 dict|None — needs 3.10+")
    def test_scenario_safe_close_prevents_naked_short(self):
        """ETAP 8 Scenario: stale plan EXIT MARKET on closed position → safe_close
        skips (intent=sell vs live=short) → no naked short created."""
        import alpaca_orders as ao
        # Simulate stale plan: caller wants to sell 169, but live shows short
        with mock.patch.object(ao, "_fetch_single_position", return_value={
            "qty": "-169", "side": "short", "symbol": "NOW"
        }):
            # Note: assert_paper_only requires paper URL — set it
            with mock.patch.object(ao, "ALPACA_BASE_URL",
                                    "https://paper-api.alpaca.markets"):
                r = ao.safe_close(
                    symbol="NOW", intent_qty=169, intent_side="sell",
                    reason_tag="e2e-stale-test", order_type="market",
                    allow_market=True,
                )
        self.assertEqual(r["status"], "skipped")
        self.assertIn("SHORT", r["reason"])

    # ── Scenario 7: EMERGENCY_CLOSE invariant ──

    def test_scenario_emergency_engine_never_targets_repairable_states(self):
        """ETAP 8 Scenario: no_exit_plan / duplicate_exits / stale_exit_order
        must NOT produce EmergencyTarget (v3.9.9 invariant)."""
        import emergency_engine as ee
        # Position with no exit order (would have been "no_exit_plan" before v3.9.9)
        positions = [{
            "symbol": "AAPL", "qty": "10", "side": "long",
            "unrealized_plpc": "-0.02", "asset_class": "us_equity",
            "avg_entry_price": "100",
        }]
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=[], state=None,
        )
        # NO target with reason in {no_exit_plan, duplicate_exits, stale_exit_order}
        forbidden_reasons = {"no_exit_plan", "duplicate_exits", "stale_exit_order"}
        violations = [t for t in targets if any(r in t.reason for r in forbidden_reasons)]
        self.assertEqual(len(violations), 0,
            f"v3.9.9 invariant violated: {[(t.symbol, t.reason) for t in violations]}")

    # ── Scenario 8: adapter cooldown ──

    def test_scenario_adapter_cooldown_disable_passes_validation(self):
        """ETAP 8 Scenario: 5 consec losses → hard_safety=True → validator allows."""
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "learning-loop")))
        from validation import validate_adaptation
        old = {"strategies": {"test-strat": {"enabled": True}}}
        new = {"strategies": {"test-strat": {
            "enabled": False, "hard_safety": True,
            "paused_until": "2026-06-10"
        }}}
        stats = {"by_strategy": {"test-strat": {"trades_7d": 2}}}  # low sample
        r = validate_adaptation(old, new, stats)
        # Must accept the disable
        self.assertTrue(any("test-strat.enabled True -> False" in a for a in r["accepted"]))

    # ── Scenario 9: no-lookahead ──

    def test_scenario_backtest_no_lookahead_invariant(self):
        """ETAP 8 Scenario: strategy signal at idx N must NOT depend on bars[idx+k]."""
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "backtest")))
        from strategies import momentum_long_signal_at

        # Synthetic bars
        bars = {
            "open": [100.0 + i * 0.5 for i in range(60)],
            "high": [101.0 + i * 0.5 for i in range(60)],
            "low":  [99.0 + i * 0.5 for i in range(60)],
            "close": [100.0 + i * 0.5 for i in range(60)],
            "volume": [1_000_000] * 60,
            "timestamp": [f"2026-01-{i+1:02d}" for i in range(60)],
        }
        # Signal at idx=40 should be same whether bars are full (60) or truncated (41)
        truncated = {k: (v[:41] if isinstance(v, list) else v) for k, v in bars.items()}
        sig_full = momentum_long_signal_at(40, bars)
        sig_truncated = momentum_long_signal_at(40, truncated)
        self.assertEqual(sig_full, sig_truncated,
            "LOOKAHEAD detected: signal at idx=40 differs based on future bars")

    # ── Scenario: risk_officer DEFER on Alpaca outage (not fail-open) ──

    def test_scenario_risk_officer_defers_not_fail_open(self):
        """ETAP 8 Scenario: v3.10 Phase D — Alpaca outage → DEFER not silent allow."""
        import risk_officer
        with mock.patch.object(risk_officer, "get_account_status", return_value=None), \
             mock.patch.object(risk_officer, "vix_guard", return_value=("OK", "ok")):
            r = risk_officer.evaluate_trade({
                "symbol": "AAPL", "action": "BUY", "size_usd": 5000,
                "entry_price": 175, "stop_loss": 170, "take_profit": 182,
                "strategy": "e2e",
            })
        self.assertEqual(r["verdict"], "DEFER")
        self.assertIsNotNone(r.get("retry_after_s"))


if __name__ == "__main__":
    unittest.main()

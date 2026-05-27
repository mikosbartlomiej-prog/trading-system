"""v3.11 Phase A — edge_validator tests."""

import os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

# Need learning-loop on path
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "learning-loop")))

import unittest
from pathlib import Path
from unittest import mock

import edge_validator as ev


def _make_trades(n_winning, n_losing, avg_win=200.0, avg_loss=-50.0):
    """Build trades with realistic drawdown shape:
    establish meaningful peak first (run of wins), then interleave.
    Avoids ~80%+ synthetic DD from a single early loss vs tiny peak."""
    out = []
    # Build initial run of wins (up to 3) to establish peak
    initial_wins = min(3, n_winning)
    for _ in range(initial_wins):
        out.append({"pnl_usd": avg_win, "pnl_pct": 5.0, "winner": True})
    nw = n_winning - initial_wins
    nl = n_losing
    # Then interleave
    while nw + nl > 0:
        if nw > 0:
            out.append({"pnl_usd": avg_win, "pnl_pct": 5.0, "winner": True})
            nw -= 1
        if nl > 0:
            out.append({"pnl_usd": avg_loss, "pnl_pct": -4.0, "winner": False})
            nl -= 1
    return out


def _write_backtest_result(tmp_dir, strategy, trades, age_days=1):
    p = Path(tmp_dir) / f"{strategy}-20260527-0000.json"
    data = {
        "strategy": strategy,
        "mode": "both",
        "all_trades_realistic": trades,
    }
    p.write_text(json.dumps(data))
    # Set mtime to be `age_days` old
    import time
    target_mtime = time.time() - (age_days * 86400)
    os.utime(p, (target_mtime, target_mtime))
    return p


class TestEdgeValidator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Redirect BACKTEST_RESULTS to tmp dir
        self._orig = ev._BACKTEST_RESULTS
        ev._BACKTEST_RESULTS = Path(self.tmp)
        # v3.11 default is DISABLED=true; for tests, force enabled (false)
        os.environ["EDGE_GATE_DISABLED"] = "false"

    def tearDown(self):
        ev._BACKTEST_RESULTS = self._orig
        os.environ.pop("EDGE_GATE_DISABLED", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_operational_tag_always_passes(self):
        ok, _, reason = ev.validate_strategy_edge("alloc-exit")
        self.assertTrue(ok)
        self.assertIn("operational", reason)

    def test_no_backtest_blocks(self):
        ok, _, reason = ev.validate_strategy_edge("momentum-long")
        self.assertFalse(ok)
        self.assertIn("no backtest", reason)

    def test_passing_edge_returns_ok(self):
        # 7 wins / 3 losses = 70% WR, profit factor (7*100)/(3*80)=2.92, MDD low
        trades = _make_trades(n_winning=7, n_losing=3)
        _write_backtest_result(self.tmp, "momentum-long", trades, age_days=5)
        ok, metrics, reason = ev.validate_strategy_edge("momentum-long")
        self.assertTrue(ok, f"expected PASS but got: {reason}, metrics={metrics}")
        self.assertGreater(metrics["win_rate"], 0.5)

    def test_failing_win_rate_blocks(self):
        # 3 wins / 7 losses = 30% WR
        trades = _make_trades(n_winning=3, n_losing=7)
        _write_backtest_result(self.tmp, "overbought-short", trades, age_days=5)
        ok, metrics, reason = ev.validate_strategy_edge("overbought-short")
        self.assertFalse(ok)
        self.assertIn("WR", reason)

    def test_stale_backtest_blocks(self):
        trades = _make_trades(n_winning=7, n_losing=3)
        _write_backtest_result(self.tmp, "stale-strat", trades, age_days=60)
        ok, _, reason = ev.validate_strategy_edge("stale-strat")
        self.assertFalse(ok)
        self.assertIn("stale", reason)

    def test_low_profit_factor_blocks(self):
        # 5 wins / 5 losses, but avg loss ($150) > avg win ($100) → PF < 1
        trades = ([{"pnl_usd": 100.0, "pnl_pct": 2.0, "winner": True} for _ in range(5)]
                  + [{"pnl_usd": -150.0, "pnl_pct": -3.0, "winner": False} for _ in range(5)])
        _write_backtest_result(self.tmp, "weak-pf", trades, age_days=5)
        ok, _, reason = ev.validate_strategy_edge("weak-pf")
        self.assertFalse(ok)
        self.assertTrue("PF" in reason or "profit_factor" in reason.lower())

    def test_insufficient_sample_blocks(self):
        # Only 5 trades, below MIN_TRADES=10
        trades = _make_trades(n_winning=4, n_losing=1)
        _write_backtest_result(self.tmp, "tiny-sample", trades, age_days=5)
        ok, _, reason = ev.validate_strategy_edge("tiny-sample")
        self.assertFalse(ok)
        self.assertIn("sample", reason.lower())

    def test_env_override_bypasses_gate(self):
        os.environ["EDGE_GATE_DISABLED"] = "true"
        try:
            ok, _, reason = ev.validate_strategy_edge("anything")
            self.assertTrue(ok)
            self.assertIn("override", reason.lower())
        finally:
            os.environ.pop("EDGE_GATE_DISABLED", None)

    def test_enforce_on_state_disables_failing_strategies(self):
        # Setup: 2 strategies — one passes, one fails
        trades_pass = _make_trades(n_winning=7, n_losing=3)
        trades_fail = _make_trades(n_winning=3, n_losing=7)
        _write_backtest_result(self.tmp, "good-strat", trades_pass, age_days=5)
        _write_backtest_result(self.tmp, "bad-strat", trades_fail, age_days=5)

        state = {
            "strategies": {
                "good-strat": {"enabled": True, "size_multiplier": 1.0},
                "bad-strat":  {"enabled": True, "size_multiplier": 1.0},
                "alloc-exit": {"enabled": True, "size_multiplier": 1.0},  # operational, exempt
            }
        }
        new_state, log = ev.enforce_edge_gate_on_state(state)
        self.assertTrue(new_state["strategies"]["good-strat"]["enabled"])
        self.assertFalse(new_state["strategies"]["bad-strat"]["enabled"])
        # Operational tag untouched
        self.assertTrue(new_state["strategies"]["alloc-exit"]["enabled"])
        # Log contains both
        log_str = " ".join(log)
        self.assertIn("good-strat PASS", log_str)
        self.assertIn("bad-strat", log_str)

    def test_per_strategy_override_skips_gate(self):
        state = {
            "strategies": {
                "experimental": {"enabled": True, "edge_gate_override": True},
            }
        }
        new_state, log = ev.enforce_edge_gate_on_state(state)
        # Should NOT disable (override)
        self.assertTrue(new_state["strategies"]["experimental"]["enabled"])
        self.assertTrue(any("override" in l for l in log))


if __name__ == "__main__":
    unittest.main()

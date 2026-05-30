"""v3.12.0 (2026-05-30) — tests for the autonomy-completion modules:

  * shared/confidence.py
  * shared/safe_mode.py
  * shared/heartbeat.py
  * shared/risk_officer.py wire-in

Audit context (ETAP 6/7/8 of full repo audit):
The system had risk gates everywhere but no single deterministic
confidence score per decision; no explicit safe_mode (different from
defensive_mode); no component heartbeat. These tests pin down the
contracts so future refactors don't regress them.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def setUpModule():
    """Isolate runtime_state writes during these tests so we don't
    pollute the production learning-loop/runtime_state.json."""
    global _TMP_RS, _ORIGINAL_RS
    _TMP_RS = tempfile.mkdtemp(prefix="rs_v3120_")
    # Patch runtime_state path via env
    os.environ["RUNTIME_STATE_DIR"] = _TMP_RS
    os.environ["AUDIT_TRADING_DIR"] = _TMP_RS  # also isolate audit emissions
    # also allow our test actor
    os.environ.setdefault("STATE_WRITE_ACTOR", "test")


def tearDownModule():
    import shutil
    os.environ.pop("RUNTIME_STATE_DIR", None)
    os.environ.pop("AUDIT_TRADING_DIR", None)
    try:
        shutil.rmtree(_TMP_RS)
    except Exception:
        pass


# ─── confidence.py ───────────────────────────────────────────────────────────


class TestConfidenceComponents(unittest.TestCase):

    def test_data_quality_fresh_tight_sufficient(self):
        from confidence import score_data_quality
        s = score_data_quality(bar_age_seconds=30, quote_spread_pct=0.04, bars_count=50, min_bars=20)
        self.assertAlmostEqual(s, 1.0)

    def test_data_quality_stale_wide_insufficient(self):
        from confidence import score_data_quality
        s = score_data_quality(bar_age_seconds=1200, quote_spread_pct=0.8, bars_count=5, min_bars=20)
        # 0.2 + 0.2 + 0.2 → 0.2
        self.assertAlmostEqual(s, 0.2)

    def test_data_quality_no_inputs_returns_neutral(self):
        from confidence import score_data_quality, NEUTRAL_COMPONENT
        self.assertEqual(score_data_quality(), NEUTRAL_COMPONENT)

    def test_signal_strength_strong_with_confirmations(self):
        from confidence import score_signal_strength
        s = score_signal_strength(primary_score=0.75, confirmations=3, max_confirmations=3)
        self.assertAlmostEqual(s, 1.0)

    def test_signal_strength_weak_zero_confirms(self):
        from confidence import score_signal_strength
        s = score_signal_strength(primary_score=0.1, confirmations=0, max_confirmations=3)
        # max(0.2, 0.1/0.5)=0.2  + 0.0 → 0.10
        self.assertAlmostEqual(s, 0.1)

    def test_regime_alignment_matrix(self):
        from confidence import score_regime_alignment
        # momentum-long in RISK_ON → 1.0
        self.assertEqual(score_regime_alignment(regime="RISK_ON", strategy="momentum-long"), 1.0)
        # momentum-long in RISK_OFF → 0.3
        self.assertEqual(score_regime_alignment(regime="RISK_OFF", strategy="momentum-long"), 0.3)
        # geo-gold in INFLATION_SHOCK → 1.0
        self.assertEqual(score_regime_alignment(regime="INFLATION_SHOCK", strategy="geo-gold"), 1.0)
        # short in RISK_ON → 0.2
        self.assertEqual(score_regime_alignment(regime="RISK_ON", strategy="overbought-short"), 0.2)
        # unknown strategy → neutral
        self.assertEqual(score_regime_alignment(regime="RISK_ON", strategy="???"), 0.5)

    def test_system_health_full(self):
        from confidence import score_system_health
        s = score_system_health(components_alive=11, components_total=11,
                                  recent_errors=0, audit_gap_seconds=60)
        self.assertAlmostEqual(s, 1.0)

    def test_system_health_degraded(self):
        from confidence import score_system_health
        s = score_system_health(components_alive=6, components_total=11,
                                  recent_errors=4, audit_gap_seconds=2000)
        # 0.545 + 0.4 + 0.4 = 1.345 / 3 ≈ 0.448
        self.assertLess(s, 0.6)
        self.assertGreater(s, 0.3)

    def test_risk_state_clean(self):
        from confidence import score_risk_state
        s = score_risk_state(intraday_pnl_pct=0.5, giveback_pct_of_peak=0.05,
                              consecutive_losses=0, drawdown_pct=0)
        self.assertEqual(s, 1.0)

    def test_risk_state_concerning(self):
        from confidence import score_risk_state
        s = score_risk_state(intraday_pnl_pct=-2.5, giveback_pct_of_peak=0.45,
                              consecutive_losses=3, drawdown_pct=-5)
        # 0.4 + 0.3 + 0.3 + 0.3 = 0.325
        self.assertLess(s, 0.4)


class TestComputeConfidence(unittest.TestCase):

    def test_high_confidence_allows(self):
        from confidence import compute_confidence
        r = compute_confidence(
            primary_score=0.7, regime="RISK_ON", strategy="momentum-long",
            bar_age_seconds=30, quote_spread_pct=0.05, bars_count=50,
            components_alive=11, components_total=11, recent_errors=0, audit_gap_seconds=60,
            intraday_pnl_pct=0.5, giveback_pct_of_peak=0.0, consecutive_losses=0, drawdown_pct=0,
        )
        self.assertEqual(r.decision, "ALLOW")
        self.assertGreater(r.total, 0.9)

    def test_low_confidence_blocks(self):
        from confidence import compute_confidence
        r = compute_confidence(
            primary_score=0.1, regime="RISK_OFF", strategy="momentum-long",
            bar_age_seconds=1200, quote_spread_pct=0.6, bars_count=8,
            components_alive=4, components_total=11, recent_errors=8, audit_gap_seconds=4000,
            intraday_pnl_pct=-4, giveback_pct_of_peak=0.6, consecutive_losses=6, drawdown_pct=-9,
        )
        self.assertEqual(r.decision, "BLOCK")
        self.assertLess(r.total, 0.3)

    def test_mid_confidence_alert_only(self):
        from confidence import compute_confidence
        r = compute_confidence(
            primary_score=0.4, regime="NEUTRAL", strategy="momentum-long",
            bar_age_seconds=200, quote_spread_pct=0.15, bars_count=20,
            components_alive=9, components_total=11, recent_errors=1, audit_gap_seconds=400,
            intraday_pnl_pct=-0.5, consecutive_losses=1,
        )
        self.assertIn(r.decision, ("ALLOW", "ALERT_ONLY"))

    def test_no_inputs_returns_neutral_block(self):
        from confidence import compute_confidence
        # All None → each component 0.5 → total 0.5 → ALERT_ONLY (= threshold)
        r = compute_confidence()
        self.assertAlmostEqual(r.total, 0.5, places=2)
        self.assertEqual(r.decision, "ALERT_ONLY")

    def test_report_serializable(self):
        from confidence import compute_confidence
        r = compute_confidence(primary_score=0.5, regime="RISK_ON", strategy="momentum-long")
        d = r.to_dict()
        self.assertIn("total", d)
        self.assertIn("components", d)
        self.assertIn("weights", d)
        self.assertIn("decision", d)

    def test_weights_normalize_to_one(self):
        from confidence import compute_confidence
        r = compute_confidence(primary_score=0.5)
        self.assertAlmostEqual(sum(r.weights.values()), 1.0, places=4)


# ─── safe_mode.py ────────────────────────────────────────────────────────────


class TestSafeMode(unittest.TestCase):

    def setUp(self):
        # Always start each test from inactive state
        import safe_mode
        try:
            safe_mode.exit_safe_mode(actor="test")
        except Exception:
            pass

    def test_inactive_by_default(self):
        from safe_mode import read_state
        s = read_state()
        self.assertFalse(s.active)

    def test_gate_allows_when_inactive(self):
        from safe_mode import gate_new_entry, SafeModeState
        ok, reason = gate_new_entry(current_state=SafeModeState.inactive())
        self.assertTrue(ok)
        self.assertIn("inactive", reason.lower())

    def test_gate_blocks_when_active(self):
        from safe_mode import gate_new_entry, SafeModeState
        active = SafeModeState(active=True, reason="audit gap", entered_at="ts",
                                 trigger="AUDIT_GAP")
        ok, reason = gate_new_entry(current_state=active)
        self.assertFalse(ok)
        self.assertIn("safe_mode ACTIVE", reason)

    def test_size_multiplier_halves_when_active(self):
        from safe_mode import size_multiplier, SafeModeState
        active = SafeModeState(active=True, reason="x", entered_at="ts", trigger="STALE_DATA")
        self.assertEqual(size_multiplier(current_state=active), 0.5)
        inactive = SafeModeState.inactive()
        self.assertEqual(size_multiplier(current_state=inactive), 1.0)

    def test_evaluate_triggers_account_outage(self):
        from safe_mode import evaluate_triggers
        active, trigger, _ = evaluate_triggers(account_fetch_failures=3)
        self.assertTrue(active)
        self.assertEqual(trigger, "ACCOUNT_OUTAGE")

    def test_evaluate_triggers_audit_gap_only_during_market(self):
        from safe_mode import evaluate_triggers
        # Outside market hours → no AUDIT_GAP trigger
        active_off, _, _ = evaluate_triggers(audit_gap_seconds=5000, is_market_hours=False)
        self.assertFalse(active_off)
        # During market hours + >1h gap → trigger
        active_on, trigger, _ = evaluate_triggers(audit_gap_seconds=5000, is_market_hours=True)
        self.assertTrue(active_on)
        self.assertEqual(trigger, "AUDIT_GAP")

    def test_evaluate_triggers_stale_data(self):
        from safe_mode import evaluate_triggers
        active, trigger, _ = evaluate_triggers(max_bar_age_seconds=1200)
        self.assertTrue(active)
        self.assertEqual(trigger, "STALE_DATA")

    def test_evaluate_triggers_clean(self):
        from safe_mode import evaluate_triggers
        active, trigger, _ = evaluate_triggers(
            account_fetch_failures=0, audit_gap_seconds=100,
            max_bar_age_seconds=60, confidence_broken_ticks=0,
        )
        self.assertFalse(active)
        self.assertIsNone(trigger)


# ─── heartbeat.py ────────────────────────────────────────────────────────────


class TestHeartbeat(unittest.TestCase):

    def test_ping_records_entry(self):
        from heartbeat import ping, read, stale
        ping("test-monitor", status="ok", message="smoke test", actor="test")
        data = read()
        self.assertIn("test-monitor", data)
        self.assertEqual(data["test-monitor"]["last_status"], "ok")
        # Within fresh window → not stale
        self.assertFalse(stale("test-monitor", max_age_seconds=600))

    def test_never_pinged_is_stale(self):
        from heartbeat import stale
        self.assertTrue(stale("never-pinged-monitor"))

    def test_alive_count_returns_tuple(self):
        from heartbeat import alive_count, ping
        ping("comp-a", actor="test")
        ping("comp-b", actor="test")
        alive, total = alive_count(components=("comp-a", "comp-b", "never-seen"))
        self.assertEqual(total, 3)
        self.assertGreaterEqual(alive, 2)

    def test_health_snapshot_shape(self):
        from heartbeat import health_snapshot
        snap = health_snapshot()
        self.assertIn("alive", snap)
        self.assertIn("total", snap)
        self.assertIn("ratio", snap)
        self.assertIn("stale_components", snap)


# ─── risk_officer wire-in ────────────────────────────────────────────────────


class TestRiskOfficerConfidenceWire(unittest.TestCase):
    """Verify risk_officer.evaluate_trade respects confidence inputs."""

    def setUp(self):
        # Force USE_OFFICER on
        os.environ["USE_RISK_OFFICER"] = "true"
        # Avoid Alpaca calls — mock account
        self.mock_account = {
            "equity": 100000, "buying_power": 200000,
            "daytrade_count": 0, "pattern_day_trader": False,
        }

    def test_high_confidence_passes(self):
        import importlib
        # Reload to pick env
        import risk_officer
        importlib.reload(risk_officer)
        with patch.object(risk_officer, "get_account_status", return_value=self.mock_account), \
             patch.object(risk_officer, "vix_guard", return_value=("OK", 1.0)), \
             patch.object(risk_officer, "concentration_ok", return_value=(True, 5.0)), \
             patch.object(risk_officer, "daily_drawdown_guard", return_value=("OK", 0)):
            proposal = {
                "symbol": "AAPL", "action": "BUY", "size_usd": 5000,
                "entry_price": 200.0, "stop_loss": 195.0, "take_profit": 215.0,
                "strategy": "momentum-long",
                "confidence_inputs": {
                    "primary_score": 0.7, "regime": "RISK_ON",
                    "strategy": "momentum-long",
                    "bar_age_seconds": 30, "bars_count": 50,
                    "components_alive": 11, "components_total": 11,
                    "recent_errors": 0, "audit_gap_seconds": 60,
                    "intraday_pnl_pct": 0.3, "consecutive_losses": 0,
                },
            }
            result = risk_officer.evaluate_trade(proposal)
            self.assertEqual(result["decision"], "APPROVE")
            # Confidence report attached
            self.assertIn("_confidence_report", proposal)
            self.assertGreater(proposal["_confidence_report"]["total"], 0.65)

    def test_low_confidence_blocks(self):
        import importlib
        import risk_officer
        importlib.reload(risk_officer)
        with patch.object(risk_officer, "get_account_status", return_value=self.mock_account), \
             patch.object(risk_officer, "vix_guard", return_value=("OK", 1.0)), \
             patch.object(risk_officer, "concentration_ok", return_value=(True, 5.0)), \
             patch.object(risk_officer, "daily_drawdown_guard", return_value=("OK", 0)):
            proposal = {
                "symbol": "AAPL", "action": "BUY", "size_usd": 5000,
                "entry_price": 200.0, "stop_loss": 195.0, "take_profit": 215.0,
                "strategy": "momentum-long",
                "confidence_inputs": {
                    "primary_score": 0.1, "regime": "RISK_OFF",
                    "strategy": "momentum-long",
                    "bar_age_seconds": 1500, "bars_count": 5,
                    "components_alive": 3, "components_total": 11,
                    "recent_errors": 8, "audit_gap_seconds": 5000,
                    "intraday_pnl_pct": -4, "giveback_pct_of_peak": 0.6,
                    "consecutive_losses": 6, "drawdown_pct": -8,
                },
            }
            result = risk_officer.evaluate_trade(proposal)
            self.assertEqual(result["decision"], "REJECT")
            # Failure reason mentions confidence
            self.assertTrue(any("confidence" in f.lower() for f in result["checks_failed"]),
                             f"checks_failed missing confidence: {result['checks_failed']}")

    def test_no_confidence_inputs_warns_but_continues(self):
        import importlib
        import risk_officer
        importlib.reload(risk_officer)
        with patch.object(risk_officer, "get_account_status", return_value=self.mock_account), \
             patch.object(risk_officer, "vix_guard", return_value=("OK", 1.0)), \
             patch.object(risk_officer, "concentration_ok", return_value=(True, 5.0)), \
             patch.object(risk_officer, "daily_drawdown_guard", return_value=("OK", 0)):
            proposal = {
                "symbol": "AAPL", "action": "BUY", "size_usd": 5000,
                "entry_price": 200.0, "stop_loss": 195.0, "take_profit": 215.0,
                "strategy": "momentum-long",
                # NO confidence_inputs — legacy caller
            }
            result = risk_officer.evaluate_trade(proposal)
            # Should APPROVE but warn about skipped check
            self.assertEqual(result["decision"], "APPROVE")
            self.assertTrue(any("confidence" in w.lower() for w in result["warnings"]),
                             f"warnings missing confidence skip note: {result['warnings']}")


# ─── session_report.py smoke test ────────────────────────────────────────────


class TestSessionReportSmoke(unittest.TestCase):
    """Just verify the script runs end-to-end without crashing."""

    def test_session_report_dry_run(self):
        import subprocess
        result = subprocess.run(
            ["python3", str(REPO_ROOT / "scripts" / "session_report.py"), "--no-write"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr[:500]}")
        self.assertIn("Session Report", result.stdout)
        self.assertIn("Intraday governor", result.stdout)
        self.assertIn("Safe mode", result.stdout)


if __name__ == "__main__":
    unittest.main()

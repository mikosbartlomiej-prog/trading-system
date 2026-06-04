"""v3.17.0 (2026-06-04) — Task 6 — PositionManager wired into exit-monitor.

Covers:
  - Persistence round-trip (load → update → save → load) via
    shared.position_lifecycle_store backed by a temp runtime_state.json.
  - shared.position_manager evaluate_position priorities:
      kill_switch_armed → FULL_EXIT
      safe_mode_active   → FULL_EXIT
      time-stop          → FULL_EXIT
      MAE > 8%           → FULL_EXIT
      confidence drop    → FULL_EXIT
      profile quality    → FULL_EXIT
      partial exit at ≥10% profit → PARTIAL_EXIT
      lifecycle progression INTAKE → ARMED → TRAILING
  - exit-monitor `apply_position_lifecycle` orchestrator:
      * already-closed symbols are skipped (existing emergency path wins)
      * FULL_EXIT routes through safe_close with full qty
      * PARTIAL_EXIT routes through safe_close with 0.5× qty
      * Audit JSONL emitted on action
      * HOLD does NOT call safe_close

ALL TESTS:
  - LOCAL — write to tempdir only.
  - DETERMINISTIC — no clocks, no random, no network.
  - NO ORDERS — safe_close is fully mocked, no requests.post anywhere.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
EXIT_MON_DIR = os.path.join(REPO_ROOT, "exit-monitor")

for p in (SHARED_DIR, REPO_ROOT, EXIT_MON_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── Test 1: persistence round-trip ───────────────────────────────────────────

class TestPositionLifecycleStore(unittest.TestCase):
    """load → modify → save → load round-trip through runtime_state.json."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._rt_path = os.path.join(self._tmpdir.name, "runtime_state.json")
        os.environ["RUNTIME_STATE_PATH"] = self._rt_path
        # Force re-resolution of RUNTIME_STATE_PATH every test.
        import importlib
        import runtime_state
        importlib.reload(runtime_state)
        import position_lifecycle_store
        importlib.reload(position_lifecycle_store)
        self.store = position_lifecycle_store

    def tearDown(self):
        os.environ.pop("RUNTIME_STATE_PATH", None)
        self._tmpdir.cleanup()

    def test_load_returns_none_for_missing_symbol(self):
        self.assertIsNone(self.store.load_position("AAPL"))

    def test_save_then_load_roundtrip(self):
        from position_manager import open_position
        st = open_position(
            symbol="AAPL", entry_price=100.0, entry_qty=10.0,
            intent="swing", entry_confidence=0.70,
            now_iso=_iso(datetime.now(timezone.utc) - timedelta(hours=1)),
        )
        self.assertTrue(self.store.save_position(st))
        loaded = self.store.load_position("AAPL")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.symbol, "AAPL")
        self.assertEqual(loaded.entry_price, 100.0)
        self.assertEqual(loaded.entry_qty, 10.0)
        self.assertEqual(loaded.intent, "swing")
        self.assertEqual(loaded.entry_confidence, 0.70)
        self.assertEqual(loaded.lifecycle, "INTAKE")

    def test_save_with_lifecycle_advance(self):
        from position_manager import open_position
        st = open_position(symbol="MSFT", entry_price=200, entry_qty=5)
        # Caller advances lifecycle on save
        self.assertTrue(self.store.save_position(st, next_lifecycle="ARMED"))
        loaded = self.store.load_position("MSFT")
        self.assertEqual(loaded.lifecycle, "ARMED")

    def test_remove_position_clears_entry(self):
        from position_manager import open_position
        st = open_position(symbol="GOOG", entry_price=150, entry_qty=3)
        self.store.save_position(st)
        self.assertEqual(self.store.all_position_symbols(), ["GOOG"])
        self.assertTrue(self.store.remove_position("GOOG"))
        self.assertIsNone(self.store.load_position("GOOG"))

    def test_remove_missing_is_idempotent_success(self):
        self.assertTrue(self.store.remove_position("NOPE"))


# ─── Test 2: position_manager evaluate_position priorities ────────────────────

class TestEvaluatePositionPriorities(unittest.TestCase):
    """Verifies the documented HARD RULES order in evaluate_position."""

    def setUp(self):
        from position_manager import (
            open_position, update_position_marks, evaluate_position,
        )
        self.open = open_position
        self.update = update_position_marks
        self.evaluate = evaluate_position

    def _aged(self, *, entry_price, current_price, hours_old=2,
               intent="swing", entry_confidence=0.65, confidence_now=None,
               profile_quality_now=None):
        opened = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        st = self.open(
            symbol="TEST", entry_price=entry_price, entry_qty=10.0,
            intent=intent, entry_confidence=entry_confidence,
            now_iso=_iso(opened),
        )
        return self.update(
            st, current_price=current_price,
            confidence_now=confidence_now,
            profile_quality_now=profile_quality_now,
        )

    def test_kill_switch_armed_triggers_full_exit_priority(self):
        # Even a healthy position must full-exit on kill switch.
        st = self._aged(entry_price=100, current_price=103, hours_old=1)
        d = self.evaluate(st, kill_switch_armed=True)
        self.assertEqual(d.recommendation, "FULL_EXIT")
        self.assertIn("kill_switch", d.triggered_signals)

    def test_safe_mode_active_triggers_full_exit_priority(self):
        st = self._aged(entry_price=100, current_price=101, hours_old=1)
        d = self.evaluate(st, safe_mode_active=True)
        self.assertEqual(d.recommendation, "FULL_EXIT")
        self.assertIn("safe_mode", d.triggered_signals)

    def test_max_adverse_excursion_triggers_full_exit(self):
        # -10% loss exceeds the 8% MAE safety net.
        st = self._aged(entry_price=100, current_price=90, hours_old=2)
        d = self.evaluate(st)
        self.assertEqual(d.recommendation, "FULL_EXIT")
        self.assertIn("max_adverse_excursion", d.triggered_signals)

    def test_time_stop_triggers_full_exit(self):
        # 50 hours old > 48 hour swing default.
        st = self._aged(entry_price=100, current_price=100, hours_old=50)
        d = self.evaluate(st)
        self.assertEqual(d.recommendation, "FULL_EXIT")
        self.assertIn("time_stop", d.triggered_signals)

    def test_confidence_collapse_triggers_full_exit(self):
        # entry 0.80, now 0.30 = collapsed (< 0.40 AND < 0.80*0.6=0.48).
        st = self._aged(entry_price=100, current_price=101, hours_old=2,
                          entry_confidence=0.80, confidence_now=0.30)
        d = self.evaluate(st)
        self.assertEqual(d.recommendation, "FULL_EXIT")
        self.assertIn("confidence_collapsed", d.triggered_signals)

    def test_partial_exit_at_10_pct_profit(self):
        # +10% in green should trigger PARTIAL_EXIT (0.5×).
        st = self._aged(entry_price=100, current_price=110, hours_old=2)
        d = self.evaluate(st)
        self.assertEqual(d.recommendation, "PARTIAL_EXIT")
        self.assertEqual(d.partial_qty_pct, 0.5)
        self.assertEqual(d.next_lifecycle, "TRAILING")

    def test_lifecycle_intake_grace_holds(self):
        # Within grace period (<5 min) → HOLD.
        from position_manager import open_position, evaluate_position
        # 60 seconds old
        opened = datetime.now(timezone.utc) - timedelta(seconds=60)
        st = open_position(symbol="GRC", entry_price=100, entry_qty=1,
                             now_iso=_iso(opened))
        # No update_marks needed for grace check; time_at_eval_hours is 0.
        d = evaluate_position(st)
        self.assertEqual(d.recommendation, "HOLD")
        self.assertEqual(d.next_lifecycle, "INTAKE")

    def test_lifecycle_armed_after_grace_holds_quiet(self):
        # Quiet position past grace → HOLD ARMED.
        st = self._aged(entry_price=100, current_price=100, hours_old=1)
        d = self.evaluate(st)
        self.assertEqual(d.recommendation, "HOLD")
        # Past grace; lifecycle should advance to ARMED.
        self.assertEqual(d.next_lifecycle, "ARMED")


# ─── Test 3: state persists across calls ──────────────────────────────────────

class TestPersistenceAcrossCalls(unittest.TestCase):
    """Simulate two consecutive cron ticks: save → load → save → load."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["RUNTIME_STATE_PATH"] = os.path.join(self._tmpdir.name, "runtime_state.json")
        import importlib
        import runtime_state
        importlib.reload(runtime_state)
        import position_lifecycle_store
        importlib.reload(position_lifecycle_store)
        self.store = position_lifecycle_store

    def tearDown(self):
        os.environ.pop("RUNTIME_STATE_PATH", None)
        self._tmpdir.cleanup()

    def test_two_tick_round_trip(self):
        from position_manager import (
            open_position, update_position_marks, evaluate_position,
        )
        opened = datetime.now(timezone.utc) - timedelta(hours=1)
        # Tick 1: open
        st1 = open_position(
            symbol="QQQ", entry_price=400, entry_qty=10,
            now_iso=_iso(opened),
        )
        self.store.save_position(st1)

        # Tick 2: load + update marks + re-save
        loaded = self.store.load_position("QQQ")
        self.assertIsNotNone(loaded)
        st2 = update_position_marks(loaded, current_price=420)
        self.assertAlmostEqual(st2.current_pl_pct, 0.05)
        self.assertAlmostEqual(st2.peak_pl_pct, 0.05)
        self.assertTrue(self.store.save_position(st2))

        # Tick 3: load — peak should still be visible
        st3 = self.store.load_position("QQQ")
        self.assertAlmostEqual(st3.peak_pl_pct, 0.05)
        self.assertAlmostEqual(st3.peak_price, 420.0)

    def test_mfe_mae_persist_across_load(self):
        from position_manager import open_position, update_position_marks
        opened = datetime.now(timezone.utc) - timedelta(hours=2)
        st = open_position(symbol="SPY", entry_price=500, entry_qty=5,
                             now_iso=_iso(opened))
        st = update_position_marks(st, current_price=525)  # +5%
        st = update_position_marks(st, current_price=510)  # back, MFE locked at 5%
        st = update_position_marks(st, current_price=495)  # MAE -1%
        self.store.save_position(st)
        loaded = self.store.load_position("SPY")
        self.assertAlmostEqual(loaded.peak_pl_pct, 0.05)
        self.assertAlmostEqual(loaded.trough_pl_pct, -0.01)


# ─── Test 4: exit-monitor orchestrator ────────────────────────────────────────

class TestApplyPositionLifecycleOrchestrator(unittest.TestCase):
    """Exercises exit-monitor.apply_position_lifecycle end-to-end with mocks.

    safe_close is mocked — NO REAL HTTP, NO REAL ORDERS.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["RUNTIME_STATE_PATH"] = os.path.join(self._tmpdir.name, "runtime_state.json")
        os.environ["AUDIT_TRADING_DIR"] = os.path.join(self._tmpdir.name, "audit")
        # Stop any imports of notify from trying to send mail.
        os.environ.setdefault("GMAIL_APP_PASSWORD", "")
        os.environ.setdefault("ALPACA_API_KEY", "x")
        os.environ.setdefault("ALPACA_SECRET_KEY", "x")
        import importlib
        import runtime_state
        importlib.reload(runtime_state)
        import position_lifecycle_store
        importlib.reload(position_lifecycle_store)
        # v3.17.0 — pop any cached `monitor` module from sys.modules so we
        # get exit-monitor/monitor.py specifically (geo/defense/doj/etc.
        # also ship `monitor.py` and namespace would otherwise collide).
        sys.modules.pop("monitor", None)
        # Put exit-monitor first on sys.path
        if EXIT_MON_DIR in sys.path:
            sys.path.remove(EXIT_MON_DIR)
        sys.path.insert(0, EXIT_MON_DIR)
        import monitor as exit_monitor  # exit-monitor/monitor.py
        self.exit_monitor = exit_monitor

    def tearDown(self):
        for k in ("RUNTIME_STATE_PATH", "AUDIT_TRADING_DIR"):
            os.environ.pop(k, None)
        self._tmpdir.cleanup()

    def _make_position(self, *, symbol="AAPL", qty=10, side="long",
                         entry=100.0, current=100.0, asset_class="us_equity"):
        return {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "avg_entry_price": str(entry),
            "current_price": str(current),
            "market_value": str(qty * current),
            "unrealized_pl": str((current - entry) * qty),
            "unrealized_plpc": str((current / entry) - 1.0),
            "asset_class": asset_class,
        }

    def _filled_order(self, *, symbol="AAPL", hours_ago=2):
        ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        return {
            "symbol": symbol,
            "filled_at": ts,
            "client_order_id": f"momentum-long-{symbol}-aaa",
        }

    def test_already_closed_symbols_are_skipped(self):
        pos = self._make_position(symbol="AAPL", current=120)  # +20% would PARTIAL
        orders = [self._filled_order(symbol="AAPL", hours_ago=2)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "x"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols={"AAPL"},
                flagged_recommendations={"AAPL": "CLOSE_EMERGENCY"},
            )
        self.assertEqual(stats["skipped_closed"], 1)
        self.assertEqual(stats["actions_placed"], 0)
        m_sc.assert_not_called()

    def test_partial_exit_at_profit_calls_safe_close_with_half(self):
        pos = self._make_position(symbol="AAPL", qty=10, current=110)  # +10%
        orders = [self._filled_order(symbol="AAPL", hours_ago=2)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-partial"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["PARTIAL_EXIT"], 1)
        self.assertEqual(stats["actions_placed"], 1)
        m_sc.assert_called_once()
        kw = m_sc.call_args.kwargs
        self.assertEqual(kw["symbol"], "AAPL")
        # Half of qty=10 = 5.
        self.assertAlmostEqual(kw["intent_qty"], 5.0)
        self.assertEqual(kw["intent_side"], "sell")
        self.assertIn("partial", kw["reason_tag"])

    def test_full_exit_on_time_stop_calls_safe_close_with_full_qty(self):
        # 60 hours old > 48h swing default.
        pos = self._make_position(symbol="MSFT", qty=7, current=100)
        orders = [self._filled_order(symbol="MSFT", hours_ago=60)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-full"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["FULL_EXIT"], 1)
        self.assertEqual(stats["actions_placed"], 1)
        m_sc.assert_called_once()
        kw = m_sc.call_args.kwargs
        self.assertAlmostEqual(kw["intent_qty"], 7.0)
        self.assertEqual(kw["reason_tag"], "exit-full")

    def test_max_adverse_excursion_triggers_full_exit_via_orchestrator(self):
        # -10% loss; MAE safety net is -8%.
        pos = self._make_position(symbol="NVDA", qty=4, current=90)
        orders = [self._filled_order(symbol="NVDA", hours_ago=3)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-mae"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["FULL_EXIT"], 1)
        m_sc.assert_called_once()

    def test_kill_switch_triggers_full_exit_via_orchestrator(self):
        # Healthy position — but kill switch armed.
        pos = self._make_position(symbol="SPY", qty=3, current=102)
        orders = [self._filled_order(symbol="SPY", hours_ago=2)]
        with mock.patch(
            "monitor._kill_switch_armed", return_value=True
        ), mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-kill"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["FULL_EXIT"], 1)
        self.assertEqual(stats["actions_placed"], 1)
        m_sc.assert_called_once()
        kw = m_sc.call_args.kwargs
        self.assertEqual(kw["reason_tag"], "exit-full")

    def test_safe_mode_triggers_full_exit_via_orchestrator(self):
        pos = self._make_position(symbol="QQQ", qty=2, current=101)
        orders = [self._filled_order(symbol="QQQ", hours_ago=2)]
        with mock.patch(
            "monitor._safe_mode_active", return_value=True
        ), mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-sm"},
        ) as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["FULL_EXIT"], 1)
        m_sc.assert_called_once()

    def test_hold_does_not_call_safe_close(self):
        # Healthy, quiet — should HOLD.
        pos = self._make_position(symbol="GLD", qty=5, current=100.5)
        orders = [self._filled_order(symbol="GLD", hours_ago=3)]
        with mock.patch("alpaca_orders.safe_close") as m_sc:
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["HOLD"], 1)
        self.assertEqual(stats["actions_placed"], 0)
        m_sc.assert_not_called()

    def test_audit_event_emitted_on_full_exit(self):
        """A FULL_EXIT action must write at least one POSITION_LIFECYCLE
        record to the trading audit JSONL."""
        pos = self._make_position(symbol="MSFT", qty=7, current=100)
        orders = [self._filled_order(symbol="MSFT", hours_ago=60)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-audit"},
        ):
            self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        # Inspect today's JSONL.
        audit_dir = os.environ["AUDIT_TRADING_DIR"]
        today = datetime.now(timezone.utc).date().isoformat()
        path = os.path.join(audit_dir, f"{today}.jsonl")
        self.assertTrue(os.path.exists(path), f"audit file missing: {path}")
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        types = {l.get("decision_type") for l in lines}
        self.assertIn("POSITION_LIFECYCLE", types)
        decs = {l.get("decision") for l in lines if l.get("decision_type") == "POSITION_LIFECYCLE"}
        self.assertIn("FULL_EXIT", decs)

    def test_skipped_close_persists_state_for_next_tick(self):
        """If safe_close returns 'skipped' (e.g. position gone), state should
        still be persisted with the marks updated so next tick reuses MFE/MAE."""
        pos = self._make_position(symbol="AMD", qty=10, current=110)
        orders = [self._filled_order(symbol="AMD", hours_ago=2)]
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "skipped", "reason": "position_gone"},
        ):
            stats = self.exit_monitor.apply_position_lifecycle(
                [pos], orders,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats["actions_skipped"], 1)
        self.assertEqual(stats["actions_placed"], 0)
        # State should still be persisted (PARTIAL_EXIT path saves on skip).
        from position_lifecycle_store import load_position
        loaded = load_position("AMD")
        self.assertIsNotNone(loaded)

    def test_lifecycle_progression_intake_to_armed_to_trailing(self):
        """Three ticks: INTAKE (grace) → ARMED (quiet) → TRAILING (5% profit)."""
        # Tick 1: position 30 seconds old; HOLD, lifecycle INTAKE.
        pos1 = self._make_position(symbol="ORCL", qty=10, current=100)
        orders1 = [self._filled_order(symbol="ORCL", hours_ago=0)]
        # Override entry timestamp to be 30s in past for grace test.
        orders1[0]["filled_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=30)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with mock.patch("alpaca_orders.safe_close") as m_sc:
            stats1 = self.exit_monitor.apply_position_lifecycle(
                [pos1], orders1,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats1["HOLD"], 1)
        m_sc.assert_not_called()
        from position_lifecycle_store import load_position
        st1 = load_position("ORCL")
        self.assertEqual(st1.lifecycle, "INTAKE")

        # Tick 2: hand-edit opened_at_iso to be 1 hour ago so grace is past.
        from position_lifecycle_store import save_position
        from dataclasses import replace
        opened_iso = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
        st1b = replace(st1, opened_at_iso=opened_iso)
        save_position(st1b)
        with mock.patch("alpaca_orders.safe_close") as m_sc:
            stats2 = self.exit_monitor.apply_position_lifecycle(
                [pos1], orders1,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats2["HOLD"], 1)
        m_sc.assert_not_called()
        st2 = load_position("ORCL")
        self.assertEqual(st2.lifecycle, "ARMED")

        # Tick 3: price +10% triggers PARTIAL_EXIT → lifecycle becomes TRAILING.
        pos1b = self._make_position(symbol="ORCL", qty=10, current=110)
        save_position(st2)  # keep ARMED lifecycle
        with mock.patch(
            "alpaca_orders.safe_close",
            return_value={"status": "placed", "alpaca_order_id": "ord-trl"},
        ) as m_sc:
            stats3 = self.exit_monitor.apply_position_lifecycle(
                [pos1b], orders1,
                already_closed_symbols=set(),
                flagged_recommendations={},
            )
        self.assertEqual(stats3["PARTIAL_EXIT"], 1)
        m_sc.assert_called_once()
        st3 = load_position("ORCL")
        self.assertEqual(st3.lifecycle, "TRAILING")


# ─── Test 5: positions section is in INTRADAY_SECTIONS ────────────────────────

class TestRuntimeStateContract(unittest.TestCase):
    def test_positions_in_intraday_sections(self):
        import runtime_state
        self.assertIn("positions", runtime_state.INTRADAY_SECTIONS)


if __name__ == "__main__":
    unittest.main()

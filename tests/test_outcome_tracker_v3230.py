"""v3.23 tests for shared/outcome_tracker.py."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import outcome_tracker as ot  # noqa: E402
import shadow_simulator as ss  # noqa: E402


_CANARY_OK = "CANARY_PREFLIGHT_DRY_RUN_OK"


def _filled_shadow(side="long", entry=100.0,
                    qty=1.0, asset="us_equity") -> ss.ShadowFill:
    return ss.ShadowFill(
        signal_id="sig-x",
        symbol="AAPL",
        strategy="momentum-long",
        side=side,
        asset_class=asset,
        intended_price=entry,
        fill_price=entry,
        qty=qty,
        timestamp_iso=
            datetime(2026, 6, 15, 14, 0, 0,
                     tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        slippage_bps=0.0,
        spread_bps=0.0,
        fill_status="FILLED",
        rejection_reason=None,
        canary_preflight_verdict=_CANARY_OK,
    )


def _rejected_shadow() -> ss.ShadowFill:
    f = _filled_shadow()
    object.__setattr__(f, "fill_status", "REJECTED_BY_GATE")
    return f


class TestHorizonMath(unittest.TestCase):
    def test_five_horizons_emitted_for_filled(self):
        out = ot.schedule_outcomes(_filled_shadow())
        names = sorted(o.horizon_name for o in out)
        self.assertEqual(
            names, sorted(["30m", "1h", "4h", "EOD", "next_open"]))

    def test_no_outcomes_for_rejected(self):
        out = ot.schedule_outcomes(_rejected_shadow())
        self.assertEqual(out, [])

    def test_no_outcomes_for_none_or_bad_input(self):
        self.assertEqual(ot.schedule_outcomes(None), [])
        self.assertEqual(ot.schedule_outcomes("not a fill"), [])

    def test_no_outcomes_when_qty_zero(self):
        f = _filled_shadow(qty=0)
        self.assertEqual(ot.schedule_outcomes(f), [])

    def test_relative_horizons_are_correct(self):
        out = ot.schedule_outcomes(_filled_shadow())
        by = {o.horizon_name: o for o in out}
        entry = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(
            by["30m"].resolves_at_iso,
            (entry + timedelta(minutes=30))
            .strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(
            by["1h"].resolves_at_iso,
            (entry + timedelta(hours=1))
            .strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(
            by["4h"].resolves_at_iso,
            (entry + timedelta(hours=4))
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


class TestMFEMAE(unittest.TestCase):
    def test_long_positive_excursion(self):
        sch = [s for s in ot.schedule_outcomes(_filled_shadow())
                if s.horizon_name == "1h"][0]
        # entry 100, qty 1, long, high 110, low 95, close 105 → MFE 10, MAE -5
        def fetch(sym, a, b):
            return {"high_max": 110.0, "low_min": 95.0,
                    "close": 105.0}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        self.assertEqual(len(outs), 1)
        o = outs[0]
        self.assertEqual(o.hypothetical_pnl, 5.0)
        self.assertEqual(o.max_favorable_excursion, 10.0)
        self.assertEqual(o.max_adverse_excursion, -5.0)
        self.assertEqual(o.is_paper_trade, False)
        self.assertEqual(o.record_type, "SHADOW_OUTCOME_OBSERVATION")

    def test_short_inverted(self):
        sch = [s for s in ot.schedule_outcomes(_filled_shadow(side="short"))
                if s.horizon_name == "1h"][0]
        # short entry 100, qty 1, high 110, low 95, close 92
        # → pnl = (100-92)*1 = 8; for short, MFE uses low (95<100 favorable)
        def fetch(sym, a, b):
            return {"high_max": 110.0, "low_min": 95.0,
                    "close": 92.0}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        o = outs[0]
        self.assertEqual(o.hypothetical_pnl, 8.0)
        self.assertEqual(o.max_favorable_excursion, 5.0)
        self.assertEqual(o.max_adverse_excursion, -10.0)


class TestHitStopFirst(unittest.TestCase):
    def test_long_stop_hit_first(self):
        sch_list = ot.schedule_outcomes(_filled_shadow())
        sch = [s for s in sch_list if s.horizon_name == "1h"][0]
        # add stop/target
        object.__setattr__(sch, "stop_price",   95.0)
        object.__setattr__(sch, "target_price", 110.0)
        def fetch(sym, a, b):
            t0 = datetime(2026, 6, 15, 14, 5, tzinfo=timezone.utc)
            t1 = datetime(2026, 6, 15, 14, 50, tzinfo=timezone.utc)
            return {"high_max": 111.0, "low_min": 94.0,
                    "close": 100.0,
                    "ts_low":  t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ts_high": t1.strftime("%Y-%m-%dT%H:%M:%SZ")}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        o = outs[0]
        self.assertTrue(o.hit_stop_first)
        self.assertFalse(o.hit_target_first)

    def test_long_target_hit_first(self):
        sch_list = ot.schedule_outcomes(_filled_shadow())
        sch = [s for s in sch_list if s.horizon_name == "1h"][0]
        object.__setattr__(sch, "stop_price",   95.0)
        object.__setattr__(sch, "target_price", 110.0)
        def fetch(sym, a, b):
            t_high = datetime(2026, 6, 15, 14, 10, tzinfo=timezone.utc)
            t_low  = datetime(2026, 6, 15, 14, 50, tzinfo=timezone.utc)
            return {"high_max": 111.0, "low_min": 94.0,
                    "close": 100.0,
                    "ts_high": t_high.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ts_low":  t_low.strftime("%Y-%m-%dT%H:%M:%SZ")}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        o = outs[0]
        self.assertTrue(o.hit_target_first)
        self.assertFalse(o.hit_stop_first)

    def test_not_yet_matured_skipped(self):
        sch_list = ot.schedule_outcomes(_filled_shadow())
        sch = [s for s in sch_list if s.horizon_name == "4h"][0]
        def fetch(sym, a, b):
            return {"close": 105.0}
        as_of = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        self.assertEqual(outs, [])

    def test_fail_soft_on_fetcher_exception(self):
        sch_list = ot.schedule_outcomes(_filled_shadow())
        sch = [s for s in sch_list if s.horizon_name == "30m"][0]
        def fetch(sym, a, b):
            raise RuntimeError("network down")
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        # Should still produce a row with defaults (close == entry).
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs[0].hypothetical_pnl, 0.0)


class TestPaperTradeFlag(unittest.TestCase):
    def test_pending_dict_has_is_paper_trade_false(self):
        sch_list = ot.schedule_outcomes(_filled_shadow())
        for s in sch_list:
            d = s.to_dict()
            self.assertFalse(d["is_paper_trade"])
            self.assertEqual(d["record_type"], "SHADOW_OUTCOME_PENDING")

    def test_resolved_dict_has_record_type_and_flag(self):
        sch = [s for s in ot.schedule_outcomes(_filled_shadow())
                if s.horizon_name == "30m"][0]
        def fetch(sym, a, b):
            return {"high_max": 102.0, "low_min": 99.0,
                    "close": 101.0}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        outs = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)
        d = outs[0].to_dict()
        self.assertEqual(d["record_type"], "SHADOW_OUTCOME_OBSERVATION")
        self.assertFalse(d["is_paper_trade"])

    def test_append_ledger_writes_jsonl(self):
        sch = [s for s in ot.schedule_outcomes(_filled_shadow())
                if s.horizon_name == "30m"][0]
        def fetch(sym, a, b):
            return {"high_max": 102.0, "low_min": 99.0,
                    "close": 101.0}
        as_of = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        out = ot.evaluate_pending(
            [sch], as_of=as_of, snapshot_fetcher=fetch)[0]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.jsonl"
            ot.append_outcome_ledger(out, path=p)
            self.assertTrue(p.exists())
            with open(p) as fp:
                rows = [json.loads(l) for l in fp if l.strip()]
            self.assertEqual(rows[0]["is_paper_trade"], False)


class TestNoBrokerAST(unittest.TestCase):
    def test_no_alpaca_orders_import_in_module(self):
        path = REPO_ROOT / "shared" / "outcome_tracker.py"
        tree = ast.parse(path.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module)
        for n in names:
            self.assertFalse("alpaca_orders" in n)
            self.assertFalse(n.startswith("requests"))
            self.assertFalse(n.startswith("urllib3"))
            self.assertFalse(n.startswith("httpx"))

    def test_no_forbidden_call_names_in_source(self):
        src = (REPO_ROOT / "shared" / "outcome_tracker.py").read_text()
        for forbidden in (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(",
            "close_all_positions(", "place_stock_bracket(",
        ):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()

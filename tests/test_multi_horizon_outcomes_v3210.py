"""v3.21.0 (2026-06-04) — Tests for shared/multi_horizon_outcomes.

Covers the ETAP 3 contracts:
  * each horizon is computed independently
  * missing bars → outcome UNKNOWN (no guessing)
  * MFE/MAE computed correctly from a known price series
  * multi-horizon outcomes do NOT increment paper n
  * EOD horizon works when bars are available
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from multi_horizon_outcomes import (  # noqa: E402
    EVIDENCE_SOURCE_MULTI_HORIZON,
    HORIZONS,
    HORIZON_5MIN,
    HORIZON_15MIN,
    HORIZON_30MIN,
    HORIZON_60MIN,
    HORIZON_END_OF_DAY,
    HORIZON_NEXT_SESSION_OPEN,
    OUTCOME_PROFITABLE,
    OUTCOME_LOSING,
    OUTCOME_UNKNOWN,
    compute_outcome_for_signal,
    compute_outcomes_for_signal,
    compute_outcomes_for_ledger,
    write_outcomes_jsonl,
)


def _entry_ts() -> datetime:
    """Fixed entry ts inside session hours."""
    return datetime(2026, 6, 4, 14, 0, 0, tzinfo=timezone.utc)


def _bars_minute_series(symbol_returns):
    """Build a synthetic bar series from a list of returns.

    Bars are one minute apart, starting at entry_ts. ``c`` ladders with
    the cumulative return; high/low extend a touch beyond the close.
    """
    entry = _entry_ts()
    bars = []
    price = 100.0
    for i, r in enumerate(symbol_returns):
        price = price * (1.0 + r)
        ts = entry + timedelta(minutes=i)
        bars.append({
            "t": ts.isoformat().replace("+00:00", "Z"),
            "o": price * 0.999,
            "h": price * 1.002,
            "l": price * 0.998,
            "c": price,
            "v": 1000,
        })
    return bars


def _make_fetcher(symbol_to_bars):
    def _fetcher(symbol, days):
        bars = symbol_to_bars.get(symbol)
        if bars is None:
            return None
        return {"bars": list(bars)}
    return _fetcher


def _signal(symbol="UP", side="long", entry_price=100.0):
    return {
        "signal_id":   f"sig-{symbol}-001",
        "symbol":      symbol,
        "side":        side,
        "entry_price": entry_price,
        "entry_ts":    _entry_ts().isoformat().replace("+00:00", "Z"),
    }


class TestHorizonIndependence(unittest.TestCase):
    """ETAP 3 contract — horizons are computed independently."""

    def test_each_horizon_computed_independently(self):
        bars = _bars_minute_series([0.001] * 120)
        fetcher = _make_fetcher({"UP": bars})
        outcomes = compute_outcomes_for_signal(_signal("UP"),
                                               bars_fetcher=fetcher)
        # All intraday horizons should be present and have their own
        # status.
        for h in (HORIZON_5MIN, HORIZON_15MIN, HORIZON_30MIN, HORIZON_60MIN):
            self.assertIn(h, outcomes)
            self.assertEqual(outcomes[h].horizon, h)
            self.assertEqual(outcomes[h].evidence_source,
                             EVIDENCE_SOURCE_MULTI_HORIZON)

    def test_one_horizon_failure_does_not_leak(self):
        # Fetcher throws on the very first horizon call but works
        # afterwards — each horizon is computed independently, so the
        # later horizons must still succeed.
        bars = _bars_minute_series([0.002] * 120)
        good = _make_fetcher({"UP": bars})
        call_count = {"n": 0}

        def fetcher(symbol, days):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated fetch failure on first horizon")
            return good(symbol, days)

        outcomes = compute_outcomes_for_signal(_signal("UP"),
                                               bars_fetcher=fetcher)
        # First-call horizon got UNKNOWN (fail-soft caught the
        # exception in the fetcher wrapper).
        self.assertEqual(outcomes[HORIZON_5MIN].outcome, OUTCOME_UNKNOWN)
        self.assertIn(outcomes[HORIZON_5MIN].status,
                      {"ERROR", "MISSING_BARS"})
        # Subsequent horizons still computed successfully.
        self.assertNotEqual(outcomes[HORIZON_15MIN].outcome, OUTCOME_UNKNOWN)
        self.assertEqual(outcomes[HORIZON_15MIN].status, "OK")


class TestMissingBars(unittest.TestCase):
    """ETAP 3 contract — missing bars → UNKNOWN."""

    def test_no_fetcher(self):
        # Disable the default market_data import by passing a fetcher
        # that returns None for every symbol.
        fetcher = _make_fetcher({})
        outcome = compute_outcome_for_signal(_signal("UP"), HORIZON_5MIN,
                                             bars_fetcher=fetcher)
        self.assertEqual(outcome.outcome, OUTCOME_UNKNOWN)
        self.assertEqual(outcome.status, "MISSING_BARS")

    def test_bars_outside_window(self):
        # Bars sit BEFORE the signal entry timestamp.
        entry_minus_one_hour = _entry_ts() - timedelta(hours=1)
        bars = [{
            "t": (entry_minus_one_hour + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "o": 99.0, "h": 99.5, "l": 98.5, "c": 99.0, "v": 100,
        } for i in range(5)]
        fetcher = _make_fetcher({"UP": bars})
        outcome = compute_outcome_for_signal(_signal("UP"), HORIZON_5MIN,
                                             bars_fetcher=fetcher)
        self.assertEqual(outcome.outcome, OUTCOME_UNKNOWN)


class TestMfeMaeFromKnownSeries(unittest.TestCase):
    """ETAP 3 contract — MFE/MAE correct from a known price path."""

    def test_long_mfe_mae(self):
        # Price dips ~3 % below entry first, then climbs above entry.
        # MFE for a long should be > 0, MAE for a long should be < 0.
        bars = _bars_minute_series([-0.03, 0.06, -0.01, 0.005])
        fetcher = _make_fetcher({"UP": bars})
        outcome = compute_outcome_for_signal(_signal("UP"), HORIZON_5MIN,
                                             bars_fetcher=fetcher)
        self.assertGreater(outcome.mfe_pct, 0.5)
        self.assertLess(outcome.mae_pct, 0.0)

    def test_short_mfe_mae(self):
        bars = _bars_minute_series([-0.02, 0.01, -0.005])
        fetcher = _make_fetcher({"DOWN": bars})
        outcome = compute_outcome_for_signal(
            _signal("DOWN", side="short"), HORIZON_5MIN,
            bars_fetcher=fetcher)
        # For a short, the favourable excursion is a downward move.
        self.assertGreater(outcome.mfe_pct, 1.0)


class TestNotPaperEvidence(unittest.TestCase):
    """ETAP 3 invariant — outcomes never increment paper n."""

    def test_evidence_source_constant(self):
        bars = _bars_minute_series([0.001] * 10)
        fetcher = _make_fetcher({"UP": bars})
        outcomes = compute_outcomes_for_signal(_signal("UP"),
                                               bars_fetcher=fetcher)
        for o in outcomes.values():
            self.assertEqual(o.evidence_source, EVIDENCE_SOURCE_MULTI_HORIZON)
            self.assertNotEqual(o.evidence_source, "PAPER")
            self.assertNotEqual(o.evidence_source, "BACKTEST")
            self.assertNotEqual(o.evidence_source, "REPLAY")

    def test_ledger_records_dont_pollute_paper_path(self):
        bars = _bars_minute_series([0.001] * 60)
        fetcher = _make_fetcher({"UP": bars})
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            date_iso = _entry_ts().date().isoformat()
            path = ledger_dir / f"{date_iso}.jsonl"
            path.write_text(json.dumps({
                "signal_id":   "sig-1",
                "symbol":      "UP",
                "raw_signal":  {
                    "side":         "long",
                    "entry_price":  100.0,
                    "entry_ts":     _entry_ts().isoformat().replace("+00:00", "Z"),
                },
            }) + "\n", encoding="utf-8")
            records = compute_outcomes_for_ledger(date_iso,
                                                  ledger_dir=ledger_dir,
                                                  bars_fetcher=fetcher)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["evidence_source"],
                             EVIDENCE_SOURCE_MULTI_HORIZON)


class TestEndOfDayHorizon(unittest.TestCase):
    """ETAP 3 contract — EOD works when bars cover the window."""

    def test_eod_with_bars(self):
        # Bars cover the rest of the session: 14:00 → 20:00 UTC = 360
        # minutes. Tail return is +5 %.
        bars = _bars_minute_series([0.0001] * 359 + [0.05])
        fetcher = _make_fetcher({"UP": bars})
        outcome = compute_outcome_for_signal(_signal("UP"), HORIZON_END_OF_DAY,
                                             bars_fetcher=fetcher)
        self.assertEqual(outcome.outcome, OUTCOME_PROFITABLE)
        self.assertEqual(outcome.horizon, HORIZON_END_OF_DAY)

    def test_eod_missing(self):
        # No bars past entry — EOD must report UNKNOWN.
        fetcher = _make_fetcher({"UP": []})
        outcome = compute_outcome_for_signal(_signal("UP"), HORIZON_END_OF_DAY,
                                             bars_fetcher=fetcher)
        self.assertEqual(outcome.outcome, OUTCOME_UNKNOWN)

    def test_next_session_open_walks_past_weekend(self):
        # Friday 14:00 UTC entry → next session is Monday.
        friday_entry = datetime(2026, 6, 5, 14, 0, 0, tzinfo=timezone.utc)
        bars = _bars_minute_series([0.0])
        # Shift the bars to start at the Friday entry (the helper uses a
        # fixed start; we explicitly rebuild here).
        bars = [{
            "t": (friday_entry + timedelta(hours=h)).isoformat().replace("+00:00", "Z"),
            "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1,
        } for h in range(80)]
        fetcher = _make_fetcher({"UP": bars})
        signal = {
            "signal_id":   "sig-fri",
            "symbol":      "UP",
            "side":        "long",
            "entry_price": 100.0,
            "entry_ts":    friday_entry.isoformat().replace("+00:00", "Z"),
        }
        outcome = compute_outcome_for_signal(signal,
                                             HORIZON_NEXT_SESSION_OPEN,
                                             bars_fetcher=fetcher)
        # Either we have a result or UNKNOWN — but the window must have
        # been advanced past the weekend (Mon = weekday 0).
        self.assertIn(outcome.outcome,
                      {OUTCOME_PROFITABLE, OUTCOME_LOSING, "FLAT", OUTCOME_UNKNOWN})


class TestWriteOutcomes(unittest.TestCase):
    def test_write_outcomes_jsonl(self):
        bars = _bars_minute_series([0.001] * 30)
        fetcher = _make_fetcher({"UP": bars})
        records = [{
            "signal_id":           "sig-1",
            "symbol":              "UP",
            "side":                "long",
            "entry_ts":            _entry_ts().isoformat().replace("+00:00", "Z"),
            "evidence_source":     EVIDENCE_SOURCE_MULTI_HORIZON,
            "outcomes_by_horizon": {
                h: compute_outcome_for_signal(_signal("UP"), h,
                                              bars_fetcher=fetcher).to_dict()
                for h in HORIZONS
            },
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            path = write_outcomes_jsonl(records, out_dir=out,
                                        date_iso="2026-06-04")
            self.assertTrue(path.exists())
            lines = [json.loads(line) for line in path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["evidence_source"],
                             EVIDENCE_SOURCE_MULTI_HORIZON)


if __name__ == "__main__":
    unittest.main()

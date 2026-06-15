"""v3.26 (Agent 3A ETAP 3) — tests for near-miss tracker wiring into
signal_emitter via maybe_record_near_miss_from_signal_event.

Verifies:
  - signal_event whose metric is within ~10% of threshold writes one
    near-miss row to the JSONL file
  - signal_event whose metric is FAR from threshold writes nothing
  - signal_event whose metric ALREADY triggers (i.e. hit) writes nothing
  - written near-miss rows always have is_paper_trade=False AND
    is_signal=False (HARD invariants)
  - the helper is fail-soft on bad input (returns None, no raise)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from near_miss_tracker import (  # noqa: E402
    DEFAULT_STRATEGY_THRESHOLD_MAP,
    NEAR_MISS_WINDOW_RATIO_DEFAULT,
    maybe_record_near_miss_from_signal_event,
)


class _FakeSignalEvent:
    """Minimal duck-type stand-in so we don't have to construct a full
    SignalEvent in tests."""

    def __init__(self, *, strategy_id, symbol, raw_signal,
                 timestamp_iso="2026-06-15T12:00:00+00:00"):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.raw_signal = dict(raw_signal)
        self.timestamp_iso = timestamp_iso


class _Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="near_miss_wired_")
        self._prev = os.environ.get("NEAR_MISS_DIR")
        os.environ["NEAR_MISS_DIR"] = self._tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("NEAR_MISS_DIR", None)
        else:
            os.environ["NEAR_MISS_DIR"] = self._prev
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _read_rows(self) -> list[dict]:
        out = []
        for f in Path(self._tmp).glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out


class TestNearMissWiringPositiveCase(_Base):

    def test_within_window_writes_one_row(self):
        # crypto-oversold-bounce: threshold rsi=30 (below).
        # rsi=33 is above (no trigger), distance=3, ratio=10% → IN window.
        ev = _FakeSignalEvent(
            strategy_id="crypto-oversold-bounce",
            symbol="ETH/USD",
            raw_signal={"rsi": 33.0},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNotNone(result)
        rows = self._read_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["strategy_id"], "crypto-oversold-bounce")
        self.assertEqual(row["symbol"], "ETH/USD")
        self.assertEqual(row["metric_name"], "rsi")
        self.assertAlmostEqual(row["threshold"], 30.0)
        self.assertAlmostEqual(row["current_value"], 33.0)
        # HARD invariants — every row.
        self.assertFalse(row["is_paper_trade"])
        self.assertFalse(row["is_signal"])

    def test_within_window_above_strategy(self):
        # crypto-momentum: threshold rsi=60 (above).
        # rsi=55 is below (no trigger), distance=5, ratio ~8% → IN window.
        ev = _FakeSignalEvent(
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            raw_signal={"rsi": 55.0, "move_24h_pct": 4.0},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNotNone(result)
        rows = self._read_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["is_paper_trade"])
        self.assertFalse(rows[0]["is_signal"])


class TestNearMissWiringNegativeCases(_Base):

    def test_far_from_threshold_writes_nothing(self):
        # crypto-momentum: threshold rsi=60. rsi=40 is 33% below — outside
        # the 15% window.
        ev = _FakeSignalEvent(
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            raw_signal={"rsi": 40.0},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNone(result)
        self.assertEqual(self._read_rows(), [])

    def test_hit_threshold_writes_nothing(self):
        # crypto-oversold-bounce: rsi=25 IS in the trigger region (<30).
        # That's a HIT, not a near-miss.
        ev = _FakeSignalEvent(
            strategy_id="crypto-oversold-bounce",
            symbol="ETH/USD",
            raw_signal={"rsi": 25.0},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNone(result)
        self.assertEqual(self._read_rows(), [])

    def test_unknown_strategy_writes_nothing(self):
        ev = _FakeSignalEvent(
            strategy_id="some-strategy-not-in-map",
            symbol="AAPL",
            raw_signal={"rsi": 55.0},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNone(result)


class TestNearMissWiringFailSoft(_Base):

    def test_missing_metric_writes_nothing(self):
        # Event has no rsi in raw_signal at all.
        ev = _FakeSignalEvent(
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            raw_signal={"signal_state": "REJECT"},
        )
        result = maybe_record_near_miss_from_signal_event(ev)
        self.assertIsNone(result)

    def test_bogus_event_does_not_raise(self):
        # An object missing the expected attributes must NOT raise.
        class _Empty: pass
        result = maybe_record_near_miss_from_signal_event(_Empty())
        # Either None (no strategy_id) or fail-soft False — must NOT raise.
        self.assertIsNone(result)


class TestDefaultMapShape(unittest.TestCase):

    def test_default_map_contains_required_entries(self):
        # Spec says these four strategies must be in the default map.
        required = {
            "crypto-oversold-bounce": ("rsi",         30.0, "below"),
            "crypto-momentum":        ("rsi",         60.0, "above"),
            "momentum-long":          ("breakout_pct", 0.02, "above"),
            "overbought-short":       ("rsi",         72.0, "above"),
        }
        for sid, (metric, thr, direction) in required.items():
            self.assertIn(sid, DEFAULT_STRATEGY_THRESHOLD_MAP)
            got_metric, got_thr, got_dir = DEFAULT_STRATEGY_THRESHOLD_MAP[sid]
            self.assertEqual(got_metric, metric)
            self.assertAlmostEqual(got_thr, thr)
            self.assertEqual(got_dir, direction)

    def test_window_default_is_15_percent(self):
        # Spec calls for ~15%.
        self.assertAlmostEqual(NEAR_MISS_WINDOW_RATIO_DEFAULT, 0.15)


if __name__ == "__main__":
    unittest.main()

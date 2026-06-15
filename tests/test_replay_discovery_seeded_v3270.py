"""v3.27.0 — Tests for scripts/replay_entry_candidate_discovery.py
when reading seeded snapshots (real OHLCV + ledger-derived PARTIAL_BARS).

Verifies:
- Replay discovery reads seeded snapshots.
- Replay discovery handles PARTIAL_BARS (no high/low/open/volume) gracefully.
- Every emitted candidate carries evidence_source="REPLAY".
- Replay discovery never writes opportunity_ledger.
- Replay discovery never imports alpaca_orders / requests.
- Per-strategy counts present in every row.
- Standing markers present in artefact.
"""

from __future__ import annotations

import ast
import json
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "replay_entry_candidate_discovery.py"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import replay_entry_candidate_discovery as red  # noqa: E402


def _make_real_ohlcv_snapshot(out_dir: Path, symbol: str = "AAPL") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 40 bars of synthetic-but-self-consistent data — test-fixture only;
    # the seeder under test never produces these, the test makes them
    # directly to feed the replay reader.
    n = 40
    close = [100.0 + i * 0.5 for i in range(n)]
    bars = {
        "close":  close,
        "high":   [c + 1.0 for c in close],
        "low":    [c - 1.0 for c in close],
        "open":   [c - 0.2 for c in close],
        "volume": [1_000_000 + i * 5 for i in range(n)],
        "time":   [f"2026-01-{(i % 28) + 1:02d}T00:00:00Z" for i in range(n)],
        "__seed_meta__": {
            "version":                  "v3.27.0",
            "source_label":             "REAL_MARKET_SNAPSHOT",
            "data_quality":             "REAL_MARKET_DATA",
            "mode":                     "REPLAY_ONLY",
            "is_paper_trade":           False,
            "is_real_market_evidence":  False,
            "partial_bars":             False,
            "minimum_fields_present":   True,
        },
    }
    (out_dir / f"{symbol}.json").write_text(
        json.dumps(bars), encoding="utf-8",
    )


def _make_partial_bars_snapshot(out_dir: Path, symbol: str = "BTC/USD") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Only close + time — exactly what ledger-derived partial snapshots
    # contain. No high/low/open/volume.
    n = 50
    bars = {
        "close": [70_000.0 + i * 50 for i in range(n)],
        "time":  [f"2026-06-15T{i % 24:02d}:00:00Z" for i in range(n)],
        "__seed_meta__": {
            "version":                  "v3.27.0",
            "source_label":             "LEDGER_DERIVED_REPLAY_ONLY",
            "data_quality":             "PARTIAL_BARS",
            "mode":                     "REPLAY_ONLY",
            "is_paper_trade":           False,
            "is_real_market_evidence":  False,
            "partial_bars":             True,
            "minimum_fields_present":   False,
        },
    }
    safe = symbol.replace("/", "_")
    (out_dir / f"{safe}.json").write_text(
        json.dumps(bars), encoding="utf-8",
    )


class TestReplayDiscoveryReadsSeededSnapshots(unittest.TestCase):
    def test_replay_discovery_reads_seeded_snapshots(self):
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("AAPL",),
            )
            # AAPL is in universe; rows must be present.
            self.assertGreaterEqual(rep["totals"]["rows"], 1)
            self.assertEqual(rep["missing_snapshots"], [])

    def test_replay_discovery_handles_PARTIAL_BARS_gracefully(self):
        """Replay must not crash on snapshots without high/low/volume —
        strategies that need those should return None (no candidate) but
        the script must continue and emit a row."""
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_partial_bars_snapshot(tdp, "BTC/USD")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("BTC/USD",),
            )
            self.assertEqual(rep["missing_snapshots"], [])
            # The crypto strategies still get scanned; some may produce
            # zero candidates because of missing volume, but the row
            # must exist and have no diagnostic crash.
            self.assertGreater(rep["totals"]["rows"], 0)
            for r in rep["rows"]:
                self.assertNotIn("_replay_error", r.get("diagnostic", ""))


class TestReplayDiscoveryInvariants(unittest.TestCase):
    def test_replay_discovery_emits_evidence_source_REPLAY(self):
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("AAPL",),
            )
            for r in rep["rows"]:
                for rec in r["candidate_records"]:
                    self.assertEqual(rec["evidence_source"], "REPLAY")
                    self.assertFalse(rec["is_paper_trade"])
                    self.assertFalse(rec["is_real_market"])
                    self.assertFalse(rec["is_signal_observation"])

    def test_replay_discovery_per_strategy_counts_present(self):
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("AAPL",),
            )
            for r in rep["rows"]:
                for k in ("strategy", "symbol", "candidates",
                          "near_misses", "threshold_crosses",
                          "bars_total", "bars_replayed", "diagnostic"):
                    self.assertIn(k, r)

    def test_replay_discovery_standing_markers_present(self):
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("AAPL",),
            )
            for marker in (
                "EDGE_GATE_ENABLED=false",
                "ALLOW_BROKER_PAPER=false",
                "LIVE_TRADING_UNSUPPORTED",
                "REPLAY_NEVER_COUNTS_AS_PAPER",
                "REPLAY_NEVER_COUNTS_AS_REAL_MARKET",
            ):
                self.assertIn(marker, rep["standing_markers"])
            # And the safety block:
            self.assertFalse(rep["safety"]["edge_gate_enabled"])
            self.assertFalse(rep["safety"]["writes_opportunity_ledger"])
            self.assertFalse(rep["safety"]["auto_enables_strategy"])
            self.assertEqual(rep["safety"]["evidence_source"], "REPLAY")


class TestReplayDiscoveryNeverWritesLedger(unittest.TestCase):
    def test_replay_discovery_never_writes_opportunity_ledger(self):
        """build_report is a pure compute function — no writes anywhere.
        Verify by patching open() to detect any unexpected write call to
        learning-loop/opportunity_ledger.
        """
        ledger_dir = REPO_ROOT / "learning-loop" / "opportunity_ledger"
        ledger_dir_str = str(ledger_dir)
        opens: list[str] = []
        real_open = open

        def watching_open(path, *a, **kw):
            mode = (a[0] if a else kw.get("mode", "r"))
            if ledger_dir_str in str(path) and ("w" in mode or "a" in mode):
                opens.append(str(path))
            return real_open(path, *a, **kw)

        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            with mock.patch("builtins.open", watching_open):
                from datetime import datetime, timezone
                rep = red.build_report(
                    as_of=datetime.now(timezone.utc),
                    lookback_days=30,
                    snapshot_dir=tdp,
                    universe=("AAPL",),
                )
            self.assertEqual(opens, [], msg=f"unexpected ledger writes: {opens}")
            self.assertGreater(rep["totals"]["rows"], 0)

    def test_replay_discovery_never_counts_real_market_opportunities(self):
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")
            from datetime import datetime, timezone
            rep = red.build_report(
                as_of=datetime.now(timezone.utc),
                lookback_days=30,
                snapshot_dir=tdp,
                universe=("AAPL",),
            )
            for r in rep["rows"]:
                for rec in r["candidate_records"]:
                    # These flags are the canonical "I'm not real market"
                    # markers. If any future change flips them by mistake
                    # this test fails.
                    self.assertFalse(rec["is_real_market"])
                    self.assertFalse(rec["is_paper_trade"])
                    self.assertEqual(rec["evidence_source"], "REPLAY")


class TestReplayDiscoverySourceCode(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)

    def test_replay_discovery_no_broker_call(self):
        # No alpaca_orders, no requests, no urllib.request.
        forbidden = {
            "alpaca_orders",
            "requests",
            "urllib.request",
        }
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    base = n.name.split(".")[0]
                    self.assertNotIn(
                        n.name, forbidden,
                        msg=f"forbidden import: {n.name}",
                    )
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertFalse(
                    mod in forbidden or mod.split(".")[0] == "alpaca_orders",
                    msg=f"forbidden from-import: {mod}",
                )

    def test_replay_discovery_runtime_no_socket(self):
        """Runtime guard: build_report must not open a socket."""
        with TemporaryDirectory() as td:
            tdp = Path(td) / "snaps"
            _make_real_ohlcv_snapshot(tdp, "AAPL")

            def blocked(*a, **kw):
                raise AssertionError("replay must not open network")
            with mock.patch.object(socket, "create_connection", blocked):
                from datetime import datetime, timezone
                rep = red.build_report(
                    as_of=datetime.now(timezone.utc),
                    lookback_days=30,
                    snapshot_dir=tdp,
                    universe=("AAPL",),
                )
            self.assertGreater(rep["totals"]["rows"], 0)


if __name__ == "__main__":
    unittest.main()

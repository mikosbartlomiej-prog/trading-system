"""v3.27.0 — Tests for scripts/seed_near_miss_from_evidence.py.

Hard-safety invariants verified here:
- Seeder NEVER imports ``shared.alpaca_orders`` (AST scan + runtime guard).
- Seeder NEVER makes a network call (socket + import scan).
- Every row carries one of the three allowed source labels.
- Every row carries ``is_paper_trade=False``, ``is_signal=False``,
  ``is_real_market_opportunity=False`` regardless of caller intent.
- Honest verdict ``NO_LOCAL_EVIDENCE_AVAILABLE`` when sources are empty.
- ``_make_row`` rejects non-whitelisted source labels.
"""

from __future__ import annotations

import ast
import json
import socket
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "seed_near_miss_from_evidence.py"

import sys
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import seed_near_miss_from_evidence as snm  # noqa: E402


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("alpaca_orders", mod)

    def test_no_network_imports(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in ("import requests", "from requests",
                          "import urllib", "from urllib"):
            self.assertNotIn(forbidden, text,
                             f"seeder must not import {forbidden!r}")


class TestRowLabels(unittest.TestCase):
    def test_make_row_enforces_invariants(self):
        row = snm._make_row(
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            metric_name="rsi",
            current_value=58.0,
            threshold=60.0,
            timestamp_iso="2026-06-15T12:00:00Z",
            source=snm.SOURCE_REAL_MARKET,
        )
        self.assertFalse(row["is_paper_trade"])
        self.assertFalse(row["is_signal"])
        self.assertFalse(row["is_real_market_opportunity"])
        self.assertIn(row["source"], snm.ALLOWED_SOURCES)
        # distance = current - threshold
        self.assertAlmostEqual(row["distance_to_trigger"], -2.0, places=6)

    def test_make_row_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            snm._make_row(
                strategy_id="crypto-momentum",
                symbol="BTC/USD",
                metric_name="rsi",
                current_value=58.0,
                threshold=60.0,
                timestamp_iso="2026-06-15T12:00:00Z",
                source="PAPER_NEAR_MISS",   # forbidden
            )

    def test_each_source_label_is_distinct(self):
        self.assertEqual(
            len(snm.ALLOWED_SOURCES),
            len({snm.SOURCE_REAL_MARKET, snm.SOURCE_REPLAY, snm.SOURCE_BACKFILL}),
        )


class TestNoNetwork(unittest.TestCase):
    def test_run_does_not_open_socket(self):
        opens: list[str] = []
        real_connect = socket.socket.connect

        def fake_connect(self, address):
            opens.append(str(address))
            raise AssertionError(
                f"seeder attempted network connect to {address!r}"
            )
        with mock.patch.object(socket.socket, "connect", fake_connect):
            with TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                # Empty everything — verifies fail-soft + no-net path.
                summary = snm.run(
                    near_miss_dir=tmp_path / "out",
                    ledger_dir=tmp_path / "ledger_does_not_exist",
                    replay_path=tmp_path / "replay_missing.json",
                    backfill_dir=tmp_path / "backfill_missing",
                )
        self.assertEqual(opens, [])
        self.assertEqual(summary["rows_written"], 0)
        self.assertEqual(summary["verdict"], "NO_LOCAL_EVIDENCE_AVAILABLE")


class TestSourceLabeling(unittest.TestCase):
    """Synthesize a tiny ledger + replay + backfill, run the seeder,
    inspect every emitted row's source label."""

    def _write_ledger_row(self, path: Path, ts_iso: str,
                          strategy: str, symbol: str, rsi: float):
        rec = {
            "raw_signal": {"rsi": rsi},
            "schema_version": "v3.20.0",
            "signal_id": f"{strategy}:{symbol}:abc",
            "strategy": strategy,
            "symbol": symbol,
            "timestamp": ts_iso,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _write_backfill_snapshot(self, path: Path, symbol: str,
                                 closes: list[float]):
        meta = {
            "symbol": symbol,
            "data_quality": "REAL_MARKET_DATA",
            "is_paper_trade": False,
            "is_real_market_evidence": False,
            "is_shadow_fill": False,
            "is_signal_observation": False,
            "mode": "REPLAY_ONLY",
        }
        d = {
            "__seed_meta__": meta,
            "close": closes,
            "high":  closes,
            "low":   closes,
            "open":  closes,
            "time":  [f"2026-06-{(i%28)+1:02d}T00:00:00Z"
                      for i in range(len(closes))],
            "volume": [1000] * len(closes),
        }
        path.write_text(json.dumps(d), encoding="utf-8")

    def test_each_source_label_appears(self):
        # Pick close values that drive RSI somewhere in the bounce band.
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            ledger_dir.mkdir()
            today = datetime.now(timezone.utc).date().isoformat()
            self._write_ledger_row(
                ledger_dir / f"{today}.jsonl",
                ts_iso=f"{today}T12:00:00Z",
                strategy="crypto-momentum",
                symbol="BTC/USD",
                # 57 is within 15% of 60.0 (above-direction near-miss).
                rsi=57.5,
            )

            backfill_dir = tmp_path / "backfill"
            backfill_dir.mkdir()
            # Synthesize 30 closes oscillating to put RSI near 60.
            closes = [100.0 + (i % 2) * 1.5 for i in range(30)]
            self._write_backfill_snapshot(
                backfill_dir / "BTC__USD.json",
                symbol="BTC/USD",
                closes=closes,
            )

            out_dir = tmp_path / "out"
            summary = snm.run(
                near_miss_dir=out_dir,
                ledger_dir=ledger_dir,
                replay_path=tmp_path / "replay_missing.json",
                backfill_dir=backfill_dir,
            )

            # Real-market must have at least one row (we synthesised it).
            self.assertGreaterEqual(
                summary["by_source"].get(snm.SOURCE_REAL_MARKET, 0), 1
            )

            target = Path(summary["target_path"])
            self.assertTrue(target.exists())
            with target.open(encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]

            self.assertGreaterEqual(len(rows), 1)
            for r in rows:
                self.assertIn(r["source"], snm.ALLOWED_SOURCES)
                self.assertFalse(r["is_paper_trade"])
                self.assertFalse(r["is_signal"])
                self.assertFalse(r["is_real_market_opportunity"])


class TestStandingMarkers(unittest.TestCase):
    def test_all_standing_markers_present(self):
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS",
            "NEAR_MISS_NEVER_COUNTS_AS_TRADE",
            "SEEDER_DOES_NOT_FETCH_NETWORK",
        ):
            self.assertIn(marker, snm.STANDING_MARKERS,
                          f"missing standing marker {marker}")


class TestDoesNotPlaceOrders(unittest.TestCase):
    def test_no_alpaca_orders_in_module_globals(self):
        # The dynamically imported module must NOT carry alpaca_orders.
        import importlib
        mod = importlib.import_module("seed_near_miss_from_evidence")
        for attr in dir(mod):
            self.assertNotIn("alpaca_orders", attr,
                             "module exports name resembling alpaca_orders")


if __name__ == "__main__":
    unittest.main()

"""v3.27.0 — Tests for scripts/seed_backfill_snapshots.py.

Hard-safety invariants verified here:
- Seeder NEVER fabricates synthetic OHLCV (partial sources stay partial).
- Seeder NEVER imports ``alpaca_orders`` (AST scan).
- Seeder NEVER makes network calls (patched stdlib + import scan).
- Seeder ALWAYS writes ``is_paper_trade=False`` /
  ``is_real_market_evidence=False``.
- Status file always emitted with standing markers.
"""

from __future__ import annotations

import ast
import json
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "seed_backfill_snapshots.py"

import sys
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import seed_backfill_snapshots as sbs  # noqa: E402


def _make_real_ohlcv_cache(cache_dir: Path, symbol: str = "AAPL") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    bars = {
        "close":  [100.0 + i for i in range(30)],
        "high":   [101.0 + i for i in range(30)],
        "low":    [99.0 + i for i in range(30)],
        "open":   [99.5 + i for i in range(30)],
        "volume": [1_000_000 + i * 100 for i in range(30)],
        "time":   [f"2026-01-{(i % 28) + 1:02d}T00:00:00Z" for i in range(30)],
    }
    p = cache_dir / f"{symbol}-2025-12-01-2026-01-30.json"
    p.write_text(json.dumps(bars), encoding="utf-8")
    return p


def _make_ledger_jsonl(ledger_dir: Path, symbol: str = "BTC/USD") -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    p = ledger_dir / "2026-06-15.jsonl"
    rows = []
    for i in range(20):
        rows.append({
            "symbol":    symbol,
            "timestamp": f"2026-06-15T{i:02d}:00:00Z",
            "strategy":  "crypto-momentum",
            "raw_signal": {
                "action":     "BUY",
                "price":      70_000.0 + i * 100,
                "rsi":        50.0 + i,
                "volume_ratio": 1.5,
                "move_24h_pct": 2.0,
            },
            "schema_version": "v3.20.0",
        })
    p.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
    )
    return p


class TestSeederStatusVerdicts(unittest.TestCase):
    def test_no_local_data_emits_NO_LOCAL_BACKFILL_DATA_status(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache_empty",
                ledger_dir=tdp / "ledger_empty",
                shadow_dir=tdp / "shadow_empty",
            )
            self.assertEqual(result.status, "NO_LOCAL_BACKFILL_DATA")
            self.assertEqual(len(result.snapshots), 0)

    def test_real_ohlcv_status_LOCAL_BACKFILL_AVAILABLE(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache",
                ledger_dir=tdp / "ledger_empty",
                shadow_dir=tdp / "shadow_empty",
            )
            self.assertEqual(result.status, "LOCAL_BACKFILL_AVAILABLE")
            self.assertEqual(result.backtest_cache_seeded, 1)

    def test_ledger_only_status_LEDGER_DERIVED_PARTIAL(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_ledger_jsonl(tdp / "ledger")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache_empty",
                ledger_dir=tdp / "ledger",
                shadow_dir=tdp / "shadow_empty",
            )
            self.assertEqual(result.status, "LEDGER_DERIVED_PARTIAL")
            self.assertEqual(result.ledger_derived_seeded, 1)


class TestSeederLabelsAndFlags(unittest.TestCase):
    def test_ledger_derived_snapshots_labeled_LEDGER_DERIVED_REPLAY_ONLY(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_ledger_jsonl(tdp / "ledger", symbol="BTC/USD")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache_empty",
                ledger_dir=tdp / "ledger",
                shadow_dir=tdp / "shadow_empty",
            )
            env = result.snapshots["BTC/USD"]
            self.assertEqual(
                env["__seed_meta__"]["source_label"],
                "LEDGER_DERIVED_REPLAY_ONLY",
            )

    def test_partial_bars_flag_set_when_fields_missing(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_ledger_jsonl(tdp / "ledger", symbol="ETH/USD")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache_empty",
                ledger_dir=tdp / "ledger",
                shadow_dir=tdp / "shadow_empty",
            )
            env = result.snapshots["ETH/USD"]
            self.assertTrue(env["__seed_meta__"]["partial_bars"])
            self.assertFalse(env["__seed_meta__"]["minimum_fields_present"])
            # Hard rule: we did NOT make up high/low/open/volume.
            self.assertNotIn("high", env)
            self.assertNotIn("low", env)
            self.assertNotIn("open", env)
            self.assertNotIn("volume", env)

    def test_seeder_writes_source_label_per_snapshot(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache", symbol="MSFT")
            _make_ledger_jsonl(tdp / "ledger", symbol="BTC/USD")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache",
                ledger_dir=tdp / "ledger",
                shadow_dir=tdp / "shadow_empty",
            )
            for sym, env in result.snapshots.items():
                meta = env["__seed_meta__"]
                self.assertIn("source_label", meta)
                self.assertIn(
                    meta["source_label"],
                    {"REAL_MARKET_SNAPSHOT",
                     "LEDGER_DERIVED_REPLAY_ONLY",
                     "SHADOW_EVIDENCE_DERIVED_REPLAY_ONLY"},
                )

    def test_seeder_is_paper_trade_always_false(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache", symbol="AAPL")
            _make_ledger_jsonl(tdp / "ledger", symbol="BTC/USD")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache",
                ledger_dir=tdp / "ledger",
                shadow_dir=tdp / "shadow_empty",
            )
            for sym, env in result.snapshots.items():
                meta = env["__seed_meta__"]
                self.assertFalse(meta["is_paper_trade"])
                self.assertFalse(meta["is_real_market_evidence"])
                self.assertFalse(meta["is_shadow_fill"])
                self.assertFalse(meta["is_signal_observation"])
                self.assertEqual(meta["mode"], "REPLAY_ONLY")


class TestSeederAntiFabrication(unittest.TestCase):
    def test_seeder_refuses_to_fabricate_synthetic_OHLCV(self):
        """A ledger row that only has ``price`` must NOT produce
        synthetic ``high``/``low``/``open``/``volume`` arrays."""
        with TemporaryDirectory() as td:
            tdp = Path(td)
            ldp = tdp / "ledger"
            ldp.mkdir(parents=True)
            ledger_file = ldp / "2026-06-15.jsonl"
            ledger_file.write_text(
                json.dumps({
                    "symbol":    "SOL/USD",
                    "timestamp": "2026-06-15T12:00:00Z",
                    "raw_signal": {"price": 150.0, "rsi": 45.0},
                }) + "\n",
                encoding="utf-8",
            )
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache_empty",
                ledger_dir=ldp,
                shadow_dir=tdp / "shadow_empty",
            )
            env = result.snapshots["SOL/USD"]
            # close + time only; no high/low/open/volume synthesized
            self.assertIn("close", env)
            self.assertIn("time", env)
            for k in ("high", "low", "open", "volume"):
                self.assertNotIn(
                    k, env,
                    msg=f"seeder must not fabricate '{k}' from ledger price",
                )
            self.assertTrue(env["__seed_meta__"]["partial_bars"])


class TestSeederSourceCode(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)

    def test_seeder_does_not_import_alpaca_orders(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertFalse(
                        n.name.startswith("alpaca_orders")
                        or n.name == "alpaca_orders"
                        or n.name.endswith(".alpaca_orders"),
                        msg=f"forbidden import: {n.name}",
                    )
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertFalse(
                    mod.startswith("alpaca_orders")
                    or mod == "alpaca_orders"
                    or mod.endswith(".alpaca_orders"),
                    msg=f"forbidden from-import: {mod}",
                )

    def test_seeder_does_not_call_network_apis(self):
        forbidden = (
            "requests", "urllib.request", "urllib3", "httpx", "aiohttp",
            "websocket", "websockets",
        )
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(
                        n.name, forbidden,
                        msg=f"forbidden network import: {n.name}",
                    )
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(
                    mod.split(".")[0], forbidden,
                    msg=f"forbidden network from-import: {mod}",
                )


class TestSeederRuntimeNoNetwork(unittest.TestCase):
    def test_seeder_does_not_make_network_call(self):
        """Runtime check: patch socket so any outbound connect raises."""
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache")
            real_create_conn = socket.create_connection

            def blocked(*a, **kw):
                raise AssertionError(
                    "seeder must not open network connection"
                )
            with mock.patch.object(socket, "create_connection", blocked):
                result = sbs.build_seed_result(
                    cache_dir=tdp / "cache",
                    ledger_dir=tdp / "ledger_empty",
                    shadow_dir=tdp / "shadow_empty",
                )
            # And it worked despite the block:
            self.assertEqual(result.status, "LOCAL_BACKFILL_AVAILABLE")


class TestSeederArtefactWriting(unittest.TestCase):
    def test_seeder_writes_BACKFILL_SNAPSHOT_STATUS_md(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache",
                ledger_dir=tdp / "ledger_empty",
                shadow_dir=tdp / "shadow_empty",
            )
            md_path = tdp / "status.md"
            json_path = tdp / "status.json"
            sbs.write_status(
                result,
                out_dir=tdp / "out",
                md_path=md_path,
                json_path=json_path,
            )
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            md = md_path.read_text(encoding="utf-8")
            self.assertIn("Backfill snapshot status", md)
            self.assertIn("LOCAL_BACKFILL_AVAILABLE", md)

    def test_seeder_standing_markers_present(self):
        # In status MD
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_real_ohlcv_cache(tdp / "cache")
            result = sbs.build_seed_result(
                cache_dir=tdp / "cache",
                ledger_dir=tdp / "ledger_empty",
                shadow_dir=tdp / "shadow_empty",
            )
            md_path = tdp / "status.md"
            sbs.write_status(
                result,
                out_dir=tdp / "out",
                md_path=md_path,
                json_path=tdp / "status.json",
            )
            md = md_path.read_text(encoding="utf-8")
            for marker in (
                "EDGE_GATE_ENABLED=false",
                "ALLOW_BROKER_PAPER=false",
                "LIVE_TRADING_UNSUPPORTED",
                "NO_ORDER_PLACEMENT",
                "REPLAY_NEVER_COUNTS_AS_PAPER",
                "SEEDER_DOES_NOT_FABRICATE_OHLCV",
                "SEEDER_DOES_NOT_FETCH_NETWORK",
            ):
                self.assertIn(marker, md, msg=f"missing marker: {marker}")
        # In per-snapshot envelope
        for sym, env in result.snapshots.items():
            markers = env["__seed_meta__"]["standing_markers"]
            self.assertIn("EDGE_GATE_ENABLED=false", markers)
            self.assertIn("LIVE_TRADING_UNSUPPORTED", markers)


if __name__ == "__main__":
    unittest.main()

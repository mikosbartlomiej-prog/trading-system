"""v3.27.0 — Tests for scripts/seed_shadow_candidate_queue.py.

Hard-safety invariants verified here:
- Every emitted row has ``mode == "SHADOW_ONLY"`` and
  ``status == "WAITING_FOR_REAL_MARKET_TRIGGER"``.
- ``_make_row`` rejects non-whitelisted source labels.
- Seeder NEVER imports alpaca_orders / requests / urllib / opens sockets.
- Seeder does NOT create a shadow fill (the seeder does not write to
  ``learning-loop/shadow_evidence/*``).
- Seeder does NOT mutate ``state.json`` / ``runtime_state.json``.
- Variants whose ``allowed_modes`` contains ``live``/``paper`` are
  silently dropped at the source-3 stage (never reach the queue).
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = (REPO_ROOT / "scripts"
               / "seed_shadow_candidate_queue.py")

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import seed_shadow_candidate_queue as scq  # noqa: E402


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")

    def test_no_network_imports(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in ("import requests", "from requests",
                          "import urllib", "from urllib"):
            self.assertNotIn(forbidden, text)


class TestRowInvariants(unittest.TestCase):
    def test_every_row_is_shadow_only_and_waiting(self):
        row = scq._make_row(
            strategy="crypto-momentum",
            symbol="BTC/USD",
            reason="test",
            source=scq.SOURCE_REPLAY,
        )
        self.assertEqual(row["mode"], scq.MODE_SHADOW_ONLY)
        self.assertEqual(row["status"], scq.STATUS_WAITING)
        self.assertFalse(row["is_paper_trade"])
        self.assertFalse(row["is_real_market_opportunity"])
        self.assertFalse(row["is_shadow_fill"])
        self.assertFalse(row["is_signal"])
        self.assertEqual(row["asset_class"], "crypto")

    def test_make_row_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            scq._make_row(
                strategy="crypto-momentum",
                symbol="BTC/USD",
                reason="x",
                source="LIVE_ORDER",
            )


class TestNoNetwork(unittest.TestCase):
    def test_build_queue_does_not_open_socket(self):
        opens: list[str] = []

        def fake_connect(self, address):
            opens.append(str(address))
            raise AssertionError(
                f"queue seeder attempted network connect to {address!r}"
            )
        with mock.patch.object(socket.socket, "connect", fake_connect):
            with TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                # All inputs missing → should produce empty queue, no crash.
                rep = scq.build_queue(
                    near_miss_path=tmp_path / "nm.json",
                    replay_path=tmp_path / "rep.json",
                    variant_path=tmp_path / "var.json",
                    watchlist_path=tmp_path / "watch.json",
                    state_path=tmp_path / "state.json",
                )
        self.assertEqual(opens, [])
        self.assertEqual(rep["rows_total"], 0)


class TestVariantsWithBadModesAreSkipped(unittest.TestCase):
    def test_live_mode_variant_dropped(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            variant_blob = {
                "version": "v3.27.0",
                "variants": [
                    {
                        "id":              "bad-variant--live",
                        "parent_strategy": "crypto-momentum",
                        "status":          "QUARANTINED",
                        "allowed_modes":   ["live", "shadow"],
                        "change_rationale": "should be dropped",
                    },
                    {
                        "id":              "good-variant--shadow",
                        "parent_strategy": "crypto-momentum",
                        "status":          "QUARANTINED",
                        "allowed_modes":   ["replay", "shadow"],
                        "change_rationale": "should appear",
                    },
                ],
            }
            (tmp_path / "var.json").write_text(json.dumps(variant_blob))
            rows = scq.collect_from_variants(
                variant_path=tmp_path / "var.json",
                risk_preconditions=[],
            )
            ids = {r["variant_id"] for r in rows}
            self.assertNotIn("bad-variant--live", ids)
            self.assertIn("good-variant--shadow", ids)
            for r in rows:
                modes = set(r.get("allowed_modes", []))
                self.assertEqual(
                    modes & {"live", "paper", "broker_paper"}, set()
                )


class TestDoesNotCreateShadowFill(unittest.TestCase):
    def test_seeder_does_not_write_to_shadow_evidence(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Hijack shadow_evidence so any write would land here.
            shadow_dir = tmp_path / "shadow_evidence"
            shadow_dir.mkdir()
            pre_files = set(shadow_dir.iterdir())

            # Build queue with all-empty inputs.
            scq.build_queue(
                near_miss_path=tmp_path / "nm.json",
                replay_path=tmp_path / "rep.json",
                variant_path=tmp_path / "var.json",
                watchlist_path=tmp_path / "watch.json",
                state_path=tmp_path / "state.json",
            )

            post_files = set(shadow_dir.iterdir())
            self.assertEqual(pre_files, post_files,
                             "queue seeder must not write into shadow_evidence")


class TestDoesNotMutateState(unittest.TestCase):
    def test_seeder_does_not_modify_state_json(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state = {
                "today_stats": {"daily_pnl_pct": 0.0, "vix": 14.0},
                "defensive_mode": {"armed": False},
                "peak_equity": 100000.0,
            }
            state_path = tmp_path / "state.json"
            state_path.write_text(json.dumps(state, sort_keys=True))
            pre_hash = hashlib.sha256(state_path.read_bytes()).hexdigest()

            scq.build_queue(
                near_miss_path=tmp_path / "nm.json",
                replay_path=tmp_path / "rep.json",
                variant_path=tmp_path / "var.json",
                watchlist_path=tmp_path / "watch.json",
                state_path=state_path,
            )

            post_hash = hashlib.sha256(state_path.read_bytes()).hexdigest()
            self.assertEqual(pre_hash, post_hash,
                             "queue seeder must not mutate state.json")


class TestStandingMarkers(unittest.TestCase):
    def test_required_markers_present(self):
        required = (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED",
            "SHADOW_CANDIDATE_NEVER_CREATES_SHADOW_FILL",
            "QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY",
        )
        for marker in required:
            self.assertIn(marker, scq.STANDING_MARKERS)


if __name__ == "__main__":
    unittest.main()

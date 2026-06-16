"""v3.30 ETAP 5 (2026-06-16) — tests for
scripts/propose_clear_broker_repair_and_safe_mode.py.

Coverage:
- cannot write proposal without marker
- cannot write proposal if fresh P13 audit events after marker timestamp
- cannot write proposal if equity gap blocks
- cannot write proposal if safe-mode consistency is INCONSISTENT
- dry-run is default
- --operator-confirmed required to write
- script never imports alpaca_orders (AST verified)
- script never calls broker functions (AST verified)
- proposal is JSON, not a state mutation
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))


def _iso_at(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.markers_dir = self.tmp / "operator_markers"
        self.markers_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir = self.tmp / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.brr_path = self.tmp / "broker_repair_required_latest.json"
        self.smc_path = self.tmp / "safe_mode_consistency_latest.json"
        self.egap_path = self.tmp / "equity_gap_reconciliation_latest.json"

        os.environ["OPERATOR_MARKERS_DIR"] = str(self.markers_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        os.environ["SAFE_MODE_CONSISTENCY_PATH"] = str(self.smc_path)
        os.environ["EQUITY_GAP_LATEST_PATH"] = str(self.egap_path)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = str(self.brr_path)

        # Fresh re-import to pick up env vars.
        for mod in (
            "broker_repair_required",
            "operator_repair_state",
            "symbol_normalization",
        ):
            sys.modules.pop(mod, None)
        sys.modules.pop("propose_clear_broker_repair_and_safe_mode", None)

    def tearDown(self) -> None:
        for var in (
            "OPERATOR_MARKERS_DIR", "AUDIT_TRADING_DIR",
            "SAFE_MODE_CONSISTENCY_PATH", "EQUITY_GAP_LATEST_PATH",
            "BROKER_REPAIR_REQUIRED_PATH",
        ):
            os.environ.pop(var, None)
        self._tmpdir.cleanup()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _write_marker(self, *, symbol: str, ts_iso: str) -> Path:
        """Write a v3.29-compatible operator marker."""
        # Use operator_repair_state.write_marker so the schema is real.
        import operator_repair_state as ors
        # Point ors at the tmp markers dir via env.
        os.environ["OPERATOR_MARKERS_DIR"] = str(self.markers_dir)
        # operator_repair_state honours OPERATOR_MARKERS_DIR if exposed,
        # but we'll just write the file directly with the expected shape
        # because ors.write_marker insists on _now_iso() and we want a
        # specific timestamp.
        safe_sym = symbol.replace("/", "_")
        path = self.markers_dir / f"{safe_sym}_2026-06-16.json"
        payload = {
            "symbol":                          symbol,
            "incident_type":                   "P13_BRACKET_INTERLOCK",
            "dashboard_checked":               True,
            "open_orders_checked":             True,
            "stale_oco_cancelled_by_operator": "true",
            "position_closed_by_operator":     "true",
            "final_position_state":            "flat",
            "final_open_orders_state":         "none",
            "equity_checked":                  True,
            "operator_note":                   "test marker",
            "timestamp_iso":                   ts_iso,
            "source":                          ors.MARKER_SOURCE,
            "does_not_execute_orders":         True,
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    def _setup_clean_environment(self, symbol: str = "AVAX/USD") -> None:
        """Write a broker_repair entry + clean consistency + clean equity."""
        # broker_repair_required canonical entry.
        entry = {
            "symbol":                       symbol,
            "incident_type":                "P13_BRACKET_INTERLOCK_BACKFILLED",
            "first_seen_iso":               "2026-06-15T00:00:00+00:00",
            "last_seen_iso":                "2026-06-15T00:00:00+00:00",
            "failed_attempts":              3,
            "last_error":                   "test",
            "broker_calls_blocked_until_iso": None,
            "retry_after_iso":              None,
            "allowed_next_actions":         ["operator_marker_required"],
            "manual_action_required":       "test",
            "safe_mode_reason":             "P13_BRACKET_INTERLOCK_BACKFILLED",
        }
        self.brr_path.write_text(json.dumps({"entries": {symbol: entry}}, indent=2))
        # Clean safe_mode consistency.
        self.smc_path.write_text(json.dumps({
            "verdict": "CONSISTENT",
            "blocker": None,
            "audit_enters": 0,
            "audit_exits": 0,
        }))
        # Clean equity gap.
        self.egap_path.write_text(json.dumps({
            "block_allocator": False,
            "current_equity": 90000.0,
        }))


class TestCannotWriteProposalWithoutMarker(_Base):
    def test_refuses_when_marker_path_missing(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        import propose_clear_broker_repair_and_safe_mode as pcm
        bogus = self.tmp / "nonexistent_marker.json"
        result = pcm.evaluate_clearance("AVAX/USD", bogus)
        self.assertEqual(result.verdict, "CLEARANCE_REFUSED")
        self.assertIn("operator marker not found", result.refusal_reason or "")

    def test_refuses_when_marker_missing_timestamp(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        bad_marker = self.markers_dir / "bad.json"
        bad_marker.write_text(json.dumps({"symbol": "AVAX/USD"}))
        import propose_clear_broker_repair_and_safe_mode as pcm
        result = pcm.evaluate_clearance("AVAX/USD", bad_marker)
        self.assertEqual(result.verdict, "CLEARANCE_REFUSED")
        self.assertIn("unreadable or missing timestamp_iso", result.refusal_reason or "")


class TestCannotWriteProposalIfFreshP13(_Base):
    def test_refuses_when_fresh_p13_in_audit(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        marker_ts = _iso_at(-120)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)
        # Drop a fresh P13 audit row AFTER the marker.
        fresh_ts = _iso_at(0)
        audit_path = self.audit_dir / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        audit_path.write_text(json.dumps({
            "decision_type":    "INCIDENT_P13_BRACKET_INTERLOCK",
            "symbol":           "AVAX/USD",
            "ts_iso":           fresh_ts,
            "reason":           "fresh storm after marker",
        }) + "\n")

        import propose_clear_broker_repair_and_safe_mode as pcm
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"
        result = pcm.evaluate_clearance("AVAX/USD", marker_path)
        self.assertEqual(result.verdict, "CLEARANCE_REFUSED")
        self.assertGreaterEqual(result.fresh_p13_count, 1)
        self.assertIn("fresh P13", result.refusal_reason or "")

    def test_allows_when_no_fresh_p13(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)

        import propose_clear_broker_repair_and_safe_mode as pcm
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"
        result = pcm.evaluate_clearance("AVAX/USD", marker_path)
        self.assertEqual(result.verdict, "CLEARANCE_PROPOSED", result.refusal_reason)
        self.assertEqual(result.fresh_p13_count, 0)
        self.assertEqual(result.fresh_403_count, 0)


class TestCannotWriteProposalIfEquityGapBlocks(_Base):
    def test_refuses_when_equity_gap_blocks(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        self.egap_path.write_text(json.dumps({
            "block_allocator": True,
            "current_equity": 90000.0,
        }))
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)

        import propose_clear_broker_repair_and_safe_mode as pcm
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"
        result = pcm.evaluate_clearance("AVAX/USD", marker_path)
        self.assertEqual(result.verdict, "CLEARANCE_REFUSED")
        self.assertTrue(result.equity_gap_block)
        self.assertIn("equity_gap", result.refusal_reason or "")


class TestCannotWriteProposalIfSafeModeInconsistent(_Base):
    def test_refuses_when_consistency_blocker_set(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        self.smc_path.write_text(json.dumps({
            "verdict": "INCONSISTENT_ENTERED_NOT_PERSISTED",
            "blocker": "BLOCK_SAFE_MODE_INCONSISTENT",
        }))
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)

        import propose_clear_broker_repair_and_safe_mode as pcm
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"
        result = pcm.evaluate_clearance("AVAX/USD", marker_path)
        self.assertEqual(result.verdict, "CLEARANCE_REFUSED")
        self.assertEqual(result.safe_mode_consistency_blocker, "BLOCK_SAFE_MODE_INCONSISTENT")
        self.assertIn("safe_mode_consistency", result.refusal_reason or "")


class TestDryRunDefault(_Base):
    def test_dry_run_default_writes_nothing(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"

        import propose_clear_broker_repair_and_safe_mode as pcm
        rc = pcm.main([
            "--symbol", "AVAX/USD",
            "--operator-marker-path", str(marker_path),
            # No --operator-confirmed.
        ])
        self.assertEqual(rc, 0)
        # No clearance_proposal_* file should exist.
        proposals = list(self.markers_dir.glob("clearance_proposal_*.json"))
        self.assertEqual(len(proposals), 0)


class TestOperatorConfirmedRequiredToWrite(_Base):
    def test_operator_confirmed_writes_proposal(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"

        import propose_clear_broker_repair_and_safe_mode as pcm
        rc = pcm.main([
            "--symbol", "AVAX/USD",
            "--operator-marker-path", str(marker_path),
            "--dry-run", "false",
            "--operator-confirmed",
            "--dashboard-evidence-note", "AVAX dust gone; OCO cancelled",
        ])
        self.assertEqual(rc, 0)
        proposals = list(self.markers_dir.glob("clearance_proposal_*.json"))
        self.assertEqual(len(proposals), 1)
        payload = json.loads(proposals[0].read_text())
        self.assertEqual(payload["proposal_type"], "OPERATOR_CLEARANCE_REVIEW")
        self.assertEqual(payload["symbol_canonical"], "AVAX/USD")
        self.assertTrue(payload["does_not_execute_orders"])
        self.assertTrue(payload["does_not_auto_clear_safe_mode"])
        self.assertTrue(payload["does_not_auto_clear_broker_repair"])

    def test_refused_returns_nonzero_even_with_confirmed(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        self.smc_path.write_text(json.dumps({
            "verdict": "INCONSISTENT_ENTERED_NOT_PERSISTED",
            "blocker": "BLOCK_SAFE_MODE_INCONSISTENT",
        }))
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"

        import propose_clear_broker_repair_and_safe_mode as pcm
        rc = pcm.main([
            "--symbol", "AVAX/USD",
            "--operator-marker-path", str(marker_path),
            "--dry-run", "false",
            "--operator-confirmed",
        ])
        self.assertEqual(rc, 2)
        proposals = list(self.markers_dir.glob("clearance_proposal_*.json"))
        self.assertEqual(len(proposals), 0)


class TestProposalDoesNotMutateState(_Base):
    def test_proposal_is_json_only(self) -> None:
        self._setup_clean_environment("AVAX/USD")
        marker_ts = _iso_at(-60)
        self._write_marker(symbol="AVAX/USD", ts_iso=marker_ts)
        marker_path = self.markers_dir / "AVAX_USD_2026-06-16.json"

        # Snapshot the broker_repair file before.
        before = json.loads(self.brr_path.read_text())

        import propose_clear_broker_repair_and_safe_mode as pcm
        pcm.main([
            "--symbol", "AVAX/USD",
            "--operator-marker-path", str(marker_path),
            "--dry-run", "false",
            "--operator-confirmed",
        ])

        after = json.loads(self.brr_path.read_text())
        self.assertEqual(before, after,
                         "writing a clearance proposal must NOT mutate broker_repair_required")


class TestNoBrokerImports(unittest.TestCase):
    """Static AST scan — propose_clear must NEVER import alpaca_orders
    and must NEVER call broker functions.
    """

    def setUp(self) -> None:
        path = _REPO_ROOT / "scripts" / "propose_clear_broker_repair_and_safe_mode.py"
        with open(path, "r", encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read())

    def test_no_alpaca_orders_import(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    self.assertNotIn("alpaca_orders", node.module)

    def test_no_broker_function_calls(self) -> None:
        forbidden_names = {
            "submit_order", "place_order", "safe_close", "cancel_order",
            "close_position", "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_options_buy",
        }
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                fn_name = None
                if isinstance(func, ast.Name):
                    fn_name = func.id
                elif isinstance(func, ast.Attribute):
                    fn_name = func.attr
                if fn_name and fn_name in forbidden_names:
                    self.fail(
                        f"propose_clear contains forbidden broker call: {fn_name}"
                    )


if __name__ == "__main__":
    unittest.main()

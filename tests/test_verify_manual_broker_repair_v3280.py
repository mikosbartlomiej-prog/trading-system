"""v3.28 ETAP 6 (2026-06-16) — tests for scripts/verify_manual_broker_repair.py.

The verifier is read-only by default and must NEVER call the broker,
import ``alpaca_orders``, or auto-clear ``safe_mode``. These tests
assert all of the above + the documented behavior contract.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "verify_manual_broker_repair.py"


def _load_module():
    """Load the script as a module so we can call ``main`` directly.

    Register in ``sys.modules`` BEFORE exec so dataclasses can resolve
    forward refs (required on Python 3.9 with
    ``from __future__ import annotations``).
    """
    if "verify_manual_broker_repair" in sys.modules:
        del sys.modules["verify_manual_broker_repair"]
    spec = importlib.util.spec_from_file_location(
        "verify_manual_broker_repair", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["verify_manual_broker_repair"] = module
    spec.loader.exec_module(module)
    return module


class _IsolatedEnv(unittest.TestCase):
    """Provide a tmp repo-rooted layout for runtime_state + audit + markers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._audit_dir = self._tmp_path / "audit"
        self._marker_dir = self._tmp_path / "operator_markers"
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._marker_dir.mkdir(parents=True, exist_ok=True)
        self._prev_audit = os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ["AUDIT_TRADING_DIR"] = str(self._audit_dir)
        self.mod = _load_module()
        # Re-point the module's _REPO_ROOT for read-only state reads.
        self._patch_repo = mock.patch.object(self.mod, "_REPO_ROOT", self._tmp_path)
        self._patch_repo.start()

    def tearDown(self):
        self._patch_repo.stop()
        if self._prev_audit is None:
            os.environ.pop("AUDIT_TRADING_DIR", None)
        else:
            os.environ["AUDIT_TRADING_DIR"] = self._prev_audit
        self._tmp.cleanup()

    # Helpers ──────────────────────────────────────────────────────────────
    def _write_marker(self, name: str = "marker.txt") -> str:
        p = self._marker_dir / name
        p.write_text("operator: alice\nts: 2026-06-16T00:00:00+00:00\n",
                     encoding="utf-8")
        return str(p)

    def _seed_broker_repair(self, sym: str = "AVAX/USD",
                            attempts: int = 3) -> None:
        ll_dir = self._tmp_path / "learning-loop"
        ll_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "v3.28",
            "updated_at":     "2026-06-16T00:00:00+00:00",
            "entries": {
                sym: {
                    "symbol":            sym,
                    "incident_type":     "P13_BRACKET_INTERLOCK",
                    "first_seen_iso":    "2026-06-15T05:46:00+00:00",
                    "last_seen_iso":     "2026-06-15T15:21:19+00:00",
                    "failed_attempts":   attempts,
                    "last_error":        "Alpaca 403 insufficient balance",
                    "manual_action_required":          "see runbook",
                    "allowed_next_actions":            ["operator_marker_required"],
                    "safe_mode_reason":                "P13",
                    "retry_after_iso":                 None,
                    "broker_calls_blocked_until_iso":  None,
                },
            },
        }
        (ll_dir / "broker_repair_required_latest.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def _seed_runtime_state(self, *, safe_mode_active: bool = True,
                             forced: bool = False) -> None:
        ll_dir = self._tmp_path / "learning-loop"
        ll_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "safe_mode": {
                "active":     safe_mode_active,
                "reason":     "P13",
                "entered_at": "2026-06-15T05:46:00+00:00",
                "trigger":    "INCIDENT_P13_BRACKET_INTERLOCK",
                "forced":     forced,
            },
        }
        (ll_dir / "runtime_state.json").write_text(
            json.dumps(payload), encoding="utf-8")


class TestVerifyManualBrokerRepair(_IsolatedEnv):

    # 1. dry-run default is true (string parsing).
    def test_01_dry_run_default_is_true(self):
        args = self.mod._parse_args(["--symbol", "AVAX/USD"])
        self.assertEqual(args.dry_run, "true")
        self.assertTrue(self.mod._str_to_bool(args.dry_run))

    # 2. Default verdict is NOT_SAFE_TO_CLEAR on any error (no marker, no state).
    def test_02_default_verdict_not_safe_on_error(self):
        result = self.mod.evaluate_local_evidence("AVAX/USD", "")
        self.assertEqual(result.verdict, self.mod.VERDICT_NOT_SAFE_TO_CLEAR)

    # 3. Marker missing → NOT_SAFE_TO_CLEAR.
    def test_03_marker_missing_fails(self):
        self._seed_broker_repair()
        self._seed_runtime_state()
        result = self.mod.evaluate_local_evidence("AVAX/USD",
                                                  "/nonexistent/path.txt")
        self.assertEqual(result.verdict, self.mod.VERDICT_NOT_SAFE_TO_CLEAR)
        self.assertTrue(any("marker" in r for r in result.reasons))

    # 4. Marker present + healthy state → SAFE_TO_CLEAR_CANDIDATE.
    def test_04_marker_present_can_succeed(self):
        self._seed_broker_repair()
        self._seed_runtime_state(safe_mode_active=True, forced=False)
        marker = self._write_marker()
        result = self.mod.evaluate_local_evidence("AVAX/USD", marker)
        self.assertEqual(result.verdict, self.mod.VERDICT_SAFE_TO_CLEAR_CANDIDATE,
                         msg=f"reasons={result.reasons}")

    # 5. --operator-confirmed required to write proposal.
    def test_05_operator_confirmed_required_for_proposal(self):
        self._seed_broker_repair()
        self._seed_runtime_state(safe_mode_active=True, forced=False)
        marker = self._write_marker()
        # Run without --operator-confirmed → no proposal file.
        rc = self.mod.main([
            "--symbol", "AVAX/USD",
            "--marker-path", marker,
            "--dry-run", "false",
        ])
        self.assertEqual(rc, 0)
        prop_dir = self._tmp_path / "learning-loop" / "operator_markers"
        proposals = list(prop_dir.glob("safe_mode_clear_proposal_*.json")) if prop_dir.exists() else []
        self.assertEqual(len(proposals), 0,
                         "Proposal file written without --operator-confirmed")

    # 6. Writes proposal — NOT a clear action.
    def test_06_writes_proposal_not_clear(self):
        self._seed_broker_repair()
        self._seed_runtime_state(safe_mode_active=True, forced=False)
        marker = self._write_marker()
        rc = self.mod.main([
            "--symbol", "AVAX/USD",
            "--marker-path", marker,
            "--operator-confirmed",
            "--dry-run", "false",
        ])
        self.assertEqual(rc, 0)
        prop_dir = self._tmp_path / "learning-loop" / "operator_markers"
        proposals = list(prop_dir.glob("safe_mode_clear_proposal_*.json"))
        self.assertEqual(len(proposals), 1,
                         "Expected exactly 1 proposal file")
        body = json.loads(proposals[0].read_text(encoding="utf-8"))
        self.assertEqual(body["kind"], "safe_mode_clear_proposal")
        self.assertEqual(body["verdict"],
                         self.mod.VERDICT_SAFE_TO_CLEAR_CANDIDATE)
        # Critical: runtime_state.json::safe_mode is NOT modified.
        rt = json.loads((self._tmp_path / "learning-loop" /
                         "runtime_state.json").read_text(encoding="utf-8"))
        self.assertTrue(rt["safe_mode"]["active"],
                        "Verifier illegally cleared safe_mode")

    # 7. AST scan: script never calls broker (no `submit_order` / `place_order` /
    #    `safe_close` / `place_stock_order` etc.).
    def test_07_ast_no_broker_calls(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        forbidden = {
            "submit_order", "place_order", "safe_close",
            "place_stock_order", "place_crypto_order", "place_option_order",
            "close_position", "close_all_positions",
            "cancel_order", "cancel_all_orders",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name: str | None = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name in forbidden:
                    self.fail(f"Forbidden broker call detected: {name}()")

    # 8. AST scan: script never imports alpaca_orders.
    def test_08_ast_no_alpaca_orders_import(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "alpaca_orders", (node.module or ""),
                    "Verifier illegally imports alpaca_orders",
                )

    # 9. Verifier MUST NOT auto-clear safe_mode under any flag combination.
    def test_09_never_clears_safe_mode(self):
        # Mock write to the runtime_state file to detect any write attempt.
        self._seed_broker_repair()
        self._seed_runtime_state(safe_mode_active=True, forced=False)
        marker = self._write_marker()
        rt_path = (self._tmp_path / "learning-loop" / "runtime_state.json")
        before = rt_path.read_text(encoding="utf-8")
        rc = self.mod.main([
            "--symbol", "AVAX/USD",
            "--marker-path", marker,
            "--operator-confirmed",
            "--dry-run", "false",
        ])
        self.assertEqual(rc, 0)
        after = rt_path.read_text(encoding="utf-8")
        self.assertEqual(before, after,
                         "runtime_state.json safe_mode section was modified")

    # 10. Audit row per run — always emitted, even on the read-only path.
    def test_10_audit_row_per_run(self):
        # Two read-only runs → at least two rows in today's JSONL.
        self.mod.main(["--symbol", "AVAX/USD"])
        self.mod.main(["--symbol", "AVAX/USD"])
        files = list(self._audit_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1,
                         f"Expected 1 audit file, got {files!r}")
        rows = [
            json.loads(line)
            for line in files[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verify_rows = [
            r for r in rows
            if r.get("decision_type") == "VERIFY_MANUAL_BROKER_REPAIR"
        ]
        self.assertGreaterEqual(len(verify_rows), 2)


if __name__ == "__main__":
    unittest.main()

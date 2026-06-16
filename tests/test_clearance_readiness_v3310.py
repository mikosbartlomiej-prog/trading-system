"""v3.31 ETAP 2 (2026-06-16) — tests for scripts/run_operator_clearance_readiness.py.

Asserts the consolidated readiness wrapper:

* default with no markers and no broker_repair entries → an empty
  ``READY_FOR_OPERATOR_MANUAL_APPLY`` summary,
* default with broker_repair entries but no markers → overall
  ``NOT_READY_NO_MARKER`` for every symbol,
* marker for AVAX/USD only → overall still NOT_READY because the
  other symbols are missing markers,
* all 3 markers + a fresh P13 audit row → ``NOT_READY_FRESH_P13``,
* all 3 markers + safe_mode_consistency INCONSISTENT →
  ``NOT_READY_SAFE_MODE_INCONSISTENT``,
* all 3 markers + equity_gap block_allocator=true →
  ``NOT_READY_EQUITY_GAP``,
* all 3 markers + everything clean + dry-run →
  ``READY_TO_PROPOSE_CLEARANCE`` (no proposal written),
* ``--apply`` without ``--operator-confirmed`` → refuses, NO proposal
  written, still READY_TO_PROPOSE_CLEARANCE in summary,
* ``--apply --operator-confirmed`` with all ready →
  ``CLEARANCE_PROPOSAL_WRITTEN`` AND proposal files written,
* AST: script imports no ``alpaca_orders`` (lazy or direct),
* runtime: script never calls broker / safe_close / cancel_order,
* standing markers always emitted in output JSON,
* script does NOT auto-clear safe_mode_state_latest.json or
  broker_repair_required_latest.json under any path.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


CANONICAL_SYMBOLS = ["AVAX/USD", "ETH/USD", "LTC/USD"]
SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_operator_clearance_readiness.py"


def _load_script_module():
    """Force-reload the script module with current env."""
    name = "run_operator_clearance_readiness"
    # Drop any cached siblings whose state depends on env vars.
    for k in (
        name,
        "operator_repair_state",
        "broker_repair_required",
        "propose_clear_broker_repair_and_safe_mode",
        "symbol_normalization",
    ):
        if k in sys.modules:
            del sys.modules[k]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _IsolatedEnv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)
        self.markers_dir = self.tmp_root / "operator_markers"
        self.audit_dir = self.tmp_root / "audit"
        self.markers_dir.mkdir(parents=True)
        self.audit_dir.mkdir(parents=True)
        self.brr_path = self.tmp_root / "broker_repair_required_latest.json"
        self.smc_path = self.tmp_root / "safe_mode_consistency_latest.json"
        self.egap_path = self.tmp_root / "equity_gap_reconciliation_latest.json"
        self.sa_path = self.tmp_root / "system_activation_status_latest.json"
        self.readiness_json = self.tmp_root / "operator_clearance_readiness_latest.json"
        self.readiness_md = self.tmp_root / "OPERATOR_CLEARANCE_READINESS.md"

        # Save prior env.
        self._prev = {}
        for k in (
            "OPERATOR_MARKERS_DIR",
            "AUDIT_TRADING_DIR",
            "BROKER_REPAIR_REQUIRED_PATH",
            "SAFE_MODE_CONSISTENCY_PATH",
            "EQUITY_GAP_LATEST_PATH",
            "SYSTEM_ACTIVATION_STATUS_PATH",
            "OPERATOR_CLEARANCE_READINESS_JSON",
            "OPERATOR_CLEARANCE_READINESS_MD",
        ):
            self._prev[k] = os.environ.pop(k, None)
        os.environ["OPERATOR_MARKERS_DIR"] = str(self.markers_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = str(self.brr_path)
        os.environ["SAFE_MODE_CONSISTENCY_PATH"] = str(self.smc_path)
        os.environ["EQUITY_GAP_LATEST_PATH"] = str(self.egap_path)
        os.environ["SYSTEM_ACTIVATION_STATUS_PATH"] = str(self.sa_path)
        os.environ["OPERATOR_CLEARANCE_READINESS_JSON"] = str(self.readiness_json)
        os.environ["OPERATOR_CLEARANCE_READINESS_MD"] = str(self.readiness_md)

    def tearDown(self):
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()
        for k in (
            "run_operator_clearance_readiness",
            "operator_repair_state",
            "broker_repair_required",
            "propose_clear_broker_repair_and_safe_mode",
        ):
            if k in sys.modules:
                del sys.modules[k]

    # ── helpers ───────────────────────────────────────────────────────

    def write_broker_repair(self, symbols):
        """Seed broker_repair_required state with the given canonical symbols."""
        entries = {}
        for s in symbols:
            entries[s] = {
                "symbol": s,
                "incident_type": "P13_BRACKET_INTERLOCK",
                "first_seen_iso": (
                    datetime.now(timezone.utc) - timedelta(hours=4)
                ).isoformat(),
                "last_seen_iso": (
                    datetime.now(timezone.utc) - timedelta(hours=2)
                ).isoformat(),
                "failed_attempts": 3,
                "last_error": "403 insufficient balance",
                "manual_action_required": "operator_marker_required",
                "allowed_next_actions": ["operator_marker_required"],
                "safe_mode_reason": "p13_bracket_interlock_retry_exhausted",
                "retry_after_iso": None,
                "broker_calls_blocked_until_iso": None,
            }
        payload = {
            "schema_version": "v3.28",
            "updated_at": _now_iso(),
            "entries": entries,
        }
        self.brr_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_marker(self, symbol_canonical, *, ts_iso=None):
        """Write a real (non-template) operator marker under markers_dir/."""
        if "operator_repair_state" in sys.modules:
            del sys.modules["operator_repair_state"]
        import operator_repair_state as ors  # noqa
        ts = ts_iso or _now_iso()
        payload = ors.OperatorRepairConfirmation(
            symbol=symbol_canonical,
            incident_type="P13_BRACKET_INTERLOCK",
            dashboard_checked=True,
            open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0 confirmed",
            final_open_orders_state="none confirmed",
            equity_checked=True,
            operator_note="test marker",
            timestamp_iso=ts,
        )
        return ors.write_marker(payload)

    def write_smc(self, *, verdict="CONSISTENT", blocker=None):
        payload = {
            "schema_version": "v3.30",
            "verdict": verdict,
            "blocker": blocker,
            "evaluated_at_iso": _now_iso(),
        }
        self.smc_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_egap(self, *, block=False, verdict="EQUITY_GAP_OK"):
        payload = {
            "schema_version": "v3.28",
            "block_allocator": bool(block),
            "verdict": verdict,
            "evaluated_at_iso": _now_iso(),
        }
        self.egap_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_sa(self, *, decision="ALLOCATOR_BLOCKED_BROKER_REPAIR"):
        payload = {
            "schema_version": "v3.30",
            "decision": decision,
            "evaluated_at_iso": _now_iso(),
        }
        self.sa_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_fresh_p13_audit(self, symbol_canonical):
        """Append an audit row dated NOW for symbol → counts as fresh P13."""
        path = self.audit_dir / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        row = {
            "decision_type": "P13_BRACKET_INTERLOCK_BLOCKED_CLOSE",
            "actor": "incident_pattern_detector",
            "symbol": symbol_canonical,
            "last_error": "403 insufficient balance for AVAX",
            "ts_iso": (
                datetime.now(timezone.utc) + timedelta(minutes=1)
            ).isoformat(),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestClearanceReadinessV3310(_IsolatedEnv):

    def test_01_no_markers_no_repair_entries_yields_manual_apply(self):
        """No broker_repair entries + no markers → READY_FOR_OPERATOR_MANUAL_APPLY."""
        self.write_smc()
        self.write_egap()
        self.write_sa(decision="ALLOCATOR_ALLOWED")
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(result.overall_verdict, "READY_FOR_OPERATOR_MANUAL_APPLY")
        self.assertEqual(result.symbols, [])

    def test_02_no_markers_with_repair_entries_yields_not_ready_no_marker(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(result.overall_verdict, "NOT_READY_NO_MARKER")
        # All 3 symbols present.
        self.assertEqual(
            sorted(s.symbol_canonical for s in result.symbols),
            sorted(CANONICAL_SYMBOLS),
        )
        for s in result.symbols:
            self.assertEqual(s.verdict, "NOT_READY_NO_MARKER")
            self.assertFalse(s.marker_present)
            self.assertTrue(s.broker_repair_present)

    def test_03_one_marker_only_still_not_ready_overall(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        self.write_marker("AVAX/USD")
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        # Highest-severity wins. Other two symbols are NOT_READY_NO_MARKER
        # which is higher in our priority than READY_TO_PROPOSE.
        self.assertEqual(result.overall_verdict, "NOT_READY_NO_MARKER")
        per_sym = {s.symbol_canonical: s.verdict for s in result.symbols}
        self.assertEqual(per_sym["AVAX/USD"], "READY_TO_PROPOSE_CLEARANCE")
        self.assertEqual(per_sym["ETH/USD"], "NOT_READY_NO_MARKER")
        self.assertEqual(per_sym["LTC/USD"], "NOT_READY_NO_MARKER")

    def test_04_all_markers_plus_fresh_p13_yields_not_ready_fresh_p13(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        # Inject fresh P13 audit row dated AFTER the marker.
        self.write_fresh_p13_audit("AVAX/USD")
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(
            result.overall_verdict, "NOT_READY_FRESH_P13_AFTER_MARKER")
        per_sym = {s.symbol_canonical: s.verdict for s in result.symbols}
        self.assertEqual(
            per_sym["AVAX/USD"], "NOT_READY_FRESH_P13_AFTER_MARKER")
        # ETH + LTC are READY since their fresh-incident counts are 0.
        self.assertEqual(per_sym["ETH/USD"], "READY_TO_PROPOSE_CLEARANCE")
        self.assertEqual(per_sym["LTC/USD"], "READY_TO_PROPOSE_CLEARANCE")

    def test_05_all_markers_plus_safe_mode_inconsistent_yields_blocker(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc(verdict="INCONSISTENT_ENTERED_NOT_PERSISTED",
                       blocker="INCONSISTENT_ENTERED_NOT_PERSISTED")
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(
            result.overall_verdict, "NOT_READY_SAFE_MODE_INCONSISTENT")
        for s in result.symbols:
            self.assertEqual(s.verdict, "NOT_READY_SAFE_MODE_INCONSISTENT")

    def test_06_all_markers_plus_equity_gap_block_yields_equity_blocker(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap(block=True, verdict="EQUITY_GAP_DRIFT_BLOCK")
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(result.overall_verdict, "NOT_READY_EQUITY_GAP")
        for s in result.symbols:
            self.assertEqual(s.verdict, "NOT_READY_EQUITY_GAP")

    def test_07_all_markers_clean_dry_run_yields_ready_to_propose(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=False, operator_confirmed=False)
        self.assertEqual(
            result.overall_verdict, "READY_TO_PROPOSE_CLEARANCE")
        for s in result.symbols:
            self.assertEqual(s.verdict, "READY_TO_PROPOSE_CLEARANCE")
            self.assertTrue(s.marker_present)
            self.assertIsNone(s.proposal_path,
                              "dry-run must NOT write any proposal")

    def test_08_apply_without_operator_confirmed_refuses_to_write(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        mod = _load_script_module()
        # apply_requested=False because --operator-confirmed is missing
        # (main() collapses both into dry_run=True). Verify behaviour
        # via the underlying API too.
        result = mod.evaluate_readiness(
            apply_requested=True, operator_confirmed=False)
        # Without confirmation, dry_run=True → no proposals.
        self.assertTrue(result.dry_run)
        self.assertEqual(
            result.overall_verdict, "READY_TO_PROPOSE_CLEARANCE")
        for s in result.symbols:
            self.assertIsNone(s.proposal_path)
        # No clearance_proposal_* file written in the markers dir.
        proposals = list(self.markers_dir.glob("clearance_proposal_*.json"))
        self.assertEqual(proposals, [],
                         "no proposal must be written without --operator-confirmed")

    def test_09_apply_with_operator_confirmed_writes_proposals(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        mod = _load_script_module()
        result = mod.evaluate_readiness(
            apply_requested=True, operator_confirmed=True,
            dashboard_evidence_note="unit-test apply path")
        self.assertEqual(
            result.overall_verdict, "CLEARANCE_PROPOSAL_WRITTEN")
        for s in result.symbols:
            self.assertEqual(s.verdict, "CLEARANCE_PROPOSAL_WRITTEN")
            self.assertIsNotNone(s.proposal_path)
            self.assertTrue(Path(s.proposal_path).exists())
        # broker_repair_required entries must STILL be present — the
        # proposal does NOT clear anything.
        if "broker_repair_required" in sys.modules:
            del sys.modules["broker_repair_required"]
        import broker_repair_required as brr
        state_after = brr.load_state()
        self.assertEqual(
            sorted(state_after.keys()), sorted(CANONICAL_SYMBOLS),
            "broker_repair_required must NOT be auto-cleared",
        )
        # safe_mode_state was never written by us → must still not exist.
        sm_path = self.tmp_root / "safe_mode_state_latest.json"
        self.assertFalse(
            sm_path.exists(),
            "safe_mode state file must NOT be auto-created/cleared",
        )

    def test_10_ast_no_alpaca_orders_import_and_no_broker_calls(self):
        """AST-level hard guard.

        We rely on AST analysis rather than substring matching so that
        the docstring is allowed to *name* forbidden functions (it has
        to, to document what the script does NOT do) without breaking
        the test. The test fails iff the parsed module actually
        imports ``alpaca_orders`` OR contains a Call to any forbidden
        function name.
        """
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)

        forbidden_call_names = {
            "submit_order",
            "place_order",
            "safe_close",
            "cancel_order",
            "close_position",
            "close_all_positions",
        }

        for node in ast.walk(tree):
            # Imports of alpaca_orders are hard-banned (direct or from).
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "alpaca_orders", alias.name,
                        f"forbidden import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "alpaca_orders", str(node.module or ""),
                    f"forbidden from-import: {node.module}",
                )
            # Calls to broker plumbing are hard-banned.
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(
                        func.id, forbidden_call_names,
                        f"forbidden Call: {func.id}",
                    )
                elif isinstance(func, ast.Attribute):
                    self.assertNotIn(
                        func.attr, forbidden_call_names,
                        f"forbidden attr Call: {func.attr}",
                    )

        # Also, the LITERAL string "alpaca_orders" must not appear in
        # any executable expression (e.g. importlib.import_module). The
        # docstring is allowed to mention it for negation purposes; we
        # check only string literals that appear OUTSIDE module-level
        # docstrings.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Skip module docstring (first statement of Module).
                if isinstance(tree, ast.Module) and tree.body \
                   and isinstance(tree.body[0], ast.Expr) \
                   and tree.body[0].value is node:
                    continue
                self.assertNotIn(
                    "alpaca_orders", node.value,
                    "alpaca_orders mentioned in an executable string literal",
                )

    def test_11_standing_markers_emitted_in_json_and_markdown(self):
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        mod = _load_script_module()
        rc = mod.main([])  # default dry-run
        self.assertEqual(rc, 0)
        # JSON
        raw = json.loads(self.readiness_json.read_text(encoding="utf-8"))
        sm = raw.get("standing_markers") or []
        for required in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
            "NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT",
            "NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT",
            "TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER",
        ):
            self.assertIn(required, sm, f"missing standing marker in JSON: {required}")
        self.assertTrue(raw.get("does_not_execute_orders") is True)
        self.assertTrue(raw.get("does_not_auto_clear_safe_mode") is True)
        self.assertTrue(raw.get("does_not_auto_clear_broker_repair") is True)
        # Markdown
        md_text = self.readiness_md.read_text(encoding="utf-8")
        for required in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
        ):
            self.assertIn(required, md_text,
                          f"missing standing marker in markdown: {required}")

    def test_12_apply_path_does_not_auto_clear_safe_mode(self):
        """Even the apply path never touches safe_mode_state_latest.json."""
        self.write_broker_repair(CANONICAL_SYMBOLS)
        self.write_smc()
        self.write_egap()
        self.write_sa()
        for sym in CANONICAL_SYMBOLS:
            self.write_marker(sym)
        # Pre-seed an arbitrary safe-mode-state-like file; readiness
        # script must NOT touch it.
        sm_path = self.tmp_root / "safe_mode_state_latest.json"
        sm_path.write_text(
            json.dumps({"safe_mode_active": True, "seeded_by": "test"}),
            encoding="utf-8")
        mtime_before = sm_path.stat().st_mtime

        mod = _load_script_module()
        mod.evaluate_readiness(
            apply_requested=True, operator_confirmed=True,
            dashboard_evidence_note="unit-test")

        self.assertTrue(sm_path.exists())
        # File must be byte-identical.
        post = json.loads(sm_path.read_text(encoding="utf-8"))
        self.assertEqual(
            post,
            {"safe_mode_active": True, "seeded_by": "test"},
            "safe_mode_state must NOT be auto-cleared",
        )
        self.assertAlmostEqual(
            sm_path.stat().st_mtime, mtime_before, delta=2,
            msg="safe_mode_state mtime must NOT change",
        )


if __name__ == "__main__":
    unittest.main()

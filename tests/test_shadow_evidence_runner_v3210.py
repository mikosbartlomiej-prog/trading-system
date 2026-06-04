"""v3.21.0 (2026-06-04) — ETAP 2 unit tests for
``scripts/run_shadow_evidence_cycle.py``.

Required coverage (spec):
  * runner works in dry-run mode (no files written)
  * runner works in shadow mode (writes opportunity + shadow ledgers)
  * runner does NOT support live mode (parser rejects --mode live)
  * runner writes opportunity ledger entry per signal
  * runner writes shadow ledger entry only after gate approval
  * runner records rejection_reasons
  * runner respects kill-switch (mock kill_switch active -> early exit, no writes)
  * runner respects safe_mode (mock safe_mode -> defers writes appropriately)
  * runner does NOT bypass risk_engine (risk REJECT -> no shadow fill)
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


# ─── Test base ────────────────────────────────────────────────────────────────


class _BaseRunnerTest(unittest.TestCase):
    """Shared scaffolding: isolated ledger dirs + stubbed modules."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.shadow_dir = root / "shadow_ledger"
        self.opportunity_dir = root / "opportunity_ledger"
        self.audit_dir = root / "audit"

        os.environ["SHADOW_LEDGER_DIR"] = str(self.shadow_dir)
        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.opportunity_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        os.environ["SHADOW_EVIDENCE_REPORT_PATH"] = str(
            root / "shadow_evidence_cycle_LATEST.md"
        )
        # Ensure the broker mode path takes the SIGNAL_ONLY default if
        # asked — we never want a real broker call in tests.
        os.environ["EVIDENCE_PRODUCTION_MODE"] = "SIGNAL_ONLY"

        # Force fresh import of all modules the runner touches so the
        # env vars above take effect.
        self._forget("scripts.run_shadow_evidence_cycle")
        self._forget("run_shadow_evidence_cycle")
        self._forget("signal_opportunity_ledger")
        self._forget("evidence_production")

        # Stub modules the runner consults via ``_import_module``. We
        # inject our doubles BEFORE importing the runner so its
        # ``__import__`` resolves to our stubs.
        self._install_stubs()

        from scripts import run_shadow_evidence_cycle as runner  # type: ignore
        self.runner = runner

    def tearDown(self):
        self.tmp.cleanup()
        for k in ("SHADOW_LEDGER_DIR", "OPPORTUNITY_LEDGER_DIR",
                  "AUDIT_TRADING_DIR", "EVIDENCE_PRODUCTION_MODE",
                  "SHADOW_EVIDENCE_REPORT_PATH"):
            os.environ.pop(k, None)
        # Clean stubs.
        for name in (
            "defensive_mode_stub", "safe_mode_stub", "regime_stub",
            "confidence_stub", "strategy_quality_gate_stub",
            "risk_officer_stub", "evidence_production_stub",
            "runtime_state_stub", "counterfactual_outcomes_stub",
            "signal_opportunity_ledger",
        ):
            self._forget(name)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _forget(mod: str) -> None:
        for key in list(sys.modules):
            if key == mod or key.endswith("." + mod):
                del sys.modules[key]

    def _install_stubs(self) -> None:
        """Inject light stubs for modules the runner imports via
        ``__import__``. We rebind names at import-resolve time using
        ``sys.modules`` so the runner's deferred ``__import__`` finds
        the stubs.

        The stubs default to "everything passes", and individual tests
        override behaviour as needed.
        """
        # signal_opportunity_ledger MUST be the real module so the
        # ledger file is actually written. Re-import a clean copy.
        sys.path.insert(0, str(REPO_ROOT / "shared"))
        sol = importlib.import_module("signal_opportunity_ledger")
        importlib.reload(sol)

        # All other stubs are inline dataclass-light shims.
        defensive_mode = type(sys)("defensive_mode")
        defensive_mode.is_full_stop_armed = lambda: False
        defensive_mode.is_defensive_mode_active = lambda: False
        sys.modules["defensive_mode"] = defensive_mode

        safe_mode = type(sys)("safe_mode")
        safe_mode.gate_new_entry = lambda: (True, "safe_mode clear")
        sys.modules["safe_mode"] = safe_mode

        regime = type(sys)("regime")
        regime.detect_regime = lambda market_signals=None: {
            "regime": "NEUTRAL", "reason": "stub", "source": "stub",
        }
        sys.modules["regime"] = regime

        class _Report:
            def __init__(self, total=0.8, decision="ALLOW", reason="stub PASS"):
                self.total = total
                self.decision = decision
                self.reason = reason

        confidence = type(sys)("confidence")
        confidence.compute_confidence = lambda **kwargs: _Report()
        sys.modules["confidence"] = confidence

        sqg = type(sys)("strategy_quality_gate")
        sqg.classify_strategy = lambda strategy, metrics: {
            "status": "GOOD", "reason": "stub quality",
        }
        sys.modules["strategy_quality_gate"] = sqg

        risk = type(sys)("risk_officer")
        risk.evaluate_trade = lambda proposal: {
            "decision":      "APPROVE",
            "checks_passed": ["stub"],
            "checks_failed": [],
            "warnings":      [],
            "rationale":     "stub approve",
        }
        sys.modules["risk_officer"] = risk

        # evidence_production stub records calls so we can assert on
        # whether the runner attempted to write shadow fills.
        ep_state = {"calls": []}

        class _ProdResult:
            def __init__(self, accepted=True, record=None):
                self.mode = "SHADOW_PAPER_SIM"
                self.accepted = accepted
                self.risk_decision = "APPROVE"
                self.risk_rationale = "stub"
                self.record = record or {"sym": "STUB"}
                self.audit_reference = "stub:audit"

            def to_dict(self):
                return {
                    "mode": self.mode,
                    "accepted": self.accepted,
                    "risk_decision": self.risk_decision,
                    "risk_rationale": self.risk_rationale,
                    "record": self.record,
                    "audit_reference": self.audit_reference,
                }

        def _produce_evidence(signal, *, mode):
            ep_state["calls"].append({"signal": dict(signal), "mode": mode})
            # Also write a fake shadow ledger row so the test can
            # observe writes on disk like the real module would.
            ledger_dir = Path(os.environ["SHADOW_LEDGER_DIR"])
            ledger_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timezone
            path = ledger_dir / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "signal_id": signal.get("signal_id"),
                    "strategy":  signal.get("strategy"),
                    "symbol":    signal.get("symbol"),
                    "mode":      mode,
                }) + "\n")
            return _ProdResult(accepted=True)

        ep = type(sys)("evidence_production")
        ep.produce_evidence = _produce_evidence
        ep.estimate_shadow_fill = lambda price, side, **kw: {
            "fill_price": price, "side": side,
        }
        ep._calls = ep_state["calls"]  # exposed for tests
        sys.modules["evidence_production"] = ep
        self._ep_calls = ep_state["calls"]

        # counterfactual_outcomes stub is a no-op.
        cf = type(sys)("counterfactual_outcomes")
        cf.compute_counterfactual_for_signal = lambda *a, **kw: None
        sys.modules["counterfactual_outcomes"] = cf

        # runtime_state stub serves an empty pre_open_plan.
        rs = type(sys)("runtime_state")
        rs.read_section = lambda name: {}
        sys.modules["runtime_state"] = rs

    # Provide synthetic state files so the runner has strategies +
    # universe + no-op pre-open plan to work with.
    def _seed_state_files(self, *, strategies: list[str] | None = None,
                          universe_symbols: list[str] | None = None) -> None:
        ls_path = REPO_ROOT / "learning-loop" / "state.json"
        un_path = REPO_ROOT / "learning-loop" / "universe_ranking_TEST.json"
        self._backup_ls = ls_path.read_text() if ls_path.exists() else None
        self._un_path = un_path

        strategies = strategies or ["momentum-long", "geo-defense"]
        ls_payload = {
            "strategies": {name: {"enabled": True} for name in strategies},
        }
        ls_path.parent.mkdir(parents=True, exist_ok=True)
        ls_path.write_text(json.dumps(ls_payload), encoding="utf-8")

        symbols = universe_symbols or ["AAPL"]
        un_path.write_text(json.dumps({
            "ranking": [
                {"symbol": s, "score": 0.6, "price": 150.0} for s in symbols
            ],
        }), encoding="utf-8")

    def _restore_state_files(self) -> None:
        ls_path = REPO_ROOT / "learning-loop" / "state.json"
        if getattr(self, "_backup_ls", None) is not None:
            ls_path.write_text(self._backup_ls)
        if getattr(self, "_un_path", None) and self._un_path.exists():
            self._un_path.unlink()


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestParserRejectsLive(_BaseRunnerTest):

    def test_parser_choices_contain_no_live(self):
        parser = self.runner.build_parser()
        # Locate the --mode action.
        mode_action = next(a for a in parser._actions if a.dest == "mode")
        self.assertNotIn("live", mode_action.choices)
        self.assertEqual(set(mode_action.choices),
                         set(self.runner.ALLOWED_MODES))
        self.assertNotIn("live", self.runner.ALLOWED_MODES)

    def test_parser_rejects_explicit_live(self):
        parser = self.runner.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--mode", "live"])

    def test_invariants_set(self):
        self.assertTrue(self.runner.LIVE_MODE_NOT_SUPPORTED)
        self.assertTrue(self.runner.RUNNER_NEVER_BYPASSES_GATES)
        self.assertTrue(self.runner.RUNNER_NEVER_PLACES_BROKER_ORDERS)

    def test_run_cycle_rejects_live_string(self):
        with self.assertRaises(ValueError):
            self.runner.run_cycle(mode="live")


class TestDryRun(_BaseRunnerTest):

    def test_dry_run_writes_no_files(self):
        self._seed_state_files()
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=True)
        finally:
            self._restore_state_files()

        self.assertTrue(result.dry_run)
        # Opportunity ledger directory NOT created.
        self.assertFalse(self.opportunity_dir.exists(),
                         "dry-run must not create opportunity ledger")
        # Shadow ledger directory NOT created.
        self.assertFalse(self.shadow_dir.exists(),
                         "dry-run must not create shadow ledger")
        # No report path written.
        self.assertIsNone(result.report_path)
        # We did still record an "observed" opportunity in-memory.
        self.assertGreaterEqual(result.opportunities_recorded, 1)


class TestShadowModeWrites(_BaseRunnerTest):

    def test_shadow_mode_writes_both_ledgers(self):
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["AAPL"])
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()

        # Opportunity ledger row written.
        self.assertTrue(self.opportunity_dir.exists())
        files = list(self.opportunity_dir.glob("*.jsonl"))
        self.assertTrue(files, "expected at least one opportunity file")
        rows = files[0].read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(rows), 1)
        first = json.loads(rows[0])
        self.assertEqual(first["strategy"], "momentum-long")
        self.assertEqual(first["symbol"], "AAPL")

        # Shadow ledger row written by our evidence_production stub.
        self.assertTrue(self.shadow_dir.exists())
        sfiles = list(self.shadow_dir.glob("*.jsonl"))
        self.assertTrue(sfiles, "expected at least one shadow file")
        srow = json.loads(sfiles[0].read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(srow["strategy"], "momentum-long")
        self.assertEqual(srow["symbol"], "AAPL")

        # And the counterfactual schedule was registered.
        self.assertGreaterEqual(len(result.counterfactual_pending), 1)


class TestRejectionRecording(_BaseRunnerTest):

    def test_risk_reject_recorded_in_opportunity_no_shadow_write(self):
        # Reconfigure risk officer to REJECT.
        risk = sys.modules["risk_officer"]
        risk.evaluate_trade = lambda proposal: {
            "decision":      "REJECT",
            "checks_passed": [],
            "checks_failed": ["ticker not on whitelist"],
            "warnings":      [],
            "rationale":     "stub reject — whitelist",
        }
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["ZZZ"])
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()

        # Opportunity ledger MUST contain the rejection reason.
        files = list(self.opportunity_dir.glob("*.jsonl"))
        rows = [json.loads(r) for r in files[0].read_text().splitlines() if r]
        risk_rows = [r for r in rows if r["risk_decision"] in ("BLOCK", "REJECT")]
        self.assertTrue(risk_rows, "expected rejection recorded")
        sample = risk_rows[0]
        joined = " ".join(sample.get("rejection_reasons") or [])
        self.assertIn("whitelist", joined.lower())

        # Shadow ledger MUST be absent — risk REJECT blocks shadow writes.
        self.assertFalse(self.shadow_dir.exists(),
                         "risk REJECT must NOT produce shadow ledger entries")
        # Result counters confirm.
        self.assertEqual(result.shadow_fills_accepted, 0)
        self.assertEqual(result.shadow_fills_attempted, 0)


class TestKillSwitchEarlyExit(_BaseRunnerTest):

    def test_kill_switch_active_exits_without_writes(self):
        dm = sys.modules["defensive_mode"]
        dm.is_full_stop_armed = lambda: True
        self._seed_state_files()
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()

        self.assertTrue(result.kill_switched)
        self.assertEqual(result.opportunities_recorded, 0)
        self.assertEqual(result.shadow_fills_attempted, 0)
        # No files written.
        self.assertFalse(self.opportunity_dir.exists())
        self.assertFalse(self.shadow_dir.exists())


class TestSafeModeDefersShadowFills(_BaseRunnerTest):

    def test_safe_mode_records_opportunity_but_skips_shadow(self):
        sm = sys.modules["safe_mode"]
        sm.gate_new_entry = lambda: (False, "SAFE_MODE active")
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["AAPL"])
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()

        self.assertTrue(result.safe_mode_deferred)
        self.assertGreaterEqual(result.opportunities_recorded, 1)
        # Critical: no shadow fills attempted.
        self.assertEqual(result.shadow_fills_attempted, 0)
        self.assertFalse(self.shadow_dir.exists())


class TestRiskEngineNotBypassed(_BaseRunnerTest):

    def test_risk_engine_unreachable_blocks_shadow(self):
        # Simulate risk officer DEFER (e.g. Alpaca outage).
        risk = sys.modules["risk_officer"]
        risk.evaluate_trade = lambda proposal: {
            "decision":      "DEFER",
            "checks_passed": [],
            "checks_failed": ["alpaca_unreachable"],
            "warnings":      [],
            "rationale":     "alpaca outage",
        }
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["AAPL"])
        try:
            result = self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()

        # No shadow accepted — risk_engine was the gate.
        self.assertEqual(result.shadow_fills_accepted, 0)
        # Opportunity still recorded.
        self.assertGreaterEqual(result.opportunities_recorded, 1)


class TestOpportunityPerObservedSignal(_BaseRunnerTest):

    def test_one_opportunity_per_strategy_observation(self):
        self._seed_state_files(
            strategies=["momentum-long", "geo-defense"],
            universe_symbols=["AAPL"],
        )
        try:
            result = self.runner.run_cycle(mode="signal_only", dry_run=False)
        finally:
            self._restore_state_files()

        files = list(self.opportunity_dir.glob("*.jsonl"))
        self.assertTrue(files)
        rows = [json.loads(r) for r in files[0].read_text().splitlines() if r]
        # One per active strategy with a non-empty universe.
        self.assertEqual(len(rows), 2)
        strategies_seen = sorted({r["strategy"] for r in rows})
        self.assertEqual(strategies_seen, ["geo-defense", "momentum-long"])
        # signal_only mode never writes shadow ledger entries.
        self.assertFalse(self.shadow_dir.exists())


class TestEvidenceProductionInvoked(_BaseRunnerTest):

    def test_shadow_mode_invokes_evidence_production(self):
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["AAPL"])
        try:
            self.runner.run_cycle(mode="shadow", dry_run=False)
        finally:
            self._restore_state_files()
        # Our stub recorded one call.
        self.assertEqual(len(self._ep_calls), 1)
        self.assertEqual(self._ep_calls[0]["mode"], "SHADOW_PAPER_SIM")

    def test_signal_only_does_not_invoke_evidence_production(self):
        self._seed_state_files(strategies=["momentum-long"],
                               universe_symbols=["AAPL"])
        try:
            self.runner.run_cycle(mode="signal_only", dry_run=False)
        finally:
            self._restore_state_files()
        self.assertEqual(len(self._ep_calls), 0)


if __name__ == "__main__":
    unittest.main()

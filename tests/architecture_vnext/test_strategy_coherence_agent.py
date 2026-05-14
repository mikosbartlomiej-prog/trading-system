"""Tests for the Strategy Coherence Agent.

Each test builds a tiny synthetic repo in a tempdir, runs the relevant
check module, and asserts the resulting Finding list. We do NOT execute
the agent against the real repo here — that's left for a smoke test
at the bottom of the file.

Strategy: keep each scenario hermetic (one tempdir, one check), so the
test is fast and easy to debug when a check changes.

Run:
    python -m unittest tests.architecture_vnext.test_strategy_coherence_agent
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.strategy_coherence_agent.checks import (   # noqa: E402
    capital_deployment,
    account_awareness,
    intraday_profit_protection,
    autonomy_and_determinism,
    runtime_state_policy,
    documentation_parity,
    regime_event_switch,
    momentum_scoring,
    options_strategy_consistency,
    risk_consistency,
    tests_coverage,
    auditability,
    intraday_trend_management,
    learning_loop_allocator,
    strategy_aggressiveness,
)
from tools.strategy_coherence_agent.main import run, _exit_code_for   # noqa: E402
from tools.strategy_coherence_agent.report import (                   # noqa: E402
    render_json, render_markdown, write_outputs,
)


# ─── Test helpers ────────────────────────────────────────────────────────────

def _scratch_repo() -> Path:
    """Create a minimal repo skeleton under a tempdir."""
    root = Path(tempfile.mkdtemp())
    for d in ("config", "docs", "shared", "exit-monitor", "options-exit-monitor",
              "price-monitor", "options-monitor", "crypto-monitor",
              "learning-loop", "tests", ".github/workflows"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ─── Capital deployment ─────────────────────────────────────────────────────

class TestCapitalDeployment(unittest.TestCase):

    def test_fail_when_cash_reserve_too_high(self):
        root = _scratch_repo()
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "capital": {
                "cash_reserve_pct_equity": 0.10,
                "target_invested_ratio":   0.90,
                "min_invested_ratio":      0.85,
                "max_idle_cash_ratio":     0.10,
            },
        }))
        findings = capital_deployment.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("CD_CASH_RESERVE_TOO_HIGH", ids)
        self.assertEqual(ids["CD_CASH_RESERVE_TOO_HIGH"].status, "FAIL")
        self.assertIn("CD_TARGET_RATIO_LOW", ids)
        self.assertEqual(ids["CD_TARGET_RATIO_LOW"].status, "FAIL")
        self.assertIn("CD_MIN_RATIO_LOW", ids)
        self.assertIn("CD_IDLE_CASH_HIGH", ids)

    def test_pass_when_fully_deployed(self):
        root = _scratch_repo()
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "capital": {
                "cash_reserve_pct_equity": 0.00,
                "target_invested_ratio":   1.00,
                "min_invested_ratio":      0.98,
                "max_idle_cash_ratio":     0.02,
            },
        }))
        findings = capital_deployment.run(root)
        statuses = {f.id: f.status for f in findings}
        self.assertEqual(statuses.get("CD_CASH_RESERVE_OK"), "PASS")
        self.assertEqual(statuses.get("CD_TARGET_RATIO_OK"), "PASS")
        self.assertEqual(statuses.get("CD_MIN_RATIO_OK"), "PASS")


# ─── Intraday profit protection ─────────────────────────────────────────────

class TestIntradayProfitProtection(unittest.TestCase):

    def test_module_missing_is_blocking(self):
        root = _scratch_repo()
        findings = intraday_profit_protection.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("IPP_MODULE_MISSING", ids)
        self.assertTrue(ids["IPP_MODULE_MISSING"].blocking)
        self.assertEqual(ids["IPP_MODULE_MISSING"].status, "FAIL")

    def test_full_pass_with_governor_and_config(self):
        root = _scratch_repo()
        _write(root / "shared" / "intraday_governor.py", """
STATE_FLAT = "FLAT"
STATE_GREEN = "GREEN"
STATE_STRONG_GREEN = "STRONG_GREEN"
STATE_GIVEBACK_WARN = "GIVEBACK_WARN"
STATE_PROFIT_LOCK = "PROFIT_LOCK"
STATE_DEFEND_DAY = "DEFEND_DAY"
STATE_RED_DAY_AFTER_GREEN = "RED_DAY_AFTER_GREEN"

class IntradaySnapshot:
    session_start_equity: float = 0
    current_equity: float = 0
    intraday_peak_equity: float = 0
    intraday_peak_pnl: float = 0
    current_intraday_pnl: float = 0
    giveback_usd: float = 0
    giveback_pct_of_peak: float = 0
    pnl_state: str = STATE_FLAT
""")
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "intraday_profit_protection": {
                "enabled": True,
                "min_profit_to_arm_usd": 1000,
                "giveback_warn_pct_of_peak": 0.25,
                "profit_lock_pct_of_peak": 0.35,
                "defend_day_pct_of_peak": 0.50,
                "red_after_green_pct_of_peak": 0.60,
                "block_new_entries_on_defend_day": True,
                "block_new_entries_on_red_after_green": True,
                "reduce_options_first": True,
                "reduce_weak_positions_first": True,
            },
            "profit_floor": {"enabled": True},
        }))
        _write(root / "exit-monitor" / "monitor.py",
               "from intraday_governor import update as ig_update\n"
               "ig_update(account)\n")
        _write(root / "options-exit-monitor" / "monitor.py",
               "from intraday_governor import get_snapshot\n"
               "decision = 'GOVERNOR'   # options-first reduction\n")
        _write(root / "shared" / "alpaca_orders.py",
               "def _intraday_governor_gate(symbol, side, size, asset_class, score=None):\n"
               "    return True, 'ok'\n")
        _write(root / "docs" / "INTRADAY_PROTECTION.md", "# Intraday Protection contract\n")
        findings = intraday_profit_protection.run(root)
        statuses = {f.id: f.status for f in findings}
        # No FAIL/BLOCKED
        for f in findings:
            self.assertNotEqual(f.status, "FAIL",
                                msg=f"unexpected FAIL: {f.id} — {f.message}")
        self.assertEqual(statuses.get("IPP_FSM_STATES_OK"), "PASS")
        self.assertEqual(statuses.get("IPP_CONFIG_KEYS_OK"), "PASS")
        self.assertEqual(statuses.get("IPP_EXIT_MONITOR_WIRED"), "PASS")
        self.assertEqual(statuses.get("IPP_ENTRY_GATE_WIRED"), "PASS")

    def test_red_after_green_block_disabled_is_blocking(self):
        root = _scratch_repo()
        _write(root / "shared" / "intraday_governor.py",
               'STATE_RED_DAY_AFTER_GREEN = "RED_DAY_AFTER_GREEN"\n')
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "intraday_profit_protection": {
                "enabled": True,
                "block_new_entries_on_defend_day": True,
                "block_new_entries_on_red_after_green": False,
            },
        }))
        findings = intraday_profit_protection.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("IPP_RED_AFTER_GREEN_NOT_BLOCKING", ids)
        self.assertTrue(ids["IPP_RED_AFTER_GREEN_NOT_BLOCKING"].blocking)


# ─── Account awareness ──────────────────────────────────────────────────────

class TestAccountAwareness(unittest.TestCase):

    def test_no_allocator_is_blocking(self):
        root = _scratch_repo()
        findings = account_awareness.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("AA_ALLOCATOR_NOT_FOUND", ids)
        self.assertTrue(ids["AA_ALLOCATOR_NOT_FOUND"].blocking)

    def test_target_only_allocator_fails(self):
        root = _scratch_repo()
        _write(root / "shared" / "allocator.py",
               "def build_plan(equity, cash, buying_power, positions):\n"
               "    return {'target_weights': {}}\n")
        findings = account_awareness.run(root)
        ids = {f.id: f for f in findings}
        # Has account fields but no delta — should FAIL on target-only
        self.assertIn("AA_ALLOCATOR_TARGET_ONLY", ids)
        self.assertEqual(ids["AA_ALLOCATOR_TARGET_ONLY"].status, "FAIL")


# ─── Autonomy & determinism ─────────────────────────────────────────────────

class TestAutonomyAndDeterminism(unittest.TestCase):

    def test_forbidden_wording_in_lifecycle_is_blocking(self):
        root = _scratch_repo()
        _write(root / "shared" / "alpaca_orders.py",
               "def place_order():\n"
               "    # Manual approval required before proceeding\n"
               "    return None\n")
        findings = autonomy_and_determinism.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("AAD_FORBIDDEN_WORDING_IN_LIFECYCLE", ids)
        self.assertTrue(ids["AAD_FORBIDDEN_WORDING_IN_LIFECYCLE"].blocking)


# ─── Runtime state policy ───────────────────────────────────────────────────

class TestRuntimeStatePolicy(unittest.TestCase):

    def test_monitor_committing_state_json_is_blocking(self):
        root = _scratch_repo()
        _write(root / "shared" / "state_policy.py",
               "ALLOWED_ACTORS = frozenset({'daily-learning'})\n")
        _write(root / ".github" / "workflows" / "price-monitor.yml", """
on: { schedule: [ { cron: '*/5 * * * *' } ] }
jobs:
  run:
    steps:
      - run: |
          git add learning-loop/state.json
          git commit -m 'monitor'
""")
        findings = runtime_state_policy.run(root)
        ids = {f.id: f for f in findings}
        self.assertIn("RSP_MONITOR_COMMITS_STATE_JSON", ids)
        self.assertTrue(ids["RSP_MONITOR_COMMITS_STATE_JSON"].blocking)

    def test_governor_using_state_json_fails(self):
        root = _scratch_repo()
        _write(root / "shared" / "state_policy.py",
               "ALLOWED_ACTORS = frozenset({'daily-learning'})\n")
        _write(root / "shared" / "intraday_governor.py",
               "STATE_PATH = 'learning-loop/state.json'\n"
               "with open(STATE_PATH) as f: pass\n")
        findings = runtime_state_policy.run(root)
        ids = {f.id: f.status for f in findings}
        self.assertEqual(ids.get("RSP_GOVERNOR_USES_STATE_JSON"), "FAIL")


# ─── Documentation parity ───────────────────────────────────────────────────

class TestDocumentationParity(unittest.TestCase):

    def test_no_conflicts_when_single_source(self):
        root = _scratch_repo()
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "capital": {"cash_reserve_pct_equity": 0.00},
        }))
        findings = documentation_parity.run(root)
        ids = {f.id: f.status for f in findings}
        # Either DP_NO_CONFLICTS (single occurrence) or pass
        self.assertEqual(ids.get("DP_NO_CONFLICTS"), "PASS")

    def test_conflict_detected_across_files(self):
        root = _scratch_repo()
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "capital": {"cash_reserve_pct_equity": 0.00},
        }))
        # An older doc still declares 10%
        _write(root / "docs" / "STRATEGY.md",
               '"cash_reserve_pct_equity": 0.10\n')
        findings = documentation_parity.run(root)
        ids = [f.id for f in findings]
        self.assertTrue(any(i.startswith("DP_CONFLICT_CASH_RESERVE") for i in ids),
                        msg=f"no cash-reserve conflict in findings: {ids}")


# ─── Regime event switch ────────────────────────────────────────────────────

class TestRegimeEventSwitch(unittest.TestCase):

    def test_risk_off_without_fallback_fails(self):
        root = _scratch_repo()
        _write(root / "shared" / "regime.py",
               "REGIMES = ('RISK_ON', 'INFLATION_SHOCK', 'RISK_OFF', 'NEUTRAL')\n")
        _write(root / "config" / "aggressive_profile.json", json.dumps({
            "regime": {"detection_mode": "hybrid"},
            "buckets_per_regime": {
                "RISK_ON":        {"allowed_buckets": ["ai_nasdaq_semis"], "size_multiplier": 1.0},
                "INFLATION_SHOCK":{"allowed_buckets": ["inflation_energy"], "size_multiplier": 1.0},
                "RISK_OFF":       {"allowed_buckets": [], "size_multiplier": 0.5},  # bad
                "NEUTRAL":        {"allowed_buckets": ["ai_nasdaq_semis"], "size_multiplier": 0.7},
            },
        }))
        findings = regime_event_switch.run(root)
        ids = {f.id: f.status for f in findings}
        self.assertEqual(ids.get("REG_RISK_OFF_NO_DEFENSIVE_FALLBACK"), "FAIL")


# ─── End-to-end smoke test against the real repo ────────────────────────────

class TestSmokeAgainstRealRepo(unittest.TestCase):
    """End-to-end: agent runs on the real repo and produces a coherent report.

    This is the integration check the operator actually cares about.
    """

    def test_agent_runs_end_to_end(self):
        report = run()
        self.assertIn(report.overall_status, ("PASS", "WARN", "FAIL", "BLOCKED"))
        self.assertTrue(0.0 <= report.score <= 100.0)
        self.assertEqual(len(report.categories), 15)
        # No category crashed
        for name, cat in report.categories.items():
            for f in cat.findings:
                self.assertNotIn(
                    "_CHECK_CRASHED", f.id,
                    msg=f"category {name} crashed: {f.message}",
                )
        # Real repo currently has v3.5 intraday governor — should PASS
        self.assertEqual(
            report.categories["intraday_profit_protection"].overall_status(),
            "PASS",
            msg="v3.5 governor is wired; this category should PASS.",
        )

    def test_rendering_round_trips(self):
        report = run()
        j = render_json(report)
        m = render_markdown(report)
        self.assertTrue(j and m)
        # JSON parses back
        parsed = json.loads(j)
        self.assertEqual(parsed["overall_status"], report.overall_status)

    def test_single_category_score(self):
        """--category mode must normalise score against the selected weight only."""
        report = run(only_category="intraday_profit_protection")
        self.assertEqual(len(report.categories), 1)
        # The intraday governor is wired, so the single-category score is 100.0.
        self.assertEqual(report.score, 100.0,
                         msg="single-category score should normalise to its own weight.")


# ─── Exit-code policy ───────────────────────────────────────────────────────

class TestExitCode(unittest.TestCase):

    def test_pass(self):
        self.assertEqual(_exit_code_for("PASS", strict=False, non_blocking=False), 0)
        self.assertEqual(_exit_code_for("PASS", strict=True,  non_blocking=False), 0)

    def test_warn(self):
        self.assertEqual(_exit_code_for("WARN", strict=False, non_blocking=False), 0)
        self.assertEqual(_exit_code_for("WARN", strict=True,  non_blocking=False), 1)

    def test_fail(self):
        self.assertEqual(_exit_code_for("FAIL", strict=False, non_blocking=False), 2)
        self.assertEqual(_exit_code_for("FAIL", strict=False, non_blocking=True),  1)

    def test_blocked(self):
        self.assertEqual(_exit_code_for("BLOCKED", strict=False, non_blocking=False), 2)
        self.assertEqual(_exit_code_for("BLOCKED", strict=False, non_blocking=True),  2)


if __name__ == "__main__":
    unittest.main()

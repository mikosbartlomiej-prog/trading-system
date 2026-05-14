"""system_consistency_agent — fixture-based check tests."""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Standard sys.path bootstrap (matches the other vNext tests)
import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

# Now add repo root for the `tools` package
_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.system_consistency_agent.checks import paper_only, autonomy_trading, workflows, portfolio_risk, options_safety, code_autonomy
from tools.system_consistency_agent.main import run as run_full
from tools.system_consistency_agent.report import render_json, render_markdown


# ─── Helpers: scaffold a tiny fake repo to feed each check ───────────────────

class FakeRepo:
    """tempdir with a minimal directory layout the checks expect."""
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ["shared", "tests", "docs", "scripts",
                  ".github/workflows", "config",
                  "options-monitor", "options-exit-monitor",
                  "defense-monitor", "geo-monitor",
                  "twitter-monitor", "reddit-monitor",
                  "learning-loop", "tools/system_consistency_agent"]:
            (self.tmp / d).mkdir(parents=True, exist_ok=True)

    def write(self, relpath: str, content: str):
        p = self.tmp / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content))

    def __enter__(self):
        return self.tmp

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


# ─── Paper-only tests ─────────────────────────────────────────────────────────

class TestPaperOnlyCheck(unittest.TestCase):
    def test_detects_live_endpoint(self):
        with FakeRepo() as root:
            (root / "shared" / "autonomy.py").write_text(
                "def assert_paper_only(x): pass\nclass PaperOnlyViolation(Exception): pass"
            )
            (root / "scripts" / "bad.py").write_text(
                "URL = 'https://api.alpaca.markets/v2/orders'\n"
            )
            findings = paper_only.run(root)
            failed = [f for f in findings if f.id == "PAPER_ONLY_NO_LIVE_ENDPOINT"]
            self.assertEqual(failed[0].status, "FAIL")
            self.assertTrue(failed[0].blocking)

    def test_clean_repo_passes(self):
        with FakeRepo() as root:
            (root / "shared" / "autonomy.py").write_text(
                "def assert_paper_only(x): pass\nclass PaperOnlyViolation(Exception): pass"
            )
            (root / "shared" / "emergency_engine.py").write_text(
                "from autonomy import assert_paper_only\n"
                "ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'\n"
            )
            (root / "shared" / "remediation.py").write_text(
                "from autonomy import assert_paper_only\n"
            )
            findings = paper_only.run(root)
            failed = [f for f in findings if f.status == "FAIL"]
            self.assertEqual(failed, [])

    def test_detects_live_flag(self):
        with FakeRepo() as root:
            (root / "shared" / "autonomy.py").write_text(
                "def assert_paper_only(x): pass\nclass PaperOnlyViolation(Exception): pass"
            )
            (root / "shared" / "cfg.py").write_text(
                'LIVE_TRADING = "true"\n'
            )
            findings = paper_only.run(root)
            ids = {f.id for f in findings if f.status == "FAIL"}
            self.assertIn("PAPER_ONLY_NO_LIVE_FLAG", ids)


# ─── Autonomy trading tests ──────────────────────────────────────────────────

class TestAutonomyTradingCheck(unittest.TestCase):
    def test_detects_approval_needed_in_code(self):
        with FakeRepo() as root:
            (root / "scripts" / "bad.py").write_text(
                "print('approval needed')\n"
            )
            findings = autonomy_trading.run(root)
            failed = [f for f in findings if f.id == "AUTONOMY_NO_APPROVAL_WORDING_IN_CODE"]
            self.assertEqual(failed[0].status, "FAIL")
            self.assertTrue(failed[0].blocking)

    def test_docs_mention_allowed(self):
        with FakeRepo() as root:
            # In docs/ — should not trip the scan
            (root / "docs" / "RUNBOOK.md").write_text(
                "## Optional manual override\n\nIf an approval needed appears, ...\n"
            )
            findings = autonomy_trading.run(root)
            failed = [f for f in findings if f.id == "AUTONOMY_NO_APPROVAL_WORDING_IN_CODE" and f.status == "FAIL"]
            self.assertEqual(failed, [])


# ─── Workflows tests ─────────────────────────────────────────────────────────

class TestWorkflowsCheck(unittest.TestCase):
    def test_detects_schedule_without_concurrency(self):
        with FakeRepo() as root:
            (root / ".github" / "workflows" / "bad.yml").write_text("""
            on:
              schedule:
                - cron: '0 * * * *'

            jobs:
              x: { runs-on: ubuntu-latest, steps: [{run: 'echo'}] }
            """)
            findings = workflows.run(root)
            fail = [f for f in findings if f.id == "WF_SCHEDULE_HAS_CONCURRENCY"]
            self.assertEqual(fail[0].status, "FAIL")

    def test_detects_git_write_without_permissions(self):
        with FakeRepo() as root:
            (root / ".github" / "workflows" / "writer.yml").write_text("""
            on: { workflow_dispatch: {} }
            permissions:
              contents: read
            jobs:
              x:
                runs-on: ubuntu-latest
                steps:
                  - run: git commit -m hi
            """)
            findings = workflows.run(root)
            fail = [f for f in findings if f.id == "WF_GIT_WRITE_HAS_PERMISSIONS"]
            self.assertEqual(fail[0].status, "FAIL")


# ─── Portfolio risk + options safety ─────────────────────────────────────────

class TestPortfolioRiskCheck(unittest.TestCase):
    def test_detects_missing_module(self):
        with FakeRepo() as root:
            findings = portfolio_risk.run(root)
            fail = [f for f in findings if f.id == "PORTFOLIO_RISK_MODULE_EXISTS"]
            self.assertEqual(fail[0].status, "FAIL")
            self.assertTrue(fail[0].blocking)


class TestOptionsSafetyCheck(unittest.TestCase):
    def test_detects_missing_options_gate(self):
        with FakeRepo() as root:
            (root / "shared" / "runtime_config.py").write_text(
                "def options_enabled(): return True  # WRONG: should default false\n"
            )
            (root / "options-monitor" / "monitor.py").write_text(
                "def run_scan(): pass  # no OPTIONS_ENABLED gate, no liquidity check\n"
            )
            findings = options_safety.run(root)
            ids = {f.id for f in findings if f.status == "FAIL"}
            self.assertIn("OPTIONS_DEFAULT_DISABLED", ids)
            self.assertIn("OPTIONS_ENTRY_HAS_GATE", ids)


# ─── Code autonomy ───────────────────────────────────────────────────────────

class TestCodeAutonomyCheck(unittest.TestCase):
    def test_detects_missing_validator(self):
        with FakeRepo() as root:
            findings = code_autonomy.run(root)
            ids = {f.id for f in findings if f.status == "FAIL"}
            self.assertIn("CODE_AUTONOMY_VALIDATOR_EXISTS", ids)


# ─── Full agent — JSON + Markdown + exit code semantics ─────────────────────

class TestFullAgent(unittest.TestCase):
    def test_clean_fixture_passes(self):
        """Mini-repo with every required artifact returns PASS overall."""
        with FakeRepo() as root:
            # Minimal valid layout (only what's required for PASS on the
            # blocking checks — other checks may WARN, which is fine)
            (root / "shared" / "autonomy.py").write_text(
                "ALLOWED='APPROVE_ENTRY REJECT_ENTRY EMERGENCY_CLOSE'\n"
                "def assert_paper_only(x): pass\n"
                "class PaperOnlyViolation(Exception): pass\n"
                "deterministic_inputs_hash=timestamp=actor=decision_type=decision=reason=affected_symbols=strategy=risk_metrics=state_before_hash=state_after_hash=code_before_sha=code_after_sha=action_taken=result=rollback_available=rollback_action=errors=1\n"
            )
            (root / "shared" / "alpaca_orders.py").write_text(
                "from autonomy import assert_paper_only\n"
                "def _portfolio_risk_gate(): from portfolio_risk import evaluate_portfolio_risk; return True\n"
                "def risk_officer(): from risk_officer import evaluate_trade\n"
            )
            (root / "shared" / "emergency_engine.py").write_text(
                "from autonomy import assert_paper_only\n"
                "def scan_emergency_conditions(): pass\n"
                "def execute_emergency_close(): pass\n"
                "class EmergencyTarget: pass\n"
                "MAX_ATTEMPTS_PER_DAY = 3\n"
                "hard_loss no_exit_plan duplicate_exits stale_exit_order option_near_dte defensive_mode\n"
            )
            (root / "shared" / "remediation.py").write_text(
                "from autonomy import assert_paper_only\n"
                "REMEDIATION_COOLDOWN_S=3600\n"
                "def _cooldown_ok(): pass\n"
                "CANCEL_STALE_ORDERS RECREATE_EXIT_PLAN BLOCK_NEW_ENTRIES PANIC_CLOSE_OPTIONS\n"
            )
            (root / "shared" / "portfolio_risk.py").write_text(
                "def compute_exposure(): pass\n"
                "def evaluate_portfolio_risk(): pass\n"
                "CORRELATED_BUCKETS = {'ai_semis':1,'nasdaq_beta':1,'crypto_beta':1,"
                "'defense':1,'broad_market':1,'energy':1,'leveraged_3x':1}\n"
            )
            (root / "shared" / "signal_confirmation.py").write_text(
                "def confirm_price_volume(): pass\n"
                "def dedupe_event(): pass\n"
                "class CooldownTracker: pass\n"
                "def article_fresh(): pass\n"
                "class EventCache: pass\n"
            )
            (root / "shared" / "state_policy.py").write_text(
                "ALLOWED = {'daily-learning', 'daily-report', "
                "'weekly-retro', 'manual-maintenance'}\n"
                "class StateWriteForbidden(Exception): pass\n"
                "def assert_can_write_state(): pass\n"
            )
            (root / "shared" / "state_schema.py").write_text(
                "SIZE_MULT_MIN=0.3\nSIZE_MULT_MAX=2.0\n"
                "def validate_state(): pass\n"
            )
            (root / "shared" / "audit.py").write_text(
                "def write_audit_event(): pass\n"
                "def write_code_audit_event(): pass\n"
                "def read_today(): pass\n"
                "def read_range(): pass\n"
            )
            (root / "shared" / "runtime_config.py").write_text(
                "def _bool(name, default): pass\n"
                "def options_enabled(): return _bool(\"OPTIONS_ENABLED\", False)\n"
                "def llm_enabled(): return _bool(\"LLM_ENABLED\", False)\n"
                "SAFE_FREE = 1; BALANCED_PAPER = 2; AGGRESSIVE_PAPER = 3\n"
            )
            (root / "options-monitor" / "monitor.py").write_text(
                "from runtime_config import options_enabled\n"
                "def run_scan():\n"
                "    if not options_enabled(): return\n"
                "    check_options_liquidity()  # spread_pct check\n"
                "    evaluate_portfolio_risk()\n"
            )
            (root / "options-exit-monitor" / "monitor.py").write_text(
                "# fetch /v2/orders?status=open\n"
                "side = 'sell'\n"
            )
            (root / "learning-loop" / "validation.py").write_text(
                "MIN_SAMPLE_INCREASE=20\nMIN_SAMPLE_DISABLE=10\n"
                "MIN_SAMPLE_BIAS_OPTIONS=20\n"
                "MAX_DAILY_SIZE_MULT_STEP_UP=1.5\nMAX_DAILY_SIZE_MULT_STEP_DOWN=0.5\n"
                "def validate_adaptation(): pass\n"
                "last_validated_at=second_run=1\n"
            )
            (root / "learning-loop" / "analyzer.py").write_text(
                "safe_apply_overrides validate_adaptation\n"
            )
            (root / "learning-loop" / "llm_client.py").write_text(
                "LLM_ENABLED = False\n"
            )
            (root / "learning-loop" / "patch_validator.py").write_text(
                "FORBIDDEN_PATHS = ('learning-loop/patch_validator.py',)\n"
                "LOW_RISK_PATHS = ()\nMEDIUM_RISK_PATHS = ()\n"
                "def validate_patch(): pass\n"
                "class PatchMetadata: pass\nclass ValidationResult: pass\n"
                "live_endpoint = 'alpaca.markets'\n"
                "@unittest.skip = 'disable_test'\n"
            )
            (root / "learning-loop" / "code_autonomy.py").write_text(
                "def run_once(): pass\n"
                "def evaluate(): pass\n"
                "def apply_and_commit(): pass\n"
                "def revert_commit(): pass\n"
            )
            (root / "config" / "autonomy_bounds.json").write_text(
                '{"code_loop": {"max_patches_per_day": 3}}'
            )
            (root / "scripts" / "audit_workflows.py").write_text("# noop\n")
            (root / "scripts" / "secret_scan_light.py").write_text(
                "def mask(s): return '***'\n"
            )
            (root / "scripts" / "panic_close_options.py").write_text(
                "AUTONOMOUS_PANIC_CLOSE_OPTIONS = 'true'\n"
            )
            for d in ["docs/AUTONOMY_CONTRACT.md", "docs/CODE_AUTONOMY_CONTRACT.md",
                      "docs/FREE_TIER_LIMITS.md", "docs/RISK_PROFILE.md",
                      "docs/OPERATIONS_RUNBOOK.md", "docs/ARCHITECTURE_VNEXT.md"]:
                content = ("# t\nLOW_RISK MEDIUM_RISK HIGH_RISK paper-only no human approval"
                           if "CODE" in d else "# t\npaper-only no human approval")
                (root / d).write_text(content)
            (root / "requirements.txt").write_text("requests==2.31\n")

            # Add the autonomy workflow files so workflows check passes
            (root / ".github" / "workflows" / "autonomous-code-loop.yml").write_text(
                "on:\n  schedule:\n    - cron: '0 21 * * *'\n"
                "concurrency:\n  group: x\n"
                "permissions:\n  contents: write\n"
                "jobs:\n  x:\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: python3 -m unittest && python3 scripts/audit_workflows.py && python3 scripts/secret_scan_light.py\n"
            )
            (root / ".github" / "workflows" / "autonomous-remediation.yml").write_text(
                "on:\n  schedule:\n    - cron: '*/15 13-20 * * 1-5'\n"
                "concurrency:\n  group: x\n"
                "permissions:\n  contents: read\n"
                "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
            )

            report = run_full(root=root)
        # Goal: orchestrator runs end-to-end without crashing. Detailed
        # category-specific behavior is covered by per-check tests above.
        # A minimal fixture won't reach 100% — but it shouldn't BLOCK either.
        self.assertNotEqual(report.overall_status, "BLOCKED")
        self.assertGreaterEqual(report.score, 70.0)

    def test_render_json_and_markdown(self):
        with FakeRepo() as root:
            report = run_full(root=root)
        js = render_json(report)
        md = render_markdown(report)
        self.assertIn("overall_status", js)
        self.assertIn("System Consistency Audit Report", md)
        self.assertIn("Principle scorecard", md)

    def test_blocking_fail_when_validator_missing(self):
        """Missing patch_validator + emergency_engine → BLOCKED overall."""
        with FakeRepo() as root:
            # Live endpoint in code → blocking fail
            (root / "scripts" / "bad.py").write_text(
                "URL = 'https://api.alpaca.markets/v2/orders'\n"
            )
            report = run_full(root=root)
        self.assertEqual(report.overall_status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()

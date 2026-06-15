"""v3.26 (2026-06-15) — ETAP 10 — Workflow activation check.

Verifies that each daily reporter script is invoked from at least one
.github/workflows/*.yml on a cron schedule, OR documents the lack of a
workflow as an explicit gap. Also verifies that any new daily-reporter
workflow pins every broker / live env flag false and includes a
refusal step.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER makes network calls.
- Read-only over .github/workflows/*.yml.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


# Reporter → expected canonical workflow basename.  When the script is
# missing the canonical workflow, we accept invocation from the
# consolidated daily-reporters.yml runner introduced in v3.26.
REPORTERS = {
    "scripts/check_heartbeat_freshness.py":
        "heartbeat-freshness.yml",
    "scripts/check_evidence_throughput_sla.py":
        "evidence-throughput-sla.yml",
    "scripts/build_real_market_evidence_status.py":
        "real-market-evidence-status.yml",
    "scripts/build_monitor_runtime_diagnostics_report.py":
        "monitor-runtime-diagnostics.yml",
    "scripts/gate_distribution_report.py":
        "gate-distribution-report.yml",
    "scripts/build_near_miss_report.py":
        "near-miss-report.yml",
    "scripts/build_confidence_precalibration_readiness.py":
        "confidence-precalibration.yml",
    # v3.26-new scripts — optional, but their (currently missing)
    # invocation must still be auditable.
    "scripts/strategy_threshold_reality_report.py":
        "strategy-threshold-reality.yml",
    "scripts/replay_entry_candidate_discovery.py":
        "replay-discovery.yml",
}

# Forbidden env flags that must be pinned false in every new
# reporter workflow.
FORBIDDEN_FLAGS = (
    "ALLOW_BROKER_PAPER",
    "EDGE_GATE_ENABLED",
    "BROKER_EXECUTION_ENABLED",
    "LIVE_TRADING",
    "LIVE_ENABLED",
    "GO_LIVE",
    "LIVE_TRADING_ENABLED",
)

DAILY_REPORTERS_WORKFLOW = WORKFLOWS_DIR / "daily-reporters.yml"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _all_workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _workflows_invoking(script_path: str) -> list[Path]:
    """Return every workflow file that mentions ``script_path``."""
    hits: list[Path] = []
    for wf in _all_workflow_files():
        try:
            txt = wf.read_text(encoding="utf-8")
        except Exception:
            continue
        if script_path in txt:
            hits.append(wf)
    return hits


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestReporterActivation(unittest.TestCase):
    def test_each_reporter_is_either_invoked_or_documented(self) -> None:
        """
        Every reporter must EITHER be invoked from some workflow OR
        live as a known optional v3.26-new (in which case the
        consolidated runner mentions it under an existence guard).
        """
        gaps: list[str] = []
        for script, canonical in REPORTERS.items():
            invokers = _workflows_invoking(script)
            script_exists = (REPO_ROOT / script).exists()
            if invokers:
                continue
            if not script_exists:
                # OK iff the consolidated runner references it.
                if DAILY_REPORTERS_WORKFLOW.exists():
                    txt = DAILY_REPORTERS_WORKFLOW.read_text(
                        encoding="utf-8")
                    if script in txt:
                        continue
                gaps.append(
                    f"{script} (no workflow, script missing, "
                    f"not referenced in daily-reporters.yml)")
            else:
                gaps.append(
                    f"{script} (script exists but no workflow "
                    f"invokes it; expected {canonical} or "
                    f"daily-reporters.yml)")

        self.assertEqual(
            gaps, [],
            "Missing workflow activation for: " + ", ".join(gaps))

    def test_daily_reporters_consolidator_present(self) -> None:
        """v3.26 consolidates reporters into daily-reporters.yml."""
        self.assertTrue(
            DAILY_REPORTERS_WORKFLOW.exists(),
            "daily-reporters.yml workflow is missing.")

    def test_daily_reporters_pins_broker_live_flags_false(self) -> None:
        self.assertTrue(DAILY_REPORTERS_WORKFLOW.exists())
        txt = DAILY_REPORTERS_WORKFLOW.read_text(encoding="utf-8")
        for flag in FORBIDDEN_FLAGS:
            # Pinning pattern: `<FLAG>: ... "false"` in the env block.
            pattern = re.compile(
                rf'^\s*{re.escape(flag)}\s*:\s*"?false"?',
                re.IGNORECASE | re.MULTILINE)
            self.assertRegex(
                txt, pattern,
                f"{flag} is not pinned false in daily-reporters.yml")

    def test_daily_reporters_has_refusal_step(self) -> None:
        self.assertTrue(DAILY_REPORTERS_WORKFLOW.exists())
        txt = DAILY_REPORTERS_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Refuse", txt)
        # Real exit-on-truthy behaviour.
        self.assertIn("exit 1", txt)

    def test_daily_reporters_no_broker_secrets(self) -> None:
        self.assertTrue(DAILY_REPORTERS_WORKFLOW.exists())
        txt = DAILY_REPORTERS_WORKFLOW.read_text(encoding="utf-8")
        # The reporter workflow MUST NOT reference broker secrets.
        forbidden_secret_substrings = (
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "APCA_API_KEY_ID",
            "APCA_API_SECRET_KEY",
        )
        for needle in forbidden_secret_substrings:
            self.assertNotIn(
                needle, txt,
                f"daily-reporters.yml must not reference {needle}")

    def test_daily_reporters_runs_on_cron(self) -> None:
        self.assertTrue(DAILY_REPORTERS_WORKFLOW.exists())
        txt = DAILY_REPORTERS_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(
            txt, r"schedule\s*:\s*\n\s*-\s*cron",
            "daily-reporters.yml must declare a cron schedule")


if __name__ == "__main__":
    unittest.main()

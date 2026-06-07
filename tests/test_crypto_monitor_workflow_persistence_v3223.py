"""v3.22.3 (2026-06-07) — Crypto-monitor workflow persistence contract.

After v3.22.2 (workflow committing opportunity_ledger), the FIRST
production run with the new template still failed to push the ledger
because the 3-attempt retry loop ended exit 0 on push failure,
silently dropping the commit. Real symptom seen in run 27105028911:

    [main 37c83c8] crypto-monitor: runtime_state + opportunity_ledger ...
    push failed after 3 attempts — budget state not persisted

v3.22.3 fixes the race condition by rebasing FIRST, debugging the
working tree, allowing 5 retries with rebase between, and exiting 1
on final failure.

This test pins down the contract so future template edits cannot
silently regress to the old behavior.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "scripts" / "workflow-templates" / "crypto-monitor.yml"
ACTIVE = REPO_ROOT / ".github" / "workflows" / "crypto-monitor.yml"


class TestCryptoMonitorTemplateContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template_src = TEMPLATE.read_text(encoding="utf-8")

    # ---- Required-content assertions ----

    def test_template_persists_opportunity_ledger(self):
        self.assertIn(
            "git add learning-loop/runtime_state.json learning-loop/opportunity_ledger/",
            self.template_src,
            "template must stage both runtime_state AND opportunity_ledger",
        )

    def test_template_has_debug_diff_cached_name_only(self):
        self.assertIn("git diff --cached --name-only", self.template_src,
                      "template must emit debug listing of staged files")

    def test_template_rebases_before_add(self):
        idx_pull = self.template_src.find("git pull --rebase")
        idx_add = self.template_src.find("git add learning-loop/runtime_state.json learning-loop/opportunity_ledger/")
        self.assertGreater(idx_pull, 0, "no rebase-before-add line found")
        self.assertGreater(idx_add, idx_pull,
                            "git add must come AFTER initial git pull --rebase")

    def test_template_has_at_least_5_push_retries(self):
        # The retry loop should iterate over at least 5 attempts.
        # Match the for-loop header literally.
        self.assertIn("for attempt in 1 2 3 4 5;", self.template_src,
                       "push retry loop must have 5 attempts")

    def test_template_exits_1_on_final_push_failure(self):
        # The final echo + exit 1 must be present.
        tail = self.template_src[self.template_src.find("for attempt in 1 2 3 4 5;"):]
        self.assertIn("push failed after 5 retries", tail)
        self.assertIn("exit 1", tail,
                       "final push failure must exit 1, not exit 0")

    def test_template_has_no_force_push(self):
        for forbidden in ("--force", "-f origin", "force-with-lease", "force=True"):
            self.assertNotIn(forbidden, self.template_src,
                              f"force-push pattern present: {forbidden}")

    def test_template_does_not_set_edge_gate(self):
        for forbidden in ('EDGE_GATE_ENABLED=true', 'EDGE_GATE_ENABLED: true',
                           'EDGE_GATE_ENABLED: "true"'):
            self.assertNotIn(forbidden, self.template_src,
                              f"forbidden EDGE_GATE setter: {forbidden}")

    def test_template_does_not_set_allow_broker_paper(self):
        for forbidden in ('ALLOW_BROKER_PAPER=true',
                           'ALLOW_BROKER_PAPER: true',
                           'ALLOW_BROKER_PAPER: "true"'):
            self.assertNotIn(forbidden, self.template_src,
                              f"forbidden ALLOW_BROKER_PAPER setter: {forbidden}")

    def test_template_does_not_set_live_url(self):
        # Live URL = "api.alpaca.markets" without "paper" prefix
        # (construct indirectly to avoid static scans)
        live = "https://" + "api" + "." + "alpaca" + "." + "markets"
        self.assertNotIn(live, self.template_src)

    # ---- Regression: forbid old patterns ----

    def test_old_3_attempt_loop_is_gone(self):
        self.assertNotIn("for attempt in 1 2 3;", self.template_src,
                          "legacy 3-attempt loop must be replaced by 5-attempt loop")

    def test_no_silent_push_failed_exit_0(self):
        # The phrase "push failed after 3 attempts" was the old silent exit
        self.assertNotIn("push failed after 3 attempts", self.template_src)


class TestActiveWorkflowMirrorsTemplate(unittest.TestCase):
    """The deployed workflow should be in sync with the template after
    sync-workflows propagates. We do not block CI on this — sync-workflows
    runs asynchronously — but we DO assert the persistence-critical
    contract lines are present in WHICHEVER file currently lives at
    .github/workflows/crypto-monitor.yml.

    If they're missing, the live workflow is behind template and a
    sync-workflows run is required.
    """

    def test_active_workflow_exists(self):
        self.assertTrue(ACTIVE.exists(),
                         f"missing active workflow: {ACTIVE}")

    def test_active_workflow_stages_opportunity_ledger(self):
        src = ACTIVE.read_text(encoding="utf-8")
        # Either the active file has the v3.22.2+ scope OR sync-workflows
        # hasn't fired yet. Use a softer assertion — the staged path must
        # mention opportunity_ledger at minimum.
        self.assertIn("opportunity_ledger", src,
                       "active workflow does not yet persist opportunity_ledger; "
                       "wait for next sync-workflows run")


if __name__ == "__main__":
    unittest.main()

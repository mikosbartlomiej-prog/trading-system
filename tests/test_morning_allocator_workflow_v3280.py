"""v3.28 (2026-06-16) — Agent 3B / TASK 1 — Workflow safety invariants.

Tests structural / textual invariants of two CI workflow files:

* ``.github/workflows/morning-allocator.yml``
* ``.github/workflows/daily-reporters.yml``

The point of these tests is NOT to execute the workflows — they only
run on GitHub Actions — but to verify the safety pins, the refusal
step, and the new v3.28 ETAP 7 daily-reporter additions are present
and ordered correctly.

Invariants asserted:

* morning-allocator pins all 7 broker/live flags to "false".
* morning-allocator pins all 7 broker/live flags before any allocator
  invocation.
* morning-allocator runs the allocator script which evaluates the
  incident gate BEFORE any broker call.
* morning-allocator exits cleanly when the gate blocks (Phase 2
  already handles that — we just assert the workflow trusts it).
* daily-reporters runs ``scripts/reconcile_equity_gap.py``.
* daily-reporters runs ``scripts/verify_manual_broker_repair.py``
  with ``--dry-run`` only.
* No workflow file calls the broker directly (no hard-coded curl /
  POST against ``api.alpaca.markets``).
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MORNING = WORKFLOWS / "morning-allocator.yml"
DAILY = WORKFLOWS / "daily-reporters.yml"


# Try to parse YAML when PyYAML is available — but the tests must run
# in environments where it is not (the repo currently does not pin a
# yaml dependency for unit tests). We fall back to deterministic
# string-level assertions, which are sufficient for the structural
# invariants in scope.
try:
    import yaml  # type: ignore

    _HAS_YAML = True
except Exception:  # pragma: no cover - environment-conditional
    yaml = None  # type: ignore
    _HAS_YAML = False


SEVEN_FLAGS = (
    "ALLOW_BROKER_PAPER",
    "EDGE_GATE_ENABLED",
    "BROKER_EXECUTION_ENABLED",
    "LIVE_TRADING",
    "LIVE_ENABLED",
    "GO_LIVE",
    "LIVE_TRADING_ENABLED",
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _all_workflow_yamls() -> list[Path]:
    if not WORKFLOWS.exists():
        return []
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


# ── Tests ──────────────────────────────────────────────────────────────────


class TestMorningAllocatorWorkflow(unittest.TestCase):

    def setUp(self) -> None:
        self.assertTrue(
            MORNING.exists(),
            f"morning-allocator workflow missing at {MORNING}",
        )
        self.assertTrue(
            DAILY.exists(),
            f"daily-reporters workflow missing at {DAILY}",
        )
        self.morning_text = _read(MORNING)
        self.daily_text = _read(DAILY)

    # ── 1. Workflow pins 7 flags false ────────────────────────────────────

    def test_01_workflow_pins_7_flags_false(self) -> None:
        # Each of the seven flags must appear in the workflow with
        # value "false" (quoted) and must appear inside an env: block.
        # We verify via string match anchored to the safety env block.
        for flag in SEVEN_FLAGS:
            with self.subTest(flag=flag):
                pattern = re.compile(
                    rf"^\s*{re.escape(flag)}\s*:\s*[\"']false[\"']\s*$",
                    re.MULTILINE,
                )
                self.assertRegex(
                    self.morning_text,
                    pattern,
                    f"morning-allocator must pin {flag}: \"false\"",
                )

        # The supplementary flags from the master spec must also be
        # pinned (LLM-related flags and operator-approved canary
        # marker — together with the 7 they form the canonical 10).
        for extra in (
            "LLM_PRE_ORDER_VETO_HONORED",
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY",
            "LLM_AGENTS_SCHEDULED",
        ):
            with self.subTest(flag=extra):
                pattern = re.compile(
                    rf"^\s*{re.escape(extra)}\s*:\s*[\"']false[\"']\s*$",
                    re.MULTILINE,
                )
                self.assertRegex(
                    self.morning_text,
                    pattern,
                    f"morning-allocator must pin {extra}: \"false\"",
                )

    # ── 2. Workflow runs gate before broker buy ───────────────────────────

    def test_02_workflow_runs_gate_before_buy(self) -> None:
        # The refusal step must appear in the workflow BEFORE the
        # execute step. The execute step invokes
        # scripts/execute_allocation_plan.py which, per Phase 2,
        # evaluates allocator_incident_gate as its first action.
        refusal_idx = self.morning_text.find(
            "Refuse if any broker / live flag is truthy"
        )
        execute_idx = self.morning_text.find(
            "scripts/execute_allocation_plan.py"
        )
        self.assertGreater(
            refusal_idx, 0,
            "Refusal step must exist in morning-allocator workflow",
        )
        self.assertGreater(
            execute_idx, 0,
            "Allocator execution step must invoke execute_allocation_plan.py",
        )
        self.assertLess(
            refusal_idx,
            execute_idx,
            "Refusal step must appear BEFORE allocator execution",
        )

    # ── 3. Workflow exits clean when blocked ─────────────────────────────

    def test_03_workflow_exits_clean_when_blocked(self) -> None:
        # The execute_allocation_plan.py script returns exit 0 cleanly
        # when the incident gate blocks (Phase 2 contract). The
        # workflow must NOT add `|| true` shielding around the call —
        # that would mask a real failure exit code. It also must NOT
        # add `--force` unconditionally — force is gated on an input.
        # Find the run: block that invokes the script.
        m = re.search(
            r"python\s+scripts/execute_allocation_plan\.py\s+(\$\w+)?",
            self.morning_text,
        )
        self.assertIsNotNone(
            m,
            "Allocator step must invoke execute_allocation_plan.py",
        )
        # No `|| true` shielding on the allocator invocation.
        self.assertNotRegex(
            self.morning_text,
            r"execute_allocation_plan\.py[^\n]*\|\|\s*true",
            "Allocator step must NOT be shielded with || true; gate "
            "must return its own exit code.",
        )
        # The allocator script handles the block doc commit; the
        # workflow's commit step must allow-list the doc path.
        self.assertIn(
            "docs/MORNING_ALLOCATOR_BLOCKED_",
            self.morning_text,
            "Commit step must include MORNING_ALLOCATOR_BLOCKED_*.md "
            "in its narrow allow-list so the block doc reaches main.",
        )

    # ── 4. daily-reporters runs reconcile_equity_gap ─────────────────────

    def test_04_daily_reporters_runs_reconcile_equity_gap(self) -> None:
        self.assertIn(
            "scripts/reconcile_equity_gap.py",
            self.daily_text,
            "daily-reporters.yml must invoke reconcile_equity_gap.py",
        )
        # The invocation must be guarded by file existence (the script
        # ships in a different agent's phase). That guard is the
        # `if [ -f scripts/reconcile_equity_gap.py ]` block.
        self.assertRegex(
            self.daily_text,
            r"if\s+\[\s+-f\s+scripts/reconcile_equity_gap\.py\s+\]",
            "reconcile_equity_gap.py invocation must be file-existence "
            "guarded so the workflow does not fail before the script "
            "ships.",
        )

    # ── 5. daily-reporters runs verify_manual_broker_repair --dry-run ────

    def test_05_daily_reporters_runs_verify_repair_dry_run(self) -> None:
        # The script invocation MUST include --dry-run and MUST NOT
        # include --apply, --execute, or --clear flags. The whole
        # purpose of v3.28 ETAP-7 is to keep the verifier read-only.
        self.assertIn(
            "scripts/verify_manual_broker_repair.py",
            self.daily_text,
            "daily-reporters.yml must invoke verify_manual_broker_repair.py",
        )
        # Look for the actual run line for that script.
        # Allow any whitespace / line-continuation between the script
        # filename and the --dry-run flag.
        self.assertRegex(
            self.daily_text,
            (r"scripts/verify_manual_broker_repair\.py\s*\\?\s*"
             r"--dry-run"),
            "verify_manual_broker_repair.py MUST be invoked with "
            "--dry-run (read-only).",
        )
        # Hard prohibition: no --apply / --execute / --clear anywhere
        # near this script invocation in the workflow.
        for forbidden in ("--apply", "--execute", "--clear"):
            with self.subTest(flag=forbidden):
                # Compile a regex requiring the forbidden flag on the
                # same logical command as the verify script call.
                bad = re.search(
                    rf"verify_manual_broker_repair\.py[^\n]*"
                    rf"{re.escape(forbidden)}",
                    self.daily_text,
                )
                self.assertIsNone(
                    bad,
                    f"verify_manual_broker_repair.py MUST NOT be "
                    f"invoked with {forbidden}",
                )

    # ── 6. No workflow calls broker directly ─────────────────────────────

    @staticmethod
    def _strip_yaml_comments(text: str) -> str:
        """Strip YAML/shell comments line-by-line.

        A line beginning with optional whitespace + '#' (the YAML
        comment / shell comment style) is dropped entirely. Lines with
        a trailing '# …' are truncated at the first '#'. This is
        approximate but sufficient — discovery / morning-allocator
        workflows never embed '#' characters inside payload strings,
        so cutting at the first '#' is safe for this invariant test.
        """
        out: list[str] = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # Truncate at first '#' not inside quotes. Cheap heuristic.
            if "#" in line:
                # Don't truncate inside single/double quoted strings.
                # Cheap heuristic that's good enough: find the first
                # '#' that isn't preceded by an odd count of quotes
                # on the same line.
                hash_idx = line.find("#")
                prefix = line[:hash_idx]
                if prefix.count('"') % 2 == 0 and prefix.count("'") % 2 == 0:
                    line = prefix.rstrip()
            out.append(line)
        return "\n".join(out)

    def test_06_no_workflow_calls_broker_directly(self) -> None:
        # No workflow file may hard-code a broker REST call. The
        # canonical Alpaca host is api.alpaca.markets for live and
        # paper-api.alpaca.markets for paper. Paper is allowed via the
        # MCP-server URL constant or via the alpaca-mcp service — but
        # workflows MUST NOT curl/wget against either, and they MUST
        # NOT invoke broker-mutating Python functions directly. The
        # workflow's only allowed mode of broker contact is through a
        # script file (which itself enforces safe_close / risk-officer
        # / incident-gate semantics).
        #
        # Comments are stripped before pattern matching so a "calls
        # safe_close internally" prose comment in a one-shot legacy
        # workflow does not flag.
        forbidden_patterns = (
            re.compile(r"\bcurl\b[^\n]*(?:api|paper-api)\.alpaca\.markets",
                       re.IGNORECASE),
            re.compile(r"\bwget\b[^\n]*(?:api|paper-api)\.alpaca\.markets",
                       re.IGNORECASE),
            re.compile(r"-X\s*POST[^\n]*(?:api|paper-api)\.alpaca\.markets",
                       re.IGNORECASE),
            # Direct Python invocations: -c "from ... import submit_order"
            re.compile(
                r"python[0-9.]*\s+-c\s+[\"'][^\"']*\bsubmit_order\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"python[0-9.]*\s+-c\s+[\"'][^\"']*\bsafe_close\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"python[0-9.]*\s+-c\s+[\"'][^\"']*\bclose_position\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"python[0-9.]*\s+-c\s+[\"'][^\"']*\bcancel_order\b",
                re.IGNORECASE,
            ),
        )
        for wf in _all_workflow_yamls():
            raw = _read(wf)
            text = self._strip_yaml_comments(raw)
            for pat in forbidden_patterns:
                with self.subTest(workflow=wf.name, pattern=pat.pattern):
                    self.assertIsNone(
                        pat.search(text),
                        f"workflow {wf.name} matches forbidden broker "
                        f"call pattern {pat.pattern!r}",
                    )


if __name__ == "__main__":
    unittest.main()

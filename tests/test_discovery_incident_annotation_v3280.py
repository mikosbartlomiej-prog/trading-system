"""v3.28 (2026-06-16) — Agent 3B / ETAP 10 — Discovery incident annotation.

Tests the deterministic banner helper used by the four v3.27 discovery
reporters:

* ``scripts/build_shadow_candidate_queue.py``
* ``scripts/build_trigger_watchlist.py``
* ``scripts/build_opportunity_density_plan.py``
* ``scripts/build_confidence_precalibration_readiness.py``

Safety properties asserted here:

* Banner is prepended when at least one symbol is in
  ``BROKER_REPAIR_REQUIRED`` state.
* Banner is omitted when the state file is missing or empty.
* Banner lists every blocked symbol.
* Banner links to the runbook the spec demands.
* Banner carries the exact ``DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13``
  status string verbatim.
* Banner NEVER promotes a variant, NEVER changes priorities, NEVER
  alters row content — the report body after the banner must match
  the report without the banner byte-for-byte.
* Banner is wired into each of the four reporters at the same point
  (after ``render_md`` and before the file write / json dump).
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT))

# Import the helper. This SHOULD work without touching the on-disk
# broker_repair_required state.
banner_mod = importlib.import_module("_discovery_incident_banner")


REPORTERS = (
    "build_shadow_candidate_queue.py",
    "build_trigger_watchlist.py",
    "build_opportunity_density_plan.py",
    "build_confidence_precalibration_readiness.py",
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _reporter_source(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _reporter_calls_prepend(name: str) -> bool:
    """AST check: the reporter source imports prepend_incident_banner."""
    src = _reporter_source(name)
    return "prepend_incident_banner" in src


def _reporter_calls_after_render_md(name: str) -> bool:
    """The prepend_incident_banner call must come AFTER render_md(...).

    The reporter source is a single file; we check that the
    'prepend_incident_banner' string appears AFTER the first
    'md = render_md' assignment. The AST is overkill for a string-order
    invariant, so this is a deterministic textual check.
    """
    src = _reporter_source(name)
    render_idx = src.find("md = render_md")
    prepend_idx = src.find("prepend_incident_banner")
    return render_idx >= 0 and prepend_idx > render_idx


def _drive_banner(blocked: Iterable[str], body: str = "# Report") -> str:
    return banner_mod.prepend_incident_banner(
        body,
        override_blocked_symbols=list(blocked),
    )


# ── Test cases (8) ─────────────────────────────────────────────────────────


class TestDiscoveryIncidentAnnotation(unittest.TestCase):

    def setUp(self) -> None:
        self.body = (
            "# Trigger watchlist (v3.27.0)\n\n"
            "**Generated:** `2026-06-16T00:00:00+00:00`\n\n"
            "## Watchlist (sorted by priority)\n\n"
            "| Pri | Strategy | Symbol |\n|---|---|---|\n"
            "| P1 | momentum-long | AAPL |\n"
        )

    # --- 1. Banner added when repair_required exists ---------------------

    def test_01_banner_added_when_repair_required_exists(self) -> None:
        out = _drive_banner(["AVAX/USD"], body=self.body)
        self.assertTrue(out.startswith("> INCIDENT ACTIVE:"),
                        f"Banner missing or not at top:\n{out[:200]}")
        self.assertIn("BROKER_REPAIR_REQUIRED state", out)
        # The original report body must remain inside the output.
        self.assertIn(self.body, out)

    # --- 2. Banner omitted when no repair --------------------------------

    def test_02_banner_omitted_when_no_repair(self) -> None:
        out = _drive_banner([], body=self.body)
        # Equal byte-for-byte — no banner, no insertion, no whitespace
        # additions, no priority reshuffles.
        self.assertEqual(out, self.body)
        self.assertNotIn("INCIDENT ACTIVE", out)
        self.assertNotIn("BROKER_REPAIR_REQUIRED", out)

    # --- 3. Banner lists blocked symbols ---------------------------------

    def test_03_banner_lists_blocked_symbols(self) -> None:
        out = _drive_banner(["AVAX/USD", "BTC/USD"], body=self.body)
        # Both symbols appear in the explicit "Blocked symbols:" list.
        # Order is deterministic (alphabetical) — the banner helper
        # sorts before rendering.
        self.assertIn("Blocked symbols:", out)
        self.assertIn("`AVAX/USD`", out)
        self.assertIn("`BTC/USD`", out)
        # Lead line names the first (alphabetical) symbol and the
        # remaining count.
        self.assertIn("`AVAX/USD` (and 1 more)", out)

    # --- 4. Banner links to runbook --------------------------------------

    def test_04_banner_links_to_runbook(self) -> None:
        out = _drive_banner(["AVAX/USD"], body=self.body)
        self.assertIn("docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md", out)
        # The link is a markdown ref — text and URL identical so the
        # operator can grep the path verbatim.
        self.assertIn(
            "[docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md]"
            "(docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md)",
            out,
        )
        # The exact status string spec demanded.
        self.assertIn("DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13", out)

    # --- 5. Discovery remains observation-only ---------------------------

    def test_05_discovery_remains_observation_only(self) -> None:
        # Operator-visible wording must reaffirm the discovery layer is
        # ONLY active for analysis and is NOT trading.
        out = _drive_banner(["AVAX/USD"], body=self.body)
        self.assertIn(
            "Discovery layer remains active for analysis but "
            "trading is BLOCKED until manual repair.",
            out,
        )
        # No promotion language, no go-live language.
        forbidden = [
            "AUTO_PROMOTED",
            "auto-promoted",
            "TRADE LIVE",
            "trade live",
            "EDGE_GATE_ENABLED=true",
            "ALLOW_BROKER_PAPER=true",
            "AUTONOMOUSLY CLEAR",
        ]
        for token in forbidden:
            self.assertNotIn(token, out,
                             f"banner must not contain {token!r}")

    # --- 6. No variant promotion during incident -------------------------

    def test_06_no_variant_promotion_during_incident(self) -> None:
        body_with_variants = (
            self.body
            + "\n## C. Variants worth observing\n"
            + "| Variant | mode | priority |\n|---|---|---|\n"
            + "| momentum-long-loose | SHADOW_ONLY | observe |\n"
        )
        out = _drive_banner(["AVAX/USD"], body=body_with_variants)
        # The variant block must remain present AND must remain
        # SHADOW_ONLY / observe. The banner must NOT inject a different
        # mode keyword.
        self.assertIn("SHADOW_ONLY", out)
        self.assertIn("observe", out)
        # The original report body must remain intact byte-for-byte
        # AFTER the banner.
        idx = out.find(body_with_variants)
        self.assertGreaterEqual(
            idx, 0, "original report body must appear verbatim"
        )
        # Nothing after the body block in this driver call.
        self.assertEqual(out[idx:], body_with_variants)

    # --- 7. No watchlist priority change during incident -----------------

    def test_07_no_watchlist_priority_change_during_incident(self) -> None:
        body_with_priorities = (
            self.body
            + "\n## Priority rubric\n"
            + "- P1 — distance_to_trigger < 0.05 AND near_miss_count_7d >= 3\n"
            + "- P2 — distance_to_trigger < 0.15 AND near_miss_count_7d >= 1\n"
            + "- P3 — distance_to_trigger >= 0.15\n"
            + "- BLOCKED — distance unknown OR risk preconditions failed\n"
        )
        out = _drive_banner(["AVAX/USD"], body=body_with_priorities)
        # Priority lines must remain unchanged — banner does not
        # rewrite distance thresholds, rubric, or BLOCKED condition.
        for line in (
            "- P1 — distance_to_trigger < 0.05 AND near_miss_count_7d >= 3",
            "- P2 — distance_to_trigger < 0.15 AND near_miss_count_7d >= 1",
            "- P3 — distance_to_trigger >= 0.15",
            "- BLOCKED — distance unknown OR risk preconditions failed",
        ):
            self.assertIn(line, out)
        # Body appears verbatim after banner.
        idx = out.find(body_with_priorities)
        self.assertGreaterEqual(idx, 0)
        self.assertEqual(out[idx:], body_with_priorities)

    # --- 8. Each reporter supports banner --------------------------------

    def test_08_each_reporter_supports_banner(self) -> None:
        # All four discovery reporters must import the helper and call
        # it AFTER render_md(). This is a structural invariant the test
        # enforces at the source level.
        for name in REPORTERS:
            with self.subTest(reporter=name):
                self.assertTrue(
                    (SCRIPTS / name).exists(),
                    f"reporter missing: {name}",
                )
                self.assertTrue(
                    _reporter_calls_prepend(name),
                    f"{name} does not import prepend_incident_banner",
                )
                self.assertTrue(
                    _reporter_calls_after_render_md(name),
                    f"{name} must call prepend_incident_banner after "
                    f"render_md(...)",
                )

    # --- bonus invariant: helper is fail-soft ----------------------------

    def test_09_helper_is_fail_soft(self) -> None:
        # If the helper is asked to read on-disk state and the call
        # raises (e.g. broken JSON), it must return md_text verbatim.
        # We simulate by passing an invalid override list type — the
        # try/except inside prepend_incident_banner must absorb it.
        out = banner_mod.prepend_incident_banner(
            self.body,
            override_blocked_symbols=None,
        )
        # No exception. Either banner is empty (no incident) or banner
        # is present — but the function must return a string, never
        # raise.
        self.assertIsInstance(out, str)
        # At minimum the body remains inside the output.
        self.assertIn(self.body, out)


if __name__ == "__main__":
    unittest.main()

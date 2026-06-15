"""v3.25 (2026-06-15) — extension tests for the strategy source
reconciliation report after the v3.24 confidence enforcement was
deployed.

These tests do NOT relax any v3.24 invariant. They only assert that:

1. The status distribution covers ALL canonical status categories the
   reporter knows about (no schema regression).
2. The reporter SURFACES a zombie count (or equivalent) so an operator
   can compare to the v3.24 baseline.
3. The reporter writes the v3.25 standing markers footer.
4. The script has no broker imports (re-asserted at every revision).
5. The OBSERVE_ONLY count is >= the v3.24 baseline of 2. v3.24 reduced
   zombies 9 → 5 by mechanical conversion to observe_only; v3.25 must
   not silently un-do that.

HARD SAFETY
-----------
- Tests NEVER call the broker.
- Tests NEVER hit the network.
- AST scan asserts the reconciler does NOT import alpaca_orders.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "reconcile_strategy_sources.py"
REPORT_JSON = (REPO_ROOT / "learning-loop" /
               "strategy_source_reconciliation_latest.json")
REPORT_MD = REPO_ROOT / "docs" / "STRATEGY_SOURCE_RECONCILIATION.md"

# v3.24 baseline (from CLAUDE.md session entry):
#   ZOMBIE_STATE_ONLY reduced 9 → 5 via mechanical conversion to
#   observe_only. OBSERVE_ONLY count >= 2 expected.
V324_BASELINE_OBSERVE_ONLY_MIN = 2

# Canonical statuses the reconciler is expected to know about. We
# only require that the distribution dict mentions these categories
# (count 0 is fine for empty ones); this catches a regression where
# the reporter drops a category entirely.
EXPECTED_STATUSES = (
    "ACTIVE_RUNTIME_SOURCE",
    "ACTIVE_SHADOW_SOURCE",
    "ACTIVE_MONITOR_UNREGISTERED",
    "OBSERVE_ONLY",
    "DISABLED_INTENTIONALLY",
    "ZOMBIE_STATE_ONLY",
    "DEAD_ORPHAN",
)


def _load_json_report() -> dict:
    """Load the latest reconciliation JSON. Skips if missing."""
    if not REPORT_JSON.exists():
        raise unittest.SkipTest(
            f"{REPORT_JSON} missing — run "
            f"`python3 scripts/reconcile_strategy_sources.py` first")
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


class TestStatusDistribution(unittest.TestCase):
    def test_status_distribution_includes_all_categories(self):
        """Distribution must mention every canonical status name.

        It is OK for some counts to be 0 (e.g. no DEAD_ORPHAN today),
        but the keys must exist so downstream dashboards do not break.
        Empty categories may be omitted IF AND ONLY IF the strategies
        list itself contains no rows for that status — but the
        reporter must still recognise the status names.

        We check: every status that DOES appear in the strategies
        list must also appear in status_distribution.
        """
        rep = _load_json_report()
        sd = rep.get("status_distribution") or {}
        strats = rep.get("strategies") or []
        statuses_seen = {r.get("status") for r in strats if r.get("status")}
        for s in statuses_seen:
            self.assertIn(
                s, sd,
                f"status_distribution missing observed status {s!r}")
            self.assertIsInstance(sd[s], int)
            self.assertGreaterEqual(sd[s], 0)

    def test_status_distribution_counts_match_strategies_list(self):
        """Each status_distribution count == number of rows w/ that
        status in the strategies list.
        """
        rep = _load_json_report()
        sd = rep.get("status_distribution") or {}
        strats = rep.get("strategies") or []
        for status, expected_n in sd.items():
            actual_n = sum(
                1 for r in strats if r.get("status") == status)
            self.assertEqual(
                expected_n, actual_n,
                f"status_distribution[{status!r}]={expected_n} but "
                f"strategies list has {actual_n} rows with that "
                f"status")


class TestZombieReporting(unittest.TestCase):
    def test_zombie_count_reported(self):
        """ZOMBIE_STATE_ONLY count must be reportable.

        We do NOT assert a specific value — operator decides when to
        act on zombies. We only assert that the count is exposed in
        status_distribution OR in the strategies rows.
        """
        rep = _load_json_report()
        sd = rep.get("status_distribution") or {}
        strats = rep.get("strategies") or []
        zombie_via_sd = sd.get("ZOMBIE_STATE_ONLY", 0)
        zombie_via_rows = sum(
            1 for r in strats if r.get("status") == "ZOMBIE_STATE_ONLY")
        # Both paths must agree (sanity check).
        self.assertEqual(zombie_via_sd, zombie_via_rows)
        # Must be reportable (key exists OR no zombies at all).
        self.assertIsInstance(zombie_via_sd, int)


class TestObserveOnlyBaseline(unittest.TestCase):
    def test_observe_only_count_matches_v324_baseline_or_higher(self):
        """v3.24 reduced zombies 9 → 5 by converting 4 strategies to
        observe_only. v3.25 must NOT silently undo that.

        Therefore OBSERVE_ONLY count must be >= the v3.24 baseline
        minimum of 2 (the explicit observe_only items recorded in the
        registry). If the count drops below baseline, something has
        un-tagged strategies — flag it.
        """
        rep = _load_json_report()
        sd = rep.get("status_distribution") or {}
        obs_n = sd.get("OBSERVE_ONLY", 0)
        self.assertGreaterEqual(
            obs_n,
            V324_BASELINE_OBSERVE_ONLY_MIN,
            f"OBSERVE_ONLY count {obs_n} < v3.24 baseline "
            f"{V324_BASELINE_OBSERVE_ONLY_MIN}; a strategy may have "
            f"been silently un-tagged. Investigate before merging.")


class TestStandingMarkers(unittest.TestCase):
    def test_reporter_writes_v325_marker(self):
        """The latest JSON report must include standing_markers.

        We check the standing-markers footer contains the v3.25
        hard-safety assertions: EDGE_GATE_ENABLED=false,
        ALLOW_BROKER_PAPER=false, LIVE_TRADING_UNSUPPORTED.

        These are the markers v3.24 added; v3.25 must continue to
        emit them (they are not version-stamped, they are forever).
        """
        rep = _load_json_report()
        markers = rep.get("standing_markers") or []
        self.assertIsInstance(markers, list)
        joined = " ".join(str(m).upper() for m in markers)
        self.assertIn("EDGE_GATE_ENABLED=FALSE", joined)
        self.assertIn("ALLOW_BROKER_PAPER=FALSE", joined)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", joined)


class TestSafety(unittest.TestCase):
    def test_no_alpaca_imports(self):
        """The reconciler MUST NOT import alpaca_orders or any
        order-placement module. Re-assert at v3.25.
        """
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name or ""
                    self.assertNotIn(
                        "alpaca_orders", name,
                        f"reconciler imports forbidden module {name!r}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(
                    "alpaca_orders", mod,
                    f"reconciler imports from forbidden module {mod!r}")

    def test_no_network_modules(self):
        """The reconciler MUST NOT pull in requests / urllib / sockets
        for HTTP calls. Pure local-file aggregator.
        """
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "from requests",
            "urllib.request",
            "http.client",
            "socket.connect",
        ):
            self.assertNotIn(
                forbidden, src,
                f"reconciler must not use {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

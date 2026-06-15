"""v3.23.0 — tests that the shadow runner uses the v3.22 diagnostic
API (``fetch_universe_snapshots_with_diagnostics``) and surfaces
``diagnostic_token_counts`` in its summary.

Mix of AST checks (no-network) + lightweight runtime tests that
patch ``market_data_provider`` to verify wiring without making any
HTTP call.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = (REPO_ROOT
               / "scripts" / "run_signal_shadow_evidence_collection.py")


class TestRunnerASTReferencesDiagnosticAPI(unittest.TestCase):

    def test_runner_references_fetch_universe_snapshots_with_diagnostics(self):
        src = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "fetch_universe_snapshots_with_diagnostics", src,
            "v3.23 runner must reference the diagnostic API")

    def test_runner_still_imports_market_data_provider_as_mdp(self):
        # Sanity: the runner must import the module so that the
        # diagnostic helper can be reached as an attribute.
        src = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "import market_data_provider as mdp", src,
            "v3.23 runner must still import the market_data_provider "
            "module")

    def test_runner_propagates_diagnostic_token_counts_in_summary(self):
        # AST-confirm there's an assignment ``summary["diagnostic_token_counts"]``
        src = RUNNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)

        seen = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "summary"):
                        sl = tgt.slice
                        # Py 3.9+ -> ast.Constant; Py 3.8 -> ast.Index
                        val = (sl.value if isinstance(sl, ast.Constant)
                               else getattr(sl, "value", None))
                        if isinstance(val, str) and val == "diagnostic_token_counts":
                            seen = True
                            break
            if seen:
                break
        self.assertTrue(
            seen,
            "Runner must assign summary['diagnostic_token_counts'] so "
            "the workflow can pipe it into workflow_health.")

    def test_runner_falls_back_to_legacy_fetch_when_diag_api_missing(self):
        # AST: confirm a ``getattr(mdp, "fetch_universe_snapshots_with_diagnostics", None)``
        # pattern is present so the runner fail-soft falls back to
        # the legacy fetcher when the helper is not exported.
        src = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'fetch_universe_snapshots_with_diagnostics', src)
        # Either getattr-based or a try/except ImportError block is OK,
        # but the legacy fetcher must still appear.
        self.assertIn(
            "mdp.fetch_universe_snapshots()", src,
            "Runner must still preserve the legacy fetch path")


class TestRunnerRuntimeWiresDiagnostic(unittest.TestCase):
    """Run ``collect()`` with mocked mdp/sog to verify diagnostic_token_counts
    flows from the v3.22 API into the summary."""

    def setUp(self) -> None:
        # Late import to ensure script is reloadable.
        sys.path.insert(
            0, str((REPO_ROOT / "scripts").resolve()))
        sys.path.insert(0, str((REPO_ROOT / "shared").resolve()))
        # Drop any cached modules so we re-import cleanly.
        for mod in (
            "run_signal_shadow_evidence_collection",
            "market_data_provider", "shadow_opportunity_generator",
        ):
            sys.modules.pop(mod, None)

    def test_diagnostic_token_counts_surface_in_summary(self):
        """When the diagnostic API is callable, its counts must
        appear in ``summary['diagnostic_token_counts']``."""
        # Build mocks for the two modules the runner imports lazily.
        fake_mdp = mock.MagicMock()
        fake_sog = mock.MagicMock()

        # Required surface on mdp.
        class FakeSnap:
            symbol = "BTC/USD"
            asset_class = "crypto"
            data_quality = "REAL_MARKET_DATA"
            status_token = "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL"
        snaps = [FakeSnap()]

        # Result-style return.
        class _DiagResult:
            snapshots = snaps
            diagnostic_token_counts = {"OK": 1}
            symbols_skipped_stale: list = []
            symbols_skipped_provider_error: list = []
        fake_mdp.fetch_universe_snapshots_with_diagnostics.return_value = (
            _DiagResult())
        fake_mdp.REAL_MARKET_SIGNAL_RECORDS_EMITTED = "REAL_MARKET_SIGNAL_RECORDS_EMITTED"
        fake_mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL = (
            "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL")
        fake_mdp.INSUFFICIENT_BARS_FOR_SIGNAL = "INSUFFICIENT_BARS_FOR_SIGNAL"
        fake_mdp.MARKET_CLOSED_OR_NO_BARS = "MARKET_CLOSED_OR_NO_BARS"
        fake_mdp.MARKET_DATA_STALE = "MARKET_DATA_STALE"
        fake_mdp.MARKET_DATA_PROVIDER_ERROR = "MARKET_DATA_PROVIDER_ERROR"
        fake_mdp.MARKET_DATA_AUTH_FAILED = "MARKET_DATA_AUTH_FAILED"
        fake_mdp.REAL_MARKET_DATA = "REAL_MARKET_DATA"
        # Required surface on sog.
        fake_sog.generate_for_universe.return_value = []

        with mock.patch.dict(sys.modules, {
            "market_data_provider": fake_mdp,
            "shadow_opportunity_generator": fake_sog,
        }):
            import run_signal_shadow_evidence_collection as runner
            importlib.reload(runner)
            summary = runner.collect(
                market_data_available=True,
                refuse_if_preflight_failed=False,
            )
        self.assertIn("diagnostic_token_counts", summary)
        self.assertEqual(
            summary["diagnostic_token_counts"], {"OK": 1})
        # Per-symbol diagnostics also populated.
        self.assertEqual(
            len(summary.get("per_symbol_diagnostics", [])), 1)


if __name__ == "__main__":
    unittest.main()

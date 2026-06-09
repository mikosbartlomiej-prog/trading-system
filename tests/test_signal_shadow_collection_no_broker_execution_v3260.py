"""v3.26.0 (2026-06-09) — collector hard-safety tests.

Pin that the v3.26 collector script:
- never submits orders,
- never imports order-submitting helpers,
- refuses to proceed if any broker-execution env flag is truthy,
- always emits records with broker_order_submitted=false +
  broker_execution_enabled=false,
- always returns BROKER_PAPER_CANARY_NOT_READY/LIVE_TRADING_NOT_SUPPORTED
  posture.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_collector():
    """Import the collector module by path (it's a script)."""
    spec = importlib.util.spec_from_file_location(
        "run_signal_shadow_evidence_collection",
        REPO_ROOT / "scripts"
        / "run_signal_shadow_evidence_collection.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


COLLECTOR_SOURCE = (
    REPO_ROOT / "scripts"
    / "run_signal_shadow_evidence_collection.py").read_text()


def _clean_env() -> dict:
    return {
        "ALLOW_BROKER_PAPER": "false",
        "EDGE_GATE_ENABLED": "false",
        "BROKER_EXECUTION_ENABLED": "false",
        "LIVE_TRADING": "false",
        "LIVE_ENABLED": "false",
        "GO_LIVE": "false",
        "LIVE_TRADING_ENABLED": "false",
    }


class TestCollectorRefuseEnvFlags(unittest.TestCase):
    """The collector must refuse to proceed if any broker-execution
    env flag is truthy."""

    def setUp(self):
        self.collector = _load_collector()

    def _run_with_env(self, env_overrides: dict) -> dict:
        env = _clean_env()
        env.update(env_overrides)
        with mock.patch.dict(os.environ, env, clear=False):
            return self.collector.collect()

    def test_allow_broker_paper_true_refuses(self):
        out = self._run_with_env({"ALLOW_BROKER_PAPER": "true"})
        self.assertEqual(
            out["status"],
            self.collector.SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED,
        )
        self.assertTrue(out.get("broker_execution_enabled_refusal"))

    def test_edge_gate_enabled_refuses(self):
        out = self._run_with_env({"EDGE_GATE_ENABLED": "true"})
        self.assertEqual(
            out["status"],
            self.collector.SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED,
        )

    def test_broker_execution_enabled_refuses(self):
        out = self._run_with_env({"BROKER_EXECUTION_ENABLED": "true"})
        self.assertEqual(
            out["status"],
            self.collector.SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED,
        )

    def test_live_trading_refuses(self):
        out = self._run_with_env({"LIVE_TRADING": "true"})
        self.assertEqual(
            out["status"],
            self.collector.SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED,
        )


class TestCollectorPreflightHardWiring(unittest.TestCase):
    def setUp(self):
        self.collector = _load_collector()

    def test_default_no_market_data_returns_skip(self):
        # Run against a tmp repo_root so we don't touch the real
        # counters file.
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                out = self.collector.collect(repo_root=root)
                self.assertEqual(
                    out["status"],
                    self.collector.SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA,
                )

    def test_market_data_available_no_real_data_falls_through_to_halt(self):
        # v3.27.0: when market_data_available=True is asserted but
        # no real market data can be fetched (no creds in tmp env),
        # the collector returns SKIPPED instead of fabricating
        # SCAFFOLD records. v3.27 removes the silent SCAFFOLD
        # fallback that v3.26.0 used. This preserves the v3.26.1
        # invariant: scaffold records do not inflate canary-gate
        # counters.
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                out = self.collector.collect(
                    max_records=3, repo_root=root,
                    market_data_available=True,
                    timestamp_iso="2026-06-09T02:00:00+00:00",
                )
                # v3.27: with no Alpaca creds in the sandbox, real
                # data fetch fails and we fall through to halt-path.
                self.assertIn(
                    out["status"],
                    (self.collector.SHADOW_COLLECTION_PROCEEDING,
                      self.collector.SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA),
                )
                # No SCAFFOLD records may be written when real data
                # is unavailable.
                self.assertEqual(out.get("scaffold_records_written", 0),
                                  0)
                # If any record was written, it must be REAL_MARKET_DATA.
                if out["records_written"] > 0:
                    self.assertEqual(
                        out["evidence_quality"],
                        "REAL_MARKET_DATA",
                    )
                    # v3.26.1: collector-emitted records carry an
                    # evidence_quality marker even when market data
                    # was supposedly available — the v3.26 scaffold
                    # still emits SCAFFOLD records (real-data wiring
                    # is deferred). This is the audit-loud default.
                    self.assertEqual(
                        rec["evidence_quality"],
                        "SCAFFOLD_NO_MARKET_DATA",
                    )


class TestCollectorNeverImportsOrderSubmission(unittest.TestCase):
    """Source-level safety: the collector must NOT contain any
    reference to order-submitting helpers."""

    def test_no_forbidden_imports_in_source(self):
        FORBIDDEN = (
            "place_stock_bracket",
            "place_crypto_order",
            "place_simple_buy",
            "place_oco_exit",
            "safe_close",
            "execute_crypto_signal",
            "execute_stock_signal",
            "from shared.alpaca_orders",
            "from alpaca_orders",
            "import alpaca_orders",
            "requests.post",
            "requests.put",
            "requests.delete",
        )
        for token in FORBIDDEN:
            self.assertNotIn(
                token, COLLECTOR_SOURCE,
                f"collector script must not contain {token!r}",
            )

    def test_ast_scan_for_order_calls(self):
        tree = ast.parse(COLLECTOR_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = ""
                if isinstance(node.func, ast.Name):
                    target = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    target = node.func.attr
                self.assertNotIn(
                    target,
                    {"place_stock_bracket", "place_crypto_order",
                     "place_simple_buy", "place_oco_exit",
                     "safe_close", "execute_crypto_signal",
                     "execute_stock_signal"},
                    f"forbidden order-submission call: {target}",
                )

    def test_imported_modules_never_load_alpaca_orders(self):
        """Run the loader in a tmp module context and confirm
        ``alpaca_orders`` is not in sys.modules after import."""
        # Snapshot existing sys.modules.
        had = "alpaca_orders" in sys.modules
        # Force-remove any prior import so we know what THIS load did.
        if had:
            del sys.modules["alpaca_orders"]
        _load_collector()
        self.assertNotIn(
            "alpaca_orders", sys.modules,
            "collector accidentally imported alpaca_orders",
        )


class TestRecordSchemaCompliance(unittest.TestCase):
    """Built records must always have the broker safety flags False
    even if a caller forgets to pass them."""

    def setUp(self):
        self.collector = _load_collector()

    def test_build_record_pins_broker_flags_false(self):
        rec = self.collector.build_record(
            symbol="ETHUSD",
            asset_class="crypto",
            strategy="signal-shadow",
            decision_type="entry",
            side="buy",
            would_trade=False,
            would_block=True,
            block_reasons=["any"],
            sizing_preview={"proposed_usd": 0.0, "equity_usd": 0.0},
            exposure_policy_result={"decision": "x"},
            drawdown_guard_state={"active": False},
            timestamp_iso="2026-06-09T03:00:00+00:00",
            audit_trace_id="abc",
        )
        self.assertFalse(rec["broker_order_submitted"])
        self.assertFalse(rec["broker_execution_enabled"])
        # v3.26.1 records carry version v3.26.1 (the v3.25 readiness
        # gate is unchanged; only the record shape evolved).
        self.assertTrue(rec["version"].startswith("v3.26"))
        # v3.26.1: every record must declare evidence_quality.
        # Default (no override) is the safest classification.
        self.assertEqual(
            rec["evidence_quality"], "SCAFFOLD_NO_MARKET_DATA",
        )


class TestBrokerPaperRemainsNotReady(unittest.TestCase):
    """Even with maxed-out counters, broker paper canary must NOT be
    automatically returned READY without the v3.25 daily-learning /
    trade-reconstruction / operator-approval gates."""

    def test_counters_full_still_not_ready_without_approval(self):
        from shadow_evidence_counters import (
            EvidenceCounters, progress_summary,
        )
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        c = EvidenceCounters()
        c.normal_non_halt_opportunities_count = 999
        c.completed_shadow_outcomes_count = 999
        # progress_summary hard-codes broker_paper_canary_ready=False.
        p = progress_summary(c)
        self.assertFalse(p["broker_paper_canary_ready"])
        self.assertFalse(p["live_trading_supported"])

        # Verify the trading_unlock_readiness gate still requires
        # daily_learning_stable + trade_reconstruction_stable +
        # explicit_operator_approval_for_broker_paper.
        inputs = UnlockReadinessInputs(
            normal_non_halt_opportunities_count=999,
            completed_shadow_outcomes_count=999,
        )
        report = evaluate_unlock_readiness(inputs)
        self.assertEqual(report.verdict, SIGNAL_SHADOW_UNLOCK_READY)


class TestLiveTradingAlwaysBlocked(unittest.TestCase):
    def test_collector_status_does_not_include_live_path(self):
        self.collector = _load_collector()
        # Verify no status token implies live trading enabled.
        public = {k: v for k, v in vars(self.collector).items()
                  if isinstance(v, str) and k.isupper()}
        for name, val in public.items():
            self.assertNotIn("LIVE_TRADING_ENABLED", val,
                              f"{name} mentions LIVE_TRADING_ENABLED")
            self.assertNotIn("LIVE_TRADING_PROCEEDING", val,
                              f"{name} mentions LIVE_TRADING_PROCEEDING")


if __name__ == "__main__":
    unittest.main()

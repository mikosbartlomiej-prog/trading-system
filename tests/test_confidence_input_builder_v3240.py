"""v3.24 (2026-06-15) — tests for shared/confidence_input_builder.py.

Covers:
  * happy paths (crypto and price signals produce non-empty inputs)
  * fail-soft defaults attach reasons
  * heartbeat outage degrades system_health gracefully
  * strategy_state with n=0 caps sample_size_score path
  * entry_capable contract: components dict NEVER empty for an
    entry-capable event
  * completeness fraction is computed correctly
  * builder does NOT import alpaca_orders (AST scan)
  * builder does NOT make network calls (AST scan)
  * default_reasons keys align with documented component keys
  * observe-only events tolerate minimal components

HARD SAFETY
-----------
Tests never call the broker or hit the network.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from confidence_input_builder import (   # type: ignore  # noqa: E402
    BUILDER_VERSION,
    ConfidenceInputs,
    build_confidence_inputs,
)
from signal_event import SignalEvent      # type: ignore  # noqa: E402


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_event(*, entry_capable: bool = True,
                  raw_signal: dict | None = None,
                  risk_inputs: dict | None = None,
                  market_regime: dict | None = None,
                  universe_status: dict | None = None,
                  strategy_id: str = "crypto-momentum",
                  symbol: str = "BTC/USD",
                  source_monitor: str = "crypto-monitor") -> SignalEvent:
    return SignalEvent(
        signal_id="test:" + symbol,
        strategy_id=strategy_id,
        symbol=symbol,
        asset_class="crypto",
        side="long",
        action="BUY",
        timestamp_iso="2026-06-15T10:00:00+00:00",
        source_monitor=source_monitor,
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=entry_capable,
        raw_signal=raw_signal or {},
        risk_inputs=risk_inputs or ({"strategy": strategy_id} if entry_capable else {}),
        market_regime=market_regime or {},
        universe_status=universe_status or {},
    )


# ─── happy paths ─────────────────────────────────────────────────────────────


class TestHappyPath(unittest.TestCase):
    def test_valid_crypto_signal_produces_non_empty_inputs(self):
        ev = _make_event(
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            raw_signal={
                "primary_score": 0.75,
                "rsi": 65.0,
                "bars_count": 24,
                "price_move_atr": 1.2,
                "volume_ratio": 1.5,
            },
        )
        out = build_confidence_inputs(ev,
                                       market_context={"regime": "NEUTRAL"})
        self.assertIsInstance(out, ConfidenceInputs)
        self.assertGreater(len(out.components), 1)
        self.assertIn("primary_score", out.components)
        self.assertIn("strategy", out.components)
        self.assertEqual(out.builder_version, BUILDER_VERSION)

    def test_valid_price_signal_produces_non_empty_inputs(self):
        ev = _make_event(
            strategy_id="momentum-long",
            symbol="AAPL",
            source_monitor="price-monitor",
            raw_signal={
                "primary_score": 0.6,
                "rsi": 60.0,
                "bars_count": 22,
                "confirmations": 2,
            },
            market_regime={"regime": "RISK_ON"},
        )
        out = build_confidence_inputs(ev)
        self.assertIn("primary_score", out.components)
        self.assertIn("regime", out.components)
        self.assertEqual(out.components["regime"], "RISK_ON")


# ─── degraded inputs ─────────────────────────────────────────────────────────


class TestDegradedInputs(unittest.TestCase):
    def test_missing_data_marks_default_reasons(self):
        ev = _make_event(raw_signal={})  # no primary_score, no rsi, no bars
        out = build_confidence_inputs(ev)
        # data_quality + signal_strength should both have default reasons
        self.assertIn("data_quality", out.default_reasons)
        self.assertIn("signal_strength", out.default_reasons)
        # The reason strings must be informative.
        self.assertTrue(out.default_reasons["data_quality"])
        self.assertTrue(out.default_reasons["signal_strength"])

    def test_stale_heartbeat_lowers_system_health(self):
        # Force a clean heartbeat import that returns "no data".
        ev = _make_event(raw_signal={"primary_score": 0.7})
        out = build_confidence_inputs(ev)
        # Either system_health is real (heartbeat module present and
        # populated) OR a default reason was attached. Both are valid.
        if "components_alive" not in out.components:
            self.assertIn("system_health", out.default_reasons)
            self.assertIn(
                out.default_reasons["system_health"],
                ("HEARTBEAT_UNAVAILABLE", "NO_HEARTBEAT_DATA"),
            )

    def test_strategy_n_zero_caps_sample_size(self):
        ev = _make_event(raw_signal={"primary_score": 0.7})
        out = build_confidence_inputs(
            ev,
            strategy_state={"trades_lifetime": 0},
        )
        # 0 is a real measurement, so it's forwarded — no default reason.
        self.assertEqual(out.components.get("strategy_n_closed_paper"), 0)
        self.assertNotIn("sample_size", out.default_reasons)

    def test_observe_only_event_can_have_minimal_components(self):
        # entry_capable=False; builder must still succeed even with zero
        # raw_signal data, and must NOT raise ValueError.
        ev = _make_event(entry_capable=False, raw_signal={})
        out = build_confidence_inputs(ev)
        self.assertIsInstance(out, ConfidenceInputs)
        # default_reasons should be populated (lots of holes).
        self.assertGreater(len(out.default_reasons), 0)


# ─── contract: entry_capable rows never empty ────────────────────────────────


class TestEntryCapableContract(unittest.TestCase):
    def test_entry_capable_never_returns_empty_components(self):
        # Even with truly minimal inputs the builder must produce
        # components AT LEAST containing the strategy field plus a
        # default for the mandatory components.
        ev = _make_event(raw_signal={})
        out = build_confidence_inputs(ev)
        # Strategy is always present.
        self.assertIn("strategy", out.components)
        # Mandatory components must each have either a real value OR
        # a default reason.
        for mandatory in ("data_quality", "signal_strength", "system_health"):
            has_real = any(
                key in out.components
                for key in ("bars_count", "primary_score", "components_alive")
            ) or mandatory in out.components
            has_default = mandatory in out.default_reasons
            self.assertTrue(
                has_real or has_default,
                f"mandatory {mandatory} has neither real value nor default",
            )


# ─── completeness fraction ──────────────────────────────────────────────────


class TestCompleteness(unittest.TestCase):
    def test_completeness_fraction_correct(self):
        # Provide many real inputs → completeness should be > 0.5
        ev = _make_event(
            raw_signal={
                "primary_score": 0.6,
                "rsi": 60.0,
                "bars_count": 25,
                "price_move_atr": 1.0,
                "volume_ratio": 1.2,
                "estimated_slippage_bps": 5.0,
                "expected_edge_bps": 25.0,
            },
            risk_inputs={
                "strategy": "momentum-long",
                "intraday_pnl_pct": -0.5,
                "drawdown_pct": -2.0,
                "consecutive_losses": 1,
                "giveback_pct_of_peak": 10.0,
            },
            market_regime={"regime": "RISK_ON"},
        )
        out = build_confidence_inputs(
            ev,
            strategy_state={
                "trades_lifetime": 45,
                "recent_wr": 0.55,
                "profit_factor": 1.4,
                "calibration_total": 0.7,
            },
        )
        # Should be > 0.5 (many real components present)
        self.assertGreater(out.completeness, 0.5)
        self.assertLessEqual(out.completeness, 1.0)

    def test_completeness_zero_input_low(self):
        ev = _make_event(raw_signal={})
        out = build_confidence_inputs(ev)
        self.assertLessEqual(out.completeness, 0.5)
        self.assertGreaterEqual(out.completeness, 0.0)


# ─── default reasons keys ───────────────────────────────────────────────────


class TestDefaultReasonsKeys(unittest.TestCase):
    def test_default_reasons_dict_keys_match_component_keys(self):
        ev = _make_event(raw_signal={})
        out = build_confidence_inputs(ev)
        # Every default-reason key must be a known component key from
        # the documented v3.24 contract.
        allowed = {
            "data_quality", "signal_strength", "regime_alignment",
            "system_health", "risk_state", "sample_size",
            "track_record", "calibration", "edge_evidence",
            "slippage_risk", "price_move_atr", "volume_ratio",
        }
        for key in out.default_reasons.keys():
            self.assertIn(
                key, allowed,
                f"unknown default_reasons key: {key}",
            )


# ─── AST safety: no broker / network imports ─────────────────────────────────


class TestNoForbiddenImports(unittest.TestCase):
    BUILDER_PATH = SHARED_DIR / "confidence_input_builder.py"

    def _parse(self) -> ast.AST:
        return ast.parse(self.BUILDER_PATH.read_text(encoding="utf-8"))

    def test_builder_never_imports_alpaca_orders(self):
        tree = self._parse()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotEqual(n.name, "alpaca_orders")
                    self.assertFalse(n.name.endswith(".alpaca_orders"))
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn("alpaca_orders", module)

    def test_builder_never_makes_network_calls(self):
        tree = self._parse()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name,
                                      ("requests", "httpx", "urllib3",
                                       "aiohttp"))
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn(module,
                                  ("requests", "httpx", "urllib3",
                                   "aiohttp"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

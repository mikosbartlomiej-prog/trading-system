"""v3.24 ETAP 8 tests — shadow_simulator.maybe_simulate_from_row.

Verifies the conservative activation pathway:
- Eligible row → ShadowFill with FILL_FILLED + standing markers.
- Any non-eligible row → ``None`` (no fill, no ledger write).
- No broker call attempted in any scenario (network.request patched).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import sys
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from shadow_simulator import (  # type: ignore  # noqa: E402
    FILL_FILLED,
    STANDING_MARKERS,
    ShadowFill,
    maybe_simulate_from_row,
)


def _eligible_row(**overrides):
    row = {
        "signal_id":    "sig-1",
        "symbol":       "AAPL",
        "strategy":     "price-momentum-long",
        "asset_class":  "us_equity",
        "side":         "long",
        "risk_decision": "APPROVE",
        "confidence_score": 0.80,
        "confidence_components": {"signal_strength": 0.9},
        "raw_signal": {
            "diagnostic_token":         None,
            "canary_preflight_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
            "observe_only":             False,
            "action":                   "BUY",
            "price":                    191.23,
        },
    }
    row.update(overrides)
    return row


class _NetworkAttempted(Exception):
    """Raised by the patched network surface if anything tries to
    place an order during a test.
    """


class TestMaybeSimulateFromRow(unittest.TestCase):

    def setUp(self):
        # Patch the requests / network surface so any attempted call
        # surfaces as a test failure rather than a silent egress.
        self._patches = []
        for target in (
            "requests.post", "requests.get", "requests.request",
            "urllib.request.urlopen",
        ):
            try:
                p = patch(target,
                          side_effect=_NetworkAttempted("network attempted"))
                p.start()
                self._patches.append(p)
            except (ImportError, ModuleNotFoundError, AttributeError):
                # Module not loaded → patch unnecessary; broker can't
                # use it anyway.
                continue

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def test_eligible_row_yields_filled_shadowfill(self):
        fill = maybe_simulate_from_row(_eligible_row())
        self.assertIsInstance(fill, ShadowFill)
        self.assertEqual(fill.fill_status, FILL_FILLED)
        self.assertFalse(fill.is_paper_trade)
        self.assertFalse(fill.broker_order_submitted)
        for marker in STANDING_MARKERS:
            self.assertIn(marker, fill.standing_markers)

    def test_non_eligible_no_confidence_returns_none(self):
        row = _eligible_row(confidence_score=None)
        self.assertIsNone(maybe_simulate_from_row(row))

    def test_non_eligible_confidence_low_returns_none(self):
        row = _eligible_row(confidence_score=0.10)
        self.assertIsNone(maybe_simulate_from_row(row))

    def test_non_eligible_risk_reject_returns_none(self):
        row = _eligible_row(risk_decision="REJECT")
        self.assertIsNone(maybe_simulate_from_row(row))

    def test_non_eligible_observe_only_returns_none(self):
        row = _eligible_row()
        row["raw_signal"]["observe_only"] = True
        self.assertIsNone(maybe_simulate_from_row(row))

    def test_non_eligible_canary_missing_returns_none(self):
        row = _eligible_row()
        row["raw_signal"].pop("canary_preflight_verdict")
        self.assertIsNone(maybe_simulate_from_row(row))

    def test_qty_clamped_to_equity_cap(self):
        row = _eligible_row()
        row["raw_signal"]["qty"] = 999.0   # huge requested qty
        fill = maybe_simulate_from_row(row)
        self.assertIsInstance(fill, ShadowFill)
        self.assertLessEqual(fill.qty, 1.0)

    def test_qty_clamped_to_crypto_cap(self):
        row = _eligible_row(asset_class="crypto")
        row["symbol"] = "BTC/USD"
        row["raw_signal"]["qty"] = 1.0     # 1 BTC; far above cap
        fill = maybe_simulate_from_row(row)
        self.assertIsInstance(fill, ShadowFill)
        self.assertLessEqual(fill.qty, 0.0001)

    def test_broker_flag_truthy_returns_none(self):
        row = _eligible_row()
        # Defence in depth: env override forces refusal.
        fill = maybe_simulate_from_row(
            row, env={"ALLOW_BROKER_PAPER": "true"})
        self.assertIsNone(fill)

    def test_no_broker_call_attempted(self):
        # Run every test path; if any patched network surface raised,
        # this whole test class would fail. The fact that the previous
        # tests pass already proves it, but we add this explicit
        # marker test for grep-ability.
        maybe_simulate_from_row(_eligible_row())
        maybe_simulate_from_row(_eligible_row(confidence_score=None))
        maybe_simulate_from_row(_eligible_row(risk_decision="REJECT"))
        # No-op success.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()

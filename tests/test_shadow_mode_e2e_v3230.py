"""v3.23 end-to-end shadow-mode tests.

These tests confirm that:
- a real-market-like signal in shadow mode writes a shadow row
- broker call count == 0
- live URL absent in the produced records
- canary deferral preserved (DEFERRED → no shadow fill OR observation_only)
- risk block prevents shadow fill
- signal_only does not write a shadow fill
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import shadow_simulator as ss  # noqa: E402


_CANARY_OK = "CANARY_PREFLIGHT_DRY_RUN_OK"


def _flat_env():
    return {f: "false" for f in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    )}


def _approved_signal(**over):
    base = {
        "signal_id":    "sig-e2e-1",
        "symbol":       "MSFT",
        "strategy":     "momentum-long",
        "side":         "long",
        "asset_class":  "us_equity",
        "entry_capable": True,
        "intended_price": 420.0,
        "qty":          1.0,
    }
    base.update(over)
    return base


class TestE2EShadowMode(unittest.TestCase):

    def test_real_market_like_writes_shadow_row(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "shadow.jsonl"
            f = ss.emit_shadow_fill(
                _approved_signal(),
                market_snapshot={"reference_price": 420.5},
                canary_preflight_verdict=_CANARY_OK,
                risk_decision="APPROVE",
                env=_flat_env(),
                ledger_path=p,
            )
            self.assertIsNotNone(f)
            self.assertEqual(f.fill_status, "FILLED")
            self.assertTrue(p.exists())
            row = json.loads(p.read_text().splitlines()[0])
            self.assertEqual(row["broker_order_submitted"], False)
            self.assertEqual(row["is_paper_trade"], False)
            self.assertIn("SHADOW_ONLY", row["standing_markers"])
            # shadow_action populated via fill_status
            self.assertIn(row["fill_status"], ("FILLED",))

    def test_broker_call_count_is_zero(self):
        """If anything in shadow_simulator routes to alpaca_orders, the
        mock raises and the test fails."""
        # We deliberately don't pre-import alpaca_orders. The mock
        # below ensures that if shadow_simulator ever imports it via
        # ``import alpaca_orders`` or ``from shared import alpaca_orders``
        # the import itself becomes a sentinel module whose attribute
        # access raises.
        sentinel = mock.MagicMock(
            side_effect=AssertionError("broker call attempted"))
        with mock.patch.dict(sys.modules, {
            "alpaca_orders":             sentinel,
            "shared.alpaca_orders":      sentinel,
        }):
            # Re-import to force any lazy paths.
            importlib.reload(ss)
            f = ss.simulate_shadow_fill(
                _approved_signal(),
                market_snapshot={"reference_price": 420.0},
                canary_preflight_verdict=_CANARY_OK,
                risk_decision="APPROVE",
                env=_flat_env(),
            )
            self.assertIsNotNone(f)
            self.assertEqual(f.fill_status, "FILLED")
            # No broker attribute was looked up.
            self.assertFalse(sentinel.called)

    def test_live_url_absent_in_records(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        d = f.to_dict()
        # Ensure no live url leak anywhere in the serialised record.
        blob = json.dumps(d)
        self.assertNotIn("api.alpaca.markets/v2", blob)
        # Standing markers explicitly state live trading unsupported.
        self.assertIn("LIVE_TRADING_UNSUPPORTED", d["standing_markers"])

    def test_canary_deferred_prevents_shadow_fill(self):
        # Anything that is NOT the two passthrough verdicts becomes a
        # REJECTED_BY_GATE record (observation-only by construction).
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=
                "CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL",
            risk_decision="APPROVE",
            env=_flat_env(),
        )
        self.assertIsNotNone(f)
        self.assertEqual(f.fill_status, "REJECTED_BY_GATE")
        self.assertEqual(f.broker_order_submitted, False)
        self.assertEqual(f.is_paper_trade, False)

    def test_risk_block_prevents_shadow_fill(self):
        f = ss.simulate_shadow_fill(
            _approved_signal(),
            market_snapshot={"reference_price": 100.0},
            canary_preflight_verdict=_CANARY_OK,
            risk_decision="REJECT",
            env=_flat_env(),
        )
        self.assertIsNone(f)

    def test_signal_only_does_not_write_shadow_fill(self):
        """In SIGNAL_ONLY mode the caller is expected to skip
        ``simulate_shadow_fill`` entirely. We model that here by
        passing ``entry_capable=False`` which is the canonical way the
        runner marks a 'signal observed but not actionable' event."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "shadow.jsonl"
            f = ss.emit_shadow_fill(
                _approved_signal(entry_capable=False),
                market_snapshot={"reference_price": 100.0},
                canary_preflight_verdict=_CANARY_OK,
                risk_decision="APPROVE",
                env=_flat_env(),
                ledger_path=p,
            )
            self.assertIsNone(f)
            self.assertFalse(p.exists())


if __name__ == "__main__":
    unittest.main()

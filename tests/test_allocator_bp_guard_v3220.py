"""
ETAP 3 of 2026-06-07 incident — tests for shared/allocator_bp_guard.py.

Scenarios required by the incident spec:
    - 8 BUYs totaling $80k vs BP $50k → 5 allowed, 3 deferred
    - BP unavailable → all allowed with warning
    - exposure cap respects existing exposure
    - pending GTC orders count toward exposure
    - fail-soft never raises
    - deferred orders have INSUFFICIENT_BP_PROJECTED reason

Plus invariant tests for the module-level safety flags and audit emission.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _buy(symbol: str, notional: float, action: str = "BUY") -> dict:
    """Minimal allocator-style order dict."""
    return {
        "symbol":        symbol,
        "action":        action,
        "asset_class":   "us_equity",
        "target_value":  notional,
        "current_value": 0.0,
        "delta":         notional,
    }


class _Base(unittest.TestCase):
    def setUp(self):
        # Sandbox audit JSONL dir so tests don't pollute repo journal/.
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = str(Path(self.tmp.name) / "journal")
        os.environ["AUDIT_CODE_DIR"] = str(Path(self.tmp.name) / "code-history")
        # Force-reimport so the in-process module re-reads env.
        for k in list(sys.modules):
            if k in ("allocator_bp_guard", "audit") or k.endswith(".allocator_bp_guard") or k.endswith(".audit"):
                del sys.modules[k]
        from allocator_bp_guard import check_buying_power_pre_execution  # noqa: WPS433
        self.check = check_buying_power_pre_execution
        import allocator_bp_guard as bpg  # noqa: WPS433
        self.bpg = bpg

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("AUDIT_CODE_DIR", None)


# ─── Required scenario: 8 BUYs $80k vs BP $50k ────────────────────────────────

class TestEightBuysAgainst50kBP(_Base):
    """Spec: 8 BUYs totaling $80k vs BP $50k → 5 allowed, 3 deferred."""

    def test_8_buys_against_50k_bp(self):
        # 8 orders × $10k = $80k requested
        orders = [_buy(f"SYM{i}", 10_000.0) for i in range(8)]
        # Pre-existing positions don't matter for the BP test; equity high
        # enough that exposure cap doesn't fire (1.5 × $200k = $300k room).
        account = {"buying_power": 50_000.0, "equity": 200_000.0}

        out = self.check(orders, account, open_positions=[], emit_audit=False)

        self.assertEqual(out["warning"], None)
        # Cumulative BP walk: 10k, 20k, 30k, 40k, 50k OK → 60k breaches → defer
        # So 5 allowed, 3 deferred.
        self.assertEqual(out["n_buys_allowed"], 5)
        self.assertEqual(out["n_buys_deferred"], 3)
        self.assertEqual(len(out["allowed_orders"]), 5)
        self.assertEqual(len(out["deferred_orders"]), 3)

        for d in out["deferred_orders"]:
            self.assertEqual(d["deferred_reason"], "INSUFFICIENT_BP_PROJECTED")
            self.assertEqual(d["status"], "deferred_bp")


# ─── Required scenario: fail-soft on missing BP data ──────────────────────────

class TestBpDataUnavailable(_Base):
    """Spec: BP unavailable → all allowed with warning."""

    def test_none_account_passes_all_through(self):
        orders = [_buy("AAPL", 50_000.0), _buy("MSFT", 80_000.0)]
        out = self.check(orders, None, emit_audit=False)
        self.assertEqual(out["warning"], "BP_DATA_UNAVAILABLE")
        self.assertEqual(len(out["allowed_orders"]), 2)
        self.assertEqual(out["deferred_orders"], [])

    def test_empty_account_passes_through(self):
        out = self.check([_buy("AAPL", 5000)], {}, emit_audit=False)
        self.assertEqual(out["warning"], "BP_DATA_UNAVAILABLE")
        self.assertEqual(len(out["allowed_orders"]), 1)

    def test_zero_bp_treated_as_unavailable(self):
        out = self.check(
            [_buy("AAPL", 5000)],
            {"buying_power": 0, "equity": 100_000},
            emit_audit=False,
        )
        self.assertEqual(out["warning"], "BP_DATA_UNAVAILABLE")


# ─── Required scenario: exposure cap respects existing exposure ───────────────

class TestExposureCap(_Base):
    """Spec: exposure cap respects existing exposure."""

    def test_exposure_cap_blocks_when_existing_positions_near_limit(self):
        # max_gross_exposure 1.5 × $100k equity = $150k cap.
        # Already $140k in open positions → only $10k headroom.
        # Two BUYs of $8k each: first fits ($148k), second breaches ($156k).
        orders = [_buy("NEW1", 8000), _buy("NEW2", 8000)]
        account = {"buying_power": 200_000.0, "equity": 100_000.0}
        positions = [{"symbol": "OLD", "market_value": 140_000.0}]

        out = self.check(orders, account, positions, emit_audit=False)
        self.assertEqual(out["n_buys_allowed"], 1)
        self.assertEqual(out["n_buys_deferred"], 1)
        d = out["deferred_orders"][0]
        self.assertEqual(d["deferred_reason"], "EXPOSURE_CAP")
        self.assertEqual(d["symbol"], "NEW2")
        # Make sure existing exposure was actually counted.
        self.assertGreater(out["total_open_exposure"], 139_000.0)


# ─── Required scenario: pending GTC orders count toward exposure ──────────────

class TestPendingGtcCountsTowardExposure(_Base):
    """Spec: pending orders count toward exposure."""

    def test_pending_gtc_consumes_exposure_room(self):
        # Cap = 1.5 × $100k = $150k. No open positions, but $145k of pending
        # GTC orders → only $5k headroom. A $10k BUY must be deferred.
        orders = [_buy("AAPL", 10_000)]
        account = {"buying_power": 500_000.0, "equity": 100_000.0}
        out = self.check(
            orders, account, open_positions=[],
            pending_gtc_notional=145_000.0,
            emit_audit=False,
        )
        self.assertEqual(out["n_buys_allowed"], 0)
        self.assertEqual(out["n_buys_deferred"], 1)
        self.assertEqual(out["deferred_orders"][0]["deferred_reason"], "EXPOSURE_CAP")
        self.assertEqual(out["total_open_exposure"], 145_000.0)


# ─── Required scenario: fail-soft never raises ────────────────────────────────

class TestFailSoftNeverRaises(_Base):
    """Spec: fail-soft never raises (also covers garbage input)."""

    def test_garbage_orders_do_not_raise(self):
        # Mix of None, missing fields, wrong types.
        weird = [
            {"symbol": "X", "action": "BUY"},  # no target / delta
            {"action": "BUY", "delta": "not-a-number"},
            None if False else {"symbol": "Y", "action": "REDUCE"},  # non-BUY
            {"symbol": "Z", "action": "BUY", "delta": -50},
        ]
        out = self.check(
            weird,
            {"buying_power": 10_000, "equity": 100_000},
            emit_audit=False,
        )
        # None of those have positive BUY notional ⇒ all allowed.
        self.assertEqual(out["n_buys_deferred"], 0)

    def test_garbage_account_status_does_not_raise(self):
        # Provided but malformed
        out = self.check(
            [_buy("X", 5000)],
            {"buying_power": "??", "equity": None},
            emit_audit=False,
        )
        self.assertEqual(out["warning"], "BP_DATA_UNAVAILABLE")

    def test_garbage_positions_do_not_raise(self):
        # market_value missing / non-numeric
        positions = [{"symbol": "A"}, {"symbol": "B", "market_value": "xx"}]
        out = self.check(
            [_buy("X", 5000)],
            {"buying_power": 20_000, "equity": 100_000},
            open_positions=positions,
            emit_audit=False,
        )
        # Garbage positions contribute 0 exposure — order passes.
        self.assertEqual(out["n_buys_allowed"], 1)


# ─── Required scenario: deferred orders carry the required reason ─────────────

class TestDeferredReasonField(_Base):
    """Spec: deferred orders have INSUFFICIENT_BP_PROJECTED reason."""

    def test_deferred_reason_string_matches_spec(self):
        orders = [_buy("A", 50_000), _buy("B", 50_000), _buy("C", 50_000)]
        account = {"buying_power": 60_000, "equity": 1_000_000}
        out = self.check(orders, account, emit_audit=False)
        deferred_reasons = {d["deferred_reason"] for d in out["deferred_orders"]}
        self.assertIn("INSUFFICIENT_BP_PROJECTED", deferred_reasons)


# ─── Invariant tests ──────────────────────────────────────────────────────────

class TestInvariants(_Base):
    """The module-level invariants the audit board demands."""

    def test_constants_present_and_true(self):
        self.assertTrue(self.bpg.BP_GUARD_NEVER_RAISES_LIMITS)
        self.assertTrue(self.bpg.BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE)

    def test_caller_cannot_raise_max_gross_above_profile(self):
        # Caller passes a wildly elevated cap. Guard must clamp DOWN to the
        # profile setting (currently 1.50). With 1.50 × $100k = $150k cap +
        # existing $100k exposure → only $50k headroom for new BUYs even
        # though caller asked for cap 5.0× ($500k).
        orders = [_buy("A", 40_000), _buy("B", 40_000)]  # would both fit at 5.0×
        account = {"buying_power": 500_000, "equity": 100_000}
        positions = [{"symbol": "OLD", "market_value": 100_000}]
        out = self.check(
            orders, account, positions,
            max_gross_exposure=5.0,  # malicious caller
            emit_audit=False,
        )
        # Clamped to profile: max_gross_exposure no greater than the profile.
        self.assertLessEqual(out["max_gross_exposure"], 1.50 + 1e-9)
        # Second BUY should be deferred due to cap.
        self.assertGreaterEqual(out["n_buys_deferred"], 1)
        if out["n_buys_deferred"] > 0:
            self.assertIn(
                out["deferred_orders"][0]["deferred_reason"],
                {"EXPOSURE_CAP", "INSUFFICIENT_BP_PROJECTED"},
            )

    def test_non_buy_orders_always_pass_through(self):
        # EXIT + REDUCE free capital — must NEVER be deferred.
        orders = [
            {"symbol": "A", "action": "EXIT",   "target_value": 0},
            {"symbol": "B", "action": "REDUCE", "target_value": 1000, "delta": -500},
            _buy("BIG", 10_000_000),  # ridiculous BUY — should be deferred
        ]
        account = {"buying_power": 50_000, "equity": 100_000}
        out = self.check(orders, account, emit_audit=False)
        # Both non-BUYs in allowed
        allowed_actions = {o.get("action") for o in out["allowed_orders"]}
        self.assertIn("EXIT", allowed_actions)
        self.assertIn("REDUCE", allowed_actions)
        # BIG BUY is deferred
        self.assertEqual(out["n_buys_deferred"], 1)
        self.assertEqual(out["deferred_orders"][0]["symbol"], "BIG")


# ─── Audit emit ───────────────────────────────────────────────────────────────

class TestAuditEmission(_Base):
    """Audit JSONL written under V322_BP_GUARD decision_type."""

    def test_audit_jsonl_written(self):
        orders = [_buy(f"S{i}", 10_000) for i in range(8)]
        account = {"buying_power": 50_000, "equity": 200_000}
        out = self.check(orders, account, emit_audit=True)
        self.assertEqual(out["n_buys_deferred"], 3)

        # Read the audit file the guard wrote into.
        import audit  # noqa: WPS433
        records = audit.read_today(kind="trading")
        v322 = [r for r in records if r.get("decision_type") == "V322_BP_GUARD"]
        self.assertGreaterEqual(len(v322), 1)
        rec = v322[-1]
        self.assertEqual(rec["actor"], "allocator-bp-guard")
        self.assertEqual(rec["decision"], "ENFORCE")
        self.assertEqual(rec["n_allowed"], 5)
        self.assertEqual(rec["n_deferred"], 3)
        self.assertEqual(rec["total_available_bp"], 50_000.0)
        self.assertEqual(rec["total_requested_notional"], 80_000.0)

    def test_audit_pass_through_decision_on_fail_soft(self):
        out = self.check([_buy("X", 1000)], None, emit_audit=True)
        self.assertEqual(out["warning"], "BP_DATA_UNAVAILABLE")
        import audit  # noqa: WPS433
        records = audit.read_today(kind="trading")
        v322 = [r for r in records if r.get("decision_type") == "V322_BP_GUARD"]
        self.assertGreaterEqual(len(v322), 1)
        self.assertEqual(v322[-1]["decision"], "PASS_THROUGH_FAIL_SOFT")
        self.assertEqual(v322[-1]["warning"], "BP_DATA_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)

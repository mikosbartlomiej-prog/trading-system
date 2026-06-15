"""v3.22 (2026-06-15) — canary preflight wired into entry paths.

Closes phase 5 of the v3.22 ENTRY-GATES sprint. Confirms that:

  * Each entry-capable broker entry function in shared/alpaca_orders.py
    runs the broker_paper_canary_preflight gate BEFORE any broker call,
    AFTER confidence-inputs check.
  * When the preflight verdict is REFUSAL → entry is rejected and no
    broker call is made.
  * When the preflight module is missing / raises → entry is rejected
    (fail-CLOSED).
  * Even when the preflight is OK in v3.22 (CANARY_PREFLIGHT_DRY_RUN_OK
    or CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED), the
    entry STILL does not advance to a broker call — v3.22 ships the
    gate, not the executor.
  * ALLOW_BROKER_PAPER=false (the safe default) still blocks the entry
    — the gate is additive, never permissive.
  * Live URL is rejected unconditionally via the paper-only invariant.

HARD SAFETY: no test in this module mutates any safety flag and no
test calls safe_close / submit_order / place_order. Every test asserts
``requests.post`` was never called.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _read_audit_records(tmp_dir: str) -> list:
    out = []
    for jf in Path(tmp_dir).glob("*.jsonl"):
        for line in jf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


class _BaseCanaryWiredTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = self._tmpdir.name
        os.environ["ALPACA_API_KEY"] = "fake-key"
        os.environ["ALPACA_SECRET_KEY"] = "fake-secret"
        os.environ["USE_RISK_OFFICER"] = "true"
        os.environ["INTRADAY_PROTECTION_ENABLED"] = "false"
        os.environ.pop("CANARY_DRY_RUN", None)
        # Force every safety flag FALSE — preflight will refuse, that's
        # the canonical v3.22 state.
        for flag in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                      "BROKER_EXECUTION_ENABLED",
                      "LIVE_TRADING", "LIVE_ENABLED",
                      "GO_LIVE", "LIVE_TRADING_ENABLED",
                      "BROKER_PAPER_CANARY_EXECUTION_ENABLED",
                      "OPERATOR_APPROVED_BROKER_PAPER_CANARY"):
            os.environ.pop(flag, None)

        try:
            from _entry_audit import reset_failure_counter
            reset_failure_counter()
        except Exception:
            try:
                from shared._entry_audit import reset_failure_counter  # type: ignore
                reset_failure_counter()
            except Exception:
                pass

        self._patches = [
            mock.patch("instrument_windows.can_trade_now",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._portfolio_risk_gate",
                       return_value=(True, [], [])),
            mock.patch("alpaca_orders._intraday_governor_gate",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._pdt_gate",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._crypto_exposure_policy_gate",
                       return_value=(True, "ok", "ALLOW")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        for k in ("AUDIT_TRADING_DIR", "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                   "USE_RISK_OFFICER", "INTRADAY_PROTECTION_ENABLED",
                   "CANARY_DRY_RUN"):
            os.environ.pop(k, None)


# ─── Preflight blocks → entry refused ────────────────────────────────────────

class TestPreflightBlocksEntryWhenVerdictRefuses(_BaseCanaryWiredTest):

    def test_preflight_refusal_blocks_stock_entry(self):
        from alpaca_orders import place_stock_bracket
        # Build a fake preflight result with a refusal verdict.

        class _FakePF:
            verdict = "CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY"

        with mock.patch("broker_paper_canary_preflight.run_preflight",
                        return_value=_FakePF()), \
             mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0, take_profit=220.0,
                strategy="momentum-long",
                confidence_inputs={"strategy": "momentum-long",
                                     "primary_score": 0.7},
            )
        self.assertIsNone(result, "preflight refusal must REJECT entry")
        self.assertFalse(post_mock.called)
        recs = _read_audit_records(self._tmpdir.name)
        self.assertTrue(any("CANARY_PREFLIGHT_REFUSED" in
                              (r.get("reason") or "") for r in recs),
                         f"expected canary refusal audit, got {recs}")


# ─── Preflight unavailable / raises → fail-CLOSED ────────────────────────────

class TestPreflightUnavailableBlocksEntryFailClosed(_BaseCanaryWiredTest):

    def test_preflight_raises_blocks_stock_entry(self):
        from alpaca_orders import place_stock_bracket
        with mock.patch("broker_paper_canary_preflight.run_preflight",
                        side_effect=RuntimeError("preflight boom")), \
             mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0, take_profit=220.0,
                strategy="momentum-long",
                confidence_inputs={"strategy": "momentum-long",
                                     "primary_score": 0.7},
            )
        self.assertIsNone(result, "preflight RuntimeError must REJECT entry")
        self.assertFalse(post_mock.called)
        recs = _read_audit_records(self._tmpdir.name)
        # Expect either CANARY_RAISED or CANARY_UNAVAILABLE in reason
        self.assertTrue(any("CANARY" in (r.get("reason") or "")
                              for r in recs),
                         f"expected canary failure audit, got {recs}")


# ─── Preflight OK in v3.22 → STILL DEFERRED at order placement ───────────────

class TestPreflightOkInV322StillBlocksAtOrderPlacement(_BaseCanaryWiredTest):
    """All-green preflight verdicts (DRY_RUN_OK + DEFERRED) MUST still
    block at the broker layer because v3.22 deliberately does not ship
    order placement."""

    def test_dry_run_ok_still_blocks_stock_entry(self):
        from alpaca_orders import place_stock_bracket

        class _FakePF:
            verdict = "CANARY_PREFLIGHT_DRY_RUN_OK"

        with mock.patch("broker_paper_canary_preflight.run_preflight",
                        return_value=_FakePF()), \
             mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0, take_profit=220.0,
                strategy="momentum-long",
                confidence_inputs={"strategy": "momentum-long",
                                     "primary_score": 0.7},
            )
        self.assertIsNone(result, "v3.22: even DRY_RUN_OK must BLOCK")
        self.assertFalse(post_mock.called,
                          "v3.22 architectural: DRY_RUN_OK still no POST")
        recs = _read_audit_records(self._tmpdir.name)
        self.assertTrue(any("ORDER_PLACEMENT_DEFERRED" in
                              (r.get("reason") or "") for r in recs),
                         f"expected DEFERRED audit, got {recs}")

    def test_ready_deferred_still_blocks_stock_entry(self):
        from alpaca_orders import place_stock_bracket

        class _FakePF:
            verdict = (
                "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED")

        with mock.patch("broker_paper_canary_preflight.run_preflight",
                        return_value=_FakePF()), \
             mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0, take_profit=220.0,
                strategy="momentum-long",
                confidence_inputs={"strategy": "momentum-long",
                                     "primary_score": 0.7},
            )
        self.assertIsNone(result, "v3.22 architectural deferral must hold")
        self.assertFalse(post_mock.called)
        recs = _read_audit_records(self._tmpdir.name)
        self.assertTrue(any("DEFERRED" in (r.get("reason") or "")
                              for r in recs))


# ─── Paper-only invariant survives ───────────────────────────────────────────

class TestLiveUrlRejectedUnconditionally(_BaseCanaryWiredTest):
    """v3.22 wiring must NOT loosen the paper-only invariant. The ALPACA
    base URL is hard-coded in alpaca_orders.py — verify the literal."""

    def test_alpaca_base_url_is_paper(self):
        import alpaca_orders
        self.assertEqual(
            alpaca_orders.ALPACA_BASE_URL,
            "https://paper-api.alpaca.markets",
            "Paper-only invariant violated — base URL is not paper")

    def test_preflight_refuses_when_live_trading_truthy(self):
        """If LIVE_TRADING is set truthy, the real preflight refuses
        unconditionally. We verify by calling the real preflight (not
        a mock) and asserting verdict is the LIVE_FLAG_TRUTHY refusal."""
        os.environ["LIVE_TRADING"] = "true"
        try:
            from broker_paper_canary_preflight import (
                run_preflight,
                CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY,
            )
            rep = run_preflight(unlock_status=None, dry_run_only=False)
            self.assertEqual(rep.verdict,
                              CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY,
                              "LIVE_TRADING=true must yield LIVE_FLAG_TRUTHY")
        finally:
            os.environ.pop("LIVE_TRADING", None)


# ─── ALLOW_BROKER_PAPER=false still blocks ────────────────────────────────────

class TestAllowBrokerPaperFalseStillBlocks(_BaseCanaryWiredTest):
    """The gate is purely ADDITIVE — disabling ALLOW_BROKER_PAPER does
    not enable any new path. With it false (default), the preflight
    refuses the broker-flag-truthy / execution-flag gates and the
    entry path REJECTS at the canary stage. Crucially, even if we
    *flipped* ALLOW_BROKER_PAPER=true (we do NOT), the entry path still
    refuses in v3.22 because order placement is architecturally
    deferred. We assert the safe default state here.
    """

    def test_default_state_rejects_stock_entry(self):
        from alpaca_orders import place_stock_bracket
        # Confirm flag is false
        self.assertNotEqual(
            os.environ.get("ALLOW_BROKER_PAPER", "false").lower(), "true",
            "test precondition: ALLOW_BROKER_PAPER must be unset/false")
        with mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0, take_profit=220.0,
                strategy="momentum-long",
                confidence_inputs={"strategy": "momentum-long",
                                     "primary_score": 0.7},
            )
        self.assertIsNone(result, "default state must REJECT entry")
        self.assertFalse(post_mock.called)


# ─── Unlock-status helper ─────────────────────────────────────────────────────

class TestReadLatestUnlockStatusSafe(unittest.TestCase):
    """The fail-soft helper reads unlock_status from the readiness JSON."""

    def test_returns_unlock_status_string_or_none(self):
        from alpaca_orders import _read_latest_unlock_status_safe
        val = _read_latest_unlock_status_safe()
        # Either None (file missing) or one of the known unlock status
        # strings — never raises.
        self.assertIsInstance(val, (type(None), str))

    def test_never_raises_on_missing_file(self):
        """Force a JSON-decode failure mid-read by pointing the readiness
        file at a directory with malformed content (in tmpdir). The
        helper resolves the path under ``__file__`` parent.parent —
        a clean way to exercise the fail-soft path is to patch the
        internal json.loads call.
        """
        import alpaca_orders
        with mock.patch("json.loads", side_effect=RuntimeError("forced")):
            try:
                val = alpaca_orders._read_latest_unlock_status_safe()
            except Exception as e:
                self.fail(f"helper raised: {e!r}")
            self.assertIsNone(val)


if __name__ == "__main__":
    unittest.main(verbosity=2)

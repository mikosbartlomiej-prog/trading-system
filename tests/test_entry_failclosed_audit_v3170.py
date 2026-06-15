"""v3.17.0 (2026-06-04) — Fail-CLOSED for new entries + mandatory entry audit.

Covers Codex audit Tasks 2 + 3 (2026-06-04):

Task 2 — Fail-CLOSED for new entries
  - shared/alpaca_orders.py: place_stock_bracket / place_crypto_order /
    place_simple_buy MUST refuse the order when:
       * risk_officer import fails
       * risk_officer.evaluate_trade raises
       * (options) the confidence module raises
    Emergency-close / safe_close MUST remain able to close even when
    risk_officer is unavailable.

Task 3 — Mandatory entry audit emit
  - Every entry decision (placed / rejected / failed) MUST emit a
    JSONL audit event via shared._entry_audit.emit_entry_audit.
  - Audit emit failures MUST NOT block the entry decision.

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
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


def _audit_dir(tmp: tempfile.TemporaryDirectory) -> str:
    return tmp.name


def _read_audit_records(tmp_dir: str) -> list[dict]:
    """Read every JSONL file in tmp_dir and return parsed records."""
    out = []
    p = Path(tmp_dir)
    for jf in p.glob("*.jsonl"):
        for line in jf.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


class _FakeResponse:
    def __init__(self, status_code=201, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text or json.dumps(self._body)

    def json(self):
        return self._body


class _BaseEntryTest(unittest.TestCase):
    """Common setUp: shared paths + audit dir + safe_close-friendly env."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = _audit_dir(self._tmpdir)
        os.environ["ALPACA_API_KEY"] = "fake-key"
        os.environ["ALPACA_SECRET_KEY"] = "fake-secret"
        os.environ["USE_RISK_OFFICER"] = "true"
        # Disable intraday governor / safe_mode escalation noise.
        os.environ["INTRADAY_PROTECTION_ENABLED"] = "false"
        # Reset the entry-audit failure counter so cross-test state
        # doesn't pollute.
        try:
            from _entry_audit import reset_failure_counter
            reset_failure_counter()
        except ImportError:
            from shared._entry_audit import reset_failure_counter  # type: ignore
            reset_failure_counter()
        # Patch out network gates so tests don't reach Alpaca / state.json /
        # instrument_windows / portfolio_risk / pdt / governor / heartbeat.
        # The 6 gates upstream of risk_officer must all return ALLOW to
        # focus on Task-2 risk-officer behavior.
        #
        # v3.22 (2026-06-15): the new entry-gate stack (confidence-mandatory
        # + canary preflight) now runs BEFORE the v3.17 fail-CLOSED logic.
        # These tests pre-date v3.22 and don't supply confidence_inputs /
        # don't mock the canary, so we explicitly bypass the v3.22 gate
        # here to keep the v3.17 test intent isolated. The v3.22 gate
        # itself is exercised by tests/test_entry_path_confidence_mandatory_v3220.py
        # and tests/test_canary_preflight_wired_v3220.py.
        self._patches = [
            mock.patch("instrument_windows.can_trade_now",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._portfolio_risk_gate",
                       return_value=(True, [], [])),
            mock.patch("alpaca_orders._intraday_governor_gate",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._pdt_gate",
                       return_value=(True, "ok")),
            mock.patch("alpaca_orders._v322_entry_gate_stack",
                       return_value=(True, "OBSERVE_ONLY_SKIP",
                                      "v3.17 test fixture bypass")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)
        os.environ.pop("USE_RISK_OFFICER", None)
        os.environ.pop("INTRADAY_PROTECTION_ENABLED", None)


# ─── Task 2 — Fail-CLOSED for stocks ──────────────────────────────────────────

class TestStockBracketFailClosed(_BaseEntryTest):

    def test_risk_officer_import_failure_refuses_entry(self):
        """If risk_officer import raises, place_stock_bracket returns None."""
        from alpaca_orders import place_stock_bracket
        # Force ImportError by removing the module and blocking re-import.
        with mock.patch.dict(sys.modules, {"risk_officer": None,
                                           "shared.risk_officer": None}):
            # Also patch builtins.__import__ so the fallback raises too.
            real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

            def _blocking_import(name, *args, **kwargs):
                if name in ("risk_officer", "shared.risk_officer"):
                    raise ImportError(f"forced — {name}")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=_blocking_import):
                with mock.patch("requests.post") as post_mock:
                    result = place_stock_bracket(
                        symbol="AAPL", side="buy", qty=10,
                        entry_price=200.0, stop_loss=190.0,
                        take_profit=220.0, strategy="momentum-long",
                    )
            self.assertIsNone(result, "fail-CLOSED: must refuse on missing risk_officer")
            self.assertFalse(post_mock.called,
                              "must NOT POST to broker when risk-officer unavailable")
        # Audit row should exist with result="rejected" and reason mentioning
        # risk-officer unavailable.
        records = _read_audit_records(_audit_dir(self._tmpdir))
        self.assertTrue(any(r.get("result") == "rejected"
                              and "risk-officer" in (r.get("reason") or "")
                              for r in records),
                         f"expected risk-officer-rejected audit row, got {records}")

    def test_risk_officer_exception_refuses_entry(self):
        """If risk_officer.evaluate_trade raises, place_stock_bracket returns None."""
        from alpaca_orders import place_stock_bracket
        with mock.patch("risk_officer.evaluate_trade",
                        side_effect=RuntimeError("boom")):
            with mock.patch("requests.post") as post_mock:
                result = place_stock_bracket(
                    symbol="AAPL", side="buy", qty=10,
                    entry_price=200.0, stop_loss=190.0,
                    take_profit=220.0, strategy="momentum-long",
                )
        self.assertIsNone(result, "fail-CLOSED: must refuse on evaluate_trade exception")
        self.assertFalse(post_mock.called)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        self.assertTrue(any("RuntimeError" in (r.get("reason") or "") for r in records),
                         f"expected exception audit row, got {records}")

    def test_successful_place_emits_placed_audit(self):
        """Happy path: bracket order placed → audit row result=placed."""
        from alpaca_orders import place_stock_bracket
        fake_verdict = {
            "decision":      "APPROVE",
            "verdict":       "ALLOW",
            "rationale":     "all good",
            "checks_passed": ["whitelist", "stop_loss"],
            "checks_failed": [],
            "warnings":      [],
        }
        fake_order = {"id": "order-abc-123", "status": "accepted"}
        with mock.patch("risk_officer.evaluate_trade", return_value=fake_verdict), \
             mock.patch("requests.post",
                        return_value=_FakeResponse(201, body=fake_order)):
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0,
                take_profit=220.0, strategy="momentum-long",
            )
        self.assertEqual(result, fake_order)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        placed = [r for r in records if r.get("result") == "placed"]
        self.assertEqual(len(placed), 1,
                          f"expected 1 placed audit, got {records}")
        rec = placed[0]
        # Required fields per Task 3 spec.
        self.assertEqual(rec["decision_type"], "APPROVE_ENTRY")
        self.assertEqual(rec["decision"], "PLACED")
        self.assertIn("AAPL", rec.get("affected_symbols", []))
        self.assertEqual(rec.get("strategy"), "momentum-long")
        inputs = rec.get("risk_metrics") or {}
        # `inputs` field is deterministic_inputs_hash; the raw inputs are
        # NOT persisted directly. We verify via action_taken instead.
        self.assertIn("BUY", rec.get("action_taken", ""))
        self.assertIn("AAPL", rec.get("action_taken", ""))

    def test_risk_officer_reject_emits_rejected_audit(self):
        """risk_officer REJECT → no order, audit row result=rejected with verdict."""
        from alpaca_orders import place_stock_bracket
        fake_verdict = {
            "decision":      "REJECT",
            "verdict":       "BLOCK",
            "rationale":     "concentration too high",
            "checks_passed": [],
            "checks_failed": ["concentration"],
            "warnings":      [],
        }
        with mock.patch("risk_officer.evaluate_trade", return_value=fake_verdict), \
             mock.patch("requests.post") as post_mock:
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0,
                take_profit=220.0, strategy="momentum-long",
            )
        self.assertIsNone(result)
        self.assertFalse(post_mock.called)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        rejected = [r for r in records if r.get("result") == "rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertIn("concentration", rejected[0].get("reason", "").lower())

    def test_broker_500_emits_failed_audit(self):
        """risk_officer APPROVE but Alpaca 500 → audit row result=failed."""
        from alpaca_orders import place_stock_bracket
        fake_verdict = {
            "decision":      "APPROVE",
            "checks_passed": ["whitelist"],
            "checks_failed": [],
            "warnings":      [],
            "rationale":     "ok",
        }
        with mock.patch("risk_officer.evaluate_trade", return_value=fake_verdict), \
             mock.patch("requests.post",
                        return_value=_FakeResponse(500, body={"error": "boom"},
                                                    text='{"error":"boom"}')):
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0,
                take_profit=220.0, strategy="momentum-long",
            )
        self.assertIsNone(result)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        failed = [r for r in records if r.get("result") == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("500", failed[0].get("reason", ""))


# ─── Task 2 — Fail-CLOSED for crypto ──────────────────────────────────────────

class TestCryptoOrderFailClosed(_BaseEntryTest):

    def test_risk_officer_exception_refuses_crypto_entry(self):
        """If risk_officer.evaluate_trade raises, place_crypto_order returns None."""
        from alpaca_orders import place_crypto_order
        with mock.patch("risk_officer.evaluate_trade",
                        side_effect=RuntimeError("boom-crypto")):
            with mock.patch("requests.post") as post_mock:
                result = place_crypto_order(
                    symbol="BTC/USD", side="buy", qty=0.1,
                    limit_price=60000.0, strategy="crypto-momentum",
                )
        self.assertIsNone(result)
        self.assertFalse(post_mock.called)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        self.assertTrue(any("boom-crypto" in (r.get("reason") or "")
                              for r in records))

    def test_risk_officer_import_failure_refuses_crypto(self):
        from alpaca_orders import place_crypto_order
        with mock.patch.dict(sys.modules, {"risk_officer": None,
                                           "shared.risk_officer": None}):
            real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

            def _blocking_import(name, *args, **kwargs):
                if name in ("risk_officer", "shared.risk_officer"):
                    raise ImportError(f"forced — {name}")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=_blocking_import):
                with mock.patch("requests.post") as post_mock:
                    result = place_crypto_order(
                        symbol="BTC/USD", side="buy", qty=0.1,
                        limit_price=60000.0, strategy="crypto-momentum",
                    )
        self.assertIsNone(result)
        self.assertFalse(post_mock.called)

    def test_successful_crypto_emits_placed_audit(self):
        from alpaca_orders import place_crypto_order
        fake_verdict = {"decision": "APPROVE", "rationale": "ok",
                        "checks_passed": [], "checks_failed": [],
                        "warnings": []}
        fake_order = {"id": "btc-order-1", "status": "accepted"}
        with mock.patch("risk_officer.evaluate_trade", return_value=fake_verdict), \
             mock.patch("requests.post",
                        return_value=_FakeResponse(201, body=fake_order)):
            result = place_crypto_order(
                symbol="BTC/USD", side="buy", qty=0.1,
                limit_price=60000.0, strategy="crypto-momentum",
            )
        self.assertEqual(result, fake_order)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        placed = [r for r in records if r.get("result") == "placed"]
        self.assertEqual(len(placed), 1)
        self.assertIn("BTC/USD", placed[0].get("affected_symbols", []))


# ─── Task 2 — Fail-CLOSED for options ─────────────────────────────────────────

class TestSimpleBuyOptionsFailClosed(_BaseEntryTest):

    def test_confidence_gate_exception_refuses_options(self):
        """If _confidence_gate raises, place_simple_buy returns None."""
        from alpaca_orders import place_simple_buy
        with mock.patch("alpaca_orders._confidence_gate",
                        side_effect=RuntimeError("conf-boom")):
            with mock.patch("requests.post") as post_mock:
                result = place_simple_buy(
                    symbol="AAPL250620C00220000", qty=1,
                    limit_price=5.50, strategy="options-momentum",
                    confidence_inputs={"strategy": "options-momentum",
                                        "primary_score": 0.7},
                )
        self.assertIsNone(result)
        self.assertFalse(post_mock.called)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        self.assertTrue(any("conf-boom" in (r.get("reason") or "")
                              for r in records))

    def test_confidence_gate_block_emits_rejected_audit(self):
        from alpaca_orders import place_simple_buy
        with mock.patch("alpaca_orders._confidence_gate",
                        return_value=(False, "confidence too low")):
            with mock.patch("requests.post") as post_mock:
                result = place_simple_buy(
                    symbol="AAPL250620C00220000", qty=1,
                    limit_price=5.50, strategy="options-momentum",
                    confidence_inputs={"strategy": "options-momentum"},
                )
        self.assertIsNone(result)
        self.assertFalse(post_mock.called)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        rejected = [r for r in records if r.get("result") == "rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertIn("confidence", rejected[0].get("reason", "").lower())

    def test_successful_options_emits_placed_audit(self):
        from alpaca_orders import place_simple_buy
        fake_order = {"id": "opt-order-1", "status": "accepted"}
        with mock.patch("alpaca_orders._confidence_gate",
                        return_value=(True, "ok")), \
             mock.patch("requests.post",
                        return_value=_FakeResponse(201, body=fake_order)):
            result = place_simple_buy(
                symbol="AAPL250620C00220000", qty=1,
                limit_price=5.50, strategy="options-momentum",
            )
        self.assertEqual(result, fake_order)
        records = _read_audit_records(_audit_dir(self._tmpdir))
        placed = [r for r in records if r.get("result") == "placed"]
        self.assertEqual(len(placed), 1)


# ─── Task 3 — Audit emit failure must not block placement ─────────────────────

class TestAuditFailureDoesNotBlock(_BaseEntryTest):

    def test_audit_emit_raises_does_not_block_stock_placement(self):
        """If the audit emit helper raises, place_stock_bracket still returns
        the broker order (audit failure must not break trading)."""
        from alpaca_orders import place_stock_bracket
        fake_verdict = {"decision": "APPROVE", "rationale": "ok",
                        "checks_passed": [], "checks_failed": [],
                        "warnings": []}
        fake_order = {"id": "still-placed", "status": "accepted"}
        # Patch deep into _entry_audit.emit_entry_audit so it raises a
        # custom exception. _emit_entry_audit_event in alpaca_orders
        # catches the exception defensively.
        with mock.patch("risk_officer.evaluate_trade", return_value=fake_verdict), \
             mock.patch("_entry_audit.emit_entry_audit",
                        side_effect=RuntimeError("audit-broken")), \
             mock.patch("requests.post",
                        return_value=_FakeResponse(201, body=fake_order)):
            result = place_stock_bracket(
                symbol="AAPL", side="buy", qty=10,
                entry_price=200.0, stop_loss=190.0,
                take_profit=220.0, strategy="momentum-long",
            )
        self.assertEqual(result, fake_order,
                          "audit failure MUST NOT block the broker call")


# ─── safe_close MUST still work when risk_officer is unavailable ─────────────

class TestSafeCloseIndependentOfRiskOfficer(_BaseEntryTest):
    """safe_close paths MUST remain operational even when risk_officer
    is broken — emergency closes can't be allowed to leak through."""

    def test_safe_close_skipped_when_position_gone_no_risk_officer(self):
        """safe_close returns status=skipped when position is gone, even
        when risk_officer import would raise."""
        from alpaca_orders import safe_close
        # Forced risk_officer import error throughout the test.
        with mock.patch.dict(sys.modules, {"risk_officer": None,
                                           "shared.risk_officer": None}):
            real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

            def _blocking_import(name, *args, **kwargs):
                if name in ("risk_officer", "shared.risk_officer"):
                    raise ImportError(f"forced — {name}")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=_blocking_import), \
                 mock.patch("alpaca_orders._fetch_single_position",
                            return_value=None), \
                 mock.patch("alpaca_orders._cancel_open_orders_for_symbol",
                            return_value={"checked": 0, "canceled": [],
                                          "failed": []}):
                result = safe_close(
                    symbol="AAPL", intent_qty=10.0,
                    reason_tag="exit-emergency",
                    order_type="market", allow_market=True,
                )
        # safe_close cannot place because position is gone — status
        # should be "skipped" with reason "position_gone".  The point
        # is: safe_close DID NOT crash because risk_officer was missing.
        self.assertEqual(result["status"], "skipped",
                          f"safe_close should still operate without risk_officer; "
                          f"got {result}")
        self.assertIn("position", result["reason"].lower())


# ─── _entry_audit helper unit tests ───────────────────────────────────────────

class TestEntryAuditHelper(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = self._tmpdir.name
        from _entry_audit import reset_failure_counter
        reset_failure_counter()

    def tearDown(self):
        self._tmpdir.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_emit_placed_creates_audit_row(self):
        from _entry_audit import emit_entry_audit
        proposal = {
            "symbol":      "AAPL",
            "action":      "BUY",
            "size_usd":    1000,
            "entry_price": 100.0,
            "stop_loss":   95.0,
            "take_profit": 110.0,
            "strategy":    "momentum-long",
        }
        ok = emit_entry_audit(
            proposal=proposal, result="placed",
            result_reason="ok", order={"id": "abc"},
        )
        self.assertTrue(ok)
        records = _read_audit_records(self._tmpdir.name)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["decision_type"], "APPROVE_ENTRY")
        self.assertEqual(rec["decision"], "PLACED")
        self.assertEqual(rec["affected_symbols"], ["AAPL"])
        self.assertEqual(rec["strategy"], "momentum-long")

    def test_emit_rejected_uses_reject_entry_decision_type(self):
        from _entry_audit import emit_entry_audit
        proposal = {"symbol": "AAPL", "action": "BUY", "strategy": "momentum-long"}
        ok = emit_entry_audit(
            proposal=proposal, result="rejected",
            result_reason="risk-officer REJECT: concentration",
        )
        self.assertTrue(ok)
        records = _read_audit_records(self._tmpdir.name)
        self.assertEqual(records[0]["decision_type"], "REJECT_ENTRY")
        self.assertEqual(records[0]["decision"], "REJECTED")

    def test_emit_never_raises(self):
        """Audit emit must NEVER propagate exceptions to caller."""
        from _entry_audit import emit_entry_audit
        # Force the inner write to explode by giving an invalid AUDIT_TRADING_DIR.
        with mock.patch("audit.write_audit_event",
                        side_effect=RuntimeError("disk-full")):
            ok = emit_entry_audit(
                proposal={"symbol": "AAPL", "action": "BUY"},
                result="placed",
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

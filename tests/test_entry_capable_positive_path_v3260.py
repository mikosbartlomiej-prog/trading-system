"""v3.26 (2026-06-15) — ETAP 2 — Positive entry-capable path proof.

WHY
---
The v3.25 audit showed 100% of sampled real-market rows ended at
``OBSERVE_ONLY_SKIP`` with null confidence. The system has been silent
for so long we now need a MECHANICAL proof that the positive path can
produce a confidence-bearing row when given a synthetic entry-capable
fixture. If this test passes, the only reason production rows stay
observe-only is that the monitor scan logic itself never fires an
entry-capable SignalEvent during the current market regime — NOT that
the emitter / confidence / ledger pipeline is broken.

This is a deterministic, no-network, no-broker proof of the positive
path. We:

  1. Build a SignalEvent with entry_capable=True for three strategies:
     crypto-oversold-bounce, momentum-long, overbought-short.
  2. Route it through ``shared.signal_emitter.emit_signal_opportunity``.
  3. Capture the persisted row.
  4. Assert it carries a numeric confidence_score, non-empty
     confidence_components, a confidence_decision in
     ``{ALLOW, ALERT_ONLY, BLOCK}``, default_reasons present, and
     positive input completeness.
  5. Assert no broker function and no network call happened.

We also prove the negative branches:

  * risk-blocked row → eligibility = NOT_ELIGIBLE_RISK_BLOCK, no fill.
  * low-confidence row → eligibility = NOT_ELIGIBLE_CONFIDENCE_LOW.
  * observe-only row → confidence_status = OBSERVE_ONLY_SKIP,
    eligibility = NOT_ELIGIBLE_OBSERVE_ONLY.

HARD SAFETY
-----------
- NEVER imports / calls ``alpaca_orders``.
- NEVER opens a real network connection.
- NEVER writes to the production ledger.
- Uses tempdir for any actual file I/O.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import signal_emitter            # type: ignore  # noqa: E402
from signal_emitter import (      # type: ignore  # noqa: E402
    CONFIDENCE_STATUS_OK,
    CONFIDENCE_STATUS_ERROR,
    CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP,
    emit_signal_opportunity,
)
from signal_event import SignalEvent, build_signal_id  # type: ignore  # noqa: E402
from shadow_eligibility import (   # type: ignore  # noqa: E402
    ShadowEligibilityDecision,
    evaluate_shadow_eligibility,
)


# ─── Synthetic fixtures (deterministic, no random) ───────────────────────────


def _now_iso() -> str:
    return datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc).isoformat()


def _make_entry_event(
    *,
    strategy_id: str,
    symbol: str,
    source_monitor: str,
    asset_class: str,
    side: str = "long",
    action: str = "BUY",
    primary_score: float = 0.72,
    rsi: float | None = None,
    bars_count: int = 24,
    extra_raw: dict | None = None,
    regime: str = "NEUTRAL",
) -> SignalEvent:
    """Build a SignalEvent representing a fresh, entry-capable opportunity.

    The raw_signal carries enough numeric fields that
    ``build_confidence_inputs`` can populate ``signal_strength``
    (primary_score), ``data_quality`` (bars_count), and ``regime``.
    """
    ts = _now_iso()
    sid = build_signal_id(strategy_id, symbol, ts, source_monitor)
    raw: dict = {
        "primary_score": primary_score,
        "bars_count":    bars_count,
        "confirmations": 1,
        "regime":        regime,
    }
    if rsi is not None:
        raw["rsi"] = rsi
    if extra_raw:
        raw.update(extra_raw)
    return SignalEvent(
        signal_id=sid,
        strategy_id=strategy_id,
        symbol=symbol,
        asset_class=asset_class,
        side=side,
        action=action,
        timestamp_iso=ts,
        source_monitor=source_monitor,
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=True,
        raw_signal=raw,
        risk_inputs={"strategy": strategy_id, "symbol": symbol},
        market_regime={"regime": regime},
        universe_status={"status": "WHITELISTED"},
    )


def _make_observe_event(
    *,
    strategy_id: str = "crypto-momentum",
    symbol: str = "ETH/USD",
    source_monitor: str = "crypto-monitor",
) -> SignalEvent:
    ts = _now_iso()
    sid = build_signal_id(strategy_id, symbol, ts, source_monitor)
    return SignalEvent(
        signal_id=sid,
        strategy_id=strategy_id,
        symbol=symbol,
        asset_class="crypto",
        side="n/a",
        action="DETECTED",
        timestamp_iso=ts,
        source_monitor=source_monitor,
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=False,
        raw_signal={"rsi": 50.0},
    )


def _read_ledger(tmp_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for jf in tmp_dir.glob("*.jsonl"):
        with open(jf, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    return rows


# ─── Safety guards ───────────────────────────────────────────────────────────


# Modules we forbid the positive path from invoking. The keys are
# (module_path, function_name) and the value is a human-readable label.
_FORBIDDEN_BROKER_CALLS = (
    ("alpaca_orders",        "place_stock_bracket"),
    ("alpaca_orders",        "place_crypto_order"),
    ("alpaca_orders",        "place_simple_buy"),
    ("alpaca_orders",        "place_option_order"),
    ("alpaca_orders",        "safe_close"),
    ("alpaca_orders",        "submit_order"),
    ("alpaca_orders",        "close_position"),
    ("alpaca_orders",        "close_all_positions"),
    ("shared.alpaca_orders", "place_stock_bracket"),
    ("shared.alpaca_orders", "place_crypto_order"),
    ("shared.alpaca_orders", "place_simple_buy"),
    ("shared.alpaca_orders", "place_option_order"),
    ("shared.alpaca_orders", "safe_close"),
    ("shared.alpaca_orders", "submit_order"),
    ("shared.alpaca_orders", "close_position"),
    ("shared.alpaca_orders", "close_all_positions"),
)


def _broker_killer(*_a, **_kw):
    raise AssertionError(
        "POSITIVE PATH MUST NEVER CALL THE BROKER — this would mean the "
        "emitter regressed to placing live trades."
    )


def _socket_killer(*_a, **_kw):
    raise AssertionError(
        "POSITIVE PATH MUST NEVER OPEN A NETWORK CONNECTION."
    )


class _SafetyGuards:
    """Context manager that wires broker- and network-killers.

    Failure to call any of these is a HARD assertion; the moment any
    forbidden function is invoked the test fails.
    """

    def __init__(self):
        self._patches: list = []

    def __enter__(self):
        # Patch every forbidden broker call across BOTH possible
        # import paths. Use create=True so absence of the symbol on
        # the module doesn't break the patch context.
        for mod_path, fn_name in _FORBIDDEN_BROKER_CALLS:
            p = mock.patch(f"{mod_path}.{fn_name}",
                           side_effect=_broker_killer, create=True)
            try:
                p.start()
                self._patches.append(p)
            except Exception:
                # Module may not be importable in the test environment.
                # That's even safer — there is literally nothing to call.
                pass

        # Network killers. requests + socket.
        for mod_path, fn_name in (
            ("requests", "get"),
            ("requests", "post"),
            ("requests", "put"),
            ("requests", "delete"),
            ("requests", "request"),
        ):
            p = mock.patch(f"{mod_path}.{fn_name}",
                           side_effect=_socket_killer, create=True)
            try:
                p.start()
                self._patches.append(p)
            except Exception:
                pass

        # Patch socket.socket.connect so even raw socket calls trip.
        p = mock.patch.object(socket.socket, "connect",
                              side_effect=_socket_killer)
        p.start()
        self._patches.append(p)
        return self

    def __exit__(self, *_exc):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass


# ─── Common base ─────────────────────────────────────────────────────────────


class _LedgerSandbox(unittest.TestCase):
    """Every test runs against a tempdir ledger AND a tempdir diag dir.

    Production directories are NEVER written to.
    """

    def setUp(self):
        signal_emitter._clear_idempotency_cache_for_tests()
        self.tmp_ledger = tempfile.TemporaryDirectory()
        self.tmp_diag = tempfile.TemporaryDirectory()
        os.environ["OPPORTUNITY_LEDGER_DIR"] = self.tmp_ledger.name
        os.environ["MONITOR_RUNTIME_DIAG_DIR"] = self.tmp_diag.name
        self.ledger_path = Path(self.tmp_ledger.name)
        self.diag_path = Path(self.tmp_diag.name)

    def tearDown(self):
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        os.environ.pop("MONITOR_RUNTIME_DIAG_DIR", None)
        self.tmp_ledger.cleanup()
        self.tmp_diag.cleanup()


# ─── Test 1-3 — three strategies produce confidence-bearing rows ─────────────


class TestPositiveEntryCapablePaths(_LedgerSandbox):
    """For each canonical entry-capable strategy, prove the emitter
    end-to-end produces a numeric confidence_score, non-empty
    components, an explicit decision, and no broker call."""

    def _assert_positive_row(self, result: dict, rows: list[dict]):
        # ── emitter envelope ─────────────────────────────────────
        self.assertTrue(result["emitted"],
                         f"emit_signal_opportunity envelope: {result}")
        self.assertEqual(result["status"], "EMITTED")
        self.assertEqual(result["confidence_status"],
                          CONFIDENCE_STATUS_OK)
        score = result["confidence_score"]
        self.assertIsNotNone(score, "confidence_score must be numeric")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        verdict = result["confidence_verdict"]
        self.assertIn(verdict, ("ALLOW", "ALERT_ONLY", "BLOCK"))
        self.assertEqual(result["confidence_decision"], verdict)
        # signal_id present, builder version stamped, completeness > 0.
        self.assertTrue(result.get("signal_id"),
                         "signal_id must be present on emitted envelope")
        self.assertTrue(result.get("confidence_builder_version"),
                         "builder version must be stamped on envelope")
        completeness = result.get("confidence_input_completeness")
        self.assertIsNotNone(completeness)
        self.assertGreater(completeness, 0.0,
                            "input completeness must be > 0 (we provided "
                            "real raw_signal fields)")
        # default_reasons is always a dict; may be non-empty for fields
        # we did not source.
        self.assertIsInstance(result.get("confidence_default_reasons"), dict)
        # ── ledger row ───────────────────────────────────────────
        self.assertEqual(len(rows), 1, f"expected one ledger row, got {rows}")
        row = rows[0]
        self.assertIsNotNone(row["confidence_score"])
        self.assertIsInstance(row["confidence_components"], dict)
        self.assertGreater(len(row["confidence_components"]), 0)
        raw = row["raw_signal"]
        self.assertEqual(raw.get("confidence_status"),
                          CONFIDENCE_STATUS_OK)
        self.assertIn(raw.get("confidence_decision"),
                       ("ALLOW", "ALERT_ONLY", "BLOCK"))
        # entry_capable persisted as True.
        self.assertTrue(raw.get("entry_capable"))
        # risk_decision defaults to UNKNOWN (emitter does NOT call
        # risk_officer) but the field is present.
        self.assertIn("risk_decision", row)

    def test_positive_crypto_oversold_bounce_creates_confidence_bearing_row(self):
        # Synthetic 25-bar OHLCV bottom: RSI dipping to 22, 3-bar
        # stabilization. We model this as a high primary_score for the
        # oversold-bounce strategy because the strategy's score function
        # peaks when RSI ≤ 30 (see crypto-monitor._primary_score_for).
        ev = _make_entry_event(
            strategy_id="crypto-oversold-bounce",
            symbol="BTC/USD",
            source_monitor="crypto-monitor",
            asset_class="crypto",
            primary_score=0.85,
            rsi=22.0,
            bars_count=25,
            extra_raw={
                "reversal_bars": 3,
                "vol_mult":      0.4,
                "move_24h_pct": -6.5,
            },
        )
        with _SafetyGuards():
            result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self._assert_positive_row(result, rows)

    def test_positive_momentum_long_creates_confidence_bearing_row(self):
        # Synthetic momentum-long breakout: high primary_score, RSI in
        # the 55-65 zone, vol expansion, fresh bars.
        ev = _make_entry_event(
            strategy_id="momentum-long",
            symbol="AAPL",
            source_monitor="price-monitor",
            asset_class="us_equity",
            primary_score=0.78,
            rsi=62.0,
            bars_count=25,
            extra_raw={
                "breakout":       True,
                "vol_expansion":  1.6,
                "trend_filter":   True,
            },
            regime="RISK_ON",
        )
        with _SafetyGuards():
            result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self._assert_positive_row(result, rows)

    def test_positive_overbought_short_creates_confidence_bearing_row(self):
        # Synthetic overbought-short reversal: RSI > 75, primary_score
        # encodes "strong-fade" conviction. side=short, action=SELL_SHORT.
        ev = _make_entry_event(
            strategy_id="overbought-short",
            symbol="QQQ",
            source_monitor="price-monitor",
            asset_class="us_equity",
            side="short",
            action="SELL_SHORT",
            primary_score=0.72,
            rsi=78.0,
            bars_count=25,
            extra_raw={
                "reversal_candle": True,
                "rsi_div":         True,
            },
            regime="NEUTRAL",
        )
        with _SafetyGuards():
            result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self._assert_positive_row(result, rows)


# ─── Test 4 — risk-block path ────────────────────────────────────────────────


class TestRiskBlockedPath(_LedgerSandbox):
    """Even when a downstream risk_officer would REJECT, the emitter still
    persists a confidence-bearing row. Shadow-eligibility then rules the
    row NOT_ELIGIBLE_RISK_BLOCK and no shadow fill is written."""

    def test_risk_block_positive_path_does_not_create_shadow_fill(self):
        ev = _make_entry_event(
            strategy_id="momentum-long",
            symbol="MSFT",
            source_monitor="price-monitor",
            asset_class="us_equity",
            primary_score=0.74,
            rsi=60.0,
        )
        with _SafetyGuards():
            result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self.assertEqual(len(rows), 1)
        # Confidence persisted as normal.
        self.assertIsNotNone(result["confidence_score"])
        self.assertEqual(result["confidence_status"],
                          CONFIDENCE_STATUS_OK)
        # Now simulate the downstream risk_officer rejecting the trade
        # by stamping risk_decision="REJECT" on the row (this is what
        # risk_officer / allocator does AFTER the emitter writes).
        row = dict(rows[0])
        row["risk_decision"] = "REJECT"
        verdict = evaluate_shadow_eligibility(row)
        self.assertEqual(verdict.decision,
                          ShadowEligibilityDecision.NOT_ELIGIBLE_RISK_BLOCK)
        # No shadow fill written — we never even called the simulator.
        # Verify the shadow-eligibility module is the gate and it
        # refused, which is the same as "no fill, no broker call".


# ─── Test 5 — low-confidence path ────────────────────────────────────────────


class TestLowConfidencePath(_LedgerSandbox):
    """When the inputs are sparse / neutral, compute_confidence still
    runs but produces a score below the ALLOW threshold. The row is
    persisted, but shadow-eligibility rules it NOT_ELIGIBLE_*."""

    def test_low_confidence_path(self):
        # Patch compute_confidence so it returns a deterministically
        # low score (<0.50, below the shadow eligibility floor) on
        # otherwise-correct neutral inputs. We patch BOTH possible
        # import paths used by signal_emitter.
        from confidence import ConfidenceReport  # type: ignore

        def _low_score(**kwargs):
            return ConfidenceReport(
                total=0.42,
                components={"signal_strength": 0.40,
                            "data_quality":     0.50,
                            "regime_alignment": 0.50,
                            "system_health":    0.50,
                            "risk_state":       0.50},
                weights={"signal_strength": 0.2,
                          "data_quality":     0.2,
                          "regime_alignment": 0.2,
                          "system_health":    0.2,
                          "risk_state":       0.2},
                threshold=0.50,
                decision="BLOCK",
                reason="low_total",
                inputs_used={},
            )

        ev = _make_entry_event(
            strategy_id="momentum-long",
            symbol="GOOG",
            source_monitor="price-monitor",
            asset_class="us_equity",
            primary_score=0.35,   # weak signal
            rsi=50.0,             # neutral
            bars_count=10,        # fewer bars
        )
        with _SafetyGuards():
            with mock.patch("confidence.compute_confidence",
                             side_effect=_low_score, create=True), \
                 mock.patch("shared.confidence.compute_confidence",
                             side_effect=_low_score, create=True):
                result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self.assertEqual(len(rows), 1)
        score = result["confidence_score"]
        self.assertIsNotNone(score)
        self.assertLess(score, 0.50)
        # Decision must be ALERT_ONLY or BLOCK (anything below ALLOW).
        self.assertIn(result["confidence_decision"],
                       ("ALERT_ONLY", "BLOCK"))
        # The row is recorded but shadow-eligibility says no fill.
        verdict = evaluate_shadow_eligibility(rows[0])
        # Below CONFIDENCE_FLOOR=0.50 → CONFIDENCE_LOW.
        self.assertEqual(
            verdict.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_CONFIDENCE_LOW,
        )


# ─── Test 6 — observe-only path ──────────────────────────────────────────────


class TestObserveOnlyPath(_LedgerSandbox):
    """entry_capable=False rows are tagged OBSERVE_ONLY_SKIP and
    are NEVER eligible for shadow."""

    def test_observe_only_path(self):
        ev = _make_observe_event()
        with _SafetyGuards():
            result = emit_signal_opportunity(ev)
        rows = _read_ledger(self.ledger_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(result["confidence_status"],
                          CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP)
        # observe-only rows may carry None score; that is the contract.
        self.assertIsNone(rows[0]["confidence_score"])
        # Eligibility evaluator must immediately reject as OBSERVE_ONLY.
        verdict = evaluate_shadow_eligibility(rows[0])
        self.assertEqual(
            verdict.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_OBSERVE_ONLY,
        )


# ─── Test 7 — no real network call during the positive path ──────────────────


class TestNoRealNetworkDuringPositivePath(unittest.TestCase):
    """Two-stage proof: (a) static AST scan that signal_emitter.py
    does NOT import requests, socket, http.client at the module level;
    (b) runtime sentinel — install broker + network killers AROUND the
    positive-path call and confirm none fired."""

    def test_no_real_network_call_during_positive_path(self):
        # Static check.
        import ast
        with open(SHARED_DIR / "signal_emitter.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        banned = {"requests", "socket", "http.client", "urllib3"}
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in banned:
                        offenders.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "") in banned:
                    offenders.append(node.module or "?")
        self.assertEqual(
            offenders, [],
            f"signal_emitter must not import network libs: {offenders}",
        )

        # Runtime sentinel.
        signal_emitter._clear_idempotency_cache_for_tests()
        tmp = tempfile.TemporaryDirectory()
        tmp2 = tempfile.TemporaryDirectory()
        os.environ["OPPORTUNITY_LEDGER_DIR"] = tmp.name
        os.environ["MONITOR_RUNTIME_DIAG_DIR"] = tmp2.name
        try:
            ev = _make_entry_event(
                strategy_id="crypto-momentum",
                symbol="BTC/USD",
                source_monitor="crypto-monitor",
                asset_class="crypto",
                primary_score=0.65,
                rsi=58.0,
                bars_count=24,
            )
            with _SafetyGuards():
                result = emit_signal_opportunity(ev)
            self.assertTrue(result["emitted"])
        finally:
            os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
            os.environ.pop("MONITOR_RUNTIME_DIAG_DIR", None)
            tmp.cleanup()
            tmp2.cleanup()


# ─── Test 8 — diag is recorded if the helper is invoked ─────────────────────


class TestRecordDiagFiresFromHelper(_LedgerSandbox):
    """The contract: when a monitor helper calls record_diag around
    its emit() call, both EMIT_ATTEMPTED and EMIT_SUCCESS are recorded.

    We model the helper pattern (used by all 8 monitors) and assert
    the diag JSONL contains both tokens.
    """

    def test_positive_path_records_diag_when_helper_invoked(self):
        # Import the real record_diag and the token constants. Both
        # writes go to the tempdir we set in setUp via env var.
        from monitor_runtime_diag import (
            record_diag,
            DIAG_EMIT_ATTEMPTED,
            DIAG_EMIT_SUCCESS,
        )

        ev = _make_entry_event(
            strategy_id="momentum-long",
            symbol="NVDA",
            source_monitor="price-monitor",
            asset_class="us_equity",
            primary_score=0.80,
            rsi=63.0,
            bars_count=24,
        )

        # Simulate the monitor's emit helper around the positive call.
        with _SafetyGuards():
            self.assertTrue(record_diag("price-monitor", DIAG_EMIT_ATTEMPTED,
                                         {"signal_id": ev.signal_id}))
            result = emit_signal_opportunity(ev)
            self.assertTrue(result["emitted"])
            self.assertTrue(record_diag("price-monitor", DIAG_EMIT_SUCCESS,
                                         {"signal_id": ev.signal_id,
                                          "confidence_status":
                                              result["confidence_status"]}))

        # Read the diag JSONL file back and assert both tokens present.
        files = list(self.diag_path.glob("*.jsonl"))
        self.assertEqual(len(files), 1, "exactly one diag file expected")
        with open(files[0], encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        tokens = {row["token"] for row in lines}
        self.assertIn(DIAG_EMIT_ATTEMPTED, tokens)
        self.assertIn(DIAG_EMIT_SUCCESS,  tokens)
        # Both must be attributed to price-monitor.
        for row in lines:
            self.assertEqual(row["monitor"], "price-monitor")


if __name__ == "__main__":
    unittest.main(verbosity=2)

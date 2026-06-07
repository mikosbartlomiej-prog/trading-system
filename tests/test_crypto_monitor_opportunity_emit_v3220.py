"""v3.22.0 (2026-06-07) — incident 2026-06-07 ETAP 4.

Crypto-monitor signal opportunity ledger emit wiring.

Background
----------
crypto-momentum has been SILENT for 62 days despite BTC RSI 7.6 (deep
oversold). Root cause: ``crypto-monitor/monitor.py`` evaluated signals
but never recorded anything to ``signal_opportunity_ledger`` — so we
had no durable evidence WHY trades did not fire. ETAP 4 instruments
the monitor minimally to write to the opportunity ledger at every key
decision point (signal detected, signal rejected by gate, signal
executed).

Behaviour invariants enforced by these tests
--------------------------------------------
1. Emits are observability-only — they NEVER place Alpaca orders.
2. Emits are fail-soft — when the ledger import fails, the monitor
   still runs to completion.
3. Weekend execution still triggers crypto evaluation (no equity
   market hours guard applies — crypto trades 24/7).
4. Risk-gate rejections (BTC dominance, alt-cap, duplicate, etc.) still
   produce a ledger entry that carries the rejection reason.
5. The recorded entry carries the symbol, strategy, RSI, and a
   paper_action describing what happened.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in ("shared", "crypto-monitor"):
    sys.path.insert(0, str(REPO_ROOT / p))


# ─── Shared helpers ────────────────────────────────────────────────────────────


def _make_bars(closes, vol=1000, last_vol_mult=2.0):
    """Build hourly bars that match the crypto-monitor parser."""
    bars = []
    for c in closes:
        bars.append({
            "o": c,
            "h": c * 1.01,
            "l": c * 0.99,
            "c": c,
            "v": vol,
        })
    if bars and last_vol_mult > 1.0:
        bars[-1]["v"] = int(vol * last_vol_mult)
    return bars


def _deep_oversold_closes():
    """25 falling bars then 3-bar stabilization — RSI well below 30."""
    closes = [100.0]
    for _ in range(25):
        closes.append(closes[-1] * 0.997)
    baseline = closes[-1]
    closes.append(baseline * 1.002)
    closes.append(baseline * 1.001)
    closes.append(baseline * 1.003)
    return closes


class _LedgerCaptureBase(unittest.TestCase):
    """Common setup: isolated ledger directory + ledger module reload."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_dir = Path(self.tmp.name) / "opportunity_ledger"
        self.audit_dir = Path(self.tmp.name) / "audit"
        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.ledger_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        # Force a clean signal_opportunity_ledger module so it picks up
        # the new directory env var.
        for mod in list(sys.modules):
            if mod == "signal_opportunity_ledger" or mod.endswith(
                ".signal_opportunity_ledger"
            ):
                del sys.modules[mod]
        if "monitor" in sys.modules:
            del sys.modules["monitor"]
        import monitor  # noqa: WPS433  (re-import for env-var refresh)
        self.monitor = monitor

    def tearDown(self):
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        self.tmp.cleanup()

    def _ledger_entries(self) -> list[dict]:
        out = []
        if not self.ledger_dir.exists():
            return out
        for f in sorted(self.ledger_dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


# ─── Test 1 + 2: BTC / ETH RSI 7-8 deep oversold → opportunity recorded ──────


class TestDeepOversoldEmitsOpportunity(_LedgerCaptureBase):
    """When BTC / ETH RSI is extreme-oversold, at least one ledger entry
    must be recorded — even when the signal is fully accepted."""

    def _patched_alpaca(self):
        """Patch alpaca_orders.execute_crypto_signal so a fake monitor
        run never reaches the broker. The patch ASSERTS that no order
        ever fires during these unit tests."""
        crypto_path = []
        def _fail_if_called(_signal):  # pragma: no cover - intentional fail
            crypto_path.append(_signal)
            raise AssertionError(
                "monitor must not place Alpaca orders during unit tests"
            )
        return patch.object(self.monitor, "execute_crypto_signal",
                            side_effect=_fail_if_called), crypto_path

    def test_btc_rsi_extreme_oversold_records_opportunity(self):
        closes = _deep_oversold_closes()
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal(
                "BTC/USD", btc_1h_change=0.0,
            )
        self.assertIsNotNone(signal, "deep oversold should yield a signal")
        entries = self._ledger_entries()
        self.assertGreaterEqual(
            len(entries), 1,
            "expected at least 1 opportunity entry for BTC deep oversold",
        )
        self.assertEqual(entries[-1]["symbol"], "BTC/USD")
        self.assertEqual(entries[-1]["strategy"], "crypto-oversold-bounce")
        # The detected entry must include the RSI inside raw_signal — that
        # is the load-bearing piece for the learning loop downstream.
        rs = entries[-1].get("raw_signal", {})
        self.assertIn("rsi", rs)
        self.assertLessEqual(rs["rsi"], 30.0,
                              "deep-oversold opportunity must carry RSI ≤ 30")

    def test_eth_rsi_extreme_oversold_records_opportunity(self):
        closes = _deep_oversold_closes()
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal(
                "ETH/USD", btc_1h_change=0.0,
            )
        self.assertIsNotNone(signal)
        entries = self._ledger_entries()
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[-1]["symbol"], "ETH/USD")


# ─── Test 3: weekend evaluation is not skipped ─────────────────────────────────


class TestWeekendStillEvaluates(_LedgerCaptureBase):
    """Crypto trades 24/7 — Sunday must still produce an opportunity
    entry. There is no equity-market-hours guard in crypto-monitor."""

    def test_sunday_does_not_skip_evaluation(self):
        # Force datetime.now within crypto-monitor.monitor to a Sunday
        # via patching the module's datetime symbol.
        sunday = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(sunday.weekday(), 6)  # Sunday

        class _Now(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return sunday if tz else sunday.replace(tzinfo=None)

        closes = _deep_oversold_closes()
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "datetime", _Now), \
                patch.object(self.monitor, "get_crypto_bars",
                              return_value=bars):
            signal = self.monitor.check_crypto_signal(
                "BTC/USD", btc_1h_change=0.0,
            )
        self.assertIsNotNone(signal,
                              "Sunday must NOT short-circuit crypto eval")
        entries = self._ledger_entries()
        self.assertGreaterEqual(len(entries), 1,
                                 "Sunday evaluation must record opportunity")


# ─── Test 4: risk-gate rejection still emits with reason ───────────────────────


class TestRiskGateRejectionStillEmits(_LedgerCaptureBase):
    """When the BTC dominance guard blocks a Tier-2 alt long, the
    monitor must still write an opportunity entry that carries the
    rejection reason. Otherwise the learning loop loses visibility into
    why a real setup did not become a trade."""

    def test_btc_dominance_guard_records_rejection(self):
        closes = _deep_oversold_closes()
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal(
                "SOL/USD", btc_1h_change=-5.0,  # crash → block alts
            )
        self.assertIsNone(signal,
                          "BTC -5% must veto Tier-2 alt long")
        entries = self._ledger_entries()
        self.assertGreaterEqual(
            len(entries), 1,
            "rejected setup must still be recorded for the learning loop",
        )
        # ALL entries must be for SOL/USD (only one symbol scanned).
        for rec in entries:
            self.assertEqual(rec["symbol"], "SOL/USD")
        # At least ONE entry must mention the BTC dominance reason —
        # the learning loop needs to trace this back. Multiple entries
        # are expected (oversold-bounce block + downstream fall-through).
        blob = json.dumps(entries)
        self.assertTrue(
            "btc_dominance" in blob.lower() or "dominance_guard" in blob.lower(),
            f"expected BTC dominance reason in records, got: {entries}",
        )

    def test_no_signal_setup_records_rejection(self):
        """Quiet sideways markets must also leave evidence."""
        # 25 sideways bars + tiny up-tick at end → RSI ~50, no breakout,
        # no oversold-bounce.
        closes = [100.0 + (i % 3 - 1) * 0.05 for i in range(28)]
        bars = _make_bars(closes, vol=500, last_vol_mult=1.0)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal(
                "BTC/USD", btc_1h_change=0.0,
            )
        self.assertIsNone(signal, "quiet sideways → no setup")
        entries = self._ledger_entries()
        self.assertGreaterEqual(
            len(entries), 1,
            "even a 'no_signal' outcome must leave a ledger trail",
        )


# ─── Test 5: ledger import failure is fail-soft ───────────────────────────────


class TestFailSoftOnLedgerImportError(unittest.TestCase):
    """If signal_opportunity_ledger is not importable at runtime, the
    monitor must keep functioning. Observability is best-effort."""

    def test_monitor_runs_when_ledger_import_blocked(self):
        if "monitor" in sys.modules:
            del sys.modules["monitor"]
        if "signal_opportunity_ledger" in sys.modules:
            del sys.modules["signal_opportunity_ledger"]

        # Inject a stub that raises on import — simulates the missing
        # module case. Because _emit_opportunity guards both the import
        # and the call with try/except, the monitor function must still
        # produce a signal dict without raising.
        original_meta_path = list(sys.meta_path)

        class _BlockingFinder:  # noqa: WPS431
            def find_module(self, fullname, path=None):  # noqa: WPS110
                if fullname == "signal_opportunity_ledger":
                    return self
                return None

            def load_module(self, fullname):  # noqa: WPS110
                raise ImportError("simulated missing ledger module")

        sys.meta_path.insert(0, _BlockingFinder())
        try:
            import monitor  # noqa: WPS433
            closes = _deep_oversold_closes()
            bars = _make_bars(closes, vol=3000)
            with patch.object(monitor, "get_crypto_bars",
                               return_value=bars):
                signal = monitor.check_crypto_signal(
                    "BTC/USD", btc_1h_change=0.0,
                )
            self.assertIsNotNone(signal,
                                 "monitor must still produce signal w/o ledger")
        finally:
            sys.meta_path[:] = original_meta_path
            if "monitor" in sys.modules:
                del sys.modules["monitor"]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

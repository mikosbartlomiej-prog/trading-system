"""v3.24 (2026-06-15) — emit_signal_opportunity MUST persist confidence.

After v3.24 every entry-capable row written to the opportunity ledger
carries either:

  * a real numeric ``confidence_score`` + non-empty
    ``confidence_components`` + ``confidence_decision``, OR
  * ``confidence_status="ERROR"`` + explicit ``confidence_error`` +
    ``blocking_reason="CONFIDENCE_COMPUTE_FAILED"``.

Observe-only rows (entry_capable=False) are tagged
``confidence_status="OBSERVE_ONLY_SKIP"`` and ``confidence_score`` may
remain null.

A silent null on an entry-capable row is a contract violation.

HARD SAFETY
-----------
Tests never call the broker or hit the network.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import signal_emitter            # type: ignore  # noqa: E402
from signal_emitter import (      # type: ignore  # noqa: E402
    CONFIDENCE_STATUS_ERROR,
    CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP,
    CONFIDENCE_STATUS_OK,
    emit_signal_opportunity,
)
from signal_event import SignalEvent    # type: ignore  # noqa: E402


def _make_entry_event(*, raw_signal: dict | None = None,
                       risk_inputs: dict | None = None,
                       market_regime: dict | None = None,
                       symbol: str = "BTC/USD",
                       strategy_id: str = "crypto-momentum") -> SignalEvent:
    return SignalEvent(
        signal_id=f"test:{symbol}:{strategy_id}",
        strategy_id=strategy_id,
        symbol=symbol,
        asset_class="crypto",
        side="long",
        action="BUY",
        timestamp_iso="2026-06-15T10:00:00+00:00",
        source_monitor="crypto-monitor",
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=True,
        raw_signal=raw_signal or {
            "primary_score": 0.7,
            "rsi": 62.0,
            "bars_count": 24,
        },
        risk_inputs=risk_inputs or {"strategy": strategy_id},
        market_regime=market_regime or {"regime": "NEUTRAL"},
    )


def _make_observe_event(*, symbol: str = "ETH/USD") -> SignalEvent:
    return SignalEvent(
        signal_id=f"test:obs:{symbol}",
        strategy_id="crypto-momentum",
        symbol=symbol,
        asset_class="crypto",
        side="n/a",
        action="DETECTED",
        timestamp_iso="2026-06-15T10:00:00+00:00",
        source_monitor="crypto-monitor",
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=False,
        raw_signal={"rsi": 45.0},
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


class _LedgerSandbox(unittest.TestCase):
    def setUp(self):
        signal_emitter._clear_idempotency_cache_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["OPPORTUNITY_LEDGER_DIR"] = self.tmp.name
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        self.tmp.cleanup()


# ─── entry-capable persistence contract ──────────────────────────────────────


class TestEntryCapablePersistence(_LedgerSandbox):
    def test_entry_capable_persists_score(self):
        ev = _make_entry_event()
        result = emit_signal_opportunity(ev)
        self.assertEqual(result["status"], "EMITTED")
        self.assertIsNotNone(result["confidence_score"])
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["confidence_score"])

    def test_entry_capable_persists_components(self):
        ev = _make_entry_event()
        emit_signal_opportunity(ev)
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0]["confidence_components"], dict)
        self.assertGreater(len(rows[0]["confidence_components"]), 0)

    def test_entry_capable_persists_decision(self):
        ev = _make_entry_event()
        result = emit_signal_opportunity(ev)
        self.assertIn(result.get("confidence_decision"),
                       ("ALLOW", "ALERT_ONLY", "BLOCK"))
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["raw_signal"].get("confidence_decision"),
                       ("ALLOW", "ALERT_ONLY", "BLOCK"))

    def test_entry_capable_persists_default_reasons(self):
        # Provide MINIMAL inputs so the builder attaches default_reasons
        ev = SignalEvent(
            signal_id="test:min:BTC/USD",
            strategy_id="crypto-momentum",
            symbol="BTC/USD",
            asset_class="crypto",
            side="long",
            action="BUY",
            timestamp_iso="2026-06-15T10:00:00+00:00",
            source_monitor="crypto-monitor",
            pipeline="monitor",
            evidence_source="PAPER",
            entry_capable=True,
            raw_signal={},   # empty → many defaults
            risk_inputs={"strategy": "crypto-momentum"},
        )
        result = emit_signal_opportunity(ev)
        # default_reasons must be a dict (possibly empty for fully-real
        # callers, but here MUST be non-empty since raw_signal is bare).
        self.assertIsInstance(result.get("confidence_default_reasons"), dict)
        self.assertGreater(len(result["confidence_default_reasons"]), 0)
        rows = _read_ledger(self.tmp_path)
        self.assertIsInstance(
            rows[0]["raw_signal"].get("confidence_default_reasons"), dict
        )
        self.assertGreater(
            len(rows[0]["raw_signal"]["confidence_default_reasons"]), 0,
        )

    def test_entry_capable_persists_builder_version(self):
        ev = _make_entry_event()
        result = emit_signal_opportunity(ev)
        self.assertTrue(result.get("confidence_builder_version"))
        rows = _read_ledger(self.tmp_path)
        self.assertTrue(
            rows[0]["raw_signal"].get("confidence_builder_version")
        )

    def test_entry_capable_persists_completeness(self):
        ev = _make_entry_event()
        result = emit_signal_opportunity(ev)
        comp = result.get("confidence_input_completeness")
        self.assertIsNotNone(comp)
        self.assertGreaterEqual(comp, 0.0)
        self.assertLessEqual(comp, 1.0)


# ─── ERROR persistence ───────────────────────────────────────────────────────


class TestErrorPersistence(_LedgerSandbox):
    def test_compute_confidence_failure_produces_explicit_error_row(self):
        ev = _make_entry_event()

        def _boom(**_kw):
            raise RuntimeError("simulated compute_confidence crash")

        # Patch BOTH possible import paths used by signal_emitter.
        with mock.patch("confidence.compute_confidence", side_effect=_boom,
                         create=True):
            with mock.patch("shared.confidence.compute_confidence",
                             side_effect=_boom, create=True):
                result = emit_signal_opportunity(ev)
        self.assertEqual(result["confidence_status"],
                          CONFIDENCE_STATUS_ERROR)
        self.assertTrue(result.get("confidence_error"))
        self.assertEqual(result.get("blocking_reason"),
                          "CONFIDENCE_COMPUTE_FAILED")
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["confidence_score"])
        self.assertEqual(rows[0]["raw_signal"]["confidence_status"],
                          CONFIDENCE_STATUS_ERROR)
        self.assertEqual(rows[0]["raw_signal"]["blocking_reason"],
                          "CONFIDENCE_COMPUTE_FAILED")


# ─── observe-only ────────────────────────────────────────────────────────────


class TestObserveOnly(_LedgerSandbox):
    def test_observe_only_row_marked_OBSERVE_ONLY_SKIP(self):
        ev = _make_observe_event()
        result = emit_signal_opportunity(ev)
        self.assertEqual(result["confidence_status"],
                          CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP)
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 1)
        # observe-only score may be null; that is OK.
        self.assertIsNone(rows[0]["confidence_score"])
        self.assertEqual(
            rows[0]["raw_signal"]["confidence_status"],
            CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP,
        )


# ─── invariants ──────────────────────────────────────────────────────────────


class TestInvariants(_LedgerSandbox):
    def test_no_silent_null_confidence_for_entry_capable(self):
        # Drive 5 distinct entry-capable events through the emitter and
        # assert every row has either a numeric score or ERROR status.
        for i in range(5):
            ev = _make_entry_event(symbol=f"COIN{i}/USD")
            emit_signal_opportunity(ev)
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 5)
        for r in rows:
            status = r["raw_signal"].get("confidence_status")
            score = r.get("confidence_score")
            entry = r["raw_signal"].get("entry_capable")
            if entry:
                if status == CONFIDENCE_STATUS_OK:
                    self.assertIsNotNone(score)
                    self.assertGreater(
                        len(r["confidence_components"] or {}), 0
                    )
                else:
                    # Only acceptable non-OK statuses are ERROR.
                    self.assertEqual(status, CONFIDENCE_STATUS_ERROR)

    def test_no_broker_call_during_persist(self):
        # The emitter MUST NOT import any broker module.
        # Strong assertion: requests.post is never invoked.
        with mock.patch("requests.post") as m_post:
            ev = _make_entry_event()
            emit_signal_opportunity(ev)
            self.assertFalse(m_post.called)

    def test_score_null_only_when_status_ERROR_or_OBSERVE_ONLY_SKIP(self):
        # Mix of cases.
        emit_signal_opportunity(_make_entry_event(symbol="A/USD"))
        emit_signal_opportunity(_make_observe_event(symbol="B/USD"))
        rows = _read_ledger(self.tmp_path)
        self.assertEqual(len(rows), 2)
        for r in rows:
            status = r["raw_signal"].get("confidence_status")
            score = r["confidence_score"]
            if score is None:
                self.assertIn(
                    status,
                    (CONFIDENCE_STATUS_ERROR,
                     CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP),
                )
            else:
                self.assertEqual(status, CONFIDENCE_STATUS_OK)


if __name__ == "__main__":
    unittest.main(verbosity=2)

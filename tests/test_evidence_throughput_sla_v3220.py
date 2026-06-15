"""v3.22 ETAP 11 (2026-06-15) — evidence throughput SLA tests.

Validates ``scripts.check_evidence_throughput_sla.evaluate``:

  - 0 signals + 0 opportunities in 1 cycle  → WARN (exit 1)
  - 0 in 2 cycles                            → FINDING_P1 (exit 2)
  - 0 in 3 cycles                            → FINDING_P0 (exit 3)
  - A single non-zero observation resets the consecutive-zero counter

The test fixtures synthesise the workflow_health_history.jsonl with the
production schema (counters_snapshot) AND with the simpler explicit
{signals, opportunities} schema accepted by the SLA computation.

No network. No imports of alpaca_orders.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for d in (SHARED_DIR, SCRIPTS_DIR, REPO_ROOT):
    if d not in sys.path:
        sys.path.insert(0, d)


def _reload():
    for n in ("check_evidence_throughput_sla",):
        sys.modules.pop(n, None)
    return importlib.import_module("check_evidence_throughput_sla")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        for r in rows:
            fp.write(json.dumps(r) + "\n")


def _empty_cycle(ts: str = "2026-06-15T13:00:00Z") -> dict:
    return {
        "appended_at_iso":   ts,
        "collector_status":  "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA",
        "counters_snapshot": {
            "completed_shadow_outcomes_count":    0,
            "halt_path_records_count":            6,   # halt records do NOT count as opportunities
            "real_market_opportunities_count":    0,
            "scaffold_no_market_data_records_count": 5,
        },
        "verdict": "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
        "workflow_conclusion": "success",
    }


def _busy_cycle(ts: str = "2026-06-15T14:00:00Z") -> dict:
    """Cycle with explicit non-zero signals+opportunities."""
    return {
        "appended_at_iso":   ts,
        "collector_status":  "OK",
        "counters_snapshot": {
            "completed_shadow_outcomes_count":    2,
            "real_market_opportunities_count":    3,
            "normal_non_halt_opportunities_count": 0,
        },
        "verdict": "AUTOMATED_PIPELINE_PRODUCING_OPPORTUNITIES",
        "workflow_conclusion": "success",
    }


class _BaseSLATest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._evidence_path = self._tmp_path / "evidence_counters_latest.json"
        self._history_path  = self._tmp_path / "workflow_health_history.jsonl"
        self._evidence_path.write_text(json.dumps({
            "completed_shadow_outcomes_count":    0,
            "real_market_opportunities_count":    0,
            "normal_non_halt_opportunities_count": 0,
            "version": "test",
        }), encoding="utf-8")
        self.chk = _reload()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _eval(self):
        return self.chk.evaluate(
            evidence_path=self._evidence_path,
            history_path=self._history_path,
        )


class TestThroughputSLA(_BaseSLATest):

    def test_zero_for_one_cycle_warn(self) -> None:
        _write_jsonl(self._history_path, [_empty_cycle()])
        r = self._eval()
        self.assertEqual(r["consecutive_zero_cycles"], 1)
        self.assertEqual(r["verdict"], "WARN")
        self.assertEqual(r["exit_code"], 1)

    def test_zero_for_two_cycles_p1(self) -> None:
        _write_jsonl(self._history_path,
                     [_empty_cycle("2026-06-15T13:00:00Z"),
                      _empty_cycle("2026-06-15T14:00:00Z")])
        r = self._eval()
        self.assertEqual(r["consecutive_zero_cycles"], 2)
        self.assertEqual(r["verdict"], "FINDING_P1")
        self.assertEqual(r["exit_code"], 2)

    def test_zero_for_three_cycles_p0(self) -> None:
        _write_jsonl(self._history_path,
                     [_empty_cycle("2026-06-15T13:00:00Z"),
                      _empty_cycle("2026-06-15T14:00:00Z"),
                      _empty_cycle("2026-06-15T15:00:00Z")])
        r = self._eval()
        self.assertEqual(r["consecutive_zero_cycles"], 3)
        self.assertEqual(r["verdict"], "FINDING_P0")
        self.assertEqual(r["exit_code"], 3)

    def test_zero_for_four_cycles_remains_p0(self) -> None:
        _write_jsonl(self._history_path,
                     [_empty_cycle(f"2026-06-15T1{n}:00:00Z") for n in range(4)])
        r = self._eval()
        self.assertGreaterEqual(r["consecutive_zero_cycles"], 4)
        self.assertEqual(r["verdict"], "FINDING_P0")
        self.assertEqual(r["exit_code"], 3)

    def test_non_zero_resets_counter(self) -> None:
        # Two empty cycles, then a busy one → reset to 0.
        _write_jsonl(self._history_path, [
            _empty_cycle("2026-06-15T13:00:00Z"),
            _empty_cycle("2026-06-15T14:00:00Z"),
            _busy_cycle("2026-06-15T15:00:00Z"),
        ])
        r = self._eval()
        self.assertEqual(r["consecutive_zero_cycles"], 0)
        self.assertEqual(r["verdict"], "OK")
        self.assertEqual(r["exit_code"], 0)

    def test_explicit_signals_opportunities_keys(self) -> None:
        # Tests honour the simpler {signals, opportunities} shape if used.
        rows = [
            {"appended_at_iso": "t1", "signals": 0, "opportunities": 0},
            {"appended_at_iso": "t2", "signals": 1, "opportunities": 0},
        ]
        _write_jsonl(self._history_path, rows)
        r = self._eval()
        self.assertEqual(r["consecutive_zero_cycles"], 0)
        self.assertEqual(r["verdict"], "OK")

    def test_no_network_required(self) -> None:
        # Spec: script must work without network. We block socket.connect
        # for the duration of evaluate() and confirm it still returns.
        original_connect = socket.socket.connect
        attempted = []

        def _no_net(self, *a, **kw):
            attempted.append(a)
            raise OSError("network blocked in test")

        socket.socket.connect = _no_net  # type: ignore
        try:
            _write_jsonl(self._history_path, [_empty_cycle()])
            r = self._eval()
        finally:
            socket.socket.connect = original_connect  # type: ignore
        self.assertEqual(r["exit_code"], 1)
        self.assertEqual(attempted, [],
                          "evaluate() must not attempt any socket connect")


if __name__ == "__main__":
    unittest.main()

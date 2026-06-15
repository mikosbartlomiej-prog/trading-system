"""v3.26 (2026-06-15) — ETAP 9 — Confidence pre-calibration reporter.

Synthetic-ledger tests for
``scripts/build_confidence_precalibration_readiness.py``.

Verifies:
  - Empty ledger → NOT_READY_NO_POSITIVE_ROWS verdict.
  - Sparse positive rows → NEEDS_MORE_ENTRY_CANDIDATES.
  - Enough rows but flat components → NEEDS_COMPONENT_VARIANCE.
  - Enough rows + varying components → READY_FOR_SHADOW_OUTCOMES.
  - Score / completeness / per-component / decision_counts shapes.
  - HARD SAFETY: reporter imports no broker / no network module.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER makes network calls (no socket / requests usage in the
  reporter or tests).
- Uses tempdir + monkey-patched ledger dir for any actual I/O; the
  production ledger is never touched.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_confidence_precalibration_readiness as bpr  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _write_rows(base_dir: Path, date_str: str,
                rows: list[dict]) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{date_str}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _make_positive_row(*, score: float,
                        components: dict[str, float],
                        decision: str = "ALERT_ONLY",
                        completeness: float = 0.8) -> dict:
    return {
        "schema_version":         "v3.20.0",
        "signal_id":              "synthetic:test:1",
        "strategy":               "momentum-long",
        "symbol":                 "AAPL",
        "timestamp":              "2026-06-15T13:30:00Z",
        "confidence_score":       score,
        "confidence_components":  components,
        "confidence_decision":    decision,
        "builder_completeness":   completeness,
        "risk_decision":          "ALLOW",
    }


def _make_null_row() -> dict:
    return {
        "schema_version":     "v3.20.0",
        "signal_id":          "synthetic:test:null:1",
        "strategy":           "momentum-long",
        "symbol":             "AAPL",
        "timestamp":          "2026-06-15T13:30:00Z",
        "confidence_score":   None,
        "confidence_components": {},
    }


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestEmptyLedger(unittest.TestCase):
    def test_no_files_yields_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty_ledger"
            empty.mkdir()
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(as_of=as_of, days=7, base_dir=empty)

        self.assertEqual(rep["verdict"],
                          bpr.VERDICT_NOT_READY)
        self.assertEqual(rep["positive_rows"], 0)
        self.assertEqual(rep["rows_total"], 0)
        self.assertEqual(rep["components"]["varying_components"], 0)
        self.assertEqual(rep["decision_counts"], {})
        self.assertFalse(rep["safety"]["imports_alpaca_orders"])
        self.assertFalse(rep["safety"]["makes_network_calls"])

    def test_null_only_ledger_yields_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            _write_rows(base, "2026-06-15",
                         [_make_null_row() for _ in range(5)])
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(as_of=as_of, days=7, base_dir=base)

        self.assertEqual(rep["verdict"],
                          bpr.VERDICT_NOT_READY)
        self.assertEqual(rep["positive_rows"], 0)
        self.assertGreater(rep["rows_total"], 0)


class TestSparsePositive(unittest.TestCase):
    def test_few_rows_yields_needs_more_candidates(self) -> None:
        """5 positive rows < default min_positive_rows (30)."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            rows = [
                _make_positive_row(
                    score=0.55 + 0.01 * i,
                    components={
                        "data_quality":      0.5 + 0.01 * i,
                        "signal_strength":   0.6 + 0.01 * i,
                        "regime_alignment":  0.7,
                        "system_health":     0.8,
                    },
                    decision="ALERT_ONLY",
                )
                for i in range(5)
            ]
            _write_rows(base, "2026-06-15", rows)
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(as_of=as_of, days=7, base_dir=base)

        self.assertEqual(rep["verdict"],
                          bpr.VERDICT_NEEDS_CANDIDATES)
        self.assertEqual(rep["positive_rows"], 5)
        # Component coverage view still produced.
        self.assertGreater(
            rep["components"]["total_components_seen"], 0)


class TestFlatComponents(unittest.TestCase):
    def test_many_rows_but_flat_components_yields_needs_variance(
            self) -> None:
        """Enough rows; all components constant → no variance."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            rows = [
                _make_positive_row(
                    # Score varies, but components are constant.
                    score=0.55 + (i % 5) * 0.01,
                    components={
                        "data_quality":      0.5,
                        "signal_strength":   0.5,
                        "regime_alignment":  0.5,
                        "system_health":     0.5,
                    },
                    decision=("ALLOW" if i % 3 == 0
                              else "ALERT_ONLY"),
                )
                for i in range(50)
            ]
            _write_rows(base, "2026-06-15", rows)
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(
                as_of=as_of, days=7, base_dir=base,
                min_positive_rows=30,
                min_varying_components=4,
            )

        self.assertEqual(rep["verdict"],
                          bpr.VERDICT_NEEDS_VARIANCE)
        self.assertEqual(rep["positive_rows"], 50)
        self.assertEqual(
            rep["components"]["varying_components"], 0)
        self.assertEqual(
            rep["components"]["default_only_components"], 4)


class TestReadyForShadow(unittest.TestCase):
    def test_enough_rows_and_variance_yields_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            rows = []
            for i in range(40):
                # All components vary across rows.
                rows.append(_make_positive_row(
                    score=0.45 + (i % 10) * 0.04,
                    components={
                        "data_quality":      0.4 + (i % 5) * 0.05,
                        "signal_strength":   0.3 + (i % 7) * 0.05,
                        "regime_alignment":  0.5 + (i % 3) * 0.10,
                        "system_health":     0.6 + (i % 4) * 0.05,
                        "risk_state":        0.7 + (i % 6) * 0.02,
                    },
                    decision=("ALLOW" if i % 4 == 0
                              else "ALERT_ONLY"),
                ))
            _write_rows(base, "2026-06-15", rows)
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(
                as_of=as_of, days=7, base_dir=base,
                min_positive_rows=30,
                min_varying_components=4,
            )

        self.assertEqual(rep["verdict"], bpr.VERDICT_READY)
        self.assertEqual(rep["positive_rows"], 40)
        self.assertGreaterEqual(
            rep["components"]["varying_components"], 4)
        # Decision counts populated.
        total = sum(rep["decision_counts"].values())
        self.assertEqual(total, 40)
        # Score summary is fully populated.
        self.assertIsNotNone(rep["score_summary"]["median"])
        self.assertIsNotNone(rep["score_summary"]["p95"])


class TestRenderingAndSafety(unittest.TestCase):
    def test_render_md_contains_standing_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            _write_rows(base, "2026-06-15", [_make_null_row()])
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(as_of=as_of, days=7, base_dir=base)

        md = bpr.render_md(rep)
        for marker in bpr.STANDING_MARKERS:
            self.assertIn(marker, md)
        # Safety contract narrative present.
        self.assertIn("NEVER", md)
        self.assertIn("alpaca_orders", md)

    def test_reporter_does_not_import_alpaca_orders(self) -> None:
        # Static scan: source must not IMPORT alpaca_orders.
        # (Documentation mentions of the name are explicitly allowed
        # — the safety contract describes what the module does NOT do.)
        src = (REPO_ROOT / "scripts"
               / "build_confidence_precalibration_readiness.py"
              ).read_text(encoding="utf-8")
        for needle in ("import alpaca_orders",
                       "from alpaca_orders",
                       "import shared.alpaca_orders",
                       "from shared.alpaca_orders",
                       "from shared import alpaca_orders"):
            self.assertNotIn(needle, src,
                              f"forbidden import detected: {needle}")
        # And the loaded module's globals have no such symbol exposed.
        self.assertNotIn("alpaca_orders", dir(bpr))

    def test_reporter_does_not_make_network_calls(self) -> None:
        # Static scan: no requests / urllib / socket / http.client
        # imports / calls in the reporter source.
        src = (REPO_ROOT / "scripts"
               / "build_confidence_precalibration_readiness.py"
              ).read_text(encoding="utf-8")
        for needle in ("import requests",
                       "from requests",
                       "urllib.request",
                       "import socket",
                       "http.client",
                       "from urllib"):
            self.assertNotIn(needle, src,
                              f"network module mentioned: {needle}")


class TestParamsAndShape(unittest.TestCase):
    def test_score_summary_is_safe_on_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            base.mkdir()
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(as_of=as_of, days=7, base_dir=base)

        s = rep["score_summary"]
        for k in ("count", "min", "median", "p95", "max", "mean"):
            self.assertIn(k, s)
        self.assertEqual(s["count"], 0)
        self.assertIsNone(s["median"])

    def test_params_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "ledger"
            _write_rows(base, "2026-06-15", [_make_null_row()])
            as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
            rep = bpr.build_report(
                as_of=as_of, days=7, base_dir=base,
                min_positive_rows=42,
                min_varying_components=5,
                variance_eps=1e-7,
            )

        self.assertEqual(
            rep["params"]["min_positive_rows"], 42)
        self.assertEqual(
            rep["params"]["min_varying_components"], 5)
        self.assertAlmostEqual(
            rep["params"]["variance_epsilon"], 1e-7)


if __name__ == "__main__":
    unittest.main()

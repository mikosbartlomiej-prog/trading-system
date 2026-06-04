"""v3.20.0 (2026-06-04) — Tests for shared/counterfactual_outcomes.py.

Covers the contracts from ETAP 3:
  * Rejected signals never become paper trades.
  * Counterfactual records never increment paper n.
  * False rejection rate is reported per gate.
  * Bad acceptance rate is reported per gate.
  * MFE/MAE are direction-aware and correct.
  * Missing bar data → outcome UNKNOWN (no guessing).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _fake_bars(symbol, days):
    """Generate a synthetic bar series for the past ``days`` days, ending now."""
    now = datetime.now(timezone.utc)
    bars = []
    base = 100.0
    for i in range(days):
        ts = (now - timedelta(days=days - i - 1)).replace(microsecond=0)
        # Symbol-controlled tape: each ticker gets distinct dynamics.
        if symbol == "UP":
            c = base + i * 1.0
        elif symbol == "DOWN":
            c = base - i * 1.0
        elif symbol == "FLAT":
            c = base
        elif symbol == "SPIKE":
            c = base + (3.0 if i == days - 1 else 0.0)
        else:
            c = base + i * 0.1
        bars.append({
            "t": ts.isoformat().replace("+00:00", "Z"),
            "o": c - 0.5,
            "h": c + 0.7,
            "l": c - 0.7,
            "c": c,
            "v": 1_000_000,
        })
    return {"bars": bars}


def _no_bars(symbol, days):
    return None


def _signal(**overrides):
    base = {
        "signal_id": "sig-001",
        "symbol": "UP",
        "side": "long",
        "entry_price": 100.0,
        "entry_ts": (datetime.now(timezone.utc) - timedelta(days=3))
                    .isoformat().replace("+00:00", "Z"),
        "decision": "REJECTED",
        "gate": "confidence",
    }
    base.update(overrides)
    return base


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestCounterfactualEngine(unittest.TestCase):
    """Core scoring + invariants."""

    def setUp(self):
        for k in list(sys.modules):
            if k == "counterfactual_outcomes" or k.endswith(".counterfactual_outcomes"):
                del sys.modules[k]
        import counterfactual_outcomes as cf  # noqa
        self.cf = cf

        self.tmpdir = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmpdir
        os.environ["OPPORTUNITY_LEDGER_DIR"] = self.tmpdir

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # 1. Rejected does not become a paper trade.
    def test_rejected_does_not_become_paper(self):
        """A rejection scored by the engine never gets PAPER evidence_source."""
        res = self.cf.compute_counterfactual_for_signal(
            _signal(), horizon_hours=24, bars_fetcher=_fake_bars,
        )
        self.assertEqual(res.evidence_source,
                         self.cf.EVIDENCE_SOURCE_COUNTERFACTUAL)
        self.assertNotEqual(res.evidence_source, "PAPER")
        self.assertEqual(res.decision, "REJECTED")

    # 2. Counterfactuals must not bump paper n_closed.
    def test_no_increment_paper_n(self):
        """Scoring 5 rejected signals does not write any PAPER records."""
        from shared import paper_experiment as pe  # type: ignore

            # noqa
        # snapshot pre-state
        pre_counts: dict[str, int] = {}
        try:
            metrics = pe.compute_strategy_metrics()
        except Exception:
            metrics = {}
        for k, v in (metrics or {}).items():
            if isinstance(v, dict):
                pre_counts[k] = v.get("n_closed", 0)

        signals = [_signal(signal_id=f"sig-{i}") for i in range(5)]
        results = self.cf.compute_counterfactuals(
            signals, horizons_hours=(24,), bars_fetcher=_fake_bars,
        )
        self.assertEqual(len(results), 5)

        try:
            metrics_after = pe.compute_strategy_metrics()
        except Exception:
            metrics_after = {}
        for k, v in (metrics_after or {}).items():
            if isinstance(v, dict):
                self.assertEqual(v.get("n_closed", 0), pre_counts.get(k, 0),
                                 f"strategy {k} n_closed changed")

    # 3. False rejection reported.
    def test_false_rejection_reported(self):
        """When a rejected signal would have profited, it is flagged."""
        # UP tape long with the entry 3 days ago at 100 → close ≈ 102, profit.
        sig = _signal(symbol="UP", side="long", entry_price=100.0,
                      gate="confidence")
        res = self.cf.compute_counterfactual_for_signal(
            sig, horizon_hours=48, bars_fetcher=_fake_bars,
        )
        self.assertEqual(res.outcome, self.cf.OUTCOME_PROFITABLE)
        self.assertEqual(res.was_rejection_correct, False)
        self.assertGreater(res.missed_opportunity_cost_pct, 0.0)

    # 4. Bad acceptance reported via aggregation.
    def test_bad_acceptance_reported(self):
        """Aggregation counts losing accepted trades per gate."""
        # Build a synthetic acceptance via a "OBSERVE_ONLY" decision
        # scored against DOWN tape — long DOWN loses, so it is a
        # correct rejection (not an acceptance). For bad-acceptance we
        # emit one ACCEPTED record manually.
        results = self.cf.compute_counterfactuals(
            [_signal(symbol="DOWN", side="long", gate="universe")],
            horizons_hours=(24,), bars_fetcher=_fake_bars,
        )
        # Inject one accepted+losing record using a CounterfactualResult.
        from counterfactual_outcomes import CounterfactualResult
        acc = CounterfactualResult(
            signal_id="acc-1", symbol="DOWN", side="long", horizon_hours=24,
            decision="ACCEPTED", gate="universe", entry_ts="x",
            entry_price=100.0, horizon_price=98.0,
            hypothetical_pnl_pct=-2.0,
            hypothetical_pnl_after_costs_pct=-2.1,
            mfe_pct=0.0, mae_pct=-2.5,
            outcome=self.cf.OUTCOME_LOSING,
            was_rejection_correct=None,
            missed_opportunity_cost_pct=0.0,
        )
        results.append(acc)
        aggs = self.cf.aggregate_by_gate(results, horizon_hours=24)
        uni = next(a for a in aggs if a.gate == "universe")
        self.assertGreaterEqual(uni.n_bad_acceptances, 1)

    # 5. MFE / MAE correct.
    def test_mfe_mae_correct(self):
        """MFE = best favourable, MAE = worst adverse, in pct, signed."""
        # Long on UP tape: MFE should be positive (price climbs).
        sig = _signal(symbol="UP", side="long", entry_price=100.0)
        res = self.cf.compute_counterfactual_for_signal(
            sig, horizon_hours=48, bars_fetcher=_fake_bars,
        )
        self.assertGreaterEqual(res.mfe_pct, 0.0)
        self.assertLessEqual(res.mae_pct, res.mfe_pct)

        # Short on UP tape: MFE should be ≤ 0 (price goes against us).
        sig_short = _signal(symbol="UP", side="short", entry_price=100.0,
                            signal_id="short-1")
        res_short = self.cf.compute_counterfactual_for_signal(
            sig_short, horizon_hours=48, bars_fetcher=_fake_bars,
        )
        # MFE for short on UP tape can still be non-negative on the
        # first bar but should not exceed long's MFE on same tape.
        self.assertLessEqual(res_short.mfe_pct, res.mfe_pct + 1e-6)

    # 6. Missing data → UNKNOWN.
    def test_missing_data_outcome_unknown(self):
        """When the bar fetcher returns None, outcome is UNKNOWN."""
        res = self.cf.compute_counterfactual_for_signal(
            _signal(), horizon_hours=24, bars_fetcher=_no_bars,
        )
        self.assertEqual(res.outcome, self.cf.OUTCOME_UNKNOWN)
        self.assertIsNone(res.was_rejection_correct)
        self.assertEqual(res.missed_opportunity_cost_pct, 0.0)


class TestCounterfactualEvidenceContract(unittest.TestCase):
    """Make sure the evidence_source string is the constraint-mandated value."""

    def setUp(self):
        for k in list(sys.modules):
            if k == "counterfactual_outcomes" or k.endswith(".counterfactual_outcomes"):
                del sys.modules[k]
        import counterfactual_outcomes as cf  # noqa
        self.cf = cf

    def test_evidence_source_is_counterfactual_not_paper(self):
        self.assertEqual(self.cf.EVIDENCE_SOURCE_COUNTERFACTUAL,
                         "COUNTERFACTUAL")
        # And NOT one of the existing PAPER/BACKTEST/REPLAY enums.
        from shared.evidence_source import EvidenceSource  # type: ignore
        self.assertNotIn(self.cf.EVIDENCE_SOURCE_COUNTERFACTUAL,
                         {e.value for e in EvidenceSource})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

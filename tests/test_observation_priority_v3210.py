"""v3.21.0 (2026-06-04) — Tests for shared/observation_priority.

Covers the ETAP 8 contracts:
  * undercovered regime → PRIORITY_OBSERVE
  * bad liquidity → priority drops
  * rejected strategy → LOW_PRIORITY or DO_NOT_OBSERVE
  * promising but under-sampled → PRIORITY_OBSERVE
  * scoring is recommendation-only — no trades placed
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from observation_priority import (  # noqa: E402
    STATUS_PRIORITY_OBSERVE,
    STATUS_NORMAL_OBSERVE,
    STATUS_LOW_PRIORITY,
    STATUS_DO_NOT_OBSERVE,
    STATUS_NEEDS_DATA,
    TARGET_PAPER_N,
    compute_priority,
    evaluate_triples,
)


def _tight_quote(price=100.0):
    return {"bid": price - 0.01, "ask": price + 0.01}


def _wide_quote(price=100.0):
    # 1 % spread → high bps relative.
    return {"bid": price * 0.995, "ask": price * 1.005}


class TestUndercoveredRegimePriority(unittest.TestCase):
    """Undercovered regime should produce PRIORITY_OBSERVE."""

    def test_undercovered_regime_priority_observe(self):
        score = compute_priority(
            strategy="momentum-long",
            symbol="AAPL",
            regime="RISK_ON",
            paper_n=2,
            opportunities_per_day=3.0,
            historical_promise=0.8,
            regime_coverage={"RISK_ON": 0.10, "NEUTRAL": 0.9},
            quote=_tight_quote(),
            unknown_rejection_rate=0.4,
            false_rejection_rate=0.4,
            strategy_ranking_score=0.7,
            lower_bound_status="EVIDENCE_IMPROVING",
        )
        self.assertEqual(score.status, STATUS_PRIORITY_OBSERVE)
        self.assertGreater(score.priority_score, 0.6)


class TestBadLiquidityLowersPriority(unittest.TestCase):
    """Wide spreads should pull priority down."""

    def test_bad_liquidity_drops_score(self):
        tight = compute_priority(
            strategy="momentum-long",
            symbol="AAPL",
            regime="NEUTRAL",
            paper_n=10,
            opportunities_per_day=1.0,
            quote=_tight_quote(),
        )
        wide = compute_priority(
            strategy="momentum-long",
            symbol="AAPL",
            regime="NEUTRAL",
            paper_n=10,
            opportunities_per_day=1.0,
            quote=_wide_quote(),
        )
        self.assertLess(wide.priority_score, tight.priority_score)


class TestRejectedStrategy(unittest.TestCase):
    """Rejected strategies must short-circuit to DO_NOT_OBSERVE."""

    def test_rejected_strategy_do_not_observe(self):
        score = compute_priority(
            strategy="bad-strategy",
            symbol="AAPL",
            regime="NEUTRAL",
            paper_n=80,
            opportunities_per_day=4.0,
            lower_bound_status="EVIDENCE_REJECT",
        )
        self.assertEqual(score.status, STATUS_DO_NOT_OBSERVE)


class TestPromisingUnderSampled(unittest.TestCase):
    """Strategies that are improving but undersampled should be bumped."""

    def test_improving_understampled_priority(self):
        score = compute_priority(
            strategy="momentum-long",
            symbol="AAPL",
            regime="NEUTRAL",
            paper_n=5,
            opportunities_per_day=2.5,
            historical_promise=0.7,
            quote=_tight_quote(),
            lower_bound_status="EVIDENCE_IMPROVING",
            false_rejection_rate=0.5,
        )
        self.assertEqual(score.status, STATUS_PRIORITY_OBSERVE)


class TestNoTradeSideEffects(unittest.TestCase):
    """The module must not place a trade even when given live-like inputs."""

    def test_no_alpaca_calls(self):
        # If anyone tried to import requests.post in this path, the
        # patched attribute would record it. We patch a wide net of
        # broker entry points.
        with mock.patch.dict(sys.modules, {}, clear=False):
            with mock.patch("requests.post") as mocked_post, \
                 mock.patch("requests.get") as mocked_get:
                compute_priority(
                    strategy="momentum-long",
                    symbol="AAPL",
                    regime="NEUTRAL",
                    paper_n=10,
                    opportunities_per_day=2.0,
                )
                mocked_post.assert_not_called()
                mocked_get.assert_not_called()


class TestNeedsData(unittest.TestCase):
    def test_no_data_returns_needs_data(self):
        score = compute_priority(
            strategy="brand-new",
            symbol="TSLA",
            regime="RISK_ON",
            paper_n=0,
            opportunities_per_day=0.0,
        )
        self.assertEqual(score.status, STATUS_NEEDS_DATA)


class TestEvaluateTriples(unittest.TestCase):
    def test_evaluate_triples_filters_invalid(self):
        triples = [
            {"strategy": "s1", "symbol": "AAPL", "regime": "NEUTRAL",
             "paper_n": 0, "opportunities_per_day": 0.0,
             "lower_bound_status": "EVIDENCE_REJECT"},
            {"strategy": "s2", "symbol": "MSFT", "regime": "RISK_ON",
             "paper_n": 5, "opportunities_per_day": 2.0,
             "historical_promise": 0.7,
             "lower_bound_status": "EVIDENCE_IMPROVING"},
            {"strategy": "", "symbol": "BAD"},
            "not-a-dict",
        ]
        scores = evaluate_triples(triples, emit_audit=False)
        self.assertEqual(len(scores), 2)
        statuses = {s.strategy: s.status for s in scores}
        self.assertEqual(statuses["s1"], STATUS_DO_NOT_OBSERVE)
        self.assertIn(statuses["s2"],
                      {STATUS_PRIORITY_OBSERVE, STATUS_NORMAL_OBSERVE})


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_score(self):
        kwargs = dict(
            strategy="momentum-long",
            symbol="AAPL",
            regime="NEUTRAL",
            paper_n=10,
            opportunities_per_day=2.0,
            historical_promise=0.7,
            quote=_tight_quote(),
            lower_bound_status="EVIDENCE_IMPROVING",
        )
        a = compute_priority(**kwargs)
        b = compute_priority(**kwargs)
        self.assertEqual(a.priority_score, b.priority_score)
        self.assertEqual(a.status, b.status)


class TestTargetPaperN(unittest.TestCase):
    def test_target_paper_n_is_50(self):
        # Public contract — exported and stable.
        self.assertEqual(TARGET_PAPER_N, 50)


if __name__ == "__main__":
    unittest.main()

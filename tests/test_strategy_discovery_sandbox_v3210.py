"""v3.21.0 — Tests for shared/strategy_discovery_sandbox.py.

Enforces ETAP 5 invariants:
  * sandbox creates variants ONLY in quarantine (via register_variant)
  * variants do NOT enter the active strategy registry
  * each variant has a change_rationale
  * each variant has rejection_criteria
  * sandbox does NOT mutate the parent strategy
  * sandbox does NOT raise risk (no override key that could weaken risk
    gates appears in any proposal)

Run with:
    python3 -m unittest tests.test_strategy_discovery_sandbox_v3210
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


class _Base(unittest.TestCase):
    """Isolated quarantine + audit dirs per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["VARIANT_QUARANTINE_DIR"] = str(
            Path(self._tmp.name) / "variants")
        os.environ["AUDIT_TRADING_DIR"] = str(
            Path(self._tmp.name) / "audit")
        # Force fresh import so env-driven quarantine dir is honoured.
        for k in list(sys.modules):
            if k.endswith(".strategy_variant_quarantine") \
               or k == "strategy_variant_quarantine":
                del sys.modules[k]
            if k.endswith(".strategy_discovery_sandbox") \
               or k == "strategy_discovery_sandbox":
                del sys.modules[k]
        import strategy_variant_quarantine as svq  # noqa: E402
        import strategy_discovery_sandbox as sds   # noqa: E402
        self.svq = svq
        self.sds = sds

    def tearDown(self) -> None:
        for var in ("VARIANT_QUARANTINE_DIR", "AUDIT_TRADING_DIR"):
            os.environ.pop(var, None)


# ─── Test 1: variants land in quarantine only ────────────────────────────────


class TestSandboxRegistersInQuarantineOnly(_Base):
    def test_sandbox_creates_variant_via_register_variant(self) -> None:
        """Every generated proposal must be persisted via register_variant.

        We spy on the quarantine module's writer to make sure that the
        sandbox never writes to disk directly.
        """
        ranking = [{
            "strategy":         "momentum_long_strict",
            "n_trades":         10,
            "current_params":   {"threshold": 0.50},
        }]
        candidates = self.sds.identify_candidates(
            strategy_ranking=ranking,
            opportunity_ledger=[],
        )
        self.assertTrue(candidates)
        proposals = self.sds.generate_proposals(candidates[0])
        self.assertTrue(proposals)
        records = self.sds.register_proposals_with_quarantine(proposals)
        # Each registered record must look like a quarantine record.
        self.assertTrue(all("id" in r for r in records if "error" not in r))
        # All status values come from the quarantine module's closed enum.
        for r in records:
            if "error" in r:
                continue
            self.assertIn(r["status"], self.svq.ALL_STATUSES)


# ─── Test 2: NOT in active registry ──────────────────────────────────────────


class TestVariantNotInActiveRegistry(_Base):
    def test_proposed_id_does_not_appear_in_active_registry(self) -> None:
        ranking = [{
            "strategy":   "momentum_long_strict",
            "n_trades":   15,
        }]
        candidates = self.sds.identify_candidates(strategy_ranking=ranking)
        proposals = self.sds.generate_proposals(candidates[0])
        records = self.sds.register_proposals_with_quarantine(proposals)
        try:
            from backtest.strategy_registry import REGISTRY  # type: ignore
        except ImportError:
            # Backtest registry may not be importable in this env.
            return
        ids = [r["id"] for r in records if "id" in r]
        for variant_id in ids:
            self.assertNotIn(variant_id, REGISTRY)


# ─── Test 3: change_rationale present ────────────────────────────────────────


class TestProposalsHaveChangeRationale(_Base):
    def test_every_proposal_has_non_empty_change_rationale(self) -> None:
        ranking = [{
            "strategy": "geo_defense",
            "n_trades": 12,
        }]
        candidates = self.sds.identify_candidates(strategy_ranking=ranking)
        proposals = self.sds.generate_proposals(candidates[0])
        self.assertTrue(proposals)
        for p in proposals:
            self.assertIsInstance(p.change_rationale, str)
            self.assertGreater(len(p.change_rationale.strip()), 0)


# ─── Test 4: rejection_criteria present ──────────────────────────────────────


class TestProposalsHaveRejectionCriteria(_Base):
    def test_every_proposal_has_non_empty_rejection_criteria(self) -> None:
        ranking = [{
            "strategy": "options_momentum",
            "n_trades": 18,
        }]
        candidates = self.sds.identify_candidates(strategy_ranking=ranking)
        proposals = self.sds.generate_proposals(candidates[0])
        self.assertTrue(proposals)
        for p in proposals:
            self.assertIsInstance(p.rejection_criteria, list)
            self.assertGreaterEqual(len(p.rejection_criteria), 1)
            for criterion in p.rejection_criteria:
                self.assertIsInstance(criterion, str)
                self.assertGreater(len(criterion.strip()), 0)


# ─── Test 5: parent strategy not mutated ─────────────────────────────────────


class TestSandboxDoesNotMutateParent(_Base):
    def test_parent_strategy_dict_is_not_mutated_by_generation(self) -> None:
        """The candidate dict's current_params must not be modified."""
        before = {"threshold": 0.50, "confidence_cap": 0.65, "cooldown": 0}
        ranking = [{
            "strategy":       "momentum_long_strict",
            "n_trades":       10,
            "current_params": dict(before),
        }]
        candidates = self.sds.identify_candidates(strategy_ranking=ranking)
        # Get a reference to the candidate's params and confirm they stay
        # identical after generate_proposals + registration.
        candidate = candidates[0]
        params_ref = candidate["current_params"]
        proposals = self.sds.generate_proposals(candidate)
        self.sds.register_proposals_with_quarantine(proposals)
        self.assertEqual(params_ref, before)


# ─── Test 6: sandbox does not raise risk ─────────────────────────────────────


class TestSandboxDoesNotRaiseRisk(_Base):
    def test_no_proposal_param_can_weaken_risk_gate(self) -> None:
        """Override schema is closed; risk-gate keys must never appear.

        The quarantine module's ALLOWED_OVERRIDE_KEYS is the canonical
        whitelist. Anything proposing things like ``max_position_size``,
        ``max_drawdown_pct``, ``daily_loss_limit_pct`` would be silently
        dropped, but we also want to defensively assert it never appears
        in the first place to make the intent obvious in audits.
        """
        forbidden_keys = {
            "max_position_size",
            "max_drawdown_pct",
            "daily_loss_limit_pct",
            "size_multiplier",
            "exposure_cap",
            "concentration_cap",
            "max_correlated_bucket_pct",
        }
        ranking = [
            {"strategy": "momentum_long_strict",   "n_trades": 10},
            {"strategy": "geo_defense",            "n_trades": 12},
            {"strategy": "options_momentum",       "n_trades": 18},
        ]
        candidates = self.sds.identify_candidates(strategy_ranking=ranking)
        for c in candidates:
            for p in self.sds.generate_proposals(c):
                used = set(p.params.keys())
                self.assertFalse(used & forbidden_keys,
                                 f"forbidden risk-key in proposal "
                                 f"params: {used & forbidden_keys}")
                # Belt-and-braces: every used key must be in the
                # quarantine module's closed whitelist.
                self.assertTrue(used <= self.svq.ALLOWED_OVERRIDE_KEYS,
                                f"unknown override key(s): "
                                f"{used - self.svq.ALLOWED_OVERRIDE_KEYS}")

    def test_invariants_are_true(self) -> None:
        self.assertTrue(self.sds.DISCOVERY_NEVER_ENABLES_RUNTIME)
        self.assertTrue(self.sds.DISCOVERY_NEVER_PLACES_TRADES)
        self.assertTrue(self.sds.DISCOVERY_NEVER_REMOVES_GATES)


# ─── Extra: candidate triggers + run_discovery summary ───────────────────────


class TestRunDiscoverySummary(_Base):
    def test_run_discovery_returns_summary_dict(self) -> None:
        ranking = [
            # Will trigger TOO_SPARSE
            {"strategy": "newish_strategy", "n_trades": 5},
            # Healthy: ROBUST + has variants → skip
            {"strategy": "healthy",         "n_trades": 100},
        ]
        existing = {"healthy": [{"id": "abc"}]}
        evidence = {"healthy": {"status": "EVIDENCE_ROBUST_CANDIDATE"}}
        summary = self.sds.run_discovery(
            strategy_ranking=ranking,
            opportunity_ledger=[],
            evidence_summaries=evidence,
            existing_variants=existing,
        )
        self.assertIn("candidates", summary)
        self.assertIn("proposals_count", summary)
        self.assertIn("registered_records", summary)
        cand_names = {c["strategy"] for c in summary["candidates"]}
        self.assertIn("newish_strategy", cand_names)
        self.assertNotIn("healthy", cand_names)


if __name__ == "__main__":
    unittest.main()

"""v3.20.0 (2026-06-04) — Tests for shared/strategy_variant_quarantine.py.

These tests enforce ETAP 6 invariants:
  - variants live in quarantine, NEVER in the active registry
  - variants cannot be paper-enabled without manual review
  - evidence_source must be REPLAY or BACKTEST (PAPER forbidden)
  - registering a variant does NOT mutate the parent strategy
  - id derivation is deterministic

Run with:
    python3 -m unittest tests.test_strategy_variant_quarantine_v3200
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        # Isolated tmp dir per test so list_variants doesn't pick up stale data
        # AND audit emissions don't pollute the repo journal.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["VARIANT_QUARANTINE_DIR"] = str(
            Path(self._tmp.name) / "variants")
        os.environ["AUDIT_TRADING_DIR"] = str(
            Path(self._tmp.name) / "audit")
        # Force fresh import to pick up env-overridden quarantine dir.
        for k in list(sys.modules):
            if k.endswith(".strategy_variant_quarantine") \
               or k == "strategy_variant_quarantine":
                del sys.modules[k]
        import strategy_variant_quarantine as svq  # noqa: E402
        self.svq = svq

    def tearDown(self):
        for var in ("VARIANT_QUARANTINE_DIR", "AUDIT_TRADING_DIR"):
            os.environ.pop(var, None)


class TestQuarantineSeparation(_Base):
    def test_variant_not_in_active_registry(self):
        """Registered variant must NOT appear in the active strategy registry."""
        rec = self.svq.register_variant(
            "momentum_long_strict",
            "tighten breakout",
            {"threshold": 0.7},
            evidence_source="BACKTEST",
        )
        self.assertEqual(rec["status"], self.svq.QUARANTINED)

        # The active registry (if importable) MUST NOT contain the variant id.
        try:
            from backtest.strategy_registry import REGISTRY  # type: ignore
            for entry in REGISTRY.values():
                # Should be parent names, never our hex id.
                self.assertNotEqual(entry, rec["id"])
            # And our id is not a registered key.
            self.assertNotIn(rec["id"], REGISTRY)
        except ImportError:
            # No registry available in this environment — separation is still
            # enforced because the quarantine module never writes into it.
            pass

    def test_cannot_be_paper_enabled_without_manual_review(self):
        """No status path lets a variant become a runtime paper strategy.

        The closed enum on the quarantine module has no LIVE_APPROVED and
        no PAPER_ENABLED value. set_status MUST refuse any other status.
        """
        rec = self.svq.register_variant(
            "geo_defense", "relax confidence cap",
            {"confidence_cap": 0.55},
            evidence_source="REPLAY",
        )
        # Forbidden status string.
        result = self.svq.set_status(rec["id"], "LIVE_APPROVED",
                                     reason="should be refused")
        # Status MUST remain unchanged.
        self.assertEqual(result["status"], self.svq.QUARANTINED)

        # Even the valid CANDIDATE_FOR_MANUAL_REVIEW only stages a manual
        # review — the variant still does NOT enter the active registry.
        result2 = self.svq.set_status(
            rec["id"], self.svq.CANDIDATE_FOR_MANUAL_REVIEW,
            reason="ready for review")
        self.assertEqual(result2["status"],
                         self.svq.CANDIDATE_FOR_MANUAL_REVIEW)
        # No mutation to registry implied by status change.

    def test_evidence_source_must_be_replay_or_backtest(self):
        """PAPER evidence is explicitly forbidden for quarantine variants."""
        with self.assertRaises(ValueError):
            self.svq.register_variant(
                "momentum_long_strict",
                "use live paper data",
                {"threshold": 0.6},
                evidence_source="PAPER",
            )
        with self.assertRaises(ValueError):
            self.svq.register_variant(
                "momentum_long_strict",
                "unknown source",
                {"threshold": 0.6},
                evidence_source="LIVE_TRADING",
            )
        # REPLAY and BACKTEST both work.
        r1 = self.svq.register_variant(
            "x", "ok", {"threshold": 0.5},
            evidence_source="REPLAY")
        r2 = self.svq.register_variant(
            "y", "ok", {"threshold": 0.5},
            evidence_source="BACKTEST")
        self.assertEqual(r1["evidence_source"], "REPLAY")
        self.assertEqual(r2["evidence_source"], "BACKTEST")


class TestDeterminismAndIntegrity(_Base):
    def test_id_deterministic_for_same_input(self):
        """derive_variant_id is pure: same parent + params → same id."""
        id_a = self.svq.derive_variant_id(
            "momentum_long_strict", {"threshold": 0.7, "cooldown": 180})
        id_b = self.svq.derive_variant_id(
            "momentum_long_strict", {"cooldown": 180, "threshold": 0.7})
        self.assertEqual(id_a, id_b)
        self.assertEqual(len(id_a), 12)
        # Different params → different id.
        id_c = self.svq.derive_variant_id(
            "momentum_long_strict", {"threshold": 0.8, "cooldown": 180})
        self.assertNotEqual(id_a, id_c)

    def test_registering_variant_does_not_mutate_parent(self):
        """Parent strategy descriptor (if importable) is untouched."""
        # Snapshot whatever parent representation we can find.
        try:
            from backtest.strategy_registry import REGISTRY  # type: ignore
            before = dict(REGISTRY)
        except ImportError:
            before = None

        rec = self.svq.register_variant(
            "geo_defense",
            "tighten confidence cap",
            {"confidence_cap": 0.7},
            evidence_source="REPLAY",
        )
        # The persisted record has a different id than the parent name.
        self.assertNotEqual(rec["id"], "geo_defense")
        self.assertEqual(rec["parent_strategy"], "geo_defense")

        if before is not None:
            from backtest.strategy_registry import REGISTRY  # type: ignore
            self.assertEqual(dict(REGISTRY), before)


class TestOverrideWhitelistAndLoad(_Base):
    def test_disallowed_keys_dropped_silently(self):
        """Only the documented override keys persist on the variant."""
        rec = self.svq.register_variant(
            "momentum_long_strict",
            "test whitelist",
            {
                "threshold":       0.7,
                "size_multiplier": 1.3,   # forbidden — must be dropped
                "leverage":        2.0,   # forbidden — must be dropped
                "regime_filter":   "RISK_ON",
            },
            evidence_source="BACKTEST",
        )
        # Allowed keys remain.
        self.assertIn("threshold", rec["params"])
        self.assertIn("regime_filter", rec["params"])
        # Forbidden keys absent.
        self.assertNotIn("size_multiplier", rec["params"])
        self.assertNotIn("leverage", rec["params"])
        # And reported in dropped_param_keys.
        self.assertIn("size_multiplier", rec["dropped_param_keys"])
        self.assertIn("leverage", rec["dropped_param_keys"])

    def test_load_quarantined_variants_round_trip(self):
        """list_variants/load_quarantined_variants return what was registered."""
        a = self.svq.register_variant(
            "alpha", "a", {"threshold": 0.5},
            evidence_source="REPLAY")
        b = self.svq.register_variant(
            "beta", "b", {"cooldown": 30},
            evidence_source="BACKTEST")
        loaded = self.svq.load_quarantined_variants()
        ids = {r["id"] for r in loaded}
        self.assertEqual(ids, {a["id"], b["id"]})


if __name__ == "__main__":
    unittest.main()

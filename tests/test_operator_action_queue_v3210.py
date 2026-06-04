"""v3.21.0 (2026-06-04) — Tests for shared/operator_action_queue.py."""

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
        self.tmp = tempfile.TemporaryDirectory()
        self.queue_path  = Path(self.tmp.name) / "queue.jsonl"
        self.report_path = Path(self.tmp.name) / "report.md"
        self.audit_path  = Path(self.tmp.name) / "audit"
        os.environ["OPERATOR_ACTION_QUEUE_PATH"] = str(self.queue_path)
        os.environ["OPERATOR_ACTION_QUEUE_REPORT_PATH"] = str(
            self.report_path
        )
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_path)

        for k in list(sys.modules):
            if k == "operator_action_queue" \
               or k.endswith(".operator_action_queue"):
                del sys.modules[k]
        import operator_action_queue as oaq  # noqa: WPS433
        self.oaq = oaq

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OPERATOR_ACTION_QUEUE_PATH", None)
        os.environ.pop("OPERATOR_ACTION_QUEUE_REPORT_PATH", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)


class TestActionsGenerated(_Base):

    def test_enqueue_action_persists(self):
        rec = self.oaq.enqueue_action(
            action_type="REVIEW_STRATEGY",
            source_module="evidence_lower_bounds",
            severity="P2",
            rationale=("Strategy below Wilson lower bound; "
                       "review-gated; non-auto-apply by design."),
            evidence_links=["docs/EVIDENCE_LOWER_BOUNDS_LATEST.md"],
            recommended_review_deadline_iso="2026-06-11T00:00:00Z",
        )
        self.assertTrue(self.queue_path.exists())
        records = self.oaq.list_actions()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], rec["id"])


class TestNonAutoApplyInvariant(_Base):
    """Spec invariant: every entry has can_auto_apply == False."""

    def test_can_auto_apply_always_false(self):
        for at in self.oaq.ACTION_TYPES:
            rec = self.oaq.make_action(
                action_type=at,
                source_module="test",
                severity="P2",
                rationale="non-auto-apply by design",
                recommended_review_deadline_iso="2026-06-30T00:00:00Z",
            )
            self.assertIs(rec["can_auto_apply"], False)

    def test_cannot_override_can_auto_apply(self):
        # Reach in via make_action's signature — the function
        # explicitly does not accept can_auto_apply, and there is no
        # public escape hatch. Verify the constants invariant instead.
        self.oaq.assert_invariants()


class TestInvariantsDocumented(_Base):
    """Spec invariant: QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY = True."""

    def test_module_level_constants(self):
        self.assertTrue(self.oaq.QUEUE_NEVER_AUTO_APPLIES)
        self.assertTrue(self.oaq.QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY)

    def test_no_live_status_exists(self):
        for status in self.oaq.STATUSES:
            self.assertNotIn("LIVE", status.upper())

    def test_no_live_action_type(self):
        for at in self.oaq.ACTION_TYPES:
            self.assertNotIn("LIVE", at.upper())


class TestDeterminism(_Base):
    """Same input -> same id; re-enqueue is idempotent."""

    def test_enqueue_is_idempotent(self):
        a = self.oaq.enqueue_action(
            action_type="REVIEW_FILL_MODEL",
            source_module="fill_model_calibration",
            severity="P1",
            rationale="MODEL_DRIFT_HIGH; review-gated.",
            evidence_links=["docs/FILL_MODEL_CALIBRATION_LATEST.md"],
            recommended_review_deadline_iso="2026-06-11T00:00:00Z",
        )
        b = self.oaq.enqueue_action(
            action_type="REVIEW_FILL_MODEL",
            source_module="fill_model_calibration",
            severity="P1",
            rationale="MODEL_DRIFT_HIGH; review-gated.",
            evidence_links=["docs/FILL_MODEL_CALIBRATION_LATEST.md"],
            recommended_review_deadline_iso="2026-06-11T00:00:00Z",
        )
        self.assertEqual(a["id"], b["id"])
        # Only one row on disk.
        with open(self.queue_path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1)


class TestReportGenerated(_Base):

    def test_render_report_is_markdown(self):
        self.oaq.enqueue_action(
            action_type="DISABLE_CANDIDATE",
            source_module="evidence_lower_bounds",
            severity="P1",
            rationale=("EVIDENCE_REJECT: PF mean high but lower bound "
                       "below 1.0; review-gated; non-auto-apply by "
                       "design."),
            evidence_links=["docs/EVIDENCE_LOWER_BOUNDS_LATEST.md"],
            recommended_review_deadline_iso="2026-06-11T00:00:00Z",
            affected_strategies=["alpha-mean-reversion"],
        )
        out_path = self.oaq.write_markdown_report()
        body = out_path.read_text(encoding="utf-8")
        self.assertIn("Operator Action Queue", body)
        self.assertIn("QUEUE_NEVER_AUTO_APPLIES: True", body)
        self.assertIn("QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY: True", body)
        self.assertIn("DISABLE_CANDIDATE", body)


class TestStatusTransition(_Base):

    def test_set_status_persists_and_preserves_invariant(self):
        rec = self.oaq.enqueue_action(
            action_type="KEEP_OBSERVING",
            source_module="experiment_scheduler",
            severity="P3",
            rationale="Sample too small; review-gated.",
            recommended_review_deadline_iso="2026-06-11T00:00:00Z",
        )
        updated = self.oaq.set_status(rec["id"], "ACKNOWLEDGED")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["status"], "ACKNOWLEDGED")
        # Invariant preserved on update.
        self.assertIs(updated["can_auto_apply"], False)


class TestValidation(_Base):

    def test_unknown_action_type_raises(self):
        with self.assertRaises(ValueError):
            self.oaq.make_action(
                action_type="REVIEW_ROCKETSHIP",
                source_module="x",
                severity="P2",
                rationale="non-auto-apply by design",
                recommended_review_deadline_iso="2026-06-11T00:00:00Z",
            )

    def test_unknown_severity_raises(self):
        with self.assertRaises(ValueError):
            self.oaq.make_action(
                action_type="NO_ACTION",
                source_module="x",
                severity="P99",
                rationale="non-auto-apply by design",
                recommended_review_deadline_iso="2026-06-11T00:00:00Z",
            )

    def test_empty_rationale_raises(self):
        with self.assertRaises(ValueError):
            self.oaq.make_action(
                action_type="NO_ACTION",
                source_module="x",
                severity="P3",
                rationale="",
                recommended_review_deadline_iso="2026-06-11T00:00:00Z",
            )


class TestRationaleDeterministicPhrasing(_Base):
    """Rationale must support deterministic-phrasing-bank wording."""

    def test_safe_phrases_constants(self):
        # All bank phrases are non-empty strings and avoid forbidden
        # wording patterns (rough sanity check; full grep happens in
        # autonomy.assert_no_forbidden_strings via tests).
        for phrase in self.oaq.SAFE_PHRASES:
            self.assertIsInstance(phrase, str)
            self.assertGreater(len(phrase), 0)


if __name__ == "__main__":
    unittest.main()

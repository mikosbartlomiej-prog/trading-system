"""
Tests for shared.routine_budget — daily Anthropic Routine call cap.

Covers:
  - Tier-based cap enforcement
  - Daily reset on UTC midnight
  - Persistence via runtime_state.json (mocked)
  - Audit emission on BLOCK/ALLOW
  - Fail-soft when runtime_state unwritable
  - Priority override
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import routine_budget  # noqa: E402


class _FakeRuntimeStore:
    """Drop-in replacement for runtime_state read/merge — pure dict."""

    def __init__(self, initial: Optional[dict] = None):
        self._d: dict = dict(initial or {})

    def read_section(self, name: str) -> dict:
        return dict(self._d.get(name) or {})

    def merge_section(self, name: str, payload: dict,
                      actor: str = "intraday-monitor") -> dict:
        cur = dict(self._d.get(name) or {})
        cur.update(payload)
        self._d[name] = cur
        return cur


def _patch_store(store: _FakeRuntimeStore):
    """Patch the module-level read_section/merge_section references."""
    return patch.multiple(
        routine_budget,
        read_section=store.read_section,
        merge_section=store.merge_section,
    )


class TestFreshDay(unittest.TestCase):
    """No prior state → full budget available."""

    def test_can_call_when_fresh(self):
        store = _FakeRuntimeStore()
        with _patch_store(store):
            ok, reason = routine_budget.can_call("daily-learning-pm")
        self.assertTrue(ok)
        self.assertIn("budget OK", reason)

    def test_get_state_fresh(self):
        store = _FakeRuntimeStore()
        with _patch_store(store):
            s = routine_budget.get_state()
        self.assertEqual(s["total_used"], 0)
        # v3.8.8 (2026-05-18): buffer raised 1 → 2 (curator volume eating
        # P0 budget across rolling Anthropic window). remaining_total = 13.
        self.assertEqual(s["remaining_total"], 13)  # daily 15 - buffer 2
        # Tier ints present
        for tname in ("P0_essential", "P1_important", "P2_optional"):
            self.assertIn(tname, s["remaining_by_tier"])


class TestRecordCall(unittest.TestCase):
    """record_call increments + persists."""

    def test_record_increments_total_and_tier(self):
        store = _FakeRuntimeStore()
        with _patch_store(store):
            routine_budget.record_call("daily-learning-pm")
            s = routine_budget.get_state()
        self.assertEqual(s["total_used"], 1)
        self.assertEqual(s["by_tier"]["P0_essential"], 1)
        self.assertEqual(s["by_routine"]["daily-learning-pm"], 1)

    def test_three_calls_three_recorded(self):
        store = _FakeRuntimeStore()
        with _patch_store(store):
            routine_budget.record_call("daily-learning-pm")
            routine_budget.record_call("daily-learning-challenger")
            routine_budget.record_call("daily-learning-revise")
            s = routine_budget.get_state()
        self.assertEqual(s["total_used"], 3)
        self.assertEqual(s["by_tier"]["P0_essential"], 3)


class TestTierCaps(unittest.TestCase):
    """Tier caps enforced; P0 doesn't starve when P2 exhausted."""

    def test_p0_cap_reached_blocks(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  4,
                "by_tier": {"P0_essential": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, reason = routine_budget.can_call("daily-learning-pm")
        self.assertFalse(ok)
        self.assertIn("P0_essential cap", reason)

    def test_p2_cap_reached_blocks_curator(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  4,
                "by_tier": {"P2_optional": 4},  # v3.8.8: P2 cap 5→4
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, reason = routine_budget.can_call("reddit-curator")
        self.assertFalse(ok)
        self.assertIn("P2_optional cap", reason)

    def test_p2_exhausted_p0_still_allowed(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  4,
                "by_tier": {"P2_optional": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, _ = routine_budget.can_call("daily-learning-pm")
        self.assertTrue(ok)


class TestDailyLimit(unittest.TestCase):
    """Total daily limit (15 - buffer 2 = 13) hard cap (v3.8.8)."""

    def test_total_13_blocks_everything(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  13,
                "by_tier": {"P0_essential": 4, "P1_important": 5, "P2_optional": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, reason = routine_budget.can_call("daily-learning-pm")
        self.assertFalse(ok)
        self.assertIn("daily routine cap", reason)


class TestDailyReset(unittest.TestCase):
    """Yesterday's counter is auto-reset on first today read."""

    def test_yesterdays_state_resets_today(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   yesterday,
                "total":  13,
                "by_tier": {"P2_optional": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, _ = routine_budget.can_call("reddit-curator")
        self.assertTrue(ok, "Yesterday's full budget should auto-reset")

    def test_explicit_reset(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  13,
                "by_tier": {"P0_essential": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            routine_budget.reset_for_new_day()
            s = routine_budget.get_state()
        self.assertEqual(s["total_used"], 0)


class TestPriorityResolution(unittest.TestCase):
    """Caller can override automatic tier lookup."""

    def test_known_routine_auto_tier(self):
        cfg = routine_budget._load_config()
        tier = routine_budget._resolve_priority(
            "daily-learning-pm", requested=None, cfg=cfg,
        )
        self.assertEqual(tier, "P0_essential")

    def test_explicit_p0_override(self):
        cfg = routine_budget._load_config()
        tier = routine_budget._resolve_priority(
            "unknown-routine", requested="P0", cfg=cfg,
        )
        self.assertEqual(tier, "P0_essential")

    def test_unknown_routine_defaults_to_p2(self):
        cfg = routine_budget._load_config()
        tier = routine_budget._resolve_priority(
            "mystery-routine", requested=None, cfg=cfg,
        )
        self.assertEqual(tier, "P2_optional")


class TestFailSoft(unittest.TestCase):
    """Persistence failures don't break the call path."""

    def test_unwritable_runtime_state_returns_true(self):
        store = _FakeRuntimeStore()

        def boom(*args, **kwargs):
            raise RuntimeError("read-only state")

        with patch.multiple(
            routine_budget,
            read_section=store.read_section,
            merge_section=boom,
        ):
            ok, _ = routine_budget.can_call("daily-learning-pm")
            self.assertTrue(ok, "can_call should not raise on unwritable state")
            # record_call also fails-soft
            state = routine_budget.record_call("daily-learning-pm")
            self.assertEqual(state["total_used"], 1,
                             "in-memory still increments even if persist fails")


class TestAuditEmission(unittest.TestCase):
    """check_and_record emits audit events."""

    def test_block_emits_audit(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  4,
                "by_tier": {"P2_optional": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            with _patch_store(store):
                ok, reason, _ = routine_budget.check_and_record("reddit-curator")
            self.assertFalse(ok)
            files = list(Path(td).glob("*.jsonl"))
            self.assertTrue(files, "BLOCK should emit audit")
            lines = files[0].read_text().strip().splitlines()
            rec = json.loads(lines[0])
            self.assertEqual(rec["decision"], "ROUTINE_BUDGET_BLOCK")

    def test_allow_emits_audit(self):
        store = _FakeRuntimeStore()
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            with _patch_store(store):
                ok, _, _ = routine_budget.check_and_record("daily-learning-pm")
            self.assertTrue(ok)
            files = list(Path(td).glob("*.jsonl"))
            self.assertTrue(files)
            rec = json.loads(files[0].read_text().strip().splitlines()[0])
            self.assertEqual(rec["decision"], "ROUTINE_BUDGET_ALLOW")


class TestCheckAndRecord(unittest.TestCase):
    """Convenience combined helper."""

    def test_allows_first_call_increments(self):
        store = _FakeRuntimeStore()
        with _patch_store(store):
            ok, reason, state = routine_budget.check_and_record("daily-learning-pm")
        self.assertTrue(ok)
        self.assertEqual(state["total_used"], 1)

    def test_block_does_not_increment(self):
        store = _FakeRuntimeStore({
            "routine_budget": {
                "date":   routine_budget._today_iso(),
                "total":  4,
                "by_tier": {"P0_essential": 4},
                "by_routine": {},
                "last_updated": "...",
            }
        })
        with _patch_store(store):
            ok, _, state = routine_budget.check_and_record("daily-learning-pm")
        self.assertFalse(ok)
        # Counter unchanged
        self.assertEqual(state["total_used"], 4)


if __name__ == "__main__":
    unittest.main()

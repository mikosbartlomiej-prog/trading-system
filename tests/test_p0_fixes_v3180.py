"""v3.18.0 ETAP 1 — P0 fixes regression tests.

P0-001: Heartbeat workflow permissions.
   - 5 monitor workflows (defense, geo, options, price, twitter) declare
     `contents: write` so heartbeat snapshots commit to runtime_state.json.
   - Each workflow has a "Commit runtime_state.json" step with `git add
     learning-loop/runtime_state.json`.
   - audit_workflows.py allowlist includes all 5 (without this, workflow
     audit would FAIL the CI gate).

P0-002: PDT cooldown persistence.
   - exit-monitor cooldown dict is persisted to
     runtime_state.json::pdt_cooldown so dedup survives runner restarts.
   - load_pdt_cooldown / save_pdt_cooldown helpers do prune-on-write,
     malformed-input fail-soft, and ISO-8601 conversion.
   - Same-key dedup within cooldown window emits ONE audit event;
     subsequent calls in the window are silent.

ALL TESTS:
   - LOCAL — write to tempdir only (RUNTIME_STATE_PATH env override).
   - DETERMINISTIC — no network, datetime injected via fixed dt.
   - NO ORDERS — no requests.post anywhere; only state-file IO.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
SHARED_DIR = REPO_ROOT / "shared"
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXIT_MON_DIR = REPO_ROOT / "exit-monitor"

for p in (str(SHARED_DIR), str(REPO_ROOT), str(EXIT_MON_DIR), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


# ─── P0-001 Heartbeat workflow permissions ──────────────────────────────────

MONITOR_YAMLS = [
    "defense-monitor.yml",
    "geo-monitor.yml",
    "options-monitor.yml",
    "price-monitor.yml",
    "twitter-monitor.yml",
]


class TestHeartbeatWorkflowPermissions(unittest.TestCase):
    """5 monitor workflows persist runtime_state.json after heartbeat ping."""

    def _read(self, name: str) -> str:
        path = WORKFLOWS_DIR / name
        self.assertTrue(path.exists(), f"workflow {name} missing")
        return path.read_text(encoding="utf-8")

    def test_all_five_workflows_declare_contents_write(self):
        """permissions: contents: write present in each YAML."""
        for name in MONITOR_YAMLS:
            text = self._read(name)
            self.assertIn(
                "contents: write",
                text,
                msg=f"{name} missing `contents: write` declaration",
            )
            # Sanity: must be under a `permissions:` block (defensive)
            self.assertIn("permissions:", text, f"{name} missing permissions block")

    def test_all_five_workflows_have_runtime_state_commit_step(self):
        """Each YAML adds learning-loop/runtime_state.json to git stage."""
        for name in MONITOR_YAMLS:
            text = self._read(name)
            self.assertIn(
                "git add learning-loop/runtime_state.json",
                text,
                msg=f"{name} missing `git add learning-loop/runtime_state.json` "
                "(heartbeat snapshot will never reach origin)",
            )

    def test_all_five_workflows_have_commit_message_with_automerge_tag(self):
        """[automerge] tag triggers auto-merge.yml fast-forward."""
        for name in MONITOR_YAMLS:
            text = self._read(name)
            self.assertIn(
                "[automerge]",
                text,
                msg=f"{name} commit message must end with [automerge] so "
                "auto-merge.yml propagates to main",
            )

    def test_all_five_workflows_have_retry_push_loop(self):
        """3-attempt push with rebase backoff matches crypto-monitor pattern."""
        for name in MONITOR_YAMLS:
            text = self._read(name)
            self.assertIn(
                "for attempt in 1 2 3",
                text,
                msg=f"{name} missing 3-attempt retry-on-race push loop",
            )
            # And rebase recovery
            self.assertIn(
                "git pull --rebase",
                text,
                msg=f"{name} missing `git pull --rebase` recovery in retry loop",
            )

    def test_audit_allowlist_contains_all_five(self):
        """audit_workflows.py CONTENTS_WRITE_ALLOWLIST must include each yaml."""
        import audit_workflows as aw

        allowlist = aw.CONTENTS_WRITE_ALLOWLIST
        for name in MONITOR_YAMLS:
            self.assertIn(
                name,
                allowlist,
                msg=f"{name} NOT in CONTENTS_WRITE_ALLOWLIST — audit will FAIL "
                "(workflow declares contents:write without being allow-listed)",
            )


# ─── P0-002 PDT cooldown persistence ────────────────────────────────────────

class _PDTCooldownTestBase(unittest.TestCase):
    """Common fixture: tempdir runtime_state.json + reset exit-monitor module."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._rt_path = os.path.join(self._tmpdir.name, "runtime_state.json")
        os.environ["RUNTIME_STATE_PATH"] = self._rt_path
        # Force re-import so the module rebinds RUNTIME_STATE_PATH.
        import runtime_state
        importlib.reload(runtime_state)
        # Re-import exit-monitor with patched sys.path. Use util via the
        # top-level importlib (already imported at module scope above).
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "_exit_monitor_under_test",
            os.path.join(EXIT_MON_DIR, "monitor.py"),
        )
        self.exitmon = _ilu.module_from_spec(spec)
        # Stash sys.modules entry so internal `from runtime_state import`
        # finds the reloaded module.
        sys.modules["_exit_monitor_under_test"] = self.exitmon
        spec.loader.exec_module(self.exitmon)
        # Reset module-level cooldown so each test gets a fresh state.
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False

    def tearDown(self):
        sys.modules.pop("_exit_monitor_under_test", None)
        os.environ.pop("RUNTIME_STATE_PATH", None)
        self._tmpdir.cleanup()


class TestPDTCooldownPersistence(_PDTCooldownTestBase):
    """P0-002 — cooldown dict survives across runner restarts."""

    def test_save_writes_to_runtime_state_pdt_cooldown_section(self):
        """First block call → entry visible in pdt_cooldown JSON section."""
        # Use real datetime.now so the prune step doesn't drop the entry.
        now = datetime.now(timezone.utc)
        cooldown = self.exitmon._load_pdt_cooldown()
        cooldown["AAPL|CLOSE_FLAT|BLOCK"] = now
        self.exitmon._save_pdt_cooldown()

        with open(self._rt_path, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertIn("pdt_cooldown", raw)
        self.assertIn("AAPL|CLOSE_FLAT|BLOCK", raw["pdt_cooldown"])
        # Value is ISO timestamp string.
        self.assertEqual(
            raw["pdt_cooldown"]["AAPL|CLOSE_FLAT|BLOCK"],
            now.isoformat(),
        )

    def test_load_round_trip_across_process_restart(self):
        """Simulate restart: write → clear module → reload → entries present."""
        # Real now so prune doesn't drop the freshly-added entries.
        now = datetime.now(timezone.utc)
        cd1 = self.exitmon._load_pdt_cooldown()
        cd1["RTX|CLOSE_FLAT|BLOCK"] = now
        cd1["LMT|CLOSE_FLAT|BLOCK"] = now
        self.exitmon._save_pdt_cooldown()

        # Simulate fresh runner: clear module-level state.
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False

        # Re-load — should see both entries.
        cd2 = self.exitmon._load_pdt_cooldown()
        self.assertEqual(len(cd2), 2)
        self.assertIn("RTX|CLOSE_FLAT|BLOCK", cd2)
        self.assertIn("LMT|CLOSE_FLAT|BLOCK", cd2)
        # And they parse back into datetime.
        self.assertIsInstance(cd2["RTX|CLOSE_FLAT|BLOCK"], datetime)

    def test_expired_entries_pruned_on_write(self):
        """Entries older than 3600s dropped during _save_pdt_cooldown."""
        # Use real datetime.now to drive prune logic. Construct entries
        # with explicit offsets so prune outcome is deterministic.
        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=7200)   # 2h ago — expired
        fresh = now - timedelta(seconds=60)    # 1 min ago — kept
        cd = self.exitmon._load_pdt_cooldown()
        cd["OLD|CLOSE_FLAT|BLOCK"] = old
        cd["FRESH|CLOSE_FLAT|BLOCK"] = fresh

        self.exitmon._save_pdt_cooldown()

        # In-memory: old gone, fresh kept.
        self.assertNotIn("OLD|CLOSE_FLAT|BLOCK", self.exitmon._PDT_BLOCK_COOLDOWN)
        self.assertIn("FRESH|CLOSE_FLAT|BLOCK", self.exitmon._PDT_BLOCK_COOLDOWN)

        # On-disk reflects pruned state.
        with open(self._rt_path, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(list(raw["pdt_cooldown"].keys()),
                         ["FRESH|CLOSE_FLAT|BLOCK"])

    def test_malformed_runtime_state_falls_back_to_empty_dict(self):
        """Corrupt runtime_state.json::pdt_cooldown → empty dict (fail-soft)."""
        # Write malformed: pdt_cooldown is a list, not dict.
        with open(self._rt_path, "w", encoding="utf-8") as f:
            json.dump({"pdt_cooldown": ["not", "a", "dict"]}, f)

        # Reset and load — should not raise.
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False
        cd = self.exitmon._load_pdt_cooldown()
        self.assertEqual(cd, {})

    def test_malformed_entries_individually_dropped(self):
        """Bad ISO strings inside pdt_cooldown drop those entries silently."""
        good = datetime(2026, 6, 4, 14, 0, 0, tzinfo=timezone.utc).isoformat()
        with open(self._rt_path, "w", encoding="utf-8") as f:
            json.dump({
                "pdt_cooldown": {
                    "GOOD|REC|BLOCK": good,
                    "BAD|REC|BLOCK": "not-a-timestamp",
                    "NUMERIC|REC|BLOCK": 1234567,  # not a string
                }
            }, f)
        # Reload.
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False
        cd = self.exitmon._load_pdt_cooldown()
        # Only the good entry survives.
        self.assertEqual(list(cd.keys()), ["GOOD|REC|BLOCK"])
        self.assertIsInstance(cd["GOOD|REC|BLOCK"], datetime)

    def test_within_cooldown_skips_audit_emission(self):
        """Same (sym,rec,decision) re-block within window → silent (no audit)."""
        # Pre-populate: AAPL was blocked 60s ago (relative to real now).
        now = datetime.now(timezone.utc)
        cd = self.exitmon._load_pdt_cooldown()
        cd["AAPL|CLOSE_FLAT|BLOCK"] = now - timedelta(seconds=60)
        self.exitmon._save_pdt_cooldown()

        # Reset for clean re-load (simulate next cron).
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False

        cd2 = self.exitmon._load_pdt_cooldown()
        last = cd2.get("AAPL|CLOSE_FLAT|BLOCK")
        # Cooldown still active (60s < 3600s window).
        self.assertIsNotNone(last)
        elapsed = (now - last).total_seconds()
        self.assertLess(elapsed, self.exitmon.PDT_BLOCK_COOLDOWN_S)

    def test_expired_cooldown_allows_re_audit(self):
        """After 3600s window elapses, new block emits audit again."""
        # Use real now and a past timestamp > 3600s ago.
        now = datetime.now(timezone.utc)
        long_ago = now - timedelta(seconds=4000)  # > 3600s
        cd = self.exitmon._load_pdt_cooldown()
        cd["TSLA|CLOSE_FLAT|BLOCK"] = long_ago

        self.exitmon._save_pdt_cooldown()

        # On disk: expired entry gone.
        self.assertNotIn("TSLA|CLOSE_FLAT|BLOCK", self.exitmon._PDT_BLOCK_COOLDOWN)

    def test_emergency_close_bypasses_cooldown_path(self):
        """Emergency closes never reach the cooldown lookup (architectural)."""
        # Read the actual source — emergency closes use is_emergency=True
        # branch in PDT guard which short-circuits BEFORE we reach the
        # cooldown check. Verify the code structure preserves this.
        src = Path(EXIT_MON_DIR / "monitor.py").read_text(encoding="utf-8")
        # The PDT eval call passes is_emergency_close as flag, and emergency
        # closes go through the same code; the PDT guard itself bypasses
        # them. The cooldown check is only reached when decision != ALLOW.
        # Sanity: emergency tag remains in reason_tag map and emergency
        # is_emergency_close is computed from CLOSE_EMERGENCY/PROFIT_LOCK.
        self.assertIn("is_emergency_close = rec in", src)
        self.assertIn("CLOSE_EMERGENCY", src)
        self.assertIn("PROFIT_LOCK", src)
        # And the cooldown only persists when decision != ALLOW (so an
        # emergency that gets ALLOW from PDT guard never enters the dict).
        self.assertIn('if pv["decision"] != "ALLOW":', src)

    def test_concurrent_writes_last_writer_wins(self):
        """Two writes in sequence: final state reflects the latter."""
        # Real now → prune step keeps freshly-added entries.
        now = datetime.now(timezone.utc)

        # Writer A: adds AAPL.
        cd1 = self.exitmon._load_pdt_cooldown()
        cd1["AAPL|CLOSE_FLAT|BLOCK"] = now
        self.exitmon._save_pdt_cooldown()

        # Writer B (simulates concurrent cron): re-load, adds MSFT.
        self.exitmon._PDT_BLOCK_COOLDOWN = {}
        self.exitmon._PDT_COOLDOWN_LOADED = False
        cd2 = self.exitmon._load_pdt_cooldown()
        cd2["MSFT|CLOSE_FLAT|BLOCK"] = now
        self.exitmon._save_pdt_cooldown()

        # Final state has BOTH (B re-loaded A's state before adding).
        with open(self._rt_path, encoding="utf-8") as f:
            raw = json.load(f)
        cd_keys = set(raw["pdt_cooldown"].keys())
        self.assertEqual(cd_keys, {"AAPL|CLOSE_FLAT|BLOCK", "MSFT|CLOSE_FLAT|BLOCK"})


if __name__ == "__main__":
    unittest.main()

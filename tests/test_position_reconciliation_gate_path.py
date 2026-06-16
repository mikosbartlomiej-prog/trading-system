"""Verify that the position reconciliation reporter writes a gate-readable
artefact at ``learning-loop/position_reconciliation_latest.json`` without
touching the unrelated followup-tracking file at
``learning-loop/position_reconciliation/latest.json``.

The mismatch was diagnosed during the v3.30 → v3.31 operator clearance
cycle: the gate (``shared.system_activation_gate``) looks for one path,
the reporter (``scripts/position_reconciliation_report``) was only writing
to ``docs/``.

HARD SAFETY: this test never calls the broker, never imports
``alpaca_orders``, never makes network calls. It exercises the reporter
through subprocess in a tempdir so the real repo state is untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTER = REPO_ROOT / "scripts" / "position_reconciliation_report.py"


class TestPositionReconciliationGatePath(unittest.TestCase):

    def setUp(self):
        # Build a minimal repo-shaped tempdir so the reporter can run
        # against a clean state without polluting the real artefacts.
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "docs").mkdir()
        (self.tmp / "learning-loop").mkdir()
        # Pre-seed the unrelated followup-tracking file so we can prove
        # the reporter does NOT touch it.
        self.untouchable = (
            self.tmp / "learning-loop" / "position_reconciliation"
        )
        self.untouchable.mkdir()
        self.untouchable_payload = {
            "version": "v3.29.unrelated",
            "generated_at_iso": "2026-06-09T18:00:00+00:00",
            "v327_followups": ["should not be touched"],
        }
        (self.untouchable / "latest.json").write_text(
            json.dumps(self.untouchable_payload, indent=2),
            encoding="utf-8",
        )
        # Copy the reporter + shared/ into the tempdir so the script can
        # resolve its REPO_ROOT-relative writes there.
        shutil.copytree(REPO_ROOT / "scripts", self.tmp / "scripts")
        shutil.copytree(REPO_ROOT / "shared",  self.tmp / "shared")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------

    def test_reporter_writes_gate_path(self):
        """Reporter writes ``learning-loop/position_reconciliation_latest.json``."""
        out_path = (
            self.tmp / "learning-loop" / "position_reconciliation_latest.json"
        )
        self.assertFalse(out_path.exists(), "preflight: gate-path must not exist yet")

        env = dict(os.environ)
        # Strip broker creds so the reporter runs in fail-soft (no network).
        env.pop("ALPACA_API_KEY", None)
        env.pop("ALPACA_SECRET_KEY", None)
        result = subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "position_reconciliation_report.py")],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                          f"reporter exited non-zero: stderr={result.stderr}")
        self.assertTrue(out_path.exists(),
                          f"gate-readable file not written: {out_path}")

    def test_payload_has_generated_at_iso(self):
        """Top-level ``generated_at_iso`` must be present so the gate can read age."""
        env = dict(os.environ)
        env.pop("ALPACA_API_KEY", None)
        env.pop("ALPACA_SECRET_KEY", None)
        subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "position_reconciliation_report.py")],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        payload = json.loads(
            (self.tmp / "learning-loop" / "position_reconciliation_latest.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("generated_at_iso", payload,
                       "gate-readable file missing top-level generated_at_iso")
        self.assertTrue(payload["generated_at_iso"],
                          "generated_at_iso must be non-empty")

    def test_existing_followup_file_untouched(self):
        """The unrelated ``learning-loop/position_reconciliation/latest.json``
        must NOT be overwritten."""
        env = dict(os.environ)
        env.pop("ALPACA_API_KEY", None)
        env.pop("ALPACA_SECRET_KEY", None)
        subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "position_reconciliation_report.py")],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        untouched = json.loads(
            (self.untouchable / "latest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(untouched, self.untouchable_payload,
                          "unrelated followup file was modified")

    def test_gate_helper_can_read_new_file(self):
        """``shared.system_activation_gate._read_position_recon_age_seconds``
        must successfully read the new gate-path file."""
        env = dict(os.environ)
        env.pop("ALPACA_API_KEY", None)
        env.pop("ALPACA_SECRET_KEY", None)
        subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "position_reconciliation_report.py")],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        # Invoke the gate helper as a subprocess so REPO_ROOT resolves
        # to the tempdir (it's derived from the module path).
        helper = (
            "import sys; sys.path.insert(0, 'shared');"
            " import system_activation_gate as g;"
            " v = g._read_position_recon_age_seconds();"
            " print('AGE_SECONDS:', v); assert v is not None and v >= 0"
        )
        result = subprocess.run(
            [sys.executable, "-c", helper],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                          f"gate helper failed: stderr={result.stderr}")
        self.assertIn("AGE_SECONDS:", result.stdout,
                       f"gate helper output unexpected: {result.stdout}")


if __name__ == "__main__":
    unittest.main()

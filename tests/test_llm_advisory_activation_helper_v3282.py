"""v3.28.2 (2026-06-09) — activation helper tests."""

from __future__ import annotations

import importlib.util as iu
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_helper():
    spec = iu.spec_from_file_location(
        "activate_llm_advisory_mesh",
        REPO_ROOT / "scripts" / "activate_llm_advisory_mesh.py")
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _NoNetwork(unittest.TestCase):
    """Stub all subprocess + shutil.which so the helper never touches
    the real gh CLI from tests."""

    def setUp(self):
        self.helper = _load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "ALLOW_BROKER_PAPER": "false",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestAutoSelectProvider(_NoNetwork):
    def test_gemini_preferred_when_secret_present(self):
        sel = self.helper.auto_select_provider(
            ["GEMINI_API_KEY", "ANTHROPIC_API_KEY"],
            free_only=True)
        self.assertEqual(sel, "gemini")

    def test_offline_mock_when_no_secret(self):
        sel = self.helper.auto_select_provider(
            [], free_only=True)
        self.assertEqual(sel, "offline_mock")

    def test_paid_provider_blocked_under_free_only(self):
        sel = self.helper.auto_select_provider(
            ["ANTHROPIC_API_KEY"], free_only=True)
        # free_only=True → paid providers ignored.
        self.assertEqual(sel, "offline_mock")

    def test_paid_provider_allowed_when_free_only_off(self):
        sel = self.helper.auto_select_provider(
            ["ANTHROPIC_API_KEY"], free_only=False)
        self.assertEqual(sel, "anthropic")


class TestCheckOnlyReadyStatus(_NoNetwork):
    def test_check_only_when_gh_authed_and_secret_present(self):
        h = self.helper
        with mock.patch.object(h, "gh_cli_available", return_value=True), \
              mock.patch.object(h, "gh_cli_authenticated", return_value=True), \
              mock.patch.object(
                h, "list_secret_names",
                return_value=(True, ["GEMINI_API_KEY"], ""),
              ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = h.main(["--check-only", "--provider", "auto"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(
            out["status"],
            "LLM_ACTIVATION_READY_GEMINI_SECRET_PRESENT")
        self.assertEqual(out["selected_provider"], "gemini")
        self.assertTrue(out["gemini_secret_present"])


class TestCheckOnlyBlockedStatuses(_NoNetwork):
    def test_blocked_no_gh_auth(self):
        h = self.helper
        with mock.patch.object(h, "gh_cli_available", return_value=True), \
              mock.patch.object(h, "gh_cli_authenticated", return_value=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = h.main(["--check-only", "--provider", "auto"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(
            out["status"],
            "LLM_ACTIVATION_BLOCKED_NO_GITHUB_AUTH")

    def test_blocked_no_provider_secret(self):
        h = self.helper
        with mock.patch.object(h, "gh_cli_available", return_value=True), \
              mock.patch.object(h, "gh_cli_authenticated", return_value=True), \
              mock.patch.object(
                h, "list_secret_names",
                return_value=(True, [], ""),
              ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = h.main(["--check-only", "--provider", "auto"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(
            out["status"],
            "LLM_ACTIVATION_BLOCKED_NO_PROVIDER_SECRET")


class TestSetVarsRequiresAuth(_NoNetwork):
    def test_set_vars_without_auth_fails(self):
        h = self.helper
        with mock.patch.object(h, "gh_cli_available", return_value=True), \
              mock.patch.object(h, "gh_cli_authenticated", return_value=False), \
              mock.patch.object(h, "set_variable",
                                  return_value=(True, "ok")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = h.main(["--set-vars", "--provider", "gemini"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(out["variables_status"],
                          "LLM_ACTIVATION_VARIABLES_FAILED")
        self.assertGreater(out["blockers_count"], 0)


class TestScheduleDisabledByDefault(_NoNetwork):
    def test_default_enable_schedule_is_false(self):
        h = self.helper
        with mock.patch.object(h, "gh_cli_available", return_value=True), \
              mock.patch.object(h, "gh_cli_authenticated", return_value=True), \
              mock.patch.object(
                h, "list_secret_names",
                return_value=(True, ["GEMINI_API_KEY"], "")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = h.main(["--check-only"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertFalse(out["schedule_enabled"])


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "activate_llm_advisory_mesh.py").read_text(
            encoding="utf-8")
        for tok in (
            "alpaca_orders", "place_stock_bracket",
            "place_crypto_order", "execute_stock_signal",
            "execute_crypto_signal",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()

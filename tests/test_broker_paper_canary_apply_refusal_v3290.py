"""v3.29 (2026-06-09) — --apply-enable refusal matrix tests."""

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
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _load_script():
    spec = iu.spec_from_file_location(
        "evaluate_broker_paper_canary_unlock",
        REPO_ROOT / "scripts"
        / "evaluate_broker_paper_canary_unlock.py")
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestApplyRefusedWhenStatusNotReady(unittest.TestCase):
    def test_refused_when_unlock_blocked(self):
        script = _load_script()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = script.main(["--apply-enable"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertFalse(out["applied"])
        self.assertIsNotNone(out["apply_refused_reason"])


class TestRefusesOnBrokerFlagTruthy(unittest.TestCase):
    def test_refuses_on_allow_broker_paper(self):
        script = _load_script()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {
            "ALLOW_BROKER_PAPER": "true",
        }, clear=False):
            with redirect_stdout(buf):
                rc = script.main([])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_ALLOW_BROKER_PAPER_IS_TRUTHY",
                       buf.getvalue())


class TestRefusesOnLiveFlagTruthy(unittest.TestCase):
    def test_refuses_on_live_trading(self):
        script = _load_script()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {
            "LIVE_TRADING": "true",
        }, clear=False):
            with redirect_stdout(buf):
                rc = script.main([])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_LIVE_TRADING_IS_TRUTHY",
                       buf.getvalue())


class TestNoOrderTokensInScript(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "evaluate_broker_paper_canary_unlock.py").read_text(
            encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order", "submit_order",
                     "place_order", "safe_close"):
            self.assertNotIn(tok, src)


class TestEvaluateOnlyDefault(unittest.TestCase):
    def test_default_mode_is_evaluate_only(self):
        # When no --apply-enable / --propose-enable is passed,
        # `applied` is False and `apply_refused_reason` is None.
        script = _load_script()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = script.main([])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().splitlines()[-1])
        self.assertFalse(out["applied"])
        self.assertIsNone(out["apply_refused_reason"])


class TestStandingMarkersAlwaysEmitted(unittest.TestCase):
    def test_markers_present(self):
        script = _load_script()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = script.main([])
        out = json.loads(buf.getvalue().splitlines()[-1])
        for m in (
            "LLM_STRATEGY_ALIGNMENT_ENFORCED",
            "LLM_ADVISORY_ONLY_CONFIRMED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
            "LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
        ):
            self.assertIn(m, out["standing_markers"])


if __name__ == "__main__":
    unittest.main()

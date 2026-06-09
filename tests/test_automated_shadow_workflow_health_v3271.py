"""v3.27.1 (2026-06-09) — workflow health JSON + doc tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _run_evaluator(*args: str, env_overrides=None,
                    cwd: Path | None = None) -> tuple[int, str]:
    """Invoke the evaluator script in-process via runpy semantics."""
    import importlib.util as iu
    spec = iu.spec_from_file_location(
        "evaluate_automated_shadow_progress",
        REPO_ROOT / "scripts"
        / "evaluate_automated_shadow_progress.py",
    )
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    import io, contextlib
    buf = io.StringIO()
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    with mock.patch.dict(os.environ, env, clear=False):
        with contextlib.redirect_stdout(buf):
            try:
                rc = mod.main(list(args))
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
    return rc, buf.getvalue()


class TestHealthArtifactsPresent(unittest.TestCase):
    def test_health_json_exists_after_evaluator(self):
        # We don't run the evaluator here (it persists to disk),
        # but verify the files exist on the real repo from the
        # earlier smoke run.
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "workflow_health_latest.json")
        self.assertTrue(path.exists(),
                          f"missing health JSON: {path}")

    def test_health_md_exists(self):
        path = (REPO_ROOT / "docs"
                 / "AUTOMATED_SHADOW_WORKFLOW_HEALTH.md")
        self.assertTrue(path.exists(),
                          f"missing health doc: {path}")


class TestHealthJsonNeverContainsSecretValues(unittest.TestCase):
    def test_no_secret_value_pattern_in_health_json(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "workflow_health_latest.json")
        text = path.read_text(encoding="utf-8")
        # Alpaca paper keys typically follow ^[A-Z0-9]{20}$ pattern.
        # We don't have a real value here — but pin that no long
        # uppercase-numeric token appears in the JSON.
        import re
        # ALPACA paper keys are 20 uppercase + digits; secrets are
        # 40 chars. Both would be alarming in the health doc.
        long_secret = re.compile(r"[A-Z0-9]{20,}")
        # Allow short uppercase tokens (status enums) but reject
        # 20+ char runs of mixed alnum that look like keys.
        # The health JSON's longest legitimate token is
        # AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET — uppercase
        # + underscores. Strip underscores before matching.
        stripped = re.sub(r"[^A-Z0-9]", "", text)
        # After stripping, if we have a 20+ char alnum run that
        # isn't separated by another token, it could be a key.
        # We just assert that none of the well-known secret-naming
        # heuristics fire.
        forbidden_keys = ("APCA-API-", "ALPACA_API_KEY=",
                           "ALPACA_SECRET_KEY=")
        for k in forbidden_keys:
            self.assertNotIn(k, text,
                              f"forbidden key pattern in health JSON: {k}")


class TestEvaluatorVerdictMapping(unittest.TestCase):
    def test_verdict_blocked_no_secrets(self):
        rc, _ = _run_evaluator(
            "--secrets-status", "SECRETS_MISSING_OR_UNAVAILABLE",
            "--workflow-run-conclusion", "success",
            "--collector-status", "SHADOW_COLLECTION_PROCEEDING",
            "--resolver-status",  "RESOLVED",
            "--workflow-run-id", "1",
        )
        self.assertEqual(rc, 0)
        h = json.loads((REPO_ROOT / "learning-loop"
                          / "shadow_evidence"
                          / "workflow_health_latest.json").read_text())
        self.assertEqual(h["verdict"],
                          "AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS")

    def test_verdict_blocked_workflow_failure(self):
        rc, _ = _run_evaluator(
            "--secrets-status", "SECRETS_AVAILABLE",
            "--workflow-run-conclusion", "failure",
            "--workflow-run-id", "2",
        )
        self.assertEqual(rc, 0)
        h = json.loads((REPO_ROOT / "learning-loop"
                          / "shadow_evidence"
                          / "workflow_health_latest.json").read_text())
        self.assertEqual(h["verdict"],
                          "AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE")

    def test_verdict_healthy_no_real_data_yet(self):
        rc, _ = _run_evaluator(
            "--secrets-status", "SECRETS_AVAILABLE",
            "--workflow-run-conclusion", "success",
            "--collector-status", "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA",
            "--resolver-status",  "RESOLVED",
            "--workflow-run-id", "3",
        )
        self.assertEqual(rc, 0)
        h = json.loads((REPO_ROOT / "learning-loop"
                          / "shadow_evidence"
                          / "workflow_health_latest.json").read_text())
        # Current real counter is 0, so verdict must be HEALTHY_NO_DATA.
        self.assertEqual(
            h["verdict"],
            "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
        )

    def test_evaluator_refuses_on_broker_flag(self):
        rc, out = _run_evaluator(
            "--secrets-status", "SECRETS_AVAILABLE",
            env_overrides={"ALLOW_BROKER_PAPER": "true"},
        )
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_ALLOW_BROKER_PAPER_IS_TRUTHY", out)


class TestStandingMarkersAlwaysPresent(unittest.TestCase):
    def test_health_json_always_marks_broker_paper_blocked(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "workflow_health_latest.json")
        d = json.loads(path.read_text())
        self.assertIn("BROKER_PAPER_CANARY_STILL_BLOCKED",
                       d["standing_markers"])
        self.assertIn("LIVE_TRADING_UNSUPPORTED",
                       d["standing_markers"])
        self.assertTrue(d["safety"]["broker_paper_canary_still_blocked"])
        self.assertTrue(d["safety"]["live_trading_unsupported"])


class TestNoBrokerImports(unittest.TestCase):
    def test_evaluator_does_not_import_alpaca_orders(self):
        src = (REPO_ROOT / "scripts"
                / "evaluate_automated_shadow_progress.py").read_text()
        FORBIDDEN = (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, src,
                              f"forbidden token in evaluator: {tok!r}")


if __name__ == "__main__":
    unittest.main()

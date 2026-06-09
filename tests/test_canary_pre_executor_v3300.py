"""v3.30 (2026-06-09) — canary pre-executor gate matrix."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _SandboxedRepo(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "configs").mkdir(parents=True, exist_ok=True)
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        (self.tmp / "configs" / "broker_paper_canary.json"
         ).write_text(real_cfg.read_text(encoding="utf-8"),
                       encoding="utf-8")
        self._patcher = mock.patch(
            "broker_paper_canary_preflight.REPO_ROOT", self.tmp)
        self._patcher.start()
        self._env = mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "false",
            "BROKER_PAPER_CANARY_EXECUTION_ENABLED": "false",
            "CANARY_DRY_RUN": "true",
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED":  "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
        }, clear=False)
        self._env.start()

    def tearDown(self):
        self._patcher.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRefusalCascade(_SandboxedRepo):

    def test_refuses_on_live_flag(self):
        import broker_paper_canary_preflight as pf
        os.environ["LIVE_TRADING"] = "true"
        try:
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=False)
        finally:
            os.environ["LIVE_TRADING"] = "false"
        self.assertEqual(rep.verdict,
                          pf.CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY)

    def test_refuses_on_broker_flag(self):
        import broker_paper_canary_preflight as pf
        os.environ["EDGE_GATE_ENABLED"] = "true"
        try:
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=False)
        finally:
            os.environ["EDGE_GATE_ENABLED"] = "false"
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY)

    def test_dry_run_returns_dry_run_ok_with_default_env(self):
        import broker_paper_canary_preflight as pf
        rep = pf.run_preflight(
            unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
            dry_run_only=True)
        self.assertEqual(rep.verdict,
                          pf.CANARY_PREFLIGHT_DRY_RUN_OK)

    def test_dry_run_false_refuses_when_execution_flag_off(self):
        import broker_paper_canary_preflight as pf
        rep = pf.run_preflight(
            unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
            dry_run_only=False)
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE)

    def test_refuses_when_unlock_not_ready(self):
        import broker_paper_canary_preflight as pf
        os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "true"
        os.environ["CANARY_DRY_RUN"] = "false"
        try:
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK",
                dry_run_only=False)
        finally:
            os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "false"
            os.environ["CANARY_DRY_RUN"] = "true"
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY)

    def test_refuses_when_operator_not_approved(self):
        import broker_paper_canary_preflight as pf
        os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "true"
        os.environ["CANARY_DRY_RUN"] = "false"
        try:
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=False)
        finally:
            os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "false"
            os.environ["CANARY_DRY_RUN"] = "true"
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL)

    def test_all_gates_green_returns_order_placement_deferred(self):
        import broker_paper_canary_preflight as pf
        os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "true"
        os.environ["CANARY_DRY_RUN"] = "false"
        os.environ["OPERATOR_APPROVED_BROKER_PAPER_CANARY"] = "true"
        try:
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=False)
        finally:
            os.environ["BROKER_PAPER_CANARY_EXECUTION_ENABLED"] = "false"
            os.environ["CANARY_DRY_RUN"] = "true"
            os.environ["OPERATOR_APPROVED_BROKER_PAPER_CANARY"] = "false"
        self.assertEqual(
            rep.verdict,
            pf.CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED,
            "v3.30 must STOP at the pre-executor — never advance to "
            "an order placement state")


class TestConfigLimitsValidation(_SandboxedRepo):

    def test_refuses_when_max_orders_per_day_too_high(self):
        import broker_paper_canary_preflight as pf
        cfg = self.tmp / "configs" / "broker_paper_canary.json"
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d["max_orders_per_day"] = 5
        cfg.write_text(json.dumps(d), encoding="utf-8")
        rep = pf.run_preflight(
            unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
            dry_run_only=True)
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID)

    def test_refuses_when_notional_cap_too_high(self):
        import broker_paper_canary_preflight as pf
        cfg = self.tmp / "configs" / "broker_paper_canary.json"
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d["max_notional_per_order_usd"] = 100
        cfg.write_text(json.dumps(d), encoding="utf-8")
        rep = pf.run_preflight(
            unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
            dry_run_only=True)
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID)

    def test_refuses_when_crypto_or_options_enabled(self):
        import broker_paper_canary_preflight as pf
        for k in ("crypto_enabled", "options_enabled"):
            cfg = self.tmp / "configs" / "broker_paper_canary.json"
            d = json.loads(cfg.read_text(encoding="utf-8"))
            d[k] = True
            cfg.write_text(json.dumps(d), encoding="utf-8")
            rep = pf.run_preflight(
                unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
                dry_run_only=True)
            self.assertEqual(
                rep.verdict,
                pf.CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID)
            d[k] = False
            cfg.write_text(json.dumps(d), encoding="utf-8")

    def test_refuses_when_canary_execution_flag_present_false(self):
        import broker_paper_canary_preflight as pf
        cfg = self.tmp / "configs" / "broker_paper_canary.json"
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d["canary_execution_flag_present"] = False
        cfg.write_text(json.dumps(d), encoding="utf-8")
        rep = pf.run_preflight(
            unlock_status="BROKER_PAPER_CANARY_UNLOCK_READY",
            dry_run_only=True)
        self.assertEqual(
            rep.verdict,
            pf.CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE)


if __name__ == "__main__":
    unittest.main()

"""v3.27.0 — Tests for scripts/seed_strategy_variant_quarantine.py.

Hard-safety invariants verified here:
- Variant ``allowed_modes`` never includes ``live`` / ``paper`` / ``broker_paper``.
- Seeder rejects when caller passes a forbidden runtime mode.
- Every registered variant starts at status ``QUARANTINED`` (per v3.20 mapping).
- ``promotion_criteria`` is present and non-trivial.
- Variants NEVER enter the active strategy registry — calling
  ``promote_variant_to_active`` raises ``NotImplementedError`` by design.
- Seeder does NOT import alpaca_orders. Seeder does NOT touch network.
- ``created_from`` is stamped on each persisted record.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = (REPO_ROOT / "scripts"
               / "seed_strategy_variant_quarantine.py")
SHARED_PATH = REPO_ROOT / "shared"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

import seed_strategy_variant_quarantine as ssv  # noqa: E402


def _reload_quarantine_module():
    """Pick up VARIANT_QUARANTINE_DIR env override fresh."""
    if "strategy_variant_quarantine" in sys.modules:
        del sys.modules["strategy_variant_quarantine"]
    return importlib.import_module("strategy_variant_quarantine")


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")

    def test_no_network_imports(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in ("import requests", "from requests",
                          "import urllib", "from urllib"):
            self.assertNotIn(forbidden, text)


class TestAllowedModesRejection(unittest.TestCase):
    def test_seeder_refuses_live_mode(self):
        with self.assertRaises(ValueError):
            ssv.build_variants(allowed_modes=("replay", "live"))

    def test_seeder_refuses_paper_mode(self):
        with self.assertRaises(ValueError):
            ssv.build_variants(allowed_modes=("paper",))

    def test_seeder_refuses_broker_paper_mode(self):
        with self.assertRaises(ValueError):
            ssv.build_variants(allowed_modes=("replay", "broker_paper"))


class TestPromotionAlwaysFails(unittest.TestCase):
    def test_promote_variant_to_active_raises(self):
        mod = _reload_quarantine_module()
        with self.assertRaises(NotImplementedError):
            mod.promote_variant_to_active("crypto-momentum--rsi_threshold_55")


class TestSeederHappyPath(unittest.TestCase):
    def test_seeds_four_variants(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["VARIANT_QUARANTINE_DIR"] = str(tmp_path / "qd")
            os.environ["VARIANT_QUARANTINE_JSONL_DIR"] = str(
                tmp_path / "qd_jsonl"
            )
            try:
                quarantine = _reload_quarantine_module()
                if "seed_strategy_variant_quarantine" in sys.modules:
                    del sys.modules["seed_strategy_variant_quarantine"]
                import seed_strategy_variant_quarantine as ssv2

                records, errors = ssv2.build_variants(
                    quarantine_module=quarantine
                )
                self.assertEqual(errors, [])
                # The spec list is the source of truth for count.
                self.assertEqual(len(records), len(ssv2.VARIANT_SPECS))

                for r in records:
                    self.assertIn(r["status"], (
                        quarantine.QUARANTINED,
                        "QUARANTINED",
                    ))
                    # allowed_modes never contains live/paper.
                    self.assertEqual(
                        set(r.get("allowed_modes", [])) & {
                            "live", "paper", "broker_paper"
                        }, set()
                    )
                    # promotion_criteria_detail has min_replay_n.
                    pd = r.get("promotion_criteria_detail", {})
                    self.assertIsInstance(pd, dict)
                    self.assertIn("min_replay_n", pd)
                    self.assertGreaterEqual(pd["min_replay_n"], 1)
                    # created_from stamped.
                    self.assertIn("created_from", r)
                    self.assertTrue(r["created_from"])
            finally:
                os.environ.pop("VARIANT_QUARANTINE_DIR", None)
                os.environ.pop("VARIANT_QUARANTINE_JSONL_DIR", None)


class TestNoNetwork(unittest.TestCase):
    def test_seeder_does_not_open_socket(self):
        opens: list[str] = []

        def fake_connect(self, address):
            opens.append(str(address))
            raise AssertionError(
                f"seeder attempted network connect to {address!r}"
            )
        with mock.patch.object(socket.socket, "connect", fake_connect):
            with TemporaryDirectory() as tmp:
                os.environ["VARIANT_QUARANTINE_DIR"] = str(
                    Path(tmp) / "qd"
                )
                os.environ["VARIANT_QUARANTINE_JSONL_DIR"] = str(
                    Path(tmp) / "qd_jsonl"
                )
                try:
                    quarantine = _reload_quarantine_module()
                    if "seed_strategy_variant_quarantine" in sys.modules:
                        del sys.modules[
                            "seed_strategy_variant_quarantine"
                        ]
                    import seed_strategy_variant_quarantine as ssv2
                    records, errors = ssv2.build_variants(
                        quarantine_module=quarantine
                    )
                finally:
                    os.environ.pop("VARIANT_QUARANTINE_DIR", None)
                    os.environ.pop("VARIANT_QUARANTINE_JSONL_DIR", None)
        self.assertEqual(opens, [])
        self.assertEqual(errors, [])
        self.assertGreater(len(records), 0)


class TestStatusStartsQuarantined(unittest.TestCase):
    def test_every_variant_starts_quarantined(self):
        for spec in ssv.VARIANT_SPECS:
            # Spec hardcoded status from the seeder build is QUARANTINED.
            self.assertNotEqual(
                "PAPER_APPROVED", spec.get("status", ""),
            )
            self.assertNotEqual(
                "LIVE_APPROVED", spec.get("status", ""),
            )


class TestCreatedFrom(unittest.TestCase):
    def test_created_from_documented(self):
        # Default is non-empty, and is the threshold_reality + near_miss path.
        with TemporaryDirectory() as tmp:
            os.environ["VARIANT_QUARANTINE_DIR"] = str(Path(tmp) / "qd")
            os.environ["VARIANT_QUARANTINE_JSONL_DIR"] = str(
                Path(tmp) / "qd_jsonl"
            )
            try:
                quarantine = _reload_quarantine_module()
                if "seed_strategy_variant_quarantine" in sys.modules:
                    del sys.modules["seed_strategy_variant_quarantine"]
                import seed_strategy_variant_quarantine as ssv2
                records, _ = ssv2.build_variants(quarantine_module=quarantine)
                for r in records:
                    self.assertIn(
                        "threshold_reality",
                        r.get("change_rationale", "")
                        + r.get("created_from", "")
                    )
            finally:
                os.environ.pop("VARIANT_QUARANTINE_DIR", None)
                os.environ.pop("VARIANT_QUARANTINE_JSONL_DIR", None)


class TestVariantsCannotReachLiveByDataclass(unittest.TestCase):
    def test_validate_allowed_modes_refuses_live(self):
        quarantine = _reload_quarantine_module()
        bad = quarantine.StrategyVariant(
            variant_id="x",
            parent_strategy_id="crypto-momentum",
            description="bad",
            rationale="should refuse",
            promotion_criteria={"min_replay_n": 30},
            rejection_criteria={},
            allowed_modes=("live",),
            status="QUARANTINED",
        )
        with self.assertRaises(ValueError):
            quarantine.validate_allowed_modes(bad)


if __name__ == "__main__":
    unittest.main()

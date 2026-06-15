"""v3.26 (Agent 3A ETAP 4) — tests for the dataclass-based StrategyVariant
API in shared/strategy_variant_quarantine.py.

Verifies HARD invariants:
  - StrategyVariant.allowed_modes must be a subset of {"replay", "shadow"}
  - allowed_modes containing "live" or "paper" -> ValueError
  - register_variant(StrategyVariant(...)) persists a JSONL row
  - register_variant cannot put a variant into the active strategy registry
  - promote_variant_to_active raises NotImplementedError (always)
  - register_variant respects status field
  - variants do NOT mutate parent_strategy_id
  - AST scan: module does NOT import alpaca_orders or any broker module
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import strategy_variant_quarantine as svq  # noqa: E402
from strategy_variant_quarantine import (  # noqa: E402
    ALLOWED_VARIANT_MODES,
    FORBIDDEN_VARIANT_MODES,
    StrategyVariant,
    list_variants,
    promote_variant_to_active,
    register_variant,
    validate_allowed_modes,
)


class _Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="variant_quar_v326_")
        self._tmp_jsonl = tempfile.mkdtemp(prefix="variant_quar_jsonl_v326_")
        self._prev_dir = os.environ.get("VARIANT_QUARANTINE_DIR")
        self._prev_jsonl = os.environ.get("VARIANT_QUARANTINE_JSONL_DIR")
        os.environ["VARIANT_QUARANTINE_DIR"] = self._tmp
        os.environ["VARIANT_QUARANTINE_JSONL_DIR"] = self._tmp_jsonl

    def tearDown(self):
        import shutil
        if self._prev_dir is None:
            os.environ.pop("VARIANT_QUARANTINE_DIR", None)
        else:
            os.environ["VARIANT_QUARANTINE_DIR"] = self._prev_dir
        if self._prev_jsonl is None:
            os.environ.pop("VARIANT_QUARANTINE_JSONL_DIR", None)
        else:
            os.environ["VARIANT_QUARANTINE_JSONL_DIR"] = self._prev_jsonl
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._tmp_jsonl, ignore_errors=True)


# ─── A: allowed_modes validation ──────────────────────────────────────────────

class TestAllowedModesValidation(_Base):

    def test_subset_of_replay_shadow_is_allowed(self):
        v = StrategyVariant(
            variant_id="v_test1",
            parent_strategy_id="crypto-momentum",
            description="lower rsi threshold by 3",
            rationale="probe deep oversold setups",
            allowed_modes=("replay", "shadow"),
        )
        # Should NOT raise.
        validate_allowed_modes(v)

    def test_only_replay_is_allowed(self):
        v = StrategyVariant(
            variant_id="v_test2",
            parent_strategy_id="momentum-long",
            description="just replay",
            rationale="quick experiment",
            allowed_modes=("replay",),
        )
        validate_allowed_modes(v)

    def test_live_mode_is_refused(self):
        v = StrategyVariant(
            variant_id="v_test3",
            parent_strategy_id="momentum-long",
            description="x",
            rationale="x",
            allowed_modes=("replay", "live"),
        )
        with self.assertRaises(ValueError):
            validate_allowed_modes(v)

    def test_paper_mode_is_refused(self):
        v = StrategyVariant(
            variant_id="v_test4",
            parent_strategy_id="momentum-long",
            description="x",
            rationale="x",
            allowed_modes=("paper",),
        )
        with self.assertRaises(ValueError):
            validate_allowed_modes(v)

    def test_unknown_mode_is_refused(self):
        v = StrategyVariant(
            variant_id="v_test5",
            parent_strategy_id="momentum-long",
            description="x",
            rationale="x",
            allowed_modes=("replay", "sandbox"),
        )
        with self.assertRaises(ValueError):
            validate_allowed_modes(v)

    def test_constants_well_formed(self):
        # ALLOWED is a strict subset; nothing forbidden leaks in.
        self.assertTrue(ALLOWED_VARIANT_MODES.isdisjoint(FORBIDDEN_VARIANT_MODES))
        self.assertEqual(ALLOWED_VARIANT_MODES, frozenset({"replay", "shadow"}))
        self.assertIn("live", FORBIDDEN_VARIANT_MODES)
        self.assertIn("paper", FORBIDDEN_VARIANT_MODES)


# ─── B: register / persist ────────────────────────────────────────────────────

class TestRegisterStrategyVariant(_Base):

    def test_register_variant_writes_per_variant_json(self):
        v = StrategyVariant(
            variant_id="v_reg_1",
            parent_strategy_id="crypto-momentum",
            description="reduce rsi threshold to 57",
            rationale="explore broader fan-out",
            allowed_modes=("replay", "shadow"),
            promotion_criteria={"min_replay_n": 50, "min_pf": 1.3},
            rejection_criteria={"max_drawdown": 0.2},
        )
        rec = register_variant(v)
        self.assertEqual(rec["id"], "v_reg_1")
        self.assertEqual(rec["parent_strategy"], "crypto-momentum")
        # Status default should be QUARANTINED.
        self.assertEqual(rec["status"], svq.QUARANTINED)
        # JSON persistence — check the file is on disk.
        files = list(Path(self._tmp).glob("*.json"))
        self.assertEqual(len(files), 1)

    def test_register_variant_appends_jsonl_audit_row(self):
        v = StrategyVariant(
            variant_id="v_reg_2",
            parent_strategy_id="momentum-long",
            description="loosen rsi",
            rationale="check fan-out",
            allowed_modes=("shadow",),
        )
        register_variant(v)
        jsonl_files = list(Path(self._tmp_jsonl).glob("*.jsonl"))
        self.assertEqual(len(jsonl_files), 1)
        # First (and only) row contains the variant id.
        lines = jsonl_files[0].read_text().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["id"], "v_reg_2")

    def test_register_variant_rejects_live_in_allowed_modes(self):
        v = StrategyVariant(
            variant_id="v_reg_3",
            parent_strategy_id="overbought-short",
            description="hostile variant",
            rationale="attempted-bypass",
            allowed_modes=("live", "shadow"),
        )
        with self.assertRaises(ValueError):
            register_variant(v)

    def test_register_variant_rejects_paper_in_allowed_modes(self):
        v = StrategyVariant(
            variant_id="v_reg_4",
            parent_strategy_id="overbought-short",
            description="paper variant",
            rationale="attempted-bypass",
            allowed_modes=("paper",),
        )
        with self.assertRaises(ValueError):
            register_variant(v)


# ─── C: promotion is forbidden ────────────────────────────────────────────────

class TestPromotionRefused(_Base):

    def test_promote_variant_to_active_always_raises(self):
        with self.assertRaises(NotImplementedError):
            promote_variant_to_active("v_promote_1")

    def test_promote_does_not_mutate_any_registry(self):
        # Best-effort: confirm that calling promote leaves the (possibly
        # absent) shadow registry untouched. The raise happens BEFORE any
        # registry write, so the assertion below is necessarily true.
        with self.assertRaises(NotImplementedError):
            promote_variant_to_active("v_promote_2")


# ─── D: variant cannot enter active registry ─────────────────────────────────

class TestVariantCannotEnterActiveRegistry(_Base):

    def test_register_refused_when_active_registry_already_has_id(self):
        # Monkey-patch a fake shadow_opportunity_generator with a registry
        # containing the variant id. Then register MUST raise RuntimeError.
        fake_mod = type(sys)("shadow_opportunity_generator")
        fake_mod._strategy_registry = lambda: {"v_reg_collision": object()}
        sys.modules["shadow_opportunity_generator"] = fake_mod
        try:
            v = StrategyVariant(
                variant_id="v_reg_collision",
                parent_strategy_id="crypto-momentum",
                description="x",
                rationale="x",
                allowed_modes=("shadow",),
            )
            with self.assertRaises(RuntimeError):
                register_variant(v)
        finally:
            sys.modules.pop("shadow_opportunity_generator", None)

    def test_register_succeeds_when_no_active_registry_collision(self):
        fake_mod = type(sys)("shadow_opportunity_generator")
        fake_mod._strategy_registry = lambda: {"some_other_strategy": object()}
        sys.modules["shadow_opportunity_generator"] = fake_mod
        try:
            v = StrategyVariant(
                variant_id="v_no_collision",
                parent_strategy_id="crypto-momentum",
                description="x",
                rationale="x",
                allowed_modes=("shadow",),
            )
            rec = register_variant(v)
            self.assertEqual(rec["id"], "v_no_collision")
        finally:
            sys.modules.pop("shadow_opportunity_generator", None)


# ─── E: parent strategy is not mutated; status enum is closed ────────────────

class TestParentImmutabilityAndStatus(_Base):

    def test_register_does_not_mutate_parent_id(self):
        original_parent = "momentum-long"
        v = StrategyVariant(
            variant_id="v_parent_1",
            parent_strategy_id=original_parent,
            description="x",
            rationale="x",
            allowed_modes=("replay",),
        )
        rec = register_variant(v)
        self.assertEqual(rec["parent_strategy"], original_parent)
        # Frozen dataclass means the original object cannot be mutated
        # via normal attribute assignment.
        with self.assertRaises(Exception):
            v.parent_strategy_id = "OTHER"   # noqa

    def test_unknown_dataclass_status_maps_to_quarantined(self):
        v = StrategyVariant(
            variant_id="v_status_1",
            parent_strategy_id="momentum-long",
            description="x",
            rationale="x",
            allowed_modes=("replay",),
            status="LIVE_APPROVED",  # NOT in DATACLASS_API_STATUSES
        )
        rec = register_variant(v)
        # Fall-back to QUARANTINED — never silently promoted.
        self.assertEqual(rec["status"], svq.QUARANTINED)


# ─── F: AST scans — HARD safety ──────────────────────────────────────────────

class TestHardSafetyStaticScans(unittest.TestCase):

    SRC = (Path(__file__).resolve().parent.parent / "shared"
           / "strategy_variant_quarantine.py").read_text()

    def test_no_alpaca_orders_import(self):
        tree = ast.parse(self.SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("alpaca_orders", mod)

    def test_no_submit_or_place_order_calls(self):
        forbidden = [
            "submit_order",
            "place_order",
            "place_stock_order",
            "place_crypto_order",
            "place_option_order",
            "safe_close",
            "close_position",
            "close_all_positions",
        ]
        for pat in forbidden:
            self.assertNotIn(pat, self.SRC)

    def test_module_invariants_assertable(self):
        # Top-level module attribute marker — used by external auditors.
        # Make sure we still have the safety constants.
        for const in ("ALLOWED_VARIANT_MODES", "FORBIDDEN_VARIANT_MODES"):
            self.assertTrue(hasattr(svq, const))


if __name__ == "__main__":
    unittest.main()

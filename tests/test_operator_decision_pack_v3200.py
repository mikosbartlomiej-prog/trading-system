"""v3.20 (2026-06-04) — Operator Decision Pack tests (ETAP 10).

Consolidation pack must:
- Generate without crash on empty state
- Show EDGE_GATE answer = NO when paper_trade_count = 0
- Render markdown with all 10 spec sections
- NOT recommend live trading
- NOT mutate any state
- Honor --no-write flag (stdout only)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestDecisionPackBuilds(unittest.TestCase):
    def setUp(self):
        # Re-import to pick up local-state changes between tests
        for mod in ("operator_decision_pack",):
            sys.modules.pop(mod, None)

    def test_build_decision_pack_returns_dict(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        self.assertIsInstance(pack, dict)
        self.assertEqual(pack["version"], "v3.20.0")

    def test_all_11_sections_present(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        for n in range(1, 12):
            key_prefix = f"section_{n}_"
            self.assertTrue(
                any(k.startswith(key_prefix) for k in pack.keys()),
                f"missing section {n} in decision pack",
            )

    def test_invariants_block_live_and_edge_gate(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        inv = pack["invariants"]
        self.assertTrue(inv["live_trading_disabled"])
        self.assertFalse(inv["edge_gate_enabled"])
        self.assertTrue(inv["no_promises_of_profit"])
        self.assertTrue(inv["evidence_sources_segregated"])
        self.assertTrue(inv["agents_review_only"])
        self.assertTrue(inv["no_paid_services"])

    def test_edge_gate_answer_is_no_when_no_paper_evidence(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        eg = pack["section_11_edge_gate_answer"]
        self.assertFalse(eg["can_flip_to_true_now"])
        self.assertIn("NO", eg["answer"])
        # Must list at least one blocker
        self.assertGreater(len(eg["blockers"]), 0)

    def test_markdown_renders_with_all_sections(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        md = odp.render_markdown(pack)
        for header in [
            "## 1. What should the system observe tomorrow?",
            "## 2. Which strategies look most promising?",
            "## 3. Which strategies look weakest?",
            "## 4. Which gates protect well?",
            "## 5. Which gates may be over-conservative?",
            "## 6. Where is data missing?",
            "## 7. Does any strategy variant deserve replay?",
            "## 8. Can EDGE_GATE flip to true?",
            "## 9. Why not?",
            "## 10. Is the system still safe / free / paper-only?",
        ]:
            self.assertIn(header, md, f"missing section: {header}")

    def test_markdown_does_not_recommend_live_trading(self):
        import operator_decision_pack as odp
        pack = odp.build_decision_pack()
        md = odp.render_markdown(pack)
        # Must NOT contain affirmative live trading prompts
        forbidden = [
            "recommend live trading",
            "switch to live",
            "enable live",
            "LIVE_APPROVED",
        ]
        for phrase in forbidden:
            self.assertNotIn(phrase.lower(), md.lower(), f"forbidden phrase present: {phrase}")


class TestCLIBehavior(unittest.TestCase):

    def test_no_write_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                ["python3", str(REPO_ROOT / "scripts" / "operator_decision_pack.py"), "--no-write"],
                capture_output=True, text=True, timeout=30,
                cwd=str(tmp_path),
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr[:500]}")
            # CWD-local docs/ must not exist
            self.assertFalse((tmp_path / "docs" / "operator_decision_pack_LATEST.md").exists())

    def test_no_write_json_outputs_valid_json(self):
        result = subprocess.run(
            ["python3", str(REPO_ROOT / "scripts" / "operator_decision_pack.py"),
             "--no-write", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr[:500]}")
        # First parseable JSON object
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout is not valid JSON: {e}; first 200 chars: {result.stdout[:200]}")
        self.assertEqual(data["version"], "v3.20.0")
        self.assertFalse(data["invariants"]["edge_gate_enabled"])


class TestReadOnlyContract(unittest.TestCase):
    """Decision pack must NEVER touch runtime_state or strategy config."""

    def test_does_not_import_alpaca_orders(self):
        # Read the module source — should not import alpaca_orders
        src = (REPO_ROOT / "scripts" / "operator_decision_pack.py").read_text()
        for forbidden in ["from alpaca_orders", "import alpaca_orders", "place_stock_bracket", "place_crypto_order"]:
            self.assertNotIn(forbidden, src, f"forbidden import/call: {forbidden}")

    def test_does_not_mutate_state_json(self):
        src = (REPO_ROOT / "scripts" / "operator_decision_pack.py").read_text()
        # No write_section, no save_state, no state.json modifications
        for forbidden in ["write_section(", "save_state(", "merge_section("]:
            self.assertNotIn(forbidden, src, f"forbidden mutation: {forbidden}")


if __name__ == "__main__":
    unittest.main()

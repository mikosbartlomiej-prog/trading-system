"""v3.22.0 (2026-06-15) — Per-monitor wiring test: options-monitor.

We verify the wiring contract via source-code inspection rather than a
module-level import. Reason: options-monitor uses PEP 604 ``dict | None``
syntax (no ``from __future__ import annotations``) so a full import is
not portable to Python 3.9. The shipping CI runs 3.11; here we keep the
test 3.9-compatible.

What we assert:
  1. The shared emitter is imported in the module.
  2. The emit call uses ``source_monitor="options-monitor"``.
  3. The emit happens BEFORE the broker dispatch in the proposal loop.
"""

from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MONITOR_PATH = os.path.join(REPO_ROOT, "options-monitor", "monitor.py")


def _read() -> str:
    with open(MONITOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestOptionsMonitorWiring(unittest.TestCase):

    def test_emit_helper_imported(self) -> None:
        src = _read()
        self.assertIn("from monitor_signal_helper import emit_monitor_signal", src,
            "options-monitor must import emit_monitor_signal from the shared helper")

    def test_emit_uses_correct_source_monitor(self) -> None:
        src = _read()
        self.assertIn("source_monitor=\"options-monitor\"", src,
            "emit call in options-monitor must set source_monitor=\"options-monitor\"")

    def test_emit_happens_before_execute_proposal_in_loop(self) -> None:
        """In the proposal loop, the emit must come BEFORE execute_proposal."""
        src = _read()
        # Find the for-loop over proposals.
        loop_idx = src.find("for proposal in proposals:")
        self.assertGreater(loop_idx, 0, "expected 'for proposal in proposals:' loop")
        loop_body = src[loop_idx:loop_idx + 4000]
        emit_idx = loop_body.find("emit_monitor_signal(")
        exec_idx = loop_body.find("execute_proposal(")
        self.assertGreater(emit_idx, 0, "emit_monitor_signal not found in proposal loop")
        self.assertGreater(exec_idx, 0, "execute_proposal not found in proposal loop")
        self.assertLess(emit_idx, exec_idx,
            "emit_monitor_signal must be called BEFORE execute_proposal "
            "so the ledger captures intent even when the broker rejects")

    def test_entry_capable_is_true_for_options(self) -> None:
        src = _read()
        # Look for entry_capable=True in the emit block.
        loop_idx = src.find("for proposal in proposals:")
        block = src[loop_idx:loop_idx + 4000]
        self.assertIn("entry_capable=True", block,
            "options-monitor emit must mark entry_capable=True for proposal signals")


if __name__ == "__main__":
    unittest.main()

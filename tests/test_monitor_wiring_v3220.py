"""v3.22.0 (2026-06-15) — ETAP 4 — Monitor wiring audit tests.

These tests scan every monitor file under the 10 monitor directories and
assert two structural properties:

1. Each monitor either imports / references ``emit_signal_opportunity``
   (directly or via the ``emit_monitor_signal`` thin wrapper) OR carries
   the documented ``NOT_APPLICABLE`` header.
2. No monitor imports ``alpaca_orders`` from inside an ``emit_*`` helper
   it just added. The emit path must be observability-only.

These tests are deliberately AST-light so they tolerate minor refactors:
they look for substrings inside the file source rather than parsed
identifiers. The point is to guard against regression of the v3.22
wiring contract, not to verify the exact AST shape.

Run:
    python3 -m unittest tests.test_monitor_wiring_v3220 -v
"""

from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


MONITORS = [
    ("price-monitor",         "monitor.py"),
    ("options-monitor",       "monitor.py"),
    ("crypto-monitor",        "monitor.py"),
    ("defense-monitor",       "monitor.py"),
    ("twitter-monitor",       "monitor.py"),
    ("reddit-monitor",        "monitor.py"),
    ("geo-monitor",           "monitor.py"),
    ("politician-monitor",    "monitor.py"),
    ("exit-monitor",          "monitor.py"),
    ("options-exit-monitor",  "monitor.py"),
]


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _emit_path_present(src: str) -> bool:
    return (
        "emit_signal_opportunity" in src
        or "emit_monitor_signal" in src
        or "NOT_APPLICABLE" in src
    )


class TestMonitorWiring(unittest.TestCase):
    """Verify each monitor is wired into the v3.22 emit path."""

    def test_each_monitor_imports_emit_or_marks_not_applicable(self) -> None:
        missing: list[str] = []
        for folder, fname in MONITORS:
            path = os.path.join(REPO_ROOT, folder, fname)
            self.assertTrue(
                os.path.exists(path),
                f"Expected monitor file to exist: {path}",
            )
            src = _read(path)
            if not _emit_path_present(src):
                missing.append(folder)
        self.assertFalse(
            missing,
            f"Monitors lacking emit_signal_opportunity / emit_monitor_signal / "
            f"NOT_APPLICABLE marker: {missing}",
        )

    def test_shared_helper_does_not_import_alpaca_orders(self) -> None:
        """The cross-monitor helper itself must not import alpaca_orders.

        Per-monitor execute functions DO import alpaca_orders intentionally —
        the broker path is separate from the observability path. The contract
        in the spec is about the SHARED EMIT HELPER, which is invoked by all
        monitors and must never be a broker-call entry point.
        """
        path = os.path.join(REPO_ROOT, "shared", "monitor_signal_helper.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # AST-level scan: parse the helper, look for any import / Call that
        # references the alpaca_orders module.
        import ast
        tree = ast.parse(src)
        bad_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "alpaca_orders" in node.module:
                    bad_imports.append(f"from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "alpaca_orders" in (alias.name or ""):
                        bad_imports.append(f"import {alias.name}")
        self.assertFalse(
            bad_imports,
            f"shared/monitor_signal_helper.py imports alpaca_orders: "
            f"{bad_imports}. The emit path must be observability-only.",
        )

    def test_emit_path_never_calls_broker_functions(self) -> None:
        """The shared helper must not call submit_order / place_order /
        safe_close / place_stock_bracket / place_crypto_order /
        place_simple_buy / place_option_order / close_position /
        close_all_positions.
        """
        path = os.path.join(REPO_ROOT, "shared", "monitor_signal_helper.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        forbidden = {
            "submit_order", "place_order", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_option_order",
            "close_position", "close_all_positions",
        }
        bad_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in forbidden:
                    bad_calls.append(name)
        self.assertFalse(
            bad_calls,
            f"shared/monitor_signal_helper.py calls broker functions: "
            f"{bad_calls}. The emit path must be observability-only.",
        )

    def test_shared_emit_helper_exists(self) -> None:
        """shared/monitor_signal_helper.py must exist and expose
        emit_monitor_signal."""
        path = os.path.join(REPO_ROOT, "shared", "monitor_signal_helper.py")
        self.assertTrue(
            os.path.exists(path),
            "shared/monitor_signal_helper.py missing — the wiring relies "
            "on this thin wrapper."
        )
        src = _read(path)
        self.assertIn("def emit_monitor_signal", src)
        # Helper must NOT import alpaca_orders.
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("import alpaca_orders", src)


if __name__ == "__main__":
    unittest.main()

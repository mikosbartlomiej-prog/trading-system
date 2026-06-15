"""v3.24 (2026-06-15) — Unit tests for shared/monitor_runtime_diag.py.

Verifies the runtime diagnostic writer:

  * appends JSONL rows correctly
  * fails soft on permission errors / disk errors
  * exposes a frozen token enum
  * never imports alpaca_orders / never opens a network socket
  * the reporter script aggregates counts correctly
  * the reporter writes the standing markers footer
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


import monitor_runtime_diag  # noqa: E402
from monitor_runtime_diag import (   # noqa: E402
    DIAG_TOKENS,
    DIAG_RAN,
    DIAG_INPUT_EMPTY,
    DIAG_NO_SIGNAL,
    DIAG_SIGNAL_DETECTED,
    DIAG_EMIT_ATTEMPTED,
    DIAG_EMIT_SUCCESS,
    DIAG_EMIT_FAILED,
    record_diag,
)


class TestRecordDiag(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir_ctx.name)
        monitor_runtime_diag._set_diag_dir_for_tests(self.tmpdir)

    def tearDown(self) -> None:
        monitor_runtime_diag._set_diag_dir_for_tests(None)
        self._tmpdir_ctx.cleanup()

    def test_record_diag_writes_jsonl_row(self) -> None:
        ok = record_diag("crypto-monitor", DIAG_RAN, detail={"coins": 11})
        self.assertTrue(ok)
        files = list(self.tmpdir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        with open(files[0], encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monitor"], "crypto-monitor")
        self.assertEqual(rows[0]["token"], DIAG_RAN)
        self.assertEqual(rows[0]["detail"], {"coins": 11})
        self.assertIn("timestamp", rows[0])

    def test_record_diag_fail_soft_on_permission_error(self) -> None:
        # Patch open to raise PermissionError. record_diag must return
        # False and never propagate.
        with mock.patch("builtins.open",
                        side_effect=PermissionError("denied")):
            result = record_diag("crypto-monitor", DIAG_RAN)
        self.assertFalse(result)

    def test_record_diag_coerces_unknown_token(self) -> None:
        ok = record_diag("crypto-monitor", "BOGUS_TOKEN")
        self.assertTrue(ok)
        files = list(self.tmpdir.glob("*.jsonl"))
        with open(files[0], encoding="utf-8") as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec["token"], "UNKNOWN")

    def test_record_diag_non_jsonable_detail_coerced(self) -> None:
        class Unjsonable:
            def __repr__(self) -> str:
                return "<Unjsonable>"

        ok = record_diag("crypto-monitor", DIAG_RAN,
                         detail={"obj": Unjsonable()})
        self.assertTrue(ok)
        files = list(self.tmpdir.glob("*.jsonl"))
        with open(files[0], encoding="utf-8") as f:
            rec = json.loads(f.readline())
        # Coercion path → string repr present.
        self.assertIn("Unjsonable", str(rec["detail"]))


class TestTokenEnum(unittest.TestCase):
    def test_token_enum_complete(self) -> None:
        expected = {
            "RAN", "INPUT_EMPTY", "NO_SIGNAL", "SIGNAL_DETECTED",
            "EMIT_ATTEMPTED", "EMIT_SUCCESS", "EMIT_FAILED",
        }
        self.assertEqual(set(DIAG_TOKENS), expected)
        self.assertEqual(DIAG_RAN, "RAN")
        self.assertEqual(DIAG_INPUT_EMPTY, "INPUT_EMPTY")
        self.assertEqual(DIAG_NO_SIGNAL, "NO_SIGNAL")
        self.assertEqual(DIAG_SIGNAL_DETECTED, "SIGNAL_DETECTED")
        self.assertEqual(DIAG_EMIT_ATTEMPTED, "EMIT_ATTEMPTED")
        self.assertEqual(DIAG_EMIT_SUCCESS, "EMIT_SUCCESS")
        self.assertEqual(DIAG_EMIT_FAILED, "EMIT_FAILED")

    def test_diag_tokens_is_frozenset(self) -> None:
        self.assertIsInstance(DIAG_TOKENS, frozenset)
        # Frozensets reject mutation attempts (no .add).
        self.assertFalse(hasattr(DIAG_TOKENS, "add"))


class TestNoNetworkCall(unittest.TestCase):
    """Confirm record_diag never opens a network socket."""

    def setUp(self) -> None:
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir_ctx.name)
        monitor_runtime_diag._set_diag_dir_for_tests(self.tmpdir)

    def tearDown(self) -> None:
        monitor_runtime_diag._set_diag_dir_for_tests(None)
        self._tmpdir_ctx.cleanup()

    def test_no_network_call_during_record(self) -> None:
        original_connect = socket.socket.connect

        captured: list = []

        def trapped_connect(self, *args, **kwargs):  # type: ignore[no-self-argument]
            captured.append(("connect", args))
            raise RuntimeError("network call attempted during record_diag")

        try:
            socket.socket.connect = trapped_connect  # type: ignore[assignment]
            ok = record_diag("crypto-monitor", DIAG_RAN, detail={"x": 1})
            self.assertTrue(ok)
        finally:
            socket.socket.connect = original_connect  # type: ignore[assignment]
        self.assertEqual(captured, [])


class TestNeverImportsAlpacaOrders(unittest.TestCase):
    def test_monitor_runtime_diag_module_never_imports_alpaca_orders(self) -> None:
        src = (REPO_ROOT / "shared" / "monitor_runtime_diag.py").read_text()
        tree = ast.parse(src)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.append(n.name)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        offenders = [i for i in imports
                     if "alpaca_orders" in i or i.endswith("alpaca_orders")]
        self.assertEqual(offenders, [],
                         f"monitor_runtime_diag imports alpaca_orders: {offenders}")


class TestReporterAggregation(unittest.TestCase):
    """Verify the reporter script aggregates counts correctly + writes
    the standing markers footer."""

    def setUp(self) -> None:
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmproot = Path(self._tmpdir_ctx.name)
        # Lay out a fake repo: learning-loop/monitor_runtime_diag/<today>.jsonl
        self.diag_dir = self.tmproot / "learning-loop" / "monitor_runtime_diag"
        self.diag_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmpdir_ctx.cleanup()

    def _seed_today(self, rows: list[dict]) -> Path:
        from datetime import datetime, timezone as _tz
        today = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        fp = self.diag_dir / f"{today}.jsonl"
        with open(fp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return fp

    def test_reporter_aggregates_counts_correctly(self) -> None:
        # Use the reporter module's functions directly with our fake dir.
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        # Reload to pick up monkey-patched constants.
        if "build_monitor_runtime_diagnostics_report" in sys.modules:
            del sys.modules["build_monitor_runtime_diagnostics_report"]
        reporter = importlib.import_module(
            "build_monitor_runtime_diagnostics_report")
        # Point reporter at our fake repo root.
        reporter.REPO_ROOT = self.tmproot
        reporter.DIAG_DIR = self.diag_dir
        reporter.DOCS_OUT = self.tmproot / "docs" / "MONITOR_RUNTIME_DIAGNOSTICS.md"
        reporter.JSON_OUT = (self.tmproot / "learning-loop"
                             / "monitor_runtime_diag_status_latest.json")

        # Seed today's file with a mixed payload.
        self._seed_today([
            {"timestamp": "2026-06-15T10:00:00Z", "monitor": "crypto-monitor",
             "token": "RAN", "detail": {}},
            {"timestamp": "2026-06-15T10:00:01Z", "monitor": "crypto-monitor",
             "token": "EMIT_SUCCESS", "detail": {}},
            {"timestamp": "2026-06-15T10:00:02Z", "monitor": "crypto-monitor",
             "token": "EMIT_SUCCESS", "detail": {}},
            {"timestamp": "2026-06-15T10:05:00Z", "monitor": "price-monitor",
             "token": "RAN", "detail": {}},
            {"timestamp": "2026-06-15T10:05:01Z", "monitor": "price-monitor",
             "token": "NO_SIGNAL", "detail": {}},
        ])
        rc = reporter.main()
        self.assertEqual(rc, 0)

        payload = json.loads(reporter.JSON_OUT.read_text())
        per = payload["aggregate"]["per_monitor"]
        self.assertEqual(per["crypto-monitor"]["RAN"], 1)
        self.assertEqual(per["crypto-monitor"]["EMIT_SUCCESS"], 2)
        self.assertEqual(per["price-monitor"]["RAN"], 1)
        self.assertEqual(per["price-monitor"]["NO_SIGNAL"], 1)
        self.assertEqual(payload["aggregate"]["total_rows"], 5)

    def test_reporter_writes_standing_markers(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        if "build_monitor_runtime_diagnostics_report" in sys.modules:
            del sys.modules["build_monitor_runtime_diagnostics_report"]
        reporter = importlib.import_module(
            "build_monitor_runtime_diagnostics_report")
        reporter.REPO_ROOT = self.tmproot
        reporter.DIAG_DIR = self.diag_dir
        reporter.DOCS_OUT = self.tmproot / "docs" / "MONITOR_RUNTIME_DIAGNOSTICS.md"
        reporter.JSON_OUT = (self.tmproot / "learning-loop"
                             / "monitor_runtime_diag_status_latest.json")

        self._seed_today([
            {"timestamp": "2026-06-15T10:00:00Z", "monitor": "crypto-monitor",
             "token": "RAN", "detail": {}},
        ])

        rc = reporter.main()
        self.assertEqual(rc, 0)

        md = reporter.DOCS_OUT.read_text()
        # Must carry the standing markers footer.
        self.assertIn("HARD-SAFETY HELD", md)
        self.assertIn("NO BROKER CALL", md)
        self.assertIn("NO NETWORK CALL", md)
        self.assertIn("FREE OPERATION", md)
        self.assertIn("v3.24", md)

        # JSON payload also carries the marker block.
        payload = json.loads(reporter.JSON_OUT.read_text())
        self.assertEqual(payload["hard_safety"]["broker_call"], False)
        self.assertEqual(payload["hard_safety"]["network_call"], False)
        self.assertEqual(payload["hard_safety"]["paid_service"], False)


if __name__ == "__main__":
    unittest.main()

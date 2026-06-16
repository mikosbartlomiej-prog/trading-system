"""v3.29 ETAP 9 (2026-06-16) — Geo monitor health audit tests.

Asserts:
- heartbeat fresh → OK
- heartbeat stale during session → FAILED
- no EMIT_SUCCESS but heartbeat fresh → DEGRADED
- 80-day claim debunked when evidence does not support it
- AST: no alpaca_orders import
- No broker call (no network at all)
- Standing markers present
- audit generates GEO_MONITOR_HEALTH_STATUS.md
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_script():
    p = _REPO_ROOT / "scripts" / "audit_geo_monitor_health.py"
    spec = importlib.util.spec_from_file_location(
        "audit_geo_monitor_health", p)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["audit_geo_monitor_health"] = m
    spec.loader.exec_module(m)
    return m


class TestVerdictFromInputs(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_heartbeat_fresh_yields_ok(self):
        hb = {"ok": True, "age_seconds": 30,
              "last_seen_iso": "2026-06-16T00:00:00+00:00",
              "status": "FRESH"}
        diag = {"available": True, "RAN": 5,
                "EMIT_SUCCESS": 2, "EMIT_FAILED": 0}
        v, r = self.m._verdict_from_inputs(hb, 5, diag, True)
        self.assertEqual(v, self.m.VERDICT_OK)

    def test_heartbeat_stale_session_yields_failed(self):
        hb = {"ok": True, "age_seconds": 7 * 3600,
              "last_seen_iso": "2026-06-16T00:00:00+00:00"}
        diag = {"available": False}
        v, r = self.m._verdict_from_inputs(hb, 0, diag, True)
        self.assertEqual(v, self.m.VERDICT_FAILED)

    def test_fresh_no_emit_success_yields_degraded(self):
        hb = {"ok": True, "age_seconds": 30}
        diag = {"available": True, "RAN": 10,
                "EMIT_SUCCESS": 0, "EMIT_FAILED": 5}
        v, r = self.m._verdict_from_inputs(hb, 0, diag, True)
        self.assertEqual(v, self.m.VERDICT_DEGRADED)


class TestEightyDayClaim(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_claim_unsupported_when_evidence_shows_fresh_heartbeat(self):
        hb = {"ok": True, "age_seconds": 1000}
        v, r = self.m._classify_80_day_claim(hb)
        self.assertEqual(v, self.m.VERDICT_CLAIM_UNSUPPORTED)


class TestNoAlpacaImport(unittest.TestCase):
    def test_no_alpaca_import_in_audit_script(self):
        p = _REPO_ROOT / "scripts" / "audit_geo_monitor_health.py"
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name or "")


class TestNoBrokerCall(unittest.TestCase):
    def test_no_broker_url_or_submit_order(self):
        text = (_REPO_ROOT / "scripts"
                / "audit_geo_monitor_health.py").read_text(encoding="utf-8")
        self.assertNotIn("api.alpaca.markets", text)
        self.assertNotIn("submit_order", text)
        self.assertNotIn("place_order", text)
        self.assertNotIn("close_position", text)


class TestStandingMarkers(unittest.TestCase):
    def test_standing_markers_in_output(self):
        m = _load_script()
        status = m.build_status()
        self.assertIn("EDGE_GATE_ENABLED=false",
                       status["standing_markers"])
        self.assertIn("ALLOW_BROKER_PAPER=false",
                       status["standing_markers"])
        self.assertIn("LIVE_TRADING_UNSUPPORTED",
                       status["standing_markers"])
        self.assertIn("NO_ORDER_PLACEMENT", status["standing_markers"])


class TestRendersMd(unittest.TestCase):
    def test_generates_md_file(self):
        m = _load_script()
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            json_path = tdir / "geo.json"
            md_path = tdir / "GEO_MONITOR_HEALTH_STATUS.md"
            with patch.object(m, "LATEST_JSON_PATH", json_path), \
                 patch.object(m, "LATEST_MD_PATH",   md_path), \
                 patch.object(sys, "argv", ["audit_geo_monitor_health.py"]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    m.main()
                self.assertTrue(json_path.exists())
                self.assertTrue(md_path.exists())
                md = md_path.read_text(encoding="utf-8")
                self.assertIn("Geo Monitor Health Audit", md)
                self.assertIn("Standing markers", md)


class TestNeverEnablesFlags(unittest.TestCase):
    """Static check — no auto flag flip."""
    def test_no_flag_assignment_to_true(self):
        text = (_REPO_ROOT / "scripts"
                / "audit_geo_monitor_health.py").read_text(encoding="utf-8")
        for bad in ("ALLOW_BROKER_PAPER = True",
                    "EDGE_GATE_ENABLED = True",
                    "LIVE_TRADING = True"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()

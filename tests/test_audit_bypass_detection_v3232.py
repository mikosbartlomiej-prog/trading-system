"""v3.23.2 (2026-06-08) — Audit-bypass detector tests."""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import audit_bypass_detector as abd


class TestClassifyPath(unittest.TestCase):
    def test_direct_market_sell_without_safe_close_is_flagged(self):
        src = textwrap.dedent('''
            import requests
            def naked():
                payload = {"symbol": "AMD", "side": "sell",
                            "type": "market", "qty": 34}
                requests.post(f"{BASE}/v2/orders", json=payload, headers=H)
        ''')
        cls = abd.classify_path(Path("scripts/some_close.py"), src)
        # No safe_close, no audit_write → ORDER_SUBMITTER_BYPASS
        self.assertEqual(cls, abd.ORDER_SUBMITTER_BYPASS)

    def test_sell_to_close_without_safe_close_is_flagged(self):
        src = textwrap.dedent('''
            import requests
            payload = {"side": "sell", "symbol": "AAPL",
                        "position_intent": "sell_to_close"}
            requests.post(URL + "/v2/orders", json=payload)
        ''')
        cls = abd.classify_path(Path("scripts/manual_x.py"), src)
        self.assertEqual(cls, abd.ORDER_SUBMITTER_BYPASS)

    def test_safe_close_path_is_allowed(self):
        src = textwrap.dedent('''
            from shared.alpaca_orders import safe_close
            def exit_routine(sym, qty):
                payload = {"side": "sell"}
                return safe_close(sym, qty)
            requests.post(f"{base}/v2/orders", json=payload)
        ''')
        cls = abd.classify_path(Path("exit-monitor/monitor.py"), src)
        self.assertEqual(cls, abd.SAFE_CLOSE_WRAPPED)

    def test_audit_equivalent_wrapped_is_allowed(self):
        src = textwrap.dedent('''
            from audit import write_audit_event
            payload = {"side": "sell"}
            write_audit_event({"event": "CLOSE_POSITION", "symbol": "X"})
            requests.post(f"{base}/v2/orders", json=payload)
        ''')
        cls = abd.classify_path(Path("scripts/wrapped.py"), src)
        self.assertEqual(cls, abd.AUDIT_EQUIVALENT_WRAPPED)

    def test_read_only_alpaca_is_allowed(self):
        src = textwrap.dedent('''
            import requests
            def fetch():
                return requests.get(f"{base}/v2/positions").json()
        ''')
        cls = abd.classify_path(Path("scripts/snapshot.py"), src)
        self.assertEqual(cls, abd.READ_ONLY)

    def test_legacy_filename_marked_legacy_dangerous(self):
        src = textwrap.dedent('''
            import requests
            side = "sell"
            payload = {"side": side, "type": "market"}
            requests.post(f"{base}/v2/orders", json=payload)
        ''')
        cls = abd.classify_path(
            Path("scripts/emergency_close_20260602.py"), src,
        )
        self.assertEqual(cls, abd.LEGACY_DANGEROUS)

    def test_no_sell_no_get_yields_unknown(self):
        src = "def helper(): return 1\n"
        cls = abd.classify_path(Path("shared/x.py"), src)
        self.assertEqual(cls, abd.UNKNOWN_REQUIRES_REVIEW)


class TestDetectBypassesIntegration(unittest.TestCase):
    """Run the detector against a synthetic repo tree.

    A controlled tree gives a deterministic invariant check independent
    of real repo content. The real-repo scan is exercised separately
    (the v3.23.2 audit-bypass report).
    """

    def test_invariant_satisfied_when_only_allowed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared").mkdir()
            (root / "shared/alpaca_orders.py").write_text(textwrap.dedent('''
                import requests
                def safe_close(sym, qty):
                    payload = {"side": "sell"}
                    return requests.post(f"{B}/v2/orders", json=payload)
            '''))
            (root / "exit-monitor").mkdir()
            (root / "exit-monitor/monitor.py").write_text(textwrap.dedent('''
                from shared.alpaca_orders import safe_close
                def close(sym, qty):
                    payload = {"side": "sell"}
                    requests.post(f"{B}/v2/orders", json=payload)
                    return safe_close(sym, qty)
            '''))
            result = abd.detect_bypasses(root)
            self.assertEqual(result["flagged_files"], [])
            self.assertTrue(result["invariant_satisfied"])

    def test_invariant_violated_when_bypass_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/raw_close.py").write_text(textwrap.dedent('''
                import requests
                payload = {"side": "sell", "type": "market", "qty": 1}
                requests.post(f"{B}/v2/orders", json=payload)
            '''))
            result = abd.detect_bypasses(root)
            self.assertGreaterEqual(len(result["flagged_files"]), 1)
            self.assertFalse(result["invariant_satisfied"])

    def test_legacy_dangerous_is_flagged_even_in_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/emergency_close_20260602.py").write_text(
                textwrap.dedent('''
                    import requests
                    side = "sell"
                    payload = {"side": side, "type": "market"}
                    requests.post(f"{B}/v2/orders", json=payload)
                '''),
            )
            result = abd.detect_bypasses(root)
            self.assertIn("scripts/emergency_close_20260602.py",
                           result["flagged_files"])
            self.assertFalse(result["invariant_satisfied"])


class TestInvariantConstantsExposed(unittest.TestCase):
    def test_three_invariants_present(self):
        self.assertTrue(abd.NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT)
        self.assertTrue(
            abd.NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT,
        )
        self.assertTrue(abd.ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT)

    def test_all_classifications_frozen(self):
        self.assertIsInstance(abd.ALL_CLASSIFICATIONS, frozenset)
        for c in (abd.SAFE_CLOSE_WRAPPED, abd.AUDIT_EQUIVALENT_WRAPPED,
                   abd.READ_ONLY, abd.ORDER_SUBMITTER_BYPASS,
                   abd.LEGACY_DANGEROUS,
                   abd.QUARANTINED_LEGACY_DANGEROUS,
                   abd.UNKNOWN_REQUIRES_REVIEW):
            self.assertIn(c, abd.ALL_CLASSIFICATIONS)

    def test_no_active_legacy_dangerous_invariant_present(self):
        self.assertTrue(abd.NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT)


class TestRealRepoScanProducedReport(unittest.TestCase):
    """The shipped JSON report itself encodes the real-repo result.

    v3.23.3: after quarantine landed, the 2 legacy scripts moved
    from ``flagged_files`` to ``quarantined_files``, the active
    bypass invariant flipped back to ``True``, and the JSON gained
    a ``quarantined_files`` key.
    """

    def test_report_exists_and_has_expected_keys(self):
        path = (REPO_ROOT / "learning-loop"
                / "position_reconciliation"
                / "audit_bypass_investigation_latest.json")
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # The detector output is nested under static_scan_summary.
        scan = data["static_scan_summary"]
        for key in ("total_scanned", "by_classification",
                     "flagged_files", "quarantined_files",
                     "invariant_satisfied"):
            self.assertIn(key, scan)

    def test_legacy_scripts_quarantined_not_flagged(self):
        path = (REPO_ROOT / "learning-loop"
                / "position_reconciliation"
                / "audit_bypass_investigation_latest.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        scan = data["static_scan_summary"]
        flagged = set(scan["flagged_files"])
        quarantined = set(scan["quarantined_files"])
        # No active legacy script should remain flagged.
        self.assertNotIn("scripts/emergency_close_20260602.py", flagged)
        self.assertNotIn("scripts/emergency_close_20260603.py", flagged)
        # Both quarantined .py.disabled paths MUST be present.
        self.assertIn(
            "scripts/quarantined_legacy_order_scripts/"
            "emergency_close_20260602.py.disabled",
            quarantined,
        )
        self.assertIn(
            "scripts/quarantined_legacy_order_scripts/"
            "emergency_close_20260603.py.disabled",
            quarantined,
        )
        # Active-bypass invariant restored.
        self.assertTrue(scan["invariant_satisfied"])


if __name__ == "__main__":
    unittest.main()

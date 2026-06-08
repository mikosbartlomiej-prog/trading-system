"""v3.23.3 (2026-06-08) — Legacy direct-order script quarantine tests.

Hard-asserts that:
- the two legacy scripts no longer exist as ``.py`` files in
  ``scripts/`` (cannot be invoked by ``python3 scripts/...``),
- the quarantined ``.py.disabled`` copies exist under
  ``scripts/quarantined_legacy_order_scripts/``,
- the README documenting the quarantine is present and carries the
  expected safety markers (``MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT``,
  ``safe_close``, ``DO NOT RUN``),
- no ACTIVE ``scripts/*.py`` file contains both ``requests.post`` →
  ``/v2/orders`` AND a sell-side literal AND is not in the
  audit-bypass allow-list,
- the audit-bypass detector classifies the quarantined files as
  ``QUARANTINED_LEGACY_DANGEROUS`` and the active scan returns
  ``invariant_satisfied=True`` with empty ``flagged_files``,
- the operator has NOT flipped ``EDGE_GATE_ENABLED`` or
  ``ALLOW_BROKER_PAPER`` to true.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


QUARANTINE_DIR = (REPO_ROOT / "scripts"
                    / "quarantined_legacy_order_scripts")
LEGACY_BASENAMES = (
    "emergency_close_20260602.py",
    "emergency_close_20260603.py",
)


class TestLegacyScriptsRemovedFromActiveLocation(unittest.TestCase):
    def test_legacy_py_files_no_longer_in_scripts_root(self):
        for name in LEGACY_BASENAMES:
            p = REPO_ROOT / "scripts" / name
            self.assertFalse(
                p.exists(),
                f"Active legacy script must NOT exist at {p}; was it"
                " restored as .py? It must stay quarantined as"
                " .py.disabled.",
            )

    def test_quarantine_dir_exists(self):
        self.assertTrue(QUARANTINE_DIR.is_dir(),
                         f"Quarantine dir missing: {QUARANTINE_DIR}")

    def test_quarantined_disabled_copies_exist(self):
        for name in LEGACY_BASENAMES:
            p = QUARANTINE_DIR / f"{name}.disabled"
            self.assertTrue(p.exists(),
                              f"Quarantined evidence missing: {p}")

    def test_quarantined_files_not_python_entrypoints(self):
        """``.py.disabled`` is not picked up by ``python3 <file>``
        as a module nor by Python's import system."""
        for name in LEGACY_BASENAMES:
            p = QUARANTINE_DIR / f"{name}.disabled"
            self.assertTrue(p.name.endswith(".py.disabled"),
                              "Quarantined file must end with"
                              " .py.disabled to be inert")
            self.assertFalse(p.name.endswith(".py"),
                              "Quarantined file MUST NOT have a .py"
                              " extension")


class TestQuarantineREADMEMarkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = QUARANTINE_DIR / "README.md"
        cls.text = cls.readme.read_text(encoding="utf-8")

    def test_readme_exists(self):
        self.assertTrue(self.readme.exists())

    def test_readme_warns_do_not_run(self):
        self.assertIn("DO NOT RUN", self.text)
        self.assertIn("DO NOT RESTORE", self.text)

    def test_readme_references_audit_gap_finding(self):
        self.assertIn(
            "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
            self.text,
        )

    def test_readme_references_safe_close(self):
        self.assertIn("safe_close", self.text)

    def test_readme_lists_both_quarantined_files(self):
        for name in LEGACY_BASENAMES:
            self.assertIn(f"{name}.disabled", self.text)


class TestNoActiveDirectOrderScriptOutsideAllowList(unittest.TestCase):
    """No ``scripts/*.py`` file may contain both a POST to
    ``/v2/orders`` and a sell-side literal unless it is in the
    audit_bypass_detector ALLOW_LIST."""

    _POST_ORDERS = re.compile(
        r"requests\.(post|request)\s*\([^)]{0,200}/v2/orders",
        re.I | re.DOTALL,
    )
    _SELL_LITERAL = re.compile(
        r"(['\"]\s*side\s*['\"]\s*[:=]\s*['\"]sell['\"]"
        r"|\bside\s*=\s*['\"]sell['\"]"
        r"|sell_to_close)",
        re.I,
    )

    def test_no_unsanctioned_active_sell_submitter(self):
        import audit_bypass_detector as abd
        offenders: list[str] = []
        for py in (REPO_ROOT / "scripts").rglob("*.py"):
            # Skip __pycache__ + the quarantine dir (it should not
            # contain .py files anyway, only .py.disabled, but be
            # robust if someone places a helper .py here later).
            rel = py.relative_to(REPO_ROOT).as_posix()
            if "/__pycache__/" in rel:
                continue
            if abd.QUARANTINE_DIR_MARKER in rel:
                continue
            try:
                src = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if (self._POST_ORDERS.search(src)
                    and self._SELL_LITERAL.search(src)):
                if rel in abd.ALLOW_LIST:
                    continue
                offenders.append(rel)
        self.assertEqual(
            offenders, [],
            f"Unsanctioned active sell-submit scripts found: "
            f"{offenders}. They must call safe_close() or be"
            " quarantined as .py.disabled.",
        )


class TestAuditBypassDetectorRecognizesQuarantine(unittest.TestCase):
    def test_classify_path_routes_disabled_extension(self):
        import audit_bypass_detector as abd
        cls = abd.classify_path(
            Path("scripts/quarantined_legacy_order_scripts/"
                  "emergency_close_20260602.py.disabled"),
            "naked direct POST source kept as evidence",
        )
        self.assertEqual(cls, abd.QUARANTINED_LEGACY_DANGEROUS)

    def test_classify_path_routes_quarantine_dir(self):
        import audit_bypass_detector as abd
        cls = abd.classify_path(
            Path("scripts/quarantined_legacy_order_scripts/anything.py"),
            "doesn't matter — directory wins",
        )
        self.assertEqual(cls, abd.QUARANTINED_LEGACY_DANGEROUS)

    def test_real_repo_scan_invariant_restored(self):
        import audit_bypass_detector as abd
        r = abd.detect_bypasses(REPO_ROOT)
        self.assertEqual(r["flagged_files"], [],
                          f"Unexpected active bypasses: "
                          f"{r['flagged_files']}")
        self.assertTrue(r["invariant_satisfied"])
        # Both quarantined files must be present.
        quarantined = set(r["quarantined_files"])
        for name in LEGACY_BASENAMES:
            self.assertIn(
                f"scripts/quarantined_legacy_order_scripts/"
                f"{name}.disabled",
                quarantined,
            )

    def test_invariant_no_active_legacy_dangerous_order_script(self):
        import audit_bypass_detector as abd
        self.assertTrue(abd.NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT)


class TestSafetyFlagsNotFlipped(unittest.TestCase):
    """v3.23.3 must not have flipped any kill-switch flag."""

    def test_edge_gate_not_enabled(self):
        v = os.environ.get("EDGE_GATE_ENABLED", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""),
                       "EDGE_GATE_ENABLED must stay disabled")

    def test_allow_broker_paper_not_enabled(self):
        v = os.environ.get("ALLOW_BROKER_PAPER", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""),
                       "ALLOW_BROKER_PAPER must stay unset")


if __name__ == "__main__":
    unittest.main()

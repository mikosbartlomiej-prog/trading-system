"""v3.31 ETAP 1 (2026-06-16) — tests for operator-marker templates.

Asserts that:

* per-symbol .md templates exist for AVAX/USD, ETH/USD, LTC/USD
  under ``docs/operator_repair_templates/`` with the canonical filename
  ``<safe_symbol>_repair_marker_template.md``,
* per-symbol .json templates exist under
  ``learning-loop/operator_markers/templates/`` with the canonical
  filename ``<safe_symbol>_repair_marker_template.json``,
* each .md and .json template starts with / contains a
  "THIS IS A TEMPLATE" notice,
* templates are NOT located directly under
  ``learning-loop/operator_markers/`` (only under
  ``learning-loop/operator_markers/templates/``),
* ``has_repair_confirmation`` does NOT return True when ONLY a
  template-named file exists (templates do not count as markers),
* ``record_operator_repair_confirmation.write_marker`` does not
  treat a template path as a real marker,
* each markdown contains the canonical schema fields,
* every .md contains every standing marker,
* none of the template files import or reference broker plumbing,
* the runbook (``docs/OPERATOR_REPAIR_CONFIRMATION.md``) references
  the template directory and includes the operator checklist.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


CANONICAL_SYMBOLS = [
    ("AVAX/USD", "AVAX_USD"),
    ("ETH/USD",  "ETH_USD"),
    ("LTC/USD",  "LTC_USD"),
]

SCHEMA_FIELDS = [
    "dashboard_checked",
    "open_orders_checked",
    "stale_oco_cancelled_by_operator",
    "position_closed_by_operator",
    "final_position_state",
    "final_open_orders_state",
    "equity_checked",
    "dashboard_timestamp_utc",
    "operator_note",
    "screenshot_reference_optional",
    "operator_name_optional",
]

STANDING_MARKERS = [
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION",
    "TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER",
]

MD_DIR = _REPO_ROOT / "docs" / "operator_repair_templates"
JSON_DIR = _REPO_ROOT / "learning-loop" / "operator_markers" / "templates"
MARKERS_DIR = _REPO_ROOT / "learning-loop" / "operator_markers"
RUNBOOK = _REPO_ROOT / "docs" / "OPERATOR_REPAIR_CONFIRMATION.md"


class TestOperatorMarkerTemplatesV3310(unittest.TestCase):

    # 1. Per-symbol .md templates exist.
    def test_01_md_templates_exist_for_all_canonical_symbols(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = MD_DIR / f"{safe}_repair_marker_template.md"
            self.assertTrue(
                path.exists(),
                f"Missing markdown template for {sym}: {path}",
            )

    # 2. Per-symbol .json templates exist.
    def test_02_json_templates_exist_for_all_canonical_symbols(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = JSON_DIR / f"{safe}_repair_marker_template.json"
            self.assertTrue(
                path.exists(),
                f"Missing JSON template for {sym}: {path}",
            )

    # 3. Each .md template starts with / contains the notice.
    def test_03_md_templates_contain_template_notice(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = MD_DIR / f"{safe}_repair_marker_template.md"
            text = path.read_text(encoding="utf-8")
            self.assertIn("THIS IS A TEMPLATE", text,
                          f"{path}: missing THIS IS A TEMPLATE notice")
            self.assertIn("does NOT count as confirmation", text,
                          f"{path}: missing 'does NOT count as confirmation'")

    # 4. JSON templates contain the notice + standing-markers + are
    #    NOT located directly under learning-loop/operator_markers/.
    def test_04_json_templates_carry_notice_and_not_at_marker_root(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = JSON_DIR / f"{safe}_repair_marker_template.json"
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertIn("_template_notice", payload,
                          f"{path}: missing _template_notice key")
            notice = str(payload["_template_notice"])
            self.assertIn("THIS IS A TEMPLATE", notice)
            self.assertIn("does NOT count as confirmation", notice)
            self.assertIn("_standing_markers", payload)
            sm = payload["_standing_markers"]
            self.assertIsInstance(sm, list)
            self.assertIn(
                "TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER", sm,
                f"{path}: missing TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER",
            )
            # Templates must live under the templates/ subdir, NOT
            # directly under learning-loop/operator_markers/.
            self.assertEqual(
                path.parent.name, "templates",
                f"{path}: expected to live under templates/ subdir",
            )

    # 5. has_repair_confirmation does NOT return True when ONLY a
    #    template file exists.
    def test_05_templates_do_not_count_as_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            markers_dir = Path(tmp) / "operator_markers"
            templates_dir = markers_dir / "templates"
            templates_dir.mkdir(parents=True)
            # Copy our real template into the isolated env's templates dir.
            real_template = JSON_DIR / "AVAX_USD_repair_marker_template.json"
            (templates_dir / real_template.name).write_text(
                real_template.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            os.environ["OPERATOR_MARKERS_DIR"] = str(markers_dir)
            try:
                if "operator_repair_state" in sys.modules:
                    del sys.modules["operator_repair_state"]
                import operator_repair_state as ors
                self.assertFalse(
                    ors.has_repair_confirmation("AVAX/USD"),
                    "templates under templates/ subdir must NOT count as markers",
                )
                self.assertIsNone(ors.load_marker("AVAX/USD"))
                self.assertEqual(ors.list_markers(), {})
            finally:
                os.environ.pop("OPERATOR_MARKERS_DIR", None)
                if "operator_repair_state" in sys.modules:
                    del sys.modules["operator_repair_state"]

    # 6. record_operator_repair_confirmation refuses to treat a
    #    template file path as a real marker — it only writes markers
    #    under <markers_dir>/<safe_sym>_<date>.json. Confirm template
    #    files have a totally different filename pattern.
    def test_06_template_filename_pattern_distinct_from_marker_pattern(self):
        marker_pattern = re.compile(r"^[A-Z0-9_]+_\d{4}-\d{2}-\d{2}\.json$")
        for _, safe in CANONICAL_SYMBOLS:
            tname = f"{safe}_repair_marker_template.json"
            self.assertIsNone(
                marker_pattern.match(tname),
                f"template filename {tname!r} must NOT match marker pattern",
            )

    # 7. Each markdown contains every canonical schema field.
    def test_07_md_contains_canonical_schema_fields(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = MD_DIR / f"{safe}_repair_marker_template.md"
            text = path.read_text(encoding="utf-8")
            for field in SCHEMA_FIELDS:
                self.assertIn(
                    field, text,
                    f"{path}: missing schema field {field!r}",
                )

    # 8. Each markdown contains every standing marker.
    def test_08_md_contains_standing_markers(self):
        for sym, safe in CANONICAL_SYMBOLS:
            path = MD_DIR / f"{safe}_repair_marker_template.md"
            text = path.read_text(encoding="utf-8")
            for m in STANDING_MARKERS:
                self.assertIn(
                    m, text, f"{path}: missing standing marker {m!r}",
                )

    # 9. None of the template files import or reference broker plumbing.
    def test_09_template_files_have_no_broker_imports(self):
        forbidden = [
            "import alpaca_orders",
            "from alpaca_orders",
            "submit_order(",
            "place_order(",
            "safe_close(",
            "cancel_order(",
            "close_position(",
            "close_all_positions(",
        ]
        all_files = list(MD_DIR.glob("*.md")) + list(JSON_DIR.glob("*.json"))
        self.assertTrue(all_files, "no template files found")
        for path in all_files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(
                    token, text,
                    f"{path}: forbidden broker reference {token!r}",
                )

    # 10. Runbook references templates + checklist + operator step
    #     to run record_operator_repair_confirmation.
    def test_10_runbook_references_templates_and_checklist(self):
        self.assertTrue(RUNBOOK.exists(), f"missing runbook: {RUNBOOK}")
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("docs/operator_repair_templates/", text)
        self.assertIn(
            "learning-loop/operator_markers/templates/", text,
            "runbook must reference the JSON templates dir",
        )
        self.assertIn("run_operator_clearance_readiness.py", text,
                      "runbook must reference the v3.31 readiness wrapper")
        self.assertIn(
            "https://app.alpaca.markets/paper/dashboard/overview", text,
            "runbook must point operator at the paper dashboard URL",
        )
        self.assertIn("paper", text.lower(),
                      "runbook must clarify paper-only")
        self.assertIn(
            "record_operator_repair_confirmation.py", text,
            "runbook must reference the real-marker CLI",
        )


if __name__ == "__main__":
    unittest.main()

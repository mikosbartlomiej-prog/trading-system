"""v3.23.0 (2026-06-15) — Agent 3C — LATEST docs freshness tests.

Verify the LATEST documentation set:

  * Stamps the current HEAD SHA and an ISO timestamp.
  * Contains the four standing safety markers verbatim
    (EDGE_GATE_ENABLED = false, ALLOW_BROKER_PAPER = false,
    LIVE_TRADING_UNSUPPORTED, NO_ORDER_PLACEMENT).
  * Doesn't promise profit or recommend live trading.

CLAUDE.md is checked specifically for the new v3.22 + v3.23 row in the
session history table.

Run:
    python3 -m unittest tests.test_latest_docs_freshness_v3230 -v
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _current_head_sha() -> str:
    """Best-effort: return HEAD SHA (or fixed string if git unavailable)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        return out
    except Exception:
        return ""


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


# The set of LATEST docs Agent 3C is responsible for. CLAUDE.md is
# tested separately because it's a session-history journal, not a
# self-contained LATEST.
_LATEST_DOCS = (
    "docs/end_of_day_status_LATEST.md",
    "docs/shadow_evidence_cycle_LATEST.md",
    "docs/HEARTBEAT_FRESHNESS_STATUS.md",
    "docs/EVIDENCE_THROUGHPUT_SLA_STATUS.md",
    "docs/MONITOR_EMISSION_STATUS.md",
)


_STANDING_MARKERS = (
    "EDGE_GATE_ENABLED = false",
    "ALLOW_BROKER_PAPER = false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
)


# Phrases that, if present, would indicate a doc has gone off-contract.
_FORBIDDEN_PROFIT_PROMISES = (
    "guaranteed profit",
    "will earn $",
    "will make $",
    "this will produce profit",
    "risk-free",
    "guaranteed return",
)


_FORBIDDEN_LIVE_RECOMMENDATIONS = (
    "set EDGE_GATE_ENABLED=true",
    "flip EDGE_GATE_ENABLED to true",
    "enable live trading",
    "turn on live trading",
    "set ALLOW_BROKER_PAPER=true",
    "we recommend going live",
)


class TestLatestDocsFreshness(unittest.TestCase):
    def test_end_of_day_status_contains_current_head(self) -> None:
        head = _current_head_sha()
        if not head:
            self.skipTest("git rev-parse HEAD unavailable")
        body = _read("docs/end_of_day_status_LATEST.md")
        self.assertIn(head, body,
                      "end_of_day_status_LATEST.md must stamp current HEAD")
        # Generated: line must exist.
        self.assertIn("Generated:", body)

    def test_shadow_evidence_cycle_contains_current_head(self) -> None:
        head = _current_head_sha()
        if not head:
            self.skipTest("git rev-parse HEAD unavailable")
        body = _read("docs/shadow_evidence_cycle_LATEST.md")
        self.assertIn(head, body,
                      "shadow_evidence_cycle_LATEST.md must stamp current HEAD")
        self.assertIn("Generated:", body)

    def test_claude_md_has_v323_row(self) -> None:
        body = _read("CLAUDE.md")
        # The new session-history row added by Agent 3C.
        self.assertIn("2026-06-15 (v3.22 + v3.23)", body,
                      "CLAUDE.md must contain the v3.22 + v3.23 session row")
        # And the Last updated: line must call out v3.23.
        self.assertIn("v3.23", body)

    def test_all_latest_docs_contain_standing_markers(self) -> None:
        for rel in _LATEST_DOCS:
            body = _read(rel)
            for marker in _STANDING_MARKERS:
                self.assertIn(marker, body,
                              f"{rel} must contain standing marker: {marker}")

    def test_no_latest_doc_promises_profit(self) -> None:
        for rel in _LATEST_DOCS + ("CLAUDE.md",):
            body = _read(rel).lower()
            for phrase in _FORBIDDEN_PROFIT_PROMISES:
                self.assertNotIn(phrase.lower(), body,
                                 f"{rel} contains forbidden profit promise: {phrase!r}")

    def test_no_latest_doc_recommends_live_trading(self) -> None:
        for rel in _LATEST_DOCS + ("CLAUDE.md",):
            body = _read(rel).lower()
            for phrase in _FORBIDDEN_LIVE_RECOMMENDATIONS:
                self.assertNotIn(phrase.lower(), body,
                                 f"{rel} contains forbidden live-trading recommendation: {phrase!r}")

    def test_monitor_emission_status_doc_exists_and_is_well_formed(self) -> None:
        body = _read("docs/MONITOR_EMISSION_STATUS.md")
        self.assertIn("# Monitor Emission Status", body)
        self.assertIn("Per-monitor table", body)
        self.assertIn("Standing markers", body)


if __name__ == "__main__":
    unittest.main()

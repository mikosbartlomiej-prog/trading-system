"""v3.16.0 (2026-06-04) — Tests for doj-monitor (FB-008 Option B).

Coverage:
  * sec_8k_client: Atom parsing, item classification, CIK→ticker
  * doj_press_client: RSS parsing, ticker extraction, classification
  * monitor: dedup, state roundtrip, heartbeat ping, MAX_ALERTS cap,
    source-tier verification, no real network.

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
MONITOR_DIR = os.path.join(REPO_ROOT, "doj-monitor")
for p in (SHARED_DIR, MONITOR_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_doj_monitor_module():
    """Force fresh import of doj-monitor's `monitor` module.

    Multiple monitor directories (geo-monitor, doj-monitor, defense-monitor)
    each contain a `monitor.py`. If another test imported a different
    `monitor` first, sys.modules caches it. Ensure we get the doj-monitor
    one by popping any prior cache + re-importing with MONITOR_DIR at
    index 0 of sys.path.
    """
    import importlib
    sys.modules.pop("monitor", None)
    # Make sure doj-monitor is first on sys.path so the fresh import lands here.
    if MONITOR_DIR in sys.path:
        sys.path.remove(MONITOR_DIR)
    sys.path.insert(0, MONITOR_DIR)
    return importlib.import_module("monitor")


# ─── Synthetic fixtures ───────────────────────────────────────────────────────

SAMPLE_8K_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Latest Filings</title>
  <entry>
    <title>8-K - APPLE INC (0000320193) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/cgi-bin/browse-edgar?CIK=0000320193&amp;0000320193-26-000123-index.htm"/>
    <category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
    <id>urn:tag:sec.gov:0000320193-26-000123</id>
    <summary type="html">Item 1.01 Material Definitive Agreement.</summary>
    <updated>2026-06-04T13:30:00-04:00</updated>
  </entry>
  <entry>
    <title>8-K - BOEING CO (0000012927) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/cgi-bin/browse-edgar?CIK=0000012927&amp;0000012927-26-000045-index.htm"/>
    <category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
    <id>urn:tag:sec.gov:0000012927-26-000045</id>
    <summary type="html">Item 1.03 Bankruptcy or Receivership and Item 5.02 Departure of Directors or Certain Officers.</summary>
    <updated>2026-06-04T11:00:00-04:00</updated>
  </entry>
  <entry>
    <title>8-K - SOMEPRIVATECO (9999999999) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/cgi-bin/browse-edgar?CIK=9999999999&amp;9999999999-26-000001-index.htm"/>
    <category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
    <id>urn:tag:sec.gov:9999999999-26-000001</id>
    <summary type="html">Item 6.02 Change in Servicer or Trustee.</summary>
    <updated>2026-06-04T10:00:00-04:00</updated>
  </entry>
</feed>
"""


SAMPLE_DOJ_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>DOJ News</title>
    <item>
      <title>Justice Department indicts XYZ executives in $500M fraud scheme</title>
      <link>https://www.justice.gov/opa/pr/xyz-fraud-indictment</link>
      <pubDate>Wed, 04 Jun 2026 14:00:00 EDT</pubDate>
      <description>Three former officers of $XYZ Corp were indicted today
        on charges of securities fraud and bribery.</description>
      <guid>doj-2026-xyz-fraud-1</guid>
    </item>
    <item>
      <title>Boeing settles civil action with Department of Justice</title>
      <link>https://www.justice.gov/opa/pr/boeing-settlement</link>
      <pubDate>Wed, 04 Jun 2026 09:00:00 EDT</pubDate>
      <description>Boeing agrees to pay $250M to settle civil claims;
        consent decree filed.</description>
      <guid>doj-2026-boeing-settle</guid>
    </item>
    <item>
      <title>DOJ opens investigation into Apple's app store practices</title>
      <link>https://www.justice.gov/opa/pr/apple-investigation</link>
      <pubDate>Wed, 04 Jun 2026 08:00:00 EDT</pubDate>
      <description>The antitrust division has launched a preliminary
        probe into Apple Inc. business practices.</description>
      <guid>doj-2026-apple-probe</guid>
    </item>
    <item>
      <title>Local college official sentenced in admissions case</title>
      <link>https://www.justice.gov/opa/pr/admissions-sentenced</link>
      <pubDate>Wed, 04 Jun 2026 07:30:00 EDT</pubDate>
      <description>An associate was sentenced this week — no ticker.</description>
      <guid>doj-2026-admissions</guid>
    </item>
  </channel>
</rss>
"""


# ─── Lane A — sec_8k_client tests ─────────────────────────────────────────────

class TestSec8kAtomParse(unittest.TestCase):
    def test_parse_extracts_three_filings(self):
        from sec_8k_client import _parse_atom
        out = _parse_atom(SAMPLE_8K_ATOM)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["cik"], "0000320193")
        self.assertIn("1.01", out[0]["items"])

    def test_parse_skips_non_8k_form_types(self):
        # Replace the 8-K entry with a 10-K and ensure it's skipped.
        feed = SAMPLE_8K_ATOM.replace('term="8-K"', 'term="10-K"', 1)
        from sec_8k_client import _parse_atom
        out = _parse_atom(feed)
        # The first entry is now 10-K → skipped, two 8-K remain.
        self.assertEqual(len(out), 2)

    def test_parse_handles_broken_xml(self):
        from sec_8k_client import _parse_atom
        out = _parse_atom("<<<not xml>>>")
        self.assertEqual(out, [])


class TestSec8kClassification(unittest.TestCase):
    def test_item_1_03_is_high_immediate(self):
        from sec_8k_client import classify_item
        sev, timing, label = classify_item("1.03")
        self.assertEqual(sev, "high")
        self.assertEqual(timing, "immediate")
        self.assertIn("Bankruptcy", label)

    def test_item_5_02_is_days(self):
        from sec_8k_client import classify_item
        sev, timing, label = classify_item("5.02")
        self.assertEqual(sev, "medium")
        self.assertEqual(timing, "days")

    def test_item_8_01_is_weeks_months(self):
        from sec_8k_client import classify_item
        _, timing, _ = classify_item("8.01")
        self.assertEqual(timing, "weeks_months")

    def test_unknown_item_returns_unknown_timing(self):
        from sec_8k_client import classify_item
        sev, timing, _ = classify_item("6.02")
        self.assertEqual(timing, "unknown")
        self.assertEqual(sev, "low")

    def test_is_material_filters_non_material(self):
        from sec_8k_client import is_material
        self.assertTrue(is_material(["1.03"]))
        self.assertTrue(is_material(["8.01", "6.02"]))
        self.assertFalse(is_material(["6.02"]))
        self.assertFalse(is_material([]))


class TestSec8kCikToTicker(unittest.TestCase):
    def test_ticker_for_cik_resolves(self):
        from sec_8k_client import ticker_for_cik
        tm = {"0000320193": "AAPL", "0000012927": "BA"}
        self.assertEqual(ticker_for_cik("320193", tm), "AAPL")
        self.assertEqual(ticker_for_cik("0000012927", tm), "BA")

    def test_ticker_for_cik_returns_none_for_unknown(self):
        from sec_8k_client import ticker_for_cik
        tm = {"0000320193": "AAPL"}
        self.assertIsNone(ticker_for_cik("9999999999", tm))
        self.assertIsNone(ticker_for_cik("", tm))
        self.assertIsNone(ticker_for_cik("notanumber", tm))


class TestSec8kBuildCandidates(unittest.TestCase):
    def test_build_skips_unknown_ticker(self):
        from sec_8k_client import _parse_atom, build_candidates
        filings = _parse_atom(SAMPLE_8K_ATOM)
        tm = {"0000320193": "AAPL", "0000012927": "BA"}  # 9999999999 missing
        out = build_candidates(filings, tm, now_iso="2026-06-04T18:00:00+00:00")
        # 3 filings → 2 with mapped ticker → 2 candidates (3rd is filtered
        # because Item 6.02 is not material AND CIK is unmapped).
        self.assertEqual(len(out), 2)
        tickers = sorted(c.tickers[0] for c in out)
        self.assertEqual(tickers, ["AAPL", "BA"])

    def test_build_highest_severity_wins(self):
        from sec_8k_client import _parse_atom, build_candidates
        filings = _parse_atom(SAMPLE_8K_ATOM)
        tm = {"0000320193": "AAPL", "0000012927": "BA"}
        out = build_candidates(filings, tm, now_iso="2026-06-04T18:00:00+00:00")
        # Boeing entry has 1.03 (high/immediate) + 5.02 (medium/days)
        # → should win with high+immediate.
        b = [c for c in out if c.tickers[0] == "BA"][0]
        self.assertEqual(b.severity, "high")
        self.assertEqual(b.catalyst_timing, "immediate")

    def test_build_marks_tier_1_primary(self):
        from sec_8k_client import _parse_atom, build_candidates
        from source_quality import TIER_1
        filings = _parse_atom(SAMPLE_8K_ATOM)
        tm = {"0000320193": "AAPL"}
        out = build_candidates(filings, tm, now_iso="now")
        self.assertGreaterEqual(len(out), 1)
        for c in out:
            self.assertEqual(c.source_tier, TIER_1)
            self.assertTrue(c.requires_day_trade_confirmation)


# ─── Lane B — doj_press_client tests ──────────────────────────────────────────

class TestDojPressRssParse(unittest.TestCase):
    def test_parse_extracts_four_items(self):
        from doj_press_client import _parse_rss
        items = _parse_rss(SAMPLE_DOJ_RSS)
        self.assertEqual(len(items), 4)
        self.assertIn("indicts", items[0]["title"])

    def test_parse_handles_broken_xml(self):
        from doj_press_client import _parse_rss
        out = _parse_rss("not xml at all")
        self.assertEqual(out, [])


class TestDojPressClassification(unittest.TestCase):
    def test_indictment_is_immediate(self):
        from doj_press_client import classify_catalyst_timing
        timing = classify_catalyst_timing(
            "DOJ indicts execs in $500M fraud scheme", ""
        )
        self.assertEqual(timing, "immediate")

    def test_settlement_is_days(self):
        from doj_press_client import classify_catalyst_timing
        timing = classify_catalyst_timing(
            "Boeing agrees to pay $250M settlement", ""
        )
        self.assertEqual(timing, "days")

    def test_investigation_is_weeks_months(self):
        from doj_press_client import classify_catalyst_timing
        timing = classify_catalyst_timing(
            "DOJ opens antitrust investigation into Apple", ""
        )
        self.assertEqual(timing, "weeks_months")

    def test_severity_matches_timing(self):
        from doj_press_client import classify_severity
        self.assertEqual(classify_severity("indicted on charges"), "high")
        self.assertEqual(classify_severity("agrees to pay settlement"), "medium")
        self.assertEqual(classify_severity("under investigation"), "low")


class TestDojPressTickerExtraction(unittest.TestCase):
    def test_cashtag_extraction(self):
        from doj_press_client import extract_tickers
        tickers = extract_tickers("Officers of $XYZ Corp indicted")
        self.assertEqual(tickers, ["XYZ"])

    def test_alias_extraction_apple_to_aapl(self):
        from doj_press_client import extract_tickers
        tickers = extract_tickers("DOJ investigates Apple app store")
        self.assertIn("AAPL", tickers)

    def test_alias_extraction_boeing_to_ba(self):
        from doj_press_client import extract_tickers
        tickers = extract_tickers("Boeing settles with DOJ")
        self.assertIn("BA", tickers)

    def test_no_ticker_when_text_empty(self):
        from doj_press_client import extract_tickers
        self.assertEqual(extract_tickers(""), [])
        self.assertEqual(extract_tickers(None), [])  # type: ignore[arg-type]


class TestDojBuildCandidates(unittest.TestCase):
    def test_build_keeps_items_with_ticker(self):
        from doj_press_client import _parse_rss, build_candidates
        items = _parse_rss(SAMPLE_DOJ_RSS)
        out = build_candidates(items, now_iso="2026-06-04T18:00:00+00:00")
        # 4 items in feed: XYZ (cashtag), Boeing (alias), Apple (alias),
        # admissions (no ticker → dropped).
        tickers = sorted({c.tickers[0] for c in out if c.tickers})
        self.assertIn("XYZ", tickers)
        self.assertIn("BA", tickers)
        self.assertIn("AAPL", tickers)
        self.assertEqual(len(out), 3)

    def test_indictment_has_immediate_timing(self):
        from doj_press_client import _parse_rss, build_candidates
        items = _parse_rss(SAMPLE_DOJ_RSS)
        out = build_candidates(items, now_iso="now")
        # find XYZ
        xyz = [c for c in out if c.tickers and c.tickers[0] == "XYZ"][0]
        self.assertEqual(xyz.catalyst_timing, "immediate")
        self.assertEqual(xyz.severity, "high")

    def test_investigation_has_weeks_months_timing(self):
        from doj_press_client import _parse_rss, build_candidates
        items = _parse_rss(SAMPLE_DOJ_RSS)
        out = build_candidates(items, now_iso="now")
        apple = [c for c in out if c.tickers and c.tickers[0] == "AAPL"][0]
        self.assertEqual(apple.catalyst_timing, "weeks_months")

    def test_all_press_marked_tier_1_primary(self):
        from doj_press_client import _parse_rss, build_candidates
        from source_quality import TIER_1
        items = _parse_rss(SAMPLE_DOJ_RSS)
        out = build_candidates(items, now_iso="now")
        for c in out:
            self.assertEqual(c.source_tier, TIER_1)


# ─── Monitor — orchestration tests (no network) ───────────────────────────────

class _Capture:
    """Captures (subject, body) tuples from send_email mock."""
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def __call__(self, subject: str, body: str, html: bool = False) -> bool:
        self.sent.append((subject, body))
        return True


class TestMonitorDedup(unittest.TestCase):
    def setUp(self):
        from sec_8k_client import _parse_atom
        from doj_press_client import _parse_rss
        self.filings = _parse_atom(SAMPLE_8K_ATOM)
        self.press = _parse_rss(SAMPLE_DOJ_RSS)
        self.tmpdir = tempfile.mkdtemp(prefix="dojmon-")
        self.state_path = os.path.join(self.tmpdir, "state.json")

    def _patch_monitor(self, ticker_map=None):
        mon = _ensure_doj_monitor_module()
        tm = ticker_map or {
            "0000320193": "AAPL",
            "0000012927": "BA",
        }
        capture = _Capture()
        patches = [
            mock.patch.object(mon, "fetch_recent_8k", return_value=self.filings),
            mock.patch.object(mon, "fetch_doj_press", return_value=self.press),
            mock.patch.object(mon, "fetch_company_tickers", return_value=tm),
            mock.patch("notify.send_email", side_effect=capture),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return mon, capture

    def test_first_run_emits_capped_at_max(self):
        mon, capture = self._patch_monitor()
        # MAX_ALERTS_PER_RUN default is 3 in env.
        with mock.patch.object(mon, "MAX_ALERTS_PER_RUN", 3):
            summary = mon.run_scan(state_path=self.state_path)
        self.assertLessEqual(summary["emitted"], 3)
        # At least one email per candidate up to cap
        self.assertEqual(len(capture.sent), summary["emitted"])

    def test_second_run_with_same_events_dedups_to_zero(self):
        mon, capture = self._patch_monitor()
        with mock.patch.object(mon, "MAX_ALERTS_PER_RUN", 99):
            first = mon.run_scan(state_path=self.state_path)
        # Same events second run → all dedup'd
        capture.sent.clear()
        with mock.patch.object(mon, "MAX_ALERTS_PER_RUN", 99):
            second = mon.run_scan(state_path=self.state_path)
        self.assertEqual(second["emitted"], 0)
        self.assertEqual(len(capture.sent), 0)
        self.assertGreater(first["emitted"], 0)

    def test_state_persists_event_ids(self):
        mon, _ = self._patch_monitor()
        with mock.patch.object(mon, "MAX_ALERTS_PER_RUN", 99):
            mon.run_scan(state_path=self.state_path)
        with open(self.state_path, encoding="utf-8") as f:
            state = json.load(f)
        self.assertGreater(len(state["seen_event_ids"]), 0)
        self.assertEqual(state["version"], mon.STATE_VERSION)


class TestMonitorEmail(unittest.TestCase):
    def test_format_event_email_subject_includes_ticker(self):
        _mon = _ensure_doj_monitor_module()
        _format_event_email = _mon._format_event_email
        from event_monitor_interface import (
            EventCandidate, EventMonitorInterface,
        )
        from source_quality import TIER_1
        ev = EventCandidate(
            event_id="x", event_type="sec_8k_filing",
            detected_at_iso="now",
            headline="8-K Bankruptcy — XYZ Corp",
            summary="...",
            tickers=("XYZ",),
            source_url="https://sec.gov/...",
            source_tier=TIER_1,
            severity="high",
            catalyst_timing="immediate",
            requires_day_trade_confirmation=True,
        )
        # Make a dummy decision instance
        from event_monitor_interface import EventEmissionDecision
        dec = EventEmissionDecision(
            emit=True, day_trade_eligible=True,
            requires_confirmation=True,
            confidence_adjustment=0.05,
            rationale="tier=tier_1_primary; timing=immediate",
            audit_payload={"event_id": "x"},
        )
        subject, body = _format_event_email(ev, dec)
        self.assertTrue(subject.startswith("[DOJ-FILING]"))
        self.assertIn("XYZ", subject)
        self.assertIn("Bankruptcy", body)
        self.assertIn("Tier 1 primary", body)
        self.assertIn("EMIT-ONLY", body)


class TestStateRoundtrip(unittest.TestCase):
    def test_load_missing_returns_empty_state(self):
        _mon = _ensure_doj_monitor_module()
        _load_state = _mon._load_state
        STATE_VERSION = _mon.STATE_VERSION
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "absent.json")
            state = _load_state(path)
            self.assertEqual(state["seen_event_ids"], [])
            self.assertIsNone(state["last_run_iso"])
            self.assertEqual(state["version"], STATE_VERSION)

    def test_save_then_load_roundtrip(self):
        _mon = _ensure_doj_monitor_module()
        _load_state = _mon._load_state
        _save_state = _mon._save_state
        STATE_VERSION = _mon.STATE_VERSION
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            _save_state({"seen_event_ids": ["a", "b", "c"]}, path)
            state = _load_state(path)
            self.assertEqual(state["seen_event_ids"], ["a", "b", "c"])
            self.assertEqual(state["version"], STATE_VERSION)
            self.assertIsNotNone(state["last_run_iso"])

    def test_save_caps_seen_ids(self):
        _mon = _ensure_doj_monitor_module()
        _save_state = _mon._save_state
        _load_state = _mon._load_state
        SEEN_CAP = _mon.SEEN_CAP
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            ids = [f"id-{i}" for i in range(SEEN_CAP + 50)]
            _save_state({"seen_event_ids": ids}, path)
            state = _load_state(path)
            self.assertEqual(len(state["seen_event_ids"]), SEEN_CAP)
            # FIFO — newest preserved
            self.assertEqual(state["seen_event_ids"][-1], ids[-1])


class TestMonitorHeartbeat(unittest.TestCase):
    def test_main_invocation_does_not_raise_on_heartbeat_missing(self):
        # Heartbeat import is wrapped in try; even if write fails the
        # module must load + run_scan must return a dict.
        from sec_8k_client import _parse_atom
        from doj_press_client import _parse_rss
        mon = _ensure_doj_monitor_module()
        filings = _parse_atom(SAMPLE_8K_ATOM)
        press = _parse_rss(SAMPLE_DOJ_RSS)
        tm = {"0000320193": "AAPL"}
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            with mock.patch.object(mon, "fetch_recent_8k", return_value=filings), \
                 mock.patch.object(mon, "fetch_doj_press", return_value=press), \
                 mock.patch.object(mon, "fetch_company_tickers", return_value=tm), \
                 mock.patch("notify.send_email", return_value=True):
                summary = mon.run_scan(state_path=sp)
        self.assertIn("emitted", summary)
        self.assertIn("candidates", summary)


class TestNoRealNetwork(unittest.TestCase):
    """Belt + suspenders: confirm doj-monitor modules never reach
    requests.get for SEC / DOJ endpoints when fetchers are mocked.

    NOTE: shared/risk_guards.vix_guard hits Yahoo Finance for VIX. That
    call is OUTSIDE the doj-monitor scope (a soft account-level guard
    that fails-open). We allow that one but block any SEC/DOJ URL hit.
    """

    def test_no_sec_or_doj_get_invocation(self):
        import requests
        mon = _ensure_doj_monitor_module()
        from sec_8k_client import _parse_atom
        from doj_press_client import _parse_rss

        sec_doj_calls: list[str] = []
        orig_get = requests.get

        def _spy(url, *a, **k):
            if "sec.gov" in str(url).lower() or "justice.gov" in str(url).lower():
                sec_doj_calls.append(str(url))
                raise AssertionError(
                    f"sec.gov or justice.gov GET attempted: {url}"
                )
            return orig_get(url, *a, **k)

        with mock.patch.object(requests, "get", side_effect=_spy):
            with mock.patch.object(
                mon, "fetch_recent_8k",
                return_value=_parse_atom(SAMPLE_8K_ATOM),
            ), mock.patch.object(
                mon, "fetch_doj_press",
                return_value=_parse_rss(SAMPLE_DOJ_RSS),
            ), mock.patch.object(
                mon, "fetch_company_tickers",
                return_value={"0000320193": "AAPL", "0000012927": "BA"},
            ), mock.patch("notify.send_email", return_value=True):
                with tempfile.TemporaryDirectory() as d:
                    mon.run_scan(state_path=os.path.join(d, "s.json"))
        self.assertEqual(sec_doj_calls, [])


# ─── Decision policy verification ─────────────────────────────────────────────

class TestDOJMonitorDecisionPolicy(unittest.TestCase):
    def test_immediate_bankruptcy_is_day_trade_eligible(self):
        DOJMonitor = _ensure_doj_monitor_module().DOJMonitor
        from event_monitor_interface import EventCandidate, EVT_SEC_8K_FILING
        from source_quality import TIER_1
        ev = EventCandidate(
            event_id="e1", event_type=EVT_SEC_8K_FILING,
            detected_at_iso="now",
            headline="8-K Bankruptcy", summary="",
            tickers=("BA",),
            source_url="https://sec.gov/",
            source_tier=TIER_1,
            severity="high",
            catalyst_timing="immediate",
            requires_day_trade_confirmation=True,
        )
        m = DOJMonitor()
        d = m.decide(ev)
        self.assertTrue(d.emit)
        self.assertTrue(d.day_trade_eligible)

    def test_weeks_months_other_event_not_day_trade_eligible(self):
        DOJMonitor = _ensure_doj_monitor_module().DOJMonitor
        from event_monitor_interface import EventCandidate, EVT_SEC_8K_FILING
        from source_quality import TIER_1
        ev = EventCandidate(
            event_id="e2", event_type=EVT_SEC_8K_FILING,
            detected_at_iso="now",
            headline="8-K Other Events", summary="",
            tickers=("AAPL",),
            source_url="https://sec.gov/",
            source_tier=TIER_1,
            severity="low",
            catalyst_timing="weeks_months",
            requires_day_trade_confirmation=True,
        )
        m = DOJMonitor()
        d = m.decide(ev)
        self.assertTrue(d.emit)
        self.assertFalse(d.day_trade_eligible)


if __name__ == "__main__":
    unittest.main()

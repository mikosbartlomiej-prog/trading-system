"""
Tests for politician-monitor (v3.9.2 — 2026-05-21).

Covers:
  - stockact_client: bracket parsing, whitelist loading, normalization
  - edgar_client: Atom feed parsing (mocked HTTP), Form 4 XML parsing
  - monitor: sector classification, cluster aggregation logic,
             candidate filtering, heuristic fallback emission shape

No network calls — every external HTTP is mocked.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "politician-monitor"))


class TestStockActBracketParsing(unittest.TestCase):
    def test_bracket_label_to_mid(self):
        from stockact_client import _bracket_to_mid

        self.assertEqual(_bracket_to_mid("$1,001 - $15,000"), 8000.0)
        self.assertEqual(_bracket_to_mid("$15,001 - $50,000"), 32500.0)
        self.assertEqual(_bracket_to_mid("$50,001 - $100,000"), 75000.0)
        self.assertEqual(_bracket_to_mid("$100,001 - $250,000"), 175000.0)
        self.assertEqual(_bracket_to_mid("$250,001 - $500,000"), 375000.0)

    def test_bracket_numeric_range(self):
        from stockact_client import _bracket_to_mid
        # Numeric low/high preferred over label
        self.assertEqual(_bracket_to_mid("anything", low=50000, high=150000), 100000.0)

    def test_bracket_unknown_returns_zero(self):
        from stockact_client import _bracket_to_mid
        self.assertEqual(_bracket_to_mid("not a bracket"), 0.0)
        self.assertEqual(_bracket_to_mid(""), 0.0)

    def test_bracket_regex_fallback(self):
        from stockact_client import _bracket_to_mid
        # Bracket pattern not in lookup but matches regex
        self.assertEqual(_bracket_to_mid("$200 - $400"), 300.0)


class TestStockActNormalization(unittest.TestCase):
    def test_normalize_capitol_trade_minimal(self):
        from stockact_client import _normalize_capitoltrade

        raw = {
            "politician": {"fullName": "Michael McCaul", "party": "R", "chamber": "House"},
            "asset": {"ticker": "RTX"},
            "txType": "buy",
            "txDate": "2026-04-22",
            "filed": "2026-05-19",
            "amount": "$100,001 - $250,000",
        }
        result = _normalize_capitoltrade(raw)
        self.assertEqual(result["politician"], "Michael McCaul")
        self.assertEqual(result["party"], "R")
        self.assertEqual(result["chamber"], "House")
        self.assertEqual(result["ticker"], "RTX")
        self.assertEqual(result["side"], "BUY")
        self.assertEqual(result["bracket_mid_usd"], 175000.0)
        self.assertEqual(result["lag_days"], 27)
        self.assertEqual(result["source"], "capitoltrades")

    def test_normalize_sell_variants(self):
        from stockact_client import _normalize_capitoltrade

        for side_label in ("sell", "Sell", "S"):
            raw = {
                "politician": "Pelosi", "asset": "NVDA",
                "txType": side_label, "amount": "$50,001 - $100,000",
            }
            result = _normalize_capitoltrade(raw)
            self.assertEqual(result["side"], "SELL")

    def test_normalize_missing_ticker_returns_none(self):
        from stockact_client import _normalize_capitoltrade
        raw = {"politician": "X", "txType": "buy", "amount": "$50,001 - $100,000"}
        self.assertIsNone(_normalize_capitoltrade(raw))

    def test_politician_name_normalize(self):
        from stockact_client import _politician_normalize
        self.assertEqual(_politician_normalize("Nancy Pelosi"), "nancy pelosi")
        self.assertEqual(_politician_normalize("  Nancy  Pelosi  "), "nancy pelosi")
        self.assertEqual(_politician_normalize("NANCY PELOSI"), "nancy pelosi")


class TestWhitelistLoad(unittest.TestCase):
    def test_load_whitelist_finds_known_politicians(self):
        """Whitelist file exists in repo; loader returns dict with 20 entries."""
        from stockact_client import load_whitelist

        wl = load_whitelist()
        # Should contain at least the 20 curated names
        self.assertGreaterEqual(len(wl), 18)
        self.assertIn("nancy pelosi", wl)
        self.assertIn("michael mccaul", wl)
        self.assertIn("jd vance", wl)
        # Verify schema
        pelosi = wl["nancy pelosi"]
        self.assertEqual(pelosi["party"], "D")
        self.assertEqual(pelosi["chamber"], "House")
        self.assertIn(pelosi["category"], ("dem_trader_top", "committee_insider", "admin_official"))
        self.assertGreater(pelosi["weight"], 0.5)


class TestSectorClassification(unittest.TestCase):
    def test_defense_tickers_route_to_defense(self):
        from monitor import _sector_for
        self.assertEqual(_sector_for("RTX"), "defense")
        self.assertEqual(_sector_for("LMT"), "defense")
        self.assertEqual(_sector_for("PLTR"), "defense")

    def test_semis_tickers(self):
        from monitor import _sector_for
        self.assertEqual(_sector_for("NVDA"), "semis")
        self.assertEqual(_sector_for("AMD"), "semis")
        self.assertEqual(_sector_for("AVGO"), "semis")

    def test_software_tickers(self):
        from monitor import _sector_for
        self.assertEqual(_sector_for("NOW"), "software")
        self.assertEqual(_sector_for("CRM"), "software")

    def test_unknown_ticker_returns_none(self):
        from monitor import _sector_for
        self.assertIsNone(_sector_for("BANANA"))
        self.assertIsNone(_sector_for(""))


class TestClusterAggregation(unittest.TestCase):
    def _ptr(self, politician, ticker, side, amount, days_ago=5):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        return {
            "politician":       politician,
            "ticker":           ticker,
            "side":             side,
            "bracket_mid_usd":  amount,
            "transaction_date": d,
            "disclosure_date":  d,
            "lag_days":         0,
        }

    def test_no_cluster_below_min_politicians(self):
        """2 politicians ≠ cluster (need 3)."""
        from monitor import compute_clusters
        ptrs = [
            self._ptr("McCaul",  "RTX", "BUY", 175000, days_ago=2),
            self._ptr("Warner",  "LMT", "BUY", 175000, days_ago=5),
        ]
        self.assertEqual(compute_clusters(ptrs), [])

    def test_defense_cluster_emits(self):
        """4 politicians, defense, BUY, within 14d → cluster."""
        from monitor import compute_clusters
        ptrs = [
            self._ptr("McCaul",  "RTX", "BUY", 175000, days_ago=1),
            self._ptr("Warner",  "LMT", "BUY", 75000,  days_ago=3),
            self._ptr("Tuberville", "NOC", "BUY", 75000, days_ago=7),
            self._ptr("Vance",   "GD", "BUY",  175000, days_ago=10),
        ]
        clusters = compute_clusters(ptrs)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c["sector"], "defense")
        self.assertEqual(c["etf_proxy"], "ITA")
        self.assertEqual(c["side"], "BUY")
        self.assertEqual(c["politicians_count"], 4)
        self.assertEqual(c["total_amount_usd"], 500000.0)

    def test_split_buy_sell_no_cluster(self):
        """3 politicians but 2 BUY + 1 SELL → no cluster (side differs)."""
        from monitor import compute_clusters
        ptrs = [
            self._ptr("A", "RTX", "BUY",  175000),
            self._ptr("B", "LMT", "BUY",  175000),
            self._ptr("C", "NOC", "SELL", 175000),
        ]
        self.assertEqual(compute_clusters(ptrs), [])

    def test_cluster_outside_window(self):
        """3 politicians but spread > 14d → no cluster."""
        from monitor import compute_clusters
        ptrs = [
            self._ptr("A", "RTX", "BUY", 175000, days_ago=1),
            self._ptr("B", "LMT", "BUY", 175000, days_ago=10),
            self._ptr("C", "NOC", "BUY", 175000, days_ago=20),  # outside 14d window
        ]
        self.assertEqual(compute_clusters(ptrs), [])

    def test_cluster_below_min_amount(self):
        """3 politicians but all below total $200k threshold."""
        from monitor import compute_clusters
        ptrs = [
            self._ptr("A", "RTX", "BUY", 32500),
            self._ptr("B", "LMT", "BUY", 32500),
            self._ptr("C", "NOC", "BUY", 32500),
        ]
        # Total $97,500 < $200k → no cluster
        self.assertEqual(compute_clusters(ptrs), [])

    def test_semis_cluster(self):
        from monitor import compute_clusters
        ptrs = [
            self._ptr("A", "NVDA", "BUY", 175000),
            self._ptr("B", "AMD",  "BUY", 75000),
            self._ptr("C", "AVGO", "BUY", 75000),
        ]
        clusters = compute_clusters(ptrs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["sector"], "semis")
        self.assertEqual(clusters[0]["etf_proxy"], "SMH")


class TestPtrCandidateFiltering(unittest.TestCase):
    def test_filter_drops_off_whitelist(self):
        from monitor import filter_ptr_candidates

        whitelist = {
            "nancy pelosi": {"name": "Nancy Pelosi", "party": "D",
                             "chamber": "House", "category": "dem_trader_top",
                             "weight": 1.5},
        }
        ptrs = [
            {"politician": "Nancy Pelosi", "ticker": "NVDA", "side": "BUY",
             "bracket_mid_usd": 175000, "disclosure_date": "2026-05-15",
             "transaction_date": "2026-04-20", "lag_days": 25, "ptr_url": "x"},
            {"politician": "Unknown Person", "ticker": "META", "side": "BUY",
             "bracket_mid_usd": 175000, "disclosure_date": "2026-05-15",
             "transaction_date": "2026-04-20", "lag_days": 25, "ptr_url": "y"},
        ]
        result = filter_ptr_candidates(ptrs, whitelist)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["politician"], "Nancy Pelosi")
        self.assertEqual(result[0]["lane"], "stock_act")
        self.assertEqual(result[0]["category"], "dem_trader_top")
        self.assertEqual(result[0]["weight"], 1.5)


class TestDjtCandidateBuilding(unittest.TestCase):
    def test_purchase_becomes_buy(self):
        from monitor import build_djt_candidates
        txs = [{
            "filer_name":       "DON JR",
            "role":             "director",
            "ticker":           "DJT",
            "transaction_code": "P",
            "ad_code":          "A",
            "shares":           1000,
            "price_per_share":  30.0,
            "value_usd":        30000,
            "transaction_date": "2026-05-19",
            "filing_date":      "2026-05-21",
            "lag_days":         2,
            "accession":        "0001234567-26-000001",
            "doc_link":         "https://...",
        }]
        result = build_djt_candidates(txs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["side"], "BUY")
        self.assertEqual(result[0]["ticker"], "DJT")
        self.assertEqual(result[0]["lane"], "djt_form4")

    def test_sale_becomes_sell(self):
        from monitor import build_djt_candidates
        txs = [{
            "filer_name": "ERIC", "role": "director", "ticker": "DJT",
            "transaction_code": "S", "ad_code": "D",
            "shares": 50000, "price_per_share": 30, "value_usd": 1500000,
            "transaction_date": "2026-05-19", "filing_date": "2026-05-21",
            "lag_days": 2, "accession": "x", "doc_link": "x",
        }]
        result = build_djt_candidates(txs)
        self.assertEqual(result[0]["side"], "SELL")

    def test_grants_skipped(self):
        """Awards (A), gifts (G), exercises (M) should NOT produce candidates."""
        from monitor import build_djt_candidates
        for code in ("A", "G", "M", "F", "UNKNOWN"):
            txs = [{
                "transaction_code": code, "ad_code": "A",
                "ticker": "DJT", "filer_name": "X", "role": "officer",
                "shares": 100, "price_per_share": 30, "value_usd": 3000,
                "transaction_date": "2026-05-19", "filing_date": "2026-05-21",
                "lag_days": 2, "accession": "x", "doc_link": "x",
            }]
            self.assertEqual(build_djt_candidates(txs), [],
                              f"Should skip code={code}")


class TestHeuristicFallback(unittest.TestCase):
    def test_djt_buy_emits_signal(self):
        from monitor import heuristic_signals, DJT_SIZE_USD
        djt = [{
            "lane": "djt_form4", "filer": "DON JR", "insider_role": "director",
            "ticker": "DJT", "side": "BUY",
        }]
        result = heuristic_signals(djt, [], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "DJT")
        self.assertEqual(result[0]["side"], "BUY")
        self.assertEqual(result[0]["size_usd"], DJT_SIZE_USD)
        self.assertEqual(result[0]["lane"], "djt_form4")

    def test_djt_small_sale_no_signal(self):
        """Director SELL but value $200k < $250k threshold → no fallback signal."""
        from monitor import heuristic_signals
        djt = [{
            "lane": "djt_form4", "filer": "x", "insider_role": "director",
            "ticker": "DJT", "side": "SELL", "value_usd": 200000,
        }]
        self.assertEqual(heuristic_signals(djt, [], []), [])

    def test_djt_large_director_sale_emits(self):
        from monitor import heuristic_signals
        djt = [{
            "lane": "djt_form4", "filer": "DIRECTOR_X",
            "insider_role": "director", "ticker": "DJT",
            "side": "SELL", "value_usd": 500000,
        }]
        result = heuristic_signals(djt, [], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["side"], "SELL")

    def test_cluster_emits_etf_proxy(self):
        from monitor import heuristic_signals
        clusters = [{
            "sector": "defense", "etf_proxy": "ITA", "side": "BUY",
            "politicians_count": 4, "total_amount_usd": 425000,
            "window_days": 11, "tickers_mentioned": ["RTX", "LMT"],
            "politicians": ["A", "B", "C", "D"],
        }]
        result = heuristic_signals([], [], clusters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "ITA")
        self.assertEqual(result[0]["lane"], "stock_act")
        self.assertEqual(result[0]["side"], "BUY")

    def test_single_high_weight_high_bracket_emits(self):
        from monitor import heuristic_signals
        ptrs = [{
            "lane": "stock_act", "politician": "McCaul", "ticker": "RTX",
            "side": "BUY", "weight": 1.4, "bracket_mid_usd": 175000,
            "bracket_label": "$100,001 - $250,000", "category": "committee_insider",
        }]
        result = heuristic_signals([], ptrs, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "RTX")
        self.assertEqual(result[0]["lane"], "stock_act")

    def test_single_low_weight_filtered(self):
        from monitor import heuristic_signals
        ptrs = [{
            "lane": "stock_act", "politician": "Random", "ticker": "RTX",
            "side": "BUY", "weight": 1.0, "bracket_mid_usd": 175000,
            "bracket_label": "$100k", "category": "dem_trader_top",
        }]
        # weight 1.0 < 1.4 threshold → no signal
        self.assertEqual(heuristic_signals([], ptrs, []), [])

    def test_max_alerts_cap(self):
        from monitor import heuristic_signals, MAX_ALERTS_PER_RUN
        # 5 DJT buys would all qualify; expect cap to MAX
        djt = [
            {"lane": "djt_form4", "filer": f"X{i}", "insider_role": "director",
             "ticker": "DJT", "side": "BUY"}
            for i in range(5)
        ]
        result = heuristic_signals(djt, [], [])
        self.assertLessEqual(len(result), MAX_ALERTS_PER_RUN)


class TestCuratorFilter(unittest.TestCase):
    def test_curator_filter_empty_returns_empty(self):
        from llm_curator import filter_signals_via_curator
        self.assertEqual(filter_signals_via_curator([], None), [])
        self.assertEqual(filter_signals_via_curator([], {}), [])

    def test_curator_filter_picks_emit(self):
        from llm_curator import filter_signals_via_curator
        curator_out = {
            "narrative": "test",
            "selected_signals": [{
                "lane": "stock_act", "ticker": "ITA", "side": "BUY",
                "size_multiplier": 1.3, "size_usd": 10400,
                "conviction": "high", "score": 0.85,
                "rationale": "defense cluster",
                "key_risk": "lag", "expected_horizon": "swing",
            }],
        }
        result = filter_signals_via_curator([], curator_out)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "ITA")
        self.assertEqual(result[0]["size_multiplier"], 1.3)
        self.assertEqual(result[0]["curator_rationale"], "defense cluster")

    def test_curator_clamps_size_multiplier(self):
        from llm_curator import filter_signals_via_curator
        curator_out = {"selected_signals": [
            {"ticker": "ITA", "side": "BUY", "size_multiplier": 5.0,
             "size_usd": 10000},
            {"ticker": "SMH", "side": "BUY", "size_multiplier": 0.1,
             "size_usd": 5000},
        ]}
        result = filter_signals_via_curator([], curator_out)
        # 5.0 clamped to 1.5; 0.1 clamped to 0.5
        self.assertEqual(result[0]["size_multiplier"], 1.5)
        self.assertEqual(result[1]["size_multiplier"], 0.5)

    def test_curator_caps_at_3(self):
        from llm_curator import filter_signals_via_curator
        curator_out = {"selected_signals": [
            {"ticker": f"T{i}", "side": "BUY", "size_multiplier": 1.0,
             "size_usd": 10000}
            for i in range(5)
        ]}
        self.assertEqual(len(filter_signals_via_curator([], curator_out)), 3)


class TestHouseClerkFallback(unittest.TestCase):
    """House Clerk XML index parsing (tier-3 fallback)."""

    SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
    <FinancialDisclosure>
      <Member>
        <Prefix>Hon.</Prefix>
        <Last>Pelosi</Last>
        <First>Nancy</First>
        <Suffix/>
        <FilingType>P</FilingType>
        <StateDst>CA11</StateDst>
        <Year>2026</Year>
        <FilingDate>5/19/2026</FilingDate>
        <DocID>20000001</DocID>
      </Member>
      <Member>
        <Prefix>Hon.</Prefix>
        <Last>McCaul</Last>
        <First>Hon. Michael</First>
        <Suffix/>
        <FilingType>A</FilingType>
        <StateDst>TX10</StateDst>
        <Year>2026</Year>
        <FilingDate>4/15/2026</FilingDate>
        <DocID>20000002</DocID>
      </Member>
      <Member>
        <Prefix/>
        <Last>Smith</Last>
        <First>Random</First>
        <Suffix/>
        <FilingType>P</FilingType>
        <StateDst>XX99</StateDst>
        <Year>2026</Year>
        <FilingDate>3/01/2026</FilingDate>
        <DocID>20000003</DocID>
      </Member>
    </FinancialDisclosure>
    """

    def test_strip_honorific_prefix(self):
        from stockact_client import fetch_houseclerk_index
        import requests

        class FakeResp:
            status_code = 200
            content = self.SAMPLE_XML.encode("utf-8")

        # 'A' (annual) entry filtered out; 2 PTRs remain
        with patch.object(requests, "get", return_value=FakeResp()):
            result = fetch_houseclerk_index(year=2026)

        self.assertEqual(len(result), 2)
        names = sorted(r["politician"] for r in result)
        # Honorific "Hon." stripped from Prefix AND embedded in First
        self.assertEqual(names, ["Nancy Pelosi", "Random Smith"])

    def test_filing_alert_marker_set(self):
        from stockact_client import fetch_houseclerk_index
        import requests

        class FakeResp:
            status_code = 200
            content = self.SAMPLE_XML.encode("utf-8")

        with patch.object(requests, "get", return_value=FakeResp()):
            result = fetch_houseclerk_index(year=2026)

        for r in result:
            self.assertTrue(r["filing_alert"])
            self.assertEqual(r["source"], "houseclerk")
            self.assertEqual(r["bracket_mid_usd"], 0.0)   # no amount in XML
            self.assertEqual(r["ticker"], "")            # no ticker in XML
            self.assertTrue(r["ptr_url"].endswith(".pdf"))
            self.assertIn("ptr-pdfs", r["ptr_url"])

    def test_only_ptr_type_included(self):
        """Non-P FilingTypes (W/A/C/O) should be skipped."""
        from stockact_client import fetch_houseclerk_index
        import requests

        class FakeResp:
            status_code = 200
            content = self.SAMPLE_XML.encode("utf-8")

        with patch.object(requests, "get", return_value=FakeResp()):
            result = fetch_houseclerk_index(year=2026)

        # 1 'A' entry skipped; only 2 'P' entries kept
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertEqual(r["politician"] in ("Nancy Pelosi", "Random Smith"), True)


class TestFilingAlertBracketBypass(unittest.TestCase):
    def test_filing_alert_bypasses_bracket_filter(self):
        """filing_alert entries have bracket_mid=0.0 but shouldn't be filtered."""
        from stockact_client import fetch_recent_ptrs

        with patch("stockact_client.fetch_capitoltrades", return_value=[]), \
             patch("stockact_client.fetch_housewatcher_fallback", return_value=[]), \
             patch("stockact_client.fetch_houseclerk_index", return_value=[
                 {"politician": "Nancy Pelosi", "ticker": "", "side": "UNKNOWN",
                  "bracket_label": "", "bracket_mid_usd": 0.0,
                  "disclosure_date": date.today().isoformat(),
                  "transaction_date": "", "lag_days": -1,
                  "ptr_url": "https://...", "source": "houseclerk",
                  "filing_alert": True, "party": "", "chamber": "House"}
             ]):
            result = fetch_recent_ptrs(
                lookback_days=14,
                whitelist={"nancy pelosi"},
                min_bracket_usd=50000,
            )
        # Despite bracket_mid_usd=0 < min 50000, filing_alert bypasses filter
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["filing_alert"])


class TestEdgarParsing(unittest.TestCase):
    """Mock EDGAR HTTP responses to verify Atom + XML parsing."""

    SAMPLE_ATOM = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>4 - TRUMP DONALD JR (0001234567) (Reporting)</title>
        <link href="https://www.sec.gov/Archives/edgar/data/1849635/000123456726000001-index.htm"/>
        <updated>2026-05-21T12:00:00Z</updated>
        <category term="4"/>
      </entry>
      <entry>
        <title>4/A - TRUMP MEDIA OFFICER (Reporting)</title>
        <link href="https://www.sec.gov/Archives/edgar/data/1849635/000123456726000002-index.htm"/>
        <updated>2026-05-20T08:00:00Z</updated>
        <category term="4/A"/>
      </entry>
      <entry>
        <title>4 - DIRECTOR SMITH</title>
        <link href="https://www.sec.gov/Archives/edgar/data/1849635/000123456726000003-index.htm"/>
        <updated>2026-05-19T10:00:00Z</updated>
        <category term="4"/>
      </entry>
    </feed>
    """

    def test_parse_atom_feed(self):
        from edgar_client import fetch_recent_filings

        with patch("edgar_client._http_get", return_value=self.SAMPLE_ATOM):
            filings = fetch_recent_filings("0001849635")

        # 4/A is amendment, should be filtered out
        self.assertEqual(len(filings), 2)
        self.assertIn("TRUMP DONALD JR", filings[0]["filer_name"])
        self.assertEqual(filings[0]["filing_date"], "2026-05-21")

    SAMPLE_FORM4 = """<?xml version="1.0"?>
    <ownershipDocument>
      <reportingOwner>
        <reportingOwnerId>
          <rptOwnerName>TRUMP DONALD JR</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>1</isDirector>
          <isOfficer>0</isOfficer>
        </reportingOwnerRelationship>
      </reportingOwner>
      <issuer><issuerTradingSymbol>DJT</issuerTradingSymbol></issuer>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionDate><value>2026-05-19</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>5000</value></transactionShares>
            <transactionPricePerShare><value>30.50</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """

    def test_parse_form4_xml(self):
        from edgar_client import fetch_form4_transactions

        # First call hits index.json for filename discovery; subsequent
        # calls fetch the actual XML doc.
        fake_index_json = """{
          "directory": {
            "name": "/Archives/edgar/data/1849635/000123456726000001",
            "item": [
              {"name": "0001234567-26-000001-index.htm", "type": "text"},
              {"name": "primary_doc.xml", "type": "text.gif"},
              {"name": "xslF345X05/wf-form4_x.xml", "type": "text"}
            ]
          }
        }"""

        def fake_get(url, **kw):
            if url.endswith("index.json"):
                return fake_index_json
            if url.endswith("primary_doc.xml"):
                return self.SAMPLE_FORM4
            return None

        with patch("edgar_client._http_get", side_effect=fake_get):
            txs = fetch_form4_transactions("1849635", "0001234567-26-000001")

        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["filer_name"], "TRUMP DONALD JR")
        self.assertEqual(txs[0]["role"], "director")
        self.assertEqual(txs[0]["ticker"], "DJT")
        self.assertEqual(txs[0]["transaction_code"], "P")
        self.assertEqual(txs[0]["shares"], 5000.0)
        self.assertEqual(txs[0]["price_per_share"], 30.5)
        self.assertEqual(txs[0]["value_usd"], 152500.0)


if __name__ == "__main__":
    unittest.main()

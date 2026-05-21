"""
SEC EDGAR Form 4 client for politician-monitor Lane A (DJT focus).

Fetches Atom feed of recent Form 4 filings for a given CIK, then
parses each Form 4 XML document to extract non-derivative insider
transactions (purchases / sales of common stock).

SEC EDGAR free public API:
  - Atom feed URL:
      https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
        &CIK={cik}&type=4&dateb=&owner=include&count=40&output=atom
  - Form 4 XML doc URL pattern:
      https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primary_doc}.xml

Rate limit: 10 req/sec; User-Agent header REQUIRED (SEC policy).
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

import requests


# Default target: Trump Media & Technology Group (DJT). Verify CIK
# before first run via https://www.sec.gov/cgi-bin/browse-edgar?CIK=DJT
DJT_CIK = os.environ.get("DJT_CIK", "0001849635")

# SEC requires identifying User-Agent. Adjust contact email via env if
# preferred — SEC monitors abuse and may rate-limit specific UAs.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "trading-system politician-monitor research@example.com",
)

EDGAR_BASE = "https://www.sec.gov"
ATOM_URL_TPL = (
    EDGAR_BASE
    + "/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb="
    + "&owner=include&count=40&output=atom"
)

# Atom + Form 4 XML namespaces
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# SEC rate limit: 10 req/sec. Sleep between detail-doc fetches.
RATE_SLEEP_S = float(os.environ.get("SEC_RATE_SLEEP_S", "0.2"))


def _http_get(url: str, timeout: int = 30) -> Optional[str]:
    """GET with SEC-compliant User-Agent. Returns text or None on error."""
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": SEC_USER_AGENT,
                "Accept": "application/atom+xml, application/xml, text/xml, */*",
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        print(f"  EDGAR GET exception {url}: {e}")
        return None
    if r.status_code != 200:
        print(f"  EDGAR GET {url}: HTTP {r.status_code}")
        return None
    return r.text


def fetch_recent_filings(cik: str = DJT_CIK, max_entries: int = 20
                          ) -> list[dict[str, Any]]:
    """
    Fetch Atom feed of recent Form 4 filings for CIK.

    Returns list of dicts:
      [{"accession": "0001234567-26-000123", "filing_date": "2026-05-21",
        "title": "...", "doc_link": "https://...",
        "filer_name": "TRUMP DONALD JR"  (best-effort from title)}]

    Empty list on any fetch failure (fail-soft).
    """
    cik_padded = str(cik).zfill(10)
    url = ATOM_URL_TPL.format(cik=cik_padded)
    text = _http_get(url)
    if not text:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"  EDGAR Atom parse error: {e}")
        return []

    out: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ATOM_NS)[:max_entries]:
        title = (entry.findtext("a:title", default="", namespaces=ATOM_NS) or "").strip()
        link_el = entry.find("a:link", ATOM_NS)
        href = link_el.get("href") if link_el is not None else ""
        updated = (entry.findtext("a:updated", default="", namespaces=ATOM_NS)
                   or "").strip()
        category_el = entry.find("a:category", ATOM_NS)
        form_type = category_el.get("term") if category_el is not None else ""

        # Only Form 4 (skip 3/5/amendments unless explicitly requested)
        if form_type and form_type != "4":
            continue

        # Parse accession from href, e.g. ".../0001234567-26-000123-index.htm"
        accession = ""
        m = re.search(r"(\d{10}-\d{2}-\d{6})", href or "")
        if m:
            accession = m.group(1)

        # Best-effort filer name from title (Atom title is something like
        # "4 - TRUMP DONALD JR (0001234567) (Reporting)")
        filer_name = ""
        title_m = re.search(r"-\s+([^()]+?)\s*\(", title or "")
        if title_m:
            filer_name = title_m.group(1).strip()

        out.append({
            "accession":   accession,
            "filing_date": updated[:10] if updated else "",
            "title":       title,
            "doc_link":    href or "",
            "filer_name":  filer_name,
        })
    return out


def _accession_path(cik: str, accession: str) -> str:
    """Convert accession 0001234567-26-000123 → 0001234567 26 000123 path component."""
    nodash = accession.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for path
    return f"/Archives/edgar/data/{cik_int}/{nodash}"


def fetch_form4_transactions(cik: str, accession: str
                              ) -> list[dict[str, Any]]:
    """
    Fetch the primary Form 4 XML doc and parse non-derivative
    transactions (common stock buys/sells).

    Form 4 XML schema (simplified, per SEC EDGAR):
      <ownershipDocument>
        <reportingOwner><reportingOwnerId>
          <rptOwnerName>TRUMP DONALD JR</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>1</isDirector>
          <officerTitle>...</officerTitle>
        </reportingOwnerRelationship></reportingOwner>
        <issuer>
          <issuerTradingSymbol>DJT</issuerTradingSymbol>
        </issuer>
        <nonDerivativeTable>
          <nonDerivativeTransaction>
            <transactionDate><value>2026-05-19</value></transactionDate>
            <transactionCoding>
              <transactionCode>P</transactionCode>  <!-- P=buy S=sell A=grant -->
            </transactionCoding>
            <transactionAmounts>
              <transactionShares><value>1000</value></transactionShares>
              <transactionPricePerShare><value>30.00</value></transactionPricePerShare>
              <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
          </nonDerivativeTransaction>
        </nonDerivativeTable>
      </ownershipDocument>

    Returns list of transaction dicts (one per non-derivative leg).
    """
    if not accession:
        return []

    # Discover the primary doc XML filename by fetching index.json for
    # this accession. SEC EDGAR provides a directory listing JSON that
    # enumerates all files in the filing — much more reliable than
    # guessing common patterns (which vary between filing agents).
    base = EDGAR_BASE + _accession_path(cik, accession)
    xml_text = None

    time.sleep(RATE_SLEEP_S)
    index_json_text = _http_get(f"{base}/index.json")
    candidate_filenames: list[str] = []

    if index_json_text:
        try:
            import json as _json
            idx = _json.loads(index_json_text)
            items = (idx.get("directory") or {}).get("item") or []
            # Form 4 XML candidates: prefer primary_doc.xml, then
            # *form4*.xml (handles wk-form4 / wf-form4 / form4 / etc.),
            # then any .xml as last resort.
            primary_first  = [it.get("name", "") for it in items
                              if (it.get("name") or "").lower() == "primary_doc.xml"]
            form4_named    = [it.get("name", "") for it in items
                              if "form4" in (it.get("name") or "").lower()
                              and (it.get("name") or "").lower().endswith(".xml")]
            other_xml      = [it.get("name", "") for it in items
                              if (it.get("name") or "").lower().endswith(".xml")
                              and "form4" not in (it.get("name") or "").lower()]
            candidate_filenames = primary_first + form4_named + other_xml
        except (ValueError, TypeError) as e:
            print(f"  EDGAR index.json parse error for {accession}: {e}")

    # Fallback: try common guesses if index.json failed
    if not candidate_filenames:
        nodash = accession.replace("-", "")
        candidate_filenames = [
            "primary_doc.xml",
            f"wf-form4_{nodash}.xml",
            f"wk-form4_{nodash}.xml",
            "form4.xml",
        ]

    for fname in candidate_filenames:
        time.sleep(RATE_SLEEP_S)
        url = f"{base}/{fname}"
        t = _http_get(url)
        if t and "<ownershipDocument" in t:
            xml_text = t
            break

    if not xml_text:
        # MVP fallback: return empty list. Monitor still sees the filing
        # exists via Atom feed metadata; transactions marked UNKNOWN are
        # filtered out at build_djt_candidates so no signal fires until
        # the XML doc becomes readable.
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Reporting owner (multiple possible but rare; take first)
    owner_name = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName", "")
    is_director = (root.findtext(".//reportingOwnerRelationship/isDirector", "")
                   or "").lower() in ("1", "true")
    is_officer = (root.findtext(".//reportingOwnerRelationship/isOfficer", "")
                  or "").lower() in ("1", "true")
    is_ten_pct = (root.findtext(".//reportingOwnerRelationship/isTenPercentOwner", "")
                  or "").lower() in ("1", "true")
    officer_title = root.findtext(".//reportingOwnerRelationship/officerTitle", "") or ""
    issuer_symbol = root.findtext(".//issuer/issuerTradingSymbol", "") or ""

    role = []
    if is_director:
        role.append("director")
    if is_officer:
        role.append(f"officer({officer_title.strip()})" if officer_title else "officer")
    if is_ten_pct:
        role.append("10pct_owner")

    out: list[dict[str, Any]] = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        date = tx.findtext("transactionDate/value", "") or ""
        code = tx.findtext("transactionCoding/transactionCode", "") or ""
        shares_s = tx.findtext("transactionAmounts/transactionShares/value", "") or ""
        price_s = tx.findtext("transactionAmounts/transactionPricePerShare/value", "") or ""
        ad_code = tx.findtext("transactionAmounts/transactionAcquiredDisposedCode/value", "") or ""

        try:
            shares = float(shares_s) if shares_s else 0.0
            price = float(price_s) if price_s else 0.0
        except ValueError:
            continue

        out.append({
            "filer_name":        owner_name.strip(),
            "role":              "/".join(role) or "unknown",
            "ticker":            issuer_symbol.strip() or "DJT",
            "transaction_date":  date,
            "transaction_code":  code,             # P=purchase, S=sale, A=grant, M=exercise, etc.
            "ad_code":           ad_code,          # A=acquired, D=disposed
            "shares":            shares,
            "price_per_share":   price,
            "value_usd":         round(shares * price, 2),
        })
    return out


def fetch_recent_djt_form4(max_entries: int = 20
                           ) -> list[dict[str, Any]]:
    """
    Convenience wrapper: fetch recent Form 4 filings for DJT and
    return parsed transaction dicts with filing metadata attached.

    Each output entry is a transaction with:
      filer_name, role, ticker, transaction_date, transaction_code,
      ad_code, shares, price_per_share, value_usd, accession,
      filing_date, doc_link, lag_days

    Filings without parseable XML transactions are returned with
    bare metadata (transaction_code="UNKNOWN") so Curator sees them.
    """
    from datetime import date

    filings = fetch_recent_filings(DJT_CIK, max_entries=max_entries)
    out: list[dict[str, Any]] = []
    today = date.today()

    for f in filings:
        txs = fetch_form4_transactions(DJT_CIK, f["accession"])
        # Compute lag days
        try:
            from datetime import datetime as _dt
            filed = _dt.strptime(f["filing_date"][:10], "%Y-%m-%d").date()
            lag = (today - filed).days
        except (ValueError, TypeError):
            lag = -1

        if not txs:
            out.append({
                "filer_name":       f.get("filer_name", ""),
                "role":             "unknown",
                "ticker":           "DJT",
                "transaction_date": f.get("filing_date", ""),
                "transaction_code": "UNKNOWN",
                "ad_code":          "",
                "shares":           0.0,
                "price_per_share":  0.0,
                "value_usd":        0.0,
                "accession":        f.get("accession", ""),
                "filing_date":      f.get("filing_date", ""),
                "doc_link":         f.get("doc_link", ""),
                "lag_days":         lag,
            })
            continue

        for tx in txs:
            tx["accession"]   = f.get("accession", "")
            tx["filing_date"] = f.get("filing_date", "")
            tx["doc_link"]    = f.get("doc_link", "")
            tx["lag_days"]    = lag
            out.append(tx)

    return out


__all__ = [
    "DJT_CIK",
    "fetch_recent_filings",
    "fetch_form4_transactions",
    "fetch_recent_djt_form4",
]

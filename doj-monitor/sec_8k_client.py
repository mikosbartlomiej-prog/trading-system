"""SEC EDGAR 8-K client (FB-008 — v3.16 doj-monitor lane).

Fetches the SEC EDGAR Atom feed of latest 8-K filings, parses the
filing metadata, classifies the 8-K item codes that we consider
material legal/governance signals, and maps the issuer CIK to a US
ticker via the free `company_tickers.json` directory.

CONTRACT
--------
- 100% free. Public SEC endpoints only. No paid feeds.
- Fail-soft: any HTTP / parse error returns an empty list or None.
- Never raises.
- Stateless: caller supplies dedup state via doj-monitor/state.json.
- Returns list[EventCandidate] (see shared/event_monitor_interface).

8-K Items considered material:
  1.01  Material Definitive Agreement                  → varies
  1.02  Termination of a Material Definitive Agreement → varies
  1.03  Bankruptcy or Receivership                     → immediate
  5.02  Departure of Directors / Officers              → days
  8.01  Other Events                                   → weeks/months

Other 8-K items are still detected but filtered out before emission
(reduces noise; can be re-enabled by env `DOJ_SEC_INCLUDE_ALL=true`).

PUBLIC ENDPOINTS
----------------
- 8-K Atom feed:
    https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K
        &dateb=&owner=include&count=40&output=atom

  Note: the spec includes a duplicate `action=getcompany` segment;
  EDGAR tolerates this. The effective request returns the latest 40
  8-K filings across all issuers.

- CIK → ticker mapping:
    https://www.sec.gov/files/company_tickers.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional

import requests

# Re-use event_monitor_interface dataclass.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
try:
    from event_monitor_interface import EventCandidate, EVT_SEC_8K_FILING
    from source_quality import TIER_1
except Exception:  # pragma: no cover — fail-soft import
    EventCandidate = None  # type: ignore[assignment]
    EVT_SEC_8K_FILING = "sec_8k_filing"
    TIER_1 = "tier_1_primary"


# ─── Constants ────────────────────────────────────────────────────────────────

EDGAR_BASE = "https://www.sec.gov"
EIGHT_K_ATOM_URL = (
    EDGAR_BASE
    + "/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&"
      "owner=include&count=40&action=getcompany&output=atom"
)
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "trading-system doj-monitor research@example.com",
)
RATE_SLEEP_S = float(os.environ.get("SEC_RATE_SLEEP_S", "0.2"))
INCLUDE_ALL_ITEMS = (
    os.environ.get("DOJ_SEC_INCLUDE_ALL", "false").lower() == "true"
)

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


# 8-K Items we surface as candidate events. Anything else is filtered.
# Item code (string) → (severity, catalyst_timing, label)
MATERIAL_ITEMS: dict[str, tuple[str, str, str]] = {
    "1.01": ("medium", "days",          "Material Definitive Agreement"),
    "1.02": ("medium", "days",          "Termination of Material Agreement"),
    "1.03": ("high",   "immediate",     "Bankruptcy or Receivership"),
    "5.02": ("medium", "days",          "Officer / Director Departure"),
    "8.01": ("low",    "weeks_months",  "Other Events"),
}


# In-process cache for company_tickers.json — loaded lazily once per run.
_TICKER_MAP_CACHE: Optional[dict[str, str]] = None


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def _http_get(url: str, *, accept: str = "*/*",
              timeout: int = 30) -> Optional[str]:
    """GET with SEC-compliant User-Agent. Returns text or None on error."""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": SEC_USER_AGENT, "Accept": accept},
            timeout=timeout,
        )
    except requests.RequestException as e:
        print(f"  SEC 8-K GET exception {url}: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"  SEC 8-K GET {url}: HTTP {r.status_code}")
        return None
    return r.text


# ─── company_tickers.json (CIK → ticker) ──────────────────────────────────────

def fetch_company_tickers() -> dict[str, str]:
    """Fetch SEC's free CIK→ticker map.

    Returns dict {"0000320193": "AAPL", ...} (CIK zero-padded to 10).
    Returns {} on any failure. Cached per process.
    """
    global _TICKER_MAP_CACHE
    if _TICKER_MAP_CACHE is not None:
        return _TICKER_MAP_CACHE

    text = _http_get(
        COMPANY_TICKERS_URL,
        accept="application/json, text/plain, */*",
    )
    if not text:
        _TICKER_MAP_CACHE = {}
        return _TICKER_MAP_CACHE

    try:
        data = json.loads(text)
    except (TypeError, ValueError) as e:
        print(f"  SEC company_tickers parse error: {e}")
        _TICKER_MAP_CACHE = {}
        return _TICKER_MAP_CACHE

    out: dict[str, str] = {}
    # SEC format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    try:
        if isinstance(data, dict):
            iterable = data.values()
        else:
            iterable = data or []
        for row in iterable:
            try:
                cik = int(row.get("cik_str") or 0)
                ticker = str(row.get("ticker") or "").strip().upper()
            except (AttributeError, TypeError, ValueError):
                continue
            if not cik or not ticker:
                continue
            out[f"{cik:010d}"] = ticker
    except Exception as e:  # pragma: no cover — defensive
        print(f"  SEC company_tickers iterate error: {e}")
        _TICKER_MAP_CACHE = {}
        return _TICKER_MAP_CACHE

    _TICKER_MAP_CACHE = out
    return out


def ticker_for_cik(cik: str | int, ticker_map: Optional[dict[str, str]] = None
                    ) -> Optional[str]:
    """Best-effort CIK lookup. Returns None when CIK not on US-listed map."""
    try:
        cik_int = int(str(cik).strip().lstrip("0") or "0")
    except (TypeError, ValueError):
        return None
    if not cik_int:
        return None
    tm = ticker_map if ticker_map is not None else fetch_company_tickers()
    return tm.get(f"{cik_int:010d}")


# ─── Atom feed parsing ────────────────────────────────────────────────────────

_CIK_RE      = re.compile(r"CIK=(\d{1,10})", re.IGNORECASE)
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
_TITLE_TYPE_RE = re.compile(r"^\s*(8-K(?:/A)?)\s*-\s*(.+?)\s*\((\d{1,10})\)",
                              re.IGNORECASE)


def _parse_atom(text: str) -> list[dict[str, Any]]:
    """Parse Atom feed → list of raw filing dicts."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"  SEC 8-K Atom parse error: {e}")
        return []

    out: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ATOM_NS):
        title = (entry.findtext("a:title", default="", namespaces=ATOM_NS) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ATOM_NS) or "").strip()
        link_el = entry.find("a:link", ATOM_NS)
        href = link_el.get("href") if link_el is not None else ""
        updated = (entry.findtext("a:updated", default="", namespaces=ATOM_NS) or "").strip()
        category_el = entry.find("a:category", ATOM_NS)
        form_type = category_el.get("term") if category_el is not None else ""

        # Restrict to 8-K (and 8-K/A amendments).
        if form_type and not form_type.upper().startswith("8-K"):
            continue

        m_acc = _ACCESSION_RE.search(href or "")
        accession = m_acc.group(1) if m_acc else ""

        # Extract CIK + issuer name from title (best-effort).
        # Title typical:  "8-K - APPLE INC (0000320193) (Filer)"
        cik = ""
        issuer = ""
        m_title = _TITLE_TYPE_RE.match(title)
        if m_title:
            issuer = m_title.group(2).strip()
            cik = m_title.group(3).strip()
        else:
            m_cik = _CIK_RE.search(href or "")
            if m_cik:
                cik = m_cik.group(1)

        # Item codes commonly appear in summary like "Item 1.01" / "Item 8.01".
        # Some Atom entries list multiple items separated by commas.
        items = _extract_items(summary + " " + title)

        out.append({
            "accession":   accession,
            "filing_date": updated[:10] if updated else "",
            "filing_iso":  updated,
            "title":       title,
            "summary":     summary,
            "doc_link":    href or "",
            "form_type":   form_type or "8-K",
            "cik":         cik,
            "issuer":      issuer,
            "items":       items,
        })
    return out


_ITEM_PATTERN = re.compile(r"item\s+(\d{1,2}\.\d{1,2})", re.IGNORECASE)


def _extract_items(text: str) -> list[str]:
    """Find all '8-K Item X.YY' references in text (deduped, ordered)."""
    if not text:
        return []
    seen: list[str] = []
    for m in _ITEM_PATTERN.finditer(text):
        code = m.group(1)
        if code not in seen:
            seen.append(code)
    return seen


# ─── Classification ──────────────────────────────────────────────────────────

def classify_item(item: str) -> tuple[str, str, str]:
    """Item code → (severity, catalyst_timing, label).

    Unknown / non-material items return ("low", "unknown", "Item <code>").
    """
    info = MATERIAL_ITEMS.get(item)
    if info:
        return info
    return ("low", "unknown", f"Item {item}")


def is_material(items: list[str]) -> bool:
    """True if at least one item is in MATERIAL_ITEMS (or override flag set)."""
    if INCLUDE_ALL_ITEMS:
        return bool(items)
    return any(it in MATERIAL_ITEMS for it in (items or []))


# ─── Public API: fetch + build candidates ────────────────────────────────────

def fetch_recent_8k() -> list[dict[str, Any]]:
    """Fetch latest 8-K filings (~40 entries) as raw dicts. Empty on failure."""
    text = _http_get(EIGHT_K_ATOM_URL, accept="application/atom+xml, application/xml, text/xml")
    if not text:
        return []
    time.sleep(RATE_SLEEP_S)
    return _parse_atom(text)


def build_candidates(filings: list[dict[str, Any]],
                     ticker_map: Optional[dict[str, str]] = None,
                     *,
                     now_iso: Optional[str] = None,
                     ) -> list[Any]:
    """Convert raw 8-K filings into EventCandidate objects.

    - Filter to material items (unless INCLUDE_ALL_ITEMS).
    - Map CIK → ticker; filings without a US-listed ticker are SKIPPED
      because we cannot trade them. Operator sees nothing.
    - Severity / catalyst_timing taken from the FIRST matching material item;
      if multiple material items co-occur, the highest-severity (high>medium>low)
      wins so the headline reflects the urgent one.
    - Each EventCandidate carries `requires_day_trade_confirmation=True`
      because filings carry forward catalysts that need price/volume.
    """
    tm = ticker_map if ticker_map is not None else fetch_company_tickers()
    detected = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    out: list[Any] = []
    for f in filings or []:
        items = f.get("items") or []
        if not is_material(items):
            continue
        ticker = ticker_for_cik(f.get("cik") or "", tm)
        if not ticker:
            # Issuer not on US-listed map → cannot trade, skip silently.
            continue

        severity, timing, label = _highest_priority_item(items)

        headline = _make_headline(f.get("issuer") or ticker, label, items)
        summary = (f.get("summary") or "")[:600]

        event_id = (
            f"sec-8k-{f.get('accession') or 'noaccession'}"
            f"-{ticker}-{items[0] if items else '0.00'}"
        )

        if EventCandidate is None:  # fallback dict if import failed
            out.append({
                "event_id":            event_id,
                "event_type":          EVT_SEC_8K_FILING,
                "detected_at_iso":     detected,
                "headline":            headline,
                "summary":             summary,
                "tickers":             (ticker,),
                "source_url":          f.get("doc_link", ""),
                "source_tier":         TIER_1,
                "severity":            severity,
                "catalyst_timing":     timing,
                "requires_day_trade_confirmation": True,
                "raw":                 f,
            })
            continue

        out.append(EventCandidate(
            event_id=event_id,
            event_type=EVT_SEC_8K_FILING,
            detected_at_iso=detected,
            headline=headline,
            summary=summary,
            tickers=(ticker,),
            source_url=f.get("doc_link", ""),
            source_tier=TIER_1,
            severity=severity,
            catalyst_timing=timing,
            requires_day_trade_confirmation=True,
        ))
    return out


def _highest_priority_item(items: list[str]) -> tuple[str, str, str]:
    """Across multiple items, return the one with highest severity (h>m>l)."""
    rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    best: tuple[str, str, str] = ("low", "unknown", "8-K")
    best_rank = -1
    for it in items or []:
        sev, timing, label = classify_item(it)
        r = rank.get(sev, 0)
        if r > best_rank:
            best = (sev, timing, label)
            best_rank = r
    return best


def _make_headline(issuer: str, label: str, items: list[str]) -> str:
    """Compact headline shown to operator + Curator."""
    items_str = ", ".join(items or [])
    if items_str:
        return f"8-K {label} — {issuer} (Items {items_str})"
    return f"8-K {label} — {issuer}"


__all__ = [
    "MATERIAL_ITEMS",
    "EIGHT_K_ATOM_URL",
    "COMPANY_TICKERS_URL",
    "fetch_company_tickers",
    "ticker_for_cik",
    "fetch_recent_8k",
    "build_candidates",
    "classify_item",
    "is_material",
]

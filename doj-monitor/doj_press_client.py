"""DOJ press releases RSS client (FB-008 — v3.16 doj-monitor lane).

Polls https://www.justice.gov/news/feed for the latest official DOJ
press releases. Best-effort ticker extraction from headline + summary
using SEC's free company_tickers.json map (company name → ticker)
plus a small alias dictionary for common short-forms.

CONTRACT
--------
- 100% free.
- Fail-soft. Returns [] / None on any error.
- Never raises.
- Returns list[EventCandidate] (shared/event_monitor_interface).

CATALYST CLASSIFICATION
-----------------------
Headline keyword → catalyst_timing:
  indict / charged / arrest / criminal / fraud / bribery → "immediate"
  settlement / plea / guilty / sentenced               → "days"
  investigation / probe / inquiry / civil              → "weeks_months"
  default                                              → "weeks_months"
"""

from __future__ import annotations

import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional

import requests

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
try:
    from event_monitor_interface import EventCandidate, EVT_DOJ_PRESS_RELEASE
    from source_quality import TIER_1
except Exception:  # pragma: no cover
    EventCandidate = None  # type: ignore[assignment]
    EVT_DOJ_PRESS_RELEASE = "doj_press_release"
    TIER_1 = "tier_1_primary"


# ─── Constants ────────────────────────────────────────────────────────────────

DOJ_FEED_URLS = [
    "https://www.justice.gov/feeds/all-press-releases.rss",
    "https://www.justice.gov/news.rss",
]

DOJ_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "trading-system doj-monitor research@example.com",
)
RATE_SLEEP_S = float(os.environ.get("DOJ_RATE_SLEEP_S", "0.2"))


# Catalyst-timing rules keyed on headline keywords (case-insensitive).
IMMEDIATE_KEYWORDS = (
    "indict", "indicted", "charges", "charged", "arrest", "arrested",
    "criminal", "fraud", "bribery", "bribe", "embezzle",
    "raid", "seized", "seizure", "convicted", "guilty plea",
    "indictment", "complaint filed",
)
DAYS_KEYWORDS = (
    "settlement", "settles", "plea", "guilty", "sentenced",
    "sentence", "consent decree", "agrees to pay", "pay penalty",
    "fine", "fines", "judgment",
)
WEEKS_MONTHS_KEYWORDS = (
    "investigation", "probe", "inquiry", "civil action",
    "civil complaint", "lawsuit", "antitrust review",
)


def _http_get(url: str, *, timeout: int = 30) -> Optional[str]:
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": DOJ_USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        print(f"  DOJ RSS GET exception {url}: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"  DOJ RSS GET {url}: HTTP {r.status_code}")
        return None
    return r.text


# ─── RSS parsing ──────────────────────────────────────────────────────────────

def _parse_rss(text: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 → list of {title, link, pub_date, summary, guid}."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"  DOJ RSS parse error: {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        # Some feeds put items at root; fall through anyway.
        channel = root
    out: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        title = (item.findtext("title", default="") or "").strip()
        link = (item.findtext("link", default="") or "").strip()
        pub_date = (item.findtext("pubDate", default="") or "").strip()
        summary = (item.findtext("description", default="") or "").strip()
        guid = (item.findtext("guid", default="") or "").strip()
        if not title:
            continue
        out.append({
            "title":    title,
            "link":     link,
            "pub_date": pub_date,
            "summary":  _strip_html(summary),
            "guid":     guid or link,
        })
    return out


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Very small HTML stripper — sufficient for DOJ press summaries."""
    if not text:
        return ""
    return _TAG_RE.sub("", text).strip()


# ─── Ticker extraction ────────────────────────────────────────────────────────

# Common informal aliases / short names. SEC's company_tickers.json holds
# the canonical legal name; press releases often use shorter forms.
SHORT_NAME_ALIASES: dict[str, str] = {
    "apple":       "AAPL",
    "microsoft":   "MSFT",
    "alphabet":    "GOOGL",
    "google":      "GOOGL",
    "amazon":      "AMZN",
    "meta":        "META",
    "facebook":    "META",
    "tesla":       "TSLA",
    "nvidia":      "NVDA",
    "amd":         "AMD",
    "boeing":      "BA",
    "lockheed":    "LMT",
    "raytheon":    "RTX",
    "northrop":    "NOC",
    "general dynamics": "GD",
    "exxon":       "XOM",
    "chevron":     "CVX",
    "wells fargo": "WFC",
    "goldman":     "GS",
    "morgan stanley": "MS",
    "jpmorgan":    "JPM",
    "jp morgan":   "JPM",
    "bank of america": "BAC",
    "citigroup":   "C",
    "citi":        "C",
    "palantir":    "PLTR",
    "intel":       "INTC",
}


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\&\.\-]+")


def _normalize(name: str) -> str:
    n = name.lower().strip()
    # Drop suffixes that pollute company_tickers titles
    for suffix in (" inc.", " inc", " corporation", " corp.", " corp",
                    " company", " co.", " co", " ltd.", " ltd",
                    " plc.", " plc", " holdings"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return " ".join(n.split())


def _build_name_to_ticker_index(ticker_map_raw: dict[str, Any]
                                 ) -> dict[str, str]:
    """SEC ticker map values include `title` → build name lookup.

    Accepts the lazy-cached map from sec_8k_client too: if the input is
    a dict {"0000320193": "AAPL"} we cannot resolve names, so we return
    the alias dict as fallback.
    """
    out: dict[str, str] = dict(SHORT_NAME_ALIASES)
    # Best-effort: if caller passes the raw SEC dict (which has title)
    # we add normalized titles too.
    try:
        if isinstance(ticker_map_raw, dict):
            for v in ticker_map_raw.values():
                if isinstance(v, dict):
                    title = str(v.get("title") or "").strip()
                    ticker = str(v.get("ticker") or "").strip().upper()
                    if title and ticker:
                        out[_normalize(title)] = ticker
    except Exception:
        pass
    return out


def extract_tickers(text: str,
                    name_index: Optional[dict[str, str]] = None,
                    *,
                    max_hits: int = 3,
                    ) -> list[str]:
    """Best-effort ticker extraction from headline + summary text.

    Strategy:
      1. Cashtags ($AAPL) — most explicit.
      2. Substring match against name_index (canonical SEC name or alias).
    """
    if not text:
        return []
    seen: list[str] = []

    # Cashtags
    for m in re.finditer(r"\$([A-Z]{1,5})\b", text):
        sym = m.group(1).upper()
        if sym not in seen:
            seen.append(sym)
            if len(seen) >= max_hits:
                return seen

    if name_index is None:
        name_index = SHORT_NAME_ALIASES

    lower = text.lower()
    for alias, ticker in name_index.items():
        if not alias or not ticker:
            continue
        if alias in lower and ticker not in seen:
            seen.append(ticker)
            if len(seen) >= max_hits:
                break
    return seen


# ─── Classification ──────────────────────────────────────────────────────────

def classify_catalyst_timing(headline: str, summary: str = "") -> str:
    """Map headline keywords → catalyst timing string.

    Priority: immediate > days > weeks_months > unknown (default
    weeks_months — investigations dominate DOJ feed).
    """
    text = f"{headline or ''} {summary or ''}".lower()
    for kw in IMMEDIATE_KEYWORDS:
        if kw in text:
            return "immediate"
    for kw in DAYS_KEYWORDS:
        if kw in text:
            return "days"
    for kw in WEEKS_MONTHS_KEYWORDS:
        if kw in text:
            return "weeks_months"
    return "weeks_months"


def classify_severity(headline: str, summary: str = "") -> str:
    """Severity flag — high for criminal action, medium for civil, low otherwise."""
    text = f"{headline or ''} {summary or ''}".lower()
    if any(kw in text for kw in IMMEDIATE_KEYWORDS):
        return "high"
    if any(kw in text for kw in DAYS_KEYWORDS):
        return "medium"
    return "low"


# ─── Public API ──────────────────────────────────────────────────────────────

def fetch_doj_press() -> list[dict[str, Any]]:
    """Fetch DOJ press release RSS. Tries each URL in DOJ_FEED_URLS."""
    for url in DOJ_FEED_URLS:
        text = _http_get(url)
        if text:
            time.sleep(RATE_SLEEP_S)
            items = _parse_rss(text)
            if items:
                return items
    return []


def build_candidates(items: list[dict[str, Any]],
                     name_index: Optional[dict[str, str]] = None,
                     *,
                     now_iso: Optional[str] = None,
                     require_ticker: bool = True,
                     ) -> list[Any]:
    """Build EventCandidate objects from DOJ press release items.

    `require_ticker=True` (default) drops items where no ticker could be
    resolved — we cannot generate a tradeable signal in that case.
    Operator opt-in via `require_ticker=False` to surface DOJ headlines
    that lack a ticker but might still be informative (alert-only).
    """
    detected = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    out: list[Any] = []
    for it in items or []:
        headline = it.get("title") or ""
        summary = it.get("summary") or ""
        link = it.get("link") or ""

        tickers = tuple(extract_tickers(f"{headline} {summary}", name_index))
        if require_ticker and not tickers:
            continue

        timing = classify_catalyst_timing(headline, summary)
        severity = classify_severity(headline, summary)

        guid = (it.get("guid") or link or headline)[:200]
        event_id = "doj-press-" + re.sub(r"[^A-Za-z0-9_\-]+", "-", guid)[:120]

        if EventCandidate is None:  # fallback dict
            out.append({
                "event_id":            event_id,
                "event_type":          EVT_DOJ_PRESS_RELEASE,
                "detected_at_iso":     detected,
                "headline":            headline[:240],
                "summary":             summary[:600],
                "tickers":             tickers,
                "source_url":          link,
                "source_tier":         TIER_1,
                "severity":            severity,
                "catalyst_timing":     timing,
                "requires_day_trade_confirmation": True,
                "raw":                 it,
            })
            continue

        out.append(EventCandidate(
            event_id=event_id,
            event_type=EVT_DOJ_PRESS_RELEASE,
            detected_at_iso=detected,
            headline=headline[:240],
            summary=summary[:600],
            tickers=tickers,
            source_url=link,
            source_tier=TIER_1,
            severity=severity,
            catalyst_timing=timing,
            requires_day_trade_confirmation=True,
        ))
    return out


__all__ = [
    "DOJ_FEED_URLS",
    "IMMEDIATE_KEYWORDS",
    "DAYS_KEYWORDS",
    "WEEKS_MONTHS_KEYWORDS",
    "SHORT_NAME_ALIASES",
    "fetch_doj_press",
    "build_candidates",
    "extract_tickers",
    "classify_catalyst_timing",
    "classify_severity",
    "_build_name_to_ticker_index",
]

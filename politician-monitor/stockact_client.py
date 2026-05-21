"""
STOCK Act PTR client — Lane B (Capitol Trades JSON).

Fetches recent Periodic Transaction Reports (PTRs) disclosed by
politicians under the STOCK Act (Stop Trading on Congressional
Knowledge Act of 2012). Free public data; no auth required.

Primary source — undocumented but stable JSON endpoint behind the
Capitol Trades web UI:
  GET https://bff.capitoltrades.com/trades?pageSize=50&page=0

Fallback — community-maintained House Stock Watcher JSON dump:
  GET https://housestockwatcher.com/api/v1/transactions  (legacy)
  GET https://housestockwatcher.com/data.json (alt mirror)

Both are best-effort; politician-monitor fails open when unavailable.

Bracket conversions (STOCK Act discloses brackets, not exact amounts):
  $1,001-$15,000        → mid $8,000
  $15,001-$50,000       → mid $32,500
  $50,001-$100,000      → mid $75,000
  $100,001-$250,000     → mid $175,000
  $250,001-$500,000     → mid $375,000
  $500,001-$1,000,000   → mid $750,000
  $1,000,001-$5,000,000 → mid $3,000,000
  $5,000,001+           → mid $7,500,000

Minimum trade-emit threshold (per whitelist + STRATEGY): bracket
mid ≥ $50,000. Lower brackets dropped before LLM call.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests


CAPITOLTRADES_BFF = os.environ.get(
    "CAPITOLTRADES_BFF_URL",
    "https://bff.capitoltrades.com/trades",
)
HOUSEWATCHER_FALLBACK = os.environ.get(
    "HOUSEWATCHER_FALLBACK_URL",
    "https://housestockwatcher.com/data.json",
)

# Minimum bracket mid required to emit. Filter applied before LLM call.
MIN_BRACKET_MID_USD = float(os.environ.get("STOCK_ACT_MIN_BRACKET_USD", "50000"))

# Lookback window for PTR scan (days). Default 14 = aligns with cluster
# aggregation window in `monitor.py`.
LOOKBACK_DAYS = int(os.environ.get("STOCK_ACT_LOOKBACK_DAYS", "14"))


# Bracket mid lookup. Both numeric ranges and label aliases supported.
_BRACKET_MIDS: dict[str, float] = {
    "$1,001 - $15,000":          8000.0,
    "$15,001 - $50,000":         32500.0,
    "$50,001 - $100,000":        75000.0,
    "$100,001 - $250,000":       175000.0,
    "$250,001 - $500,000":       375000.0,
    "$500,001 - $1,000,000":     750000.0,
    "$1,000,001 - $5,000,000":   3000000.0,
    "$5,000,001 - $25,000,000":  15000000.0,
    "$5,000,001+":               7500000.0,
}


def _bracket_to_mid(label: str, low: Optional[float] = None,
                     high: Optional[float] = None) -> float:
    """Map disclosure bracket to estimated midpoint USD."""
    if low is not None and high is not None:
        try:
            return (float(low) + float(high)) / 2.0
        except (TypeError, ValueError):
            pass

    key = (label or "").strip()
    if key in _BRACKET_MIDS:
        return _BRACKET_MIDS[key]

    # Best-effort parse "$50,001 - $100,000" → 75000
    m = re.match(r"\$([\d,]+)\s*-\s*\$([\d,]+)", key)
    if m:
        try:
            lo = float(m.group(1).replace(",", ""))
            hi = float(m.group(2).replace(",", ""))
            return (lo + hi) / 2.0
        except ValueError:
            pass

    return 0.0


def _http_get_json(url: str, params: Optional[dict] = None, timeout: int = 20,
                   extra_headers: Optional[dict] = None) -> Any:
    """GET JSON. Returns parsed dict/list or None on any failure."""
    # Capitol Trades sits behind Cloudflare WAF — needs browser-like
    # headers to avoid 503 / challenge-page responses.
    headers = {
        "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin":          "https://www.capitoltrades.com",
        "Referer":         "https://www.capitoltrades.com/trades",
    }
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        print(f"  STOCK Act GET exception {url}: {e}")
        return None
    if r.status_code != 200:
        print(f"  STOCK Act GET {url}: HTTP {r.status_code}")
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ─── Fallback: House Stock Watcher (community-maintained JSON dump) ──────────

def fetch_housewatcher_fallback() -> list[dict[str, Any]]:
    """
    Fallback source — House Stock Watcher JSON dump (community-scraped,
    refreshed ~daily). House Reps only (no Senate); covers last ~12 months.

    Schema (per https://housestockwatcher.com docs):
      [
        {"disclosure_year": 2026, "disclosure_date": "05/19/2026",
         "transaction_date": "2026-04-22", "owner": "self",
         "ticker": "RTX", "asset_description": "...",
         "type": "purchase" | "sale_full" | "sale_partial",
         "amount": "$100,001 - $250,000",
         "representative": "Hon. Michael McCaul",
         "district": "TX22", "ptr_link": "https://..."}
      ]
    """
    # Try a few common community URLs (best-effort, community sites move).
    candidates = [
        "https://housestockwatcher.com/api",
        "https://house-stock-watcher-data.s3.us-east-2.amazonaws.com/data/all_transactions.json",
        "https://housestockwatcher.com/data.json",
    ]

    raw = None
    for url in candidates:
        # Use plain headers (no Capitol Trades Cloudflare workarounds needed
        # for these CDN-served JSON files).
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "trading-system politician-monitor "
                                       "mikosbartlomiej@gmail.com",
                         "Accept": "application/json"},
                timeout=30,
            )
            if r.status_code == 200:
                try:
                    raw = r.json()
                    print(f"  STOCK Act fallback: housewatcher OK from {url}")
                    break
                except ValueError:
                    continue
        except requests.RequestException:
            continue

    if not raw:
        return []

    # housewatcher payload may be a list or wrapped {data: [...]}
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("transactions") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    out: list[dict[str, Any]] = []
    for item in items[:500]:  # cap at 500 most recent
        if not isinstance(item, dict):
            continue
        normalized = _normalize_housewatcher(item)
        if normalized:
            out.append(normalized)
    return out


def fetch_houseclerk_index(year: Optional[int] = None
                            ) -> list[dict[str, Any]]:
    """
    Official House Clerk XML index of all member filings for given year.

    Returns metadata-only entries (no ticker/amount — XML doesn't include
    transaction details). Each PTR (FilingType=P) entry resolves to a
    PDF at https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<year>/<DocID>.pdf
    where the operator can read the actual transactions.

    Used as tier-3 fallback when Capitol Trades + housewatcher both down.
    The monitor emits these as "filing_alert" rows — single politician +
    PDF link, no auto-execute (no ticker known yet).
    """
    import xml.etree.ElementTree as ET

    if year is None:
        year = date.today().year

    url = (f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/"
           f"{year}FD.xml")
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "trading-system politician-monitor "
                                   "mikosbartlomiej@gmail.com"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"  STOCK Act houseclerk GET exception: {e}")
        return []
    if r.status_code != 200:
        print(f"  STOCK Act houseclerk GET: HTTP {r.status_code}")
        return []

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        print(f"  STOCK Act houseclerk XML parse error: {e}")
        return []

    out: list[dict[str, Any]] = []
    for member in root.findall("Member"):
        filing_type = (member.findtext("FilingType") or "").strip()
        # P = Periodic Transaction Report (the only filings with trades)
        if filing_type != "P":
            continue
        last = (member.findtext("Last") or "").strip()
        first = (member.findtext("First") or "").strip()
        state_dst = (member.findtext("StateDst") or "").strip()
        filing_date_str = (member.findtext("FilingDate") or "").strip()
        doc_id = (member.findtext("DocID") or "").strip()

        # Build "First Last" (skip Prefix honorific "Hon." and Suffix —
        # whitelist uses just First Last format like "Nancy Pelosi"). Strip
        # any embedded honorific from First field too as defensive measure.
        for honorific in ("Hon.", "Hon", "Rep.", "Rep", "Mr.", "Ms.", "Mrs.", "Dr."):
            if first.startswith(honorific + " "):
                first = first[len(honorific) + 1:].strip()
        full_name = f"{first} {last}".strip()

        # Parse filing date MM/DD/YYYY → YYYY-MM-DD
        filing_date = ""
        try:
            filing_date = datetime.strptime(
                filing_date_str, "%m/%d/%Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

        if not full_name or not doc_id:
            continue

        ptr_url = (f"https://disclosures-clerk.house.gov/public_disc/"
                   f"ptr-pdfs/{year}/{doc_id}.pdf")

        out.append({
            "politician":       full_name,
            "party":            "",
            "chamber":          "House",
            "state_dst":        state_dst,
            "ticker":           "",                   # unknown from index
            "side":             "UNKNOWN",
            "bracket_label":    "",
            "bracket_mid_usd":  0.0,                  # forces alert-only path
            "transaction_date": "",
            "disclosure_date":  filing_date,
            "lag_days":         -1,
            "ptr_url":          ptr_url,
            "doc_id":           doc_id,
            "source":           "houseclerk",
            "filing_alert":     True,                 # marker — no ticker yet
        })
    return out


def _normalize_housewatcher(raw: dict) -> Optional[dict[str, Any]]:
    """Map House Stock Watcher entry to internal trade dict."""
    try:
        rep = (raw.get("representative") or raw.get("Representative") or "").strip()
        # Strip "Hon. " honorific prefix if present
        if rep.lower().startswith("hon. "):
            rep = rep[5:].strip()

        ticker = (raw.get("ticker") or raw.get("Ticker") or "").upper().strip()
        side_raw = (raw.get("type") or raw.get("Type") or "").lower()
        if "purchase" in side_raw or side_raw == "p":
            side = "BUY"
        elif "sale" in side_raw or side_raw == "s":
            side = "SELL"
        elif "exchange" in side_raw:
            return None   # swaps/exchanges — informational only
        else:
            side = side_raw.upper() or "UNKNOWN"

        bracket = (raw.get("amount") or raw.get("Amount") or "").strip()
        bracket_mid = _bracket_to_mid(bracket)

        # Date format varies: "05/19/2026" or "2026-05-19"
        def _normalize_date(d: str) -> str:
            d = (d or "").strip()
            if not d:
                return ""
            if "/" in d:
                # MM/DD/YYYY → YYYY-MM-DD
                try:
                    return datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    return d
            return d[:10]

        tx_date = _normalize_date(raw.get("transaction_date") or "")
        disc_date = _normalize_date(raw.get("disclosure_date") or "")

        lag_days = -1
        try:
            tx_d = datetime.strptime(tx_date, "%Y-%m-%d").date()
            disc_d = datetime.strptime(disc_date, "%Y-%m-%d").date()
            lag_days = (disc_d - tx_d).days
        except (ValueError, TypeError):
            pass

        if not rep or not ticker:
            return None

        return {
            "politician":       rep,
            "party":            "",            # housewatcher doesn't always include
            "chamber":          "House",       # House-only by definition
            "ticker":           ticker,
            "side":             side,
            "bracket_label":    bracket,
            "bracket_mid_usd":  bracket_mid,
            "transaction_date": tx_date,
            "disclosure_date":  disc_date,
            "lag_days":         lag_days,
            "ptr_url":          raw.get("ptr_link") or raw.get("link") or "",
            "source":           "housewatcher",
        }
    except Exception as e:
        print(f"  STOCK Act housewatcher normalize exception: {e}")
        return None


def _politician_normalize(name: str) -> str:
    """Normalize politician name for whitelist matching."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def fetch_capitoltrades(page_size: int = 50, max_pages: int = 3
                        ) -> list[dict[str, Any]]:
    """
    Fetch recent trades from Capitol Trades undocumented JSON endpoint.

    Returns normalized list of dicts:
      [{"politician": "Michael McCaul", "party": "R", "chamber": "House",
        "ticker": "RTX", "side": "BUY"|"SELL",
        "bracket_label": "$100,001 - $250,000", "bracket_mid_usd": 175000,
        "transaction_date": "2026-04-22", "disclosure_date": "2026-05-19",
        "lag_days": 27, "ptr_url": "https://..."}]
    """
    all_trades: list[dict[str, Any]] = []
    for page in range(max_pages):
        data = _http_get_json(
            CAPITOLTRADES_BFF,
            params={"pageSize": page_size, "page": page},
        )
        if not isinstance(data, dict):
            break
        items = data.get("data") or data.get("trades") or []
        if not isinstance(items, list):
            break
        if not items:
            break

        for raw in items:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_capitoltrade(raw)
            if normalized:
                all_trades.append(normalized)

        # Stop early if last page short
        if len(items) < page_size:
            break

    return all_trades


def _normalize_capitoltrade(raw: dict) -> Optional[dict[str, Any]]:
    """Map raw Capitol Trades JSON entry to internal trade dict."""
    try:
        # Schema is undocumented — handle common variations
        politician = raw.get("politician") or {}
        if isinstance(politician, str):
            name = politician
            party = ""
            chamber = ""
        else:
            name = (politician.get("fullName")
                    or politician.get("name")
                    or "")
            party = politician.get("party") or ""
            chamber = politician.get("chamber") or politician.get("house") or ""

        asset = raw.get("asset") or {}
        if isinstance(asset, str):
            ticker = asset
        else:
            ticker = (asset.get("ticker") or asset.get("symbol") or "").upper()

        side = (raw.get("txType") or raw.get("type")
                or raw.get("transactionType") or "").lower()
        if "buy" in side or side == "p":
            side = "BUY"
        elif "sell" in side or side == "s":
            side = "SELL"
        else:
            side = side.upper() or "UNKNOWN"

        tx_date = (raw.get("txDate") or raw.get("transactionDate")
                   or raw.get("_txDate") or "")[:10]
        disclosure_date = (raw.get("filed") or raw.get("disclosureDate")
                           or raw.get("filingDate") or "")[:10]

        # Bracket — try labeled string first, then numeric range
        bracket_label = (raw.get("amount") or raw.get("value")
                         or raw.get("bracket") or "")
        bracket_low = raw.get("amountLow") or raw.get("low")
        bracket_high = raw.get("amountHigh") or raw.get("high")
        if isinstance(bracket_label, dict):
            bracket_low = bracket_label.get("low")
            bracket_high = bracket_label.get("high")
            bracket_label = bracket_label.get("label", "") or ""

        bracket_mid = _bracket_to_mid(bracket_label or "",
                                      low=bracket_low, high=bracket_high)

        # Lag (disclosure - transaction)
        lag_days = -1
        try:
            tx_d = datetime.strptime(tx_date, "%Y-%m-%d").date()
            disc_d = datetime.strptime(disclosure_date, "%Y-%m-%d").date()
            lag_days = (disc_d - tx_d).days
        except (ValueError, TypeError):
            pass

        ptr_url = (raw.get("ptrUrl") or raw.get("filingUrl")
                   or raw.get("url") or "")

        if not name or not ticker:
            return None

        return {
            "politician":       name,
            "party":            party,
            "chamber":          chamber,
            "ticker":           ticker,
            "side":             side,
            "bracket_label":    bracket_label,
            "bracket_mid_usd":  bracket_mid,
            "transaction_date": tx_date,
            "disclosure_date":  disclosure_date,
            "lag_days":         lag_days,
            "ptr_url":          ptr_url,
            "source":           "capitoltrades",
        }
    except Exception as e:
        print(f"  STOCK Act normalize exception: {e}")
        return None


def fetch_recent_ptrs(lookback_days: int = LOOKBACK_DAYS,
                      whitelist: Optional[set[str]] = None,
                      min_bracket_usd: float = MIN_BRACKET_MID_USD,
                      ) -> list[dict[str, Any]]:
    """
    Fetch + filter PTRs from last `lookback_days`.

    Args:
      lookback_days: only return disclosures with disclosure_date within window
      whitelist: set of politician names (normalized lowercase); None = no filter
      min_bracket_usd: drop trades below this bracket midpoint

    Returns filtered + normalized list (politician + party + chamber +
    ticker + side + bracket_mid_usd + dates + lag + ptr_url).
    """
    trades = fetch_capitoltrades()
    if not trades:
        print(f"  STOCK Act: 0 trades from Capitol Trades (endpoint may be "
              f"503/blocked) — trying housewatcher fallback...")
        trades = fetch_housewatcher_fallback()
        if not trades:
            print(f"  STOCK Act: housewatcher fallback returned 0 — "
                  f"trying official House Clerk XML index (tier 3)...")
            trades = fetch_houseclerk_index()
            if not trades:
                print(f"  STOCK Act: ALL 3 sources returned 0 — "
                      f"likely temporary outage; next cron retries")
                return []
            print(f"  STOCK Act: houseclerk XML returned {len(trades)} "
                  f"filing alerts (metadata only — no ticker/amount; "
                  f"operator reads PDF via ptr_url)")
        else:
            print(f"  STOCK Act: housewatcher fallback returned {len(trades)} trades")

    cutoff = date.today() - timedelta(days=lookback_days)
    out: list[dict[str, Any]] = []
    skipped_old = 0
    skipped_below_bracket = 0
    skipped_not_whitelisted = 0

    for t in trades:
        # Date filter
        try:
            disc_d = datetime.strptime(t["disclosure_date"], "%Y-%m-%d").date()
            if disc_d < cutoff:
                skipped_old += 1
                continue
        except (ValueError, TypeError):
            # Missing date → keep (let Curator decide)
            pass

        # Bracket filter — houseclerk filing_alert entries bypass (no ticker
        # yet, so bracket unknown; they're metadata-only "operator review" alerts)
        if not t.get("filing_alert") and t["bracket_mid_usd"] < min_bracket_usd:
            skipped_below_bracket += 1
            continue

        # Whitelist filter
        if whitelist:
            if _politician_normalize(t["politician"]) not in whitelist:
                skipped_not_whitelisted += 1
                continue

        out.append(t)

    print(f"  STOCK Act: {len(out)} trades passed "
          f"(skipped: {skipped_old} old, {skipped_below_bracket} below bracket, "
          f"{skipped_not_whitelisted} not whitelisted)")
    return out


# ─── Whitelist loader ─────────────────────────────────────────────

WHITELIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".claude", "rules", "politicians-whitelist.md",
)


def load_whitelist(path: str = WHITELIST_PATH) -> dict[str, dict[str, Any]]:
    """
    Parse politicians-whitelist.md → dict keyed by normalized politician name.

    Returns: {"michael mccaul": {"name": "Michael McCaul", "party": "R",
              "chamber": "House", "category": "committee_insider",
              "weight": 1.4}, ...}

    Returns empty dict on parse failure (caller can fail-open).
    """
    out: dict[str, dict[str, Any]] = {}
    if not os.path.exists(path):
        return out

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return out

    # Lines look like: "Michael McCaul | R | House | committee_insider | 1.4"
    line_re = re.compile(
        r"^\s*([A-Za-z][A-Za-z .'\-]+?)\s*\|\s*([RD])\s*\|\s*"
        r"([A-Za-z /]+?)\s*\|\s*(\w+)\s*\|\s*([\d.]+)\s*$"
    )
    for line in text.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        name, party, chamber, category, weight_s = m.groups()
        try:
            weight = float(weight_s)
        except ValueError:
            weight = 1.0
        out[_politician_normalize(name)] = {
            "name":     name.strip(),
            "party":    party,
            "chamber":  chamber.strip(),
            "category": category,
            "weight":   weight,
        }
    return out


__all__ = [
    "MIN_BRACKET_MID_USD",
    "LOOKBACK_DAYS",
    "fetch_capitoltrades",
    "fetch_recent_ptrs",
    "load_whitelist",
    "_bracket_to_mid",
    "_politician_normalize",
]

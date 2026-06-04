"""v3.16.0 (2026-06-04) — Historical event-data fetcher for the backtest harness.

Uses GDELT 2.0 Event Database — FREE, no auth, daily exports going back to 2015.
We download 15-minute CSV.zip slices, filter by EventCode + SourceCommonName
whitelist, and persist a normalized JSONL cache.

DATA SOURCE
-----------
GDELT 2.0 export URL pattern:
    http://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip

Each 15-min slice is a zipped CSV with ~hundreds of rows. Schema docs:
    http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf

We use minimal subset of columns:
    [0] GlobalEventID
    [1] Day  (YYYYMMDD)
    [26] EventCode  (CAMEO code — e.g. "190" = use of military force)
    [27] EventBaseCode
    [28] EventRootCode
    [29] QuadClass  (1 verbal cooperation, 2 material cooperation,
                    3 verbal conflict, 4 material conflict)
    [30] GoldsteinScale  (-10..+10; conflict negative, cooperation positive)
    [31] NumMentions
    [32] NumSources
    [33] NumArticles
    [34] AvgTone
    [35-44] Actor1Geo / Actor2Geo / ActionGeo
    [57] SOURCEURL
    [58] (in v2 file) ActionGeo_CountryCode

For Phase 1 MVP we use a narrower whitelist (military/energy/monetary CAMEO codes)
+ headline-keyword filter via the shared classifier.

CACHE
-----
backtest/cache/events/<YYYY-MM-DD>.jsonl

Each line is a JSON event:
    {"event_id": "...", "day": "YYYY-MM-DD", "event_code": "190",
     "goldstein": -8.0, "quad_class": 4, "num_articles": 12,
     "source_url": "...", "headline": "...", "summary": ""}

Fail-soft contract: any HTTP / parse failure returns [] for that slice.

CONSTRAINTS
-----------
- FREE only (GDELT public bucket).
- No auth.
- No paid mirror.
- Rate-limited at the caller — default 1 req/sec.
- Cache always honored unless `use_cache=False`.

The harness is offline by design after first cache write. CI runs use
synthetic fixture events; live network calls only when operator explicitly
runs `python -m backtest.run --strategy geo-defense --start ... --days ...`
in a connected environment.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone

# requests is optional for tests that work on synthetic events only.
try:
    import requests  # type: ignore
    _HAS_REQUESTS = True
except Exception:
    requests = None  # type: ignore
    _HAS_REQUESTS = False


# ─── Paths ────────────────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "events")

# Public GDELT bucket. No auth needed.
GDELT_V2_BASE = "http://data.gdeltproject.org/gdeltv2"

# CAMEO root codes relevant to our strategies (Phase 1 whitelist).
#   "19" — use of military force (defense events)
#   "20" — unconventional mass violence
#   "16" — appeal to yield (sanctions / embargo)
#   "17" — coerce (sanctions, threats)
#   "18" — assault
#   "13" — threaten
# We don't filter by root code strictly — caller may supply broader/narrower
# whitelist via `event_code_prefixes`.
DEFAULT_DEFENSE_PREFIXES   = ("19", "20", "18", "17", "13")
DEFAULT_ENERGY_PREFIXES    = ("166", "172", "171", "1722")  # threats/embargo
DEFAULT_MONETARY_PREFIXES  = ("01", "02", "030")            # rate decisions et al.


# ─── Rate-limit guard (module state) ──────────────────────────────────────────

_LAST_FETCH_TS: float = 0.0
DEFAULT_MIN_INTERVAL_S: float = 1.0


def _rate_limit(min_interval_s: float = DEFAULT_MIN_INTERVAL_S) -> None:
    """Sleep just enough to space requests by `min_interval_s`."""
    global _LAST_FETCH_TS
    now = time.monotonic()
    elapsed = now - _LAST_FETCH_TS
    if 0.0 < elapsed < min_interval_s:
        time.sleep(min_interval_s - elapsed)
    _LAST_FETCH_TS = time.monotonic()


# ─── Event dataclass ──────────────────────────────────────────────────────────

@dataclass
class HistoricalEvent:
    event_id:        str
    day:             str           # YYYY-MM-DD
    event_code:      str
    quad_class:      int
    goldstein:       float
    num_articles:    int
    source_url:      str
    headline:        str = ""
    summary:         str = ""
    detected_at_iso: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _cache_path_for_day(day: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{day}.jsonl")


def load_cached_events(day: str) -> list[HistoricalEvent]:
    """Read cached events for a single day. Returns [] when no cache yet."""
    path = _cache_path_for_day(day)
    if not os.path.exists(path):
        return []
    out: list[HistoricalEvent] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    out.append(HistoricalEvent(**d))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def save_events_to_cache(day: str, events) -> int:
    """Atomic append-or-overwrite of events to `<day>.jsonl`. Returns count written."""
    path = _cache_path_for_day(day)
    try:
        with open(path, "w", encoding="utf-8") as f:
            count = 0
            for ev in events:
                d = ev.to_dict() if isinstance(ev, HistoricalEvent) else dict(ev)
                f.write(json.dumps(d, default=str) + "\n")
                count += 1
        return count
    except Exception:
        return 0


# ─── GDELT CSV parsing ────────────────────────────────────────────────────────

def parse_gdelt_csv_zip(payload: bytes,
                        event_code_prefixes: tuple = (),
                        ) -> list[HistoricalEvent]:
    """Parse a GDELT v2 export CSV.zip blob into HistoricalEvent list.

    Args:
        payload: raw bytes of the .CSV.zip download
        event_code_prefixes: optional filter — keep only events whose
            EventCode starts with one of these prefixes. Empty tuple = keep all.

    Returns:
        list[HistoricalEvent] (possibly empty). Fail-soft on any error.
    """
    out: list[HistoricalEvent] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            for name in zf.namelist():
                if not name.endswith(".CSV"):
                    continue
                with zf.open(name) as fh:
                    text = fh.read().decode("utf-8", errors="replace")
                for line in text.splitlines():
                    cols = line.split("\t")
                    if len(cols) < 58:
                        continue
                    try:
                        event_id = cols[0].strip()
                        day_raw  = cols[1].strip()           # YYYYMMDD
                        if len(day_raw) != 8 or not day_raw.isdigit():
                            continue
                        day_iso  = f"{day_raw[:4]}-{day_raw[4:6]}-{day_raw[6:8]}"
                        event_code = cols[26].strip()
                        if event_code_prefixes and not any(
                            event_code.startswith(p) for p in event_code_prefixes
                        ):
                            continue
                        quad_class   = int(cols[29] or 0)
                        goldstein    = float(cols[30] or 0.0)
                        num_articles = int(cols[33] or 0)
                        source_url   = cols[57].strip()
                        out.append(HistoricalEvent(
                            event_id=event_id,
                            day=day_iso,
                            event_code=event_code,
                            quad_class=quad_class,
                            goldstein=goldstein,
                            num_articles=num_articles,
                            source_url=source_url,
                            # GDELT v2 CSV doesn't carry headline text directly;
                            # SOURCEURL is the lead. Caller can backfill via
                            # NewsAPI later if needed.
                            headline="",
                            summary="",
                            detected_at_iso=f"{day_iso}T00:00:00+00:00",
                        ))
                    except Exception:
                        continue
    except Exception:
        return []
    return out


# ─── Fetcher ──────────────────────────────────────────────────────────────────

def fetch_gdelt_slice(timestamp_utc: datetime,
                       event_code_prefixes: tuple = DEFAULT_DEFENSE_PREFIXES,
                       *,
                       rate_limit_s: float = DEFAULT_MIN_INTERVAL_S,
                       timeout_s: float = 30.0,
                       ) -> list[HistoricalEvent]:
    """Fetch + parse a single 15-min GDELT export slice. Fail-soft → []."""
    if not _HAS_REQUESTS:
        return []
    # Round to 15-minute boundary (GDELT publishes :00, :15, :30, :45).
    minute = (timestamp_utc.minute // 15) * 15
    snapped = timestamp_utc.replace(minute=minute, second=0, microsecond=0)
    stamp = snapped.strftime("%Y%m%d%H%M%S")
    url = f"{GDELT_V2_BASE}/{stamp}.export.CSV.zip"
    try:
        _rate_limit(rate_limit_s)
        r = requests.get(url, timeout=timeout_s)
        if r.status_code != 200:
            return []
        return parse_gdelt_csv_zip(r.content, event_code_prefixes=event_code_prefixes)
    except Exception:
        return []


def fetch_events_for_day(day_iso: str,
                          event_code_prefixes: tuple = DEFAULT_DEFENSE_PREFIXES,
                          *,
                          use_cache: bool = True,
                          rate_limit_s: float = DEFAULT_MIN_INTERVAL_S,
                          max_slices_per_day: int = 96,
                          ) -> list[HistoricalEvent]:
    """Fetch all 15-min slices for a single day, deduping by event_id.

    Returns events sorted by day. Fail-soft contract: on any error → [].

    Args:
        day_iso:  "YYYY-MM-DD"
        event_code_prefixes: CAMEO prefix filter
        use_cache: short-circuit when cache file exists and non-empty
        rate_limit_s: min seconds between fetches
        max_slices_per_day: cap (96 = full day at 15-min cadence)
    """
    if use_cache:
        cached = load_cached_events(day_iso)
        if cached:
            return cached
    if not _HAS_REQUESTS:
        return []
    try:
        date = datetime.strptime(day_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return []

    seen_ids: set = set()
    out: list[HistoricalEvent] = []
    for slice_idx in range(max_slices_per_day):
        ts = date + timedelta(minutes=slice_idx * 15)
        for ev in fetch_gdelt_slice(ts, event_code_prefixes, rate_limit_s=rate_limit_s):
            if ev.event_id in seen_ids:
                continue
            seen_ids.add(ev.event_id)
            out.append(ev)
    if use_cache and out:
        save_events_to_cache(day_iso, out)
    return out


def fetch_events_for_range(start_iso: str,
                            end_iso: str,
                            event_code_prefixes: tuple = DEFAULT_DEFENSE_PREFIXES,
                            *,
                            use_cache: bool = True,
                            rate_limit_s: float = DEFAULT_MIN_INTERVAL_S,
                            ) -> list[HistoricalEvent]:
    """Inclusive [start_iso, end_iso] day-by-day fetch. Returns aggregated list."""
    try:
        start = datetime.strptime(start_iso, "%Y-%m-%d").date()
        end   = datetime.strptime(end_iso, "%Y-%m-%d").date()
    except Exception:
        return []
    if end < start:
        return []
    out: list[HistoricalEvent] = []
    cur = start
    while cur <= end:
        day_str = cur.isoformat()
        out.extend(fetch_events_for_day(day_str, event_code_prefixes,
                                         use_cache=use_cache,
                                         rate_limit_s=rate_limit_s))
        cur += timedelta(days=1)
    return out


# ─── Synthetic event helper (for offline tests) ───────────────────────────────

def synthesize_event(headline: str,
                      *,
                      day_iso: str = "2026-01-01",
                      event_code: str = "190",
                      quad_class: int = 4,
                      goldstein: float = -7.0,
                      num_articles: int = 10,
                      source_url: str = "https://example.com/news",
                      summary: str = "",
                      ) -> HistoricalEvent:
    """Helper for tests + harness smoke runs — no network required."""
    return HistoricalEvent(
        event_id=f"synth-{hash((headline, day_iso)) & 0xffffffff}",
        day=day_iso,
        event_code=event_code,
        quad_class=quad_class,
        goldstein=goldstein,
        num_articles=num_articles,
        source_url=source_url,
        headline=headline,
        summary=summary,
        detected_at_iso=f"{day_iso}T12:00:00+00:00",
    )


__all__ = [
    "HistoricalEvent",
    "CACHE_DIR", "GDELT_V2_BASE",
    "DEFAULT_DEFENSE_PREFIXES", "DEFAULT_ENERGY_PREFIXES", "DEFAULT_MONETARY_PREFIXES",
    "DEFAULT_MIN_INTERVAL_S",
    "load_cached_events", "save_events_to_cache",
    "parse_gdelt_csv_zip",
    "fetch_gdelt_slice", "fetch_events_for_day", "fetch_events_for_range",
    "synthesize_event",
]

"""
Geopolitical News Monitor
Skanuje newsy dot. konfliktu Bliski Wschód / Trump / Iran-Izrael
i wysyła alerty do Claude Routine gdy wykryje istotne wydarzenia
"""

import os
import sys
import json
import time
import hashlib
import requests
import feedparser
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from risk_guards import vix_guard, daily_drawdown_guard, get_account_status
    from event_scoring import score_and_decide
    from market_data import compute_reaction_metrics
except ImportError:
    def vix_guard(): return ("OK", 1.0)
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub", "credibility": 60, "prob_shift": 60, "reaction": 50}
    def compute_reaction_metrics(_s): return None


GEO_SOURCE_TYPE_MAP = {
    "Finnhub":  "major_outlet",
    "NewsAPI":  "major_outlet",
    "Reuters":  "reuters_ap",
    "AP News":  "reuters_ap",
}


def _geo_event_type(score: int) -> str:
    if score >= 4:
        return "policy_announced"
    return "threat_or_warning"


def _geo_magnitude(score: int) -> str:
    if score >= 5:
        return "large"
    if score >= 3:
        return "normal"
    return "small"


def attach_event_scoring(news_items: list[dict]) -> list[dict]:
    """
    For each news item, attach event-probability scoring under `scoring`.
    Filters out IGNORE_EVENT and WAIT_FOR_CONFIRMATION; keeps
    FOLLOW_REACTION and CONTRARIAN_CANDIDATE (the routine decides what
    to do with contrarian items).

    Geo-monitor doesn't carry a single ticker (news -> routine resolves
    target), so we use SPY as a market-wide reaction proxy. For genuine
    geo escalation, SPY tends to react via risk-off across the index;
    individual defense/energy names move even more, but SPY is the most
    stable single-symbol proxy we have.
    """
    spy_metrics = compute_reaction_metrics("SPY")
    if spy_metrics:
        pma, vr, gap = spy_metrics["price_move_atr"], spy_metrics["volume_ratio"], spy_metrics["gap_pct"]
        print(f"  Market reaction (SPY): move={pma}×ATR vol={vr}× gap={gap}%")
    else:
        pma, vr, gap = 0.5, 1.0, 0.0
        print("  Market reaction: SPY bars unavailable -> using placeholders")

    kept = []
    for item in news_items:
        src_type = GEO_SOURCE_TYPE_MAP.get(item.get("source", ""), "major_outlet")
        scoring = score_and_decide(
            source_type    = src_type,
            event_type     = _geo_event_type(item.get("score", 0)),
            price_move_atr = pma,
            volume_ratio   = vr,
            gap_pct        = gap,
            magnitude      = _geo_magnitude(item.get("score", 0)),
        )
        item["scoring"]          = scoring
        item["reaction_metrics"] = spy_metrics
        if scoring["stance"] in ("FOLLOW_REACTION", "CONTRARIAN_CANDIDATE"):
            kept.append(item)
        else:
            print(f"    [event-layer] dropped {item.get('title','')[:60]}: {scoring['stance']}")
    return kept

# ─── Konfiguracja ────────────────────────────────────────────────────────────

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_GEO_WORKER_URL", "")
FINNHUB_API_KEY       = os.environ.get("FINNHUB_API_KEY", "")
NEWSAPI_KEY           = os.environ.get("NEWSAPI_KEY", "")

# Słowa kluczowe — geopolityka Bliski Wschód / Trump
KEYWORDS_HIGH = [
    # Eskalacja — najwyższy priorytet
    "iran nuclear", "iran attack", "israel strike", "middle east war",
    "strait of hormuz", "oil embargo", "trump sanction iran",
    "hezbollah attack", "hamas", "iran missile",
]

KEYWORDS_MEDIUM = [
    # Ważne ale nie krytyczne
    "iran", "israel", "middle east", "trump tariff", "trump sanction",
    "oil supply", "opec", "trump executive order", "trade war",
    "nuclear deal", "biden iran", "netanyahu", "tehran",
]

# Aktywa dotknięte przez geopolitykę
ASSET_MAP = {
    "defense":  ["RTX", "LMT", "NOC", "LHX", "GD"],   # spółki obronne
    "energy":   ["XOM", "CVX", "USO", "XLE"],           # ropa i energia
    "gold":     ["GLD", "IAU", "GDX"],                  # złoto safe haven
    "tech":     ["QQQ", "SPY"],                         # broad market
}

# RSS feeds do monitorowania
RSS_FEEDS = [
    "https://feeds.reuters.com/Reuters/worldNews",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://rss.cnn.com/rss/edition_world.rss",
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
]

# ─── Pomocnicze ──────────────────────────────────────────────────────────────

def news_hash(title: str) -> str:
    """Unikalny hash newsa żeby nie wysyłać duplikatów"""
    return hashlib.md5(title.lower().encode()).hexdigest()[:12]


def score_news(text: str) -> tuple[int, str]:
    """
    Ocenia istotność newsa.
    Zwraca (score, priority): score > 0 = wart wysłania
    """
    text_lower = text.lower()
    score = 0
    priority = "LOW"

    for kw in KEYWORDS_HIGH:
        if kw in text_lower:
            score += 3

    for kw in KEYWORDS_MEDIUM:
        if kw in text_lower:
            score += 1

    if score >= 3:
        priority = "HIGH"
    elif score >= 1:
        priority = "MEDIUM"

    return score, priority


def fetch_finnhub_news() -> list[dict]:
    """Pobiera ogólne newsy z Finnhub"""
    if not FINNHUB_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_API_KEY},
            timeout=10,
        )
        items = resp.json() if resp.ok else []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = []
        for item in items:
            ts = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            if ts >= cutoff:
                result.append({
                    "title":   item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "url":     item.get("url", ""),
                    "source":  item.get("source", "Finnhub"),
                    "time":    ts.isoformat(),
                })
        print(f"  Finnhub: {len(result)} newsów (ostatnie 24h)")
        return result
    except Exception as e:
        print(f"  Finnhub error: {e}")
        return []


def fetch_newsapi(query: str) -> list[dict]:
    """Pobiera newsy z NewsAPI.org dla zapytania"""
    if not NEWSAPI_KEY:
        return []
    try:
        from_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_time,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
        result = []
        for item in data.get("articles", []):
            result.append({
                "title":   item.get("title", ""),
                "summary": item.get("description", ""),
                "url":     item.get("url", ""),
                "source":  item.get("source", {}).get("name", "NewsAPI"),
                "time":    item.get("publishedAt", ""),
            })
        print(f"  NewsAPI: {len(result)} newsów (ostatnie 24h, status: {data.get('status')})")
        return result
    except Exception as e:
        print(f"  NewsAPI error: {e}")
        return []


def fetch_rss_feeds() -> list[dict]:
    """Pobiera newsy z RSS feedów"""
    result = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            count_before = len(result)
            for entry in feed.entries[:20]:
                pub = entry.get("published_parsed")
                if pub:
                    ts = datetime(*pub[:6], tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                result.append({
                    "title":   entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "url":     entry.get("link", ""),
                    "source":  feed.feed.get("title", url),
                    "time":    entry.get("published", ""),
                })
            print(f"  RSS {feed.feed.get('title', url)[:40]}: {len(result) - count_before} newsów")
        except Exception as e:
            print(f"  RSS error ({url}): {e}")
    return result


def send_alert(news_items: list[dict], priority: str) -> bool:
    """Wysyła alert do Cloudflare Worker → Claude Routine"""
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_GEO_WORKER_URL — pomijam wysyłanie")
        return False

    payload = {
        "type":       "geopolitical_alert",
        "priority":   priority,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "news_count": len(news_items),
        "asset_map":  ASSET_MAP,
        "news":       news_items[:10],  # max 10 newsów na raz
    }

    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=payload,
            timeout=30,
        )
        print(f"  Alert wysłany: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania alertu: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def run_scan():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] Skanuję newsy geopolityczne...")

    # v2.0 safety net: account-level circuit breaker BEFORE VIX guard
    dd_status, _ = daily_drawdown_guard()
    if dd_status == "HALT":
        return

    vix_status, _ = vix_guard()
    if vix_status == "HALT":
        return

    # Zbierz newsy ze wszystkich źródeł
    all_news = []
    all_news += fetch_finnhub_news()
    all_news += fetch_newsapi("Iran OR Israel OR 'Middle East' OR Trump sanctions OR Trump tariff")
    all_news += fetch_rss_feeds()

    print(f"  Pobrano {len(all_news)} newsów łącznie")

    # Filtruj i oceniaj
    relevant = []
    seen_hashes = set()

    for item in all_news:
        text = f"{item['title']} {item['summary']}"
        h = news_hash(item['title'])

        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        score, priority = score_news(text)
        if score > 0:
            item["score"]    = score
            item["priority"] = priority
            relevant.append(item)

    # Sortuj po score malejąco
    relevant.sort(key=lambda x: x["score"], reverse=True)

    print(f"  Znaleziono {len(relevant)} istotnych newsów")

    # Event-probability layer — filtruje słabe credibility / brak reakcji
    relevant = attach_event_scoring(relevant)
    print(f"  Po event-scoring: {len(relevant)} newsów")

    if not relevant:
        print("  Brak istotnych newsów po event-scoring — koniec skanowania")
        return

    # Określ ogólny priorytet
    max_score  = relevant[0]["score"]
    top_priority = "HIGH" if max_score >= 3 else "MEDIUM"

    # Pokaż top newsy
    print(f"\n  TOP newsy (priorytet: {top_priority}):")
    for item in relevant[:5]:
        print(f"  [{item['priority']}] {item['title'][:80]}")

    # Wyślij alert
    print(f"\n  Wysyłam alert do Claude Routine...")
    send_alert(relevant, top_priority)


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Geopolitical News Monitor")
    print(f"  Finnhub: {'✓' if FINNHUB_API_KEY else '✗'}")
    print(f"  NewsAPI: {'✓' if NEWSAPI_KEY else '✗ (opcjonalne)'}")
    print(f"  Worker URL: {'✓' if CLOUDFLARE_WORKER_URL else '✗'}")
    print("=" * 60)

    run_scan()

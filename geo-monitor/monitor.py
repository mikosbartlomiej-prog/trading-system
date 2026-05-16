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
    from risk_guards import vix_guard, daily_drawdown_guard, get_account_status, has_open_position, concentration_ok
    from event_scoring import score_and_decide
    from market_data import compute_reaction_metrics
    from alpaca_orders import execute_stock_signal
    from notify import notify_signal, notify_summary
except ImportError:
    def vix_guard(): return ("OK", 1.0)
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def has_open_position(_s): return False
    def concentration_ok(_s, _sz, equity=None): return (True, 0.0)
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub", "credibility": 60, "prob_shift": 60, "reaction": 50}
    def compute_reaction_metrics(_s): return None
    def execute_stock_signal(_s): return None
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass


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

# v3.8.7 (2026-05-16): direct execution mode. USE_ROUTINE=true reverts to
# legacy Cloudflare Worker → Claude Routine path (DEPRECATED, kept as
# fallback only). Default false routes through alpaca_orders.execute_stock_signal
# matching defense-monitor's pattern.
USE_ROUTINE = os.environ.get("USE_ROUTINE", "false").lower() == "true"
AUTO_EXECUTE = os.environ.get("AUTO_EXECUTE_GEO", "true").lower() == "true"
MAX_TRADES_PER_RUN = int(os.environ.get("GEO_MAX_TRADES_PER_RUN", "2"))

# Strategy sizing per docs/STRATEGY.md §4.4 (geopolitical bucket).
SIZE_USD_HIGH_PRIORITY   = 8000.0   # major escalation (e.g. iran attack, strait of hormuz)
SIZE_USD_MEDIUM_PRIORITY = 4000.0   # routine news (e.g. trump tariff, opec)
GEO_SL_PCT               = -5.0     # -5% stop-loss
GEO_TP_PCT               = 10.0     # +10% take-profit (conservative for news-driven)

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


def _classify_news_to_signals(news_items: list[dict], top_priority: str) -> list[dict]:
    """
    v3.8.7 (2026-05-16): direct execution classifier (replaces deprecated
    routine path). For each news item, build (ticker, side, strategy)
    signal dict mirroring defense-monitor's pattern. Mapping based on
    keyword bucket + sentiment.

    Pattern rules:
      - "iran attack" / "israel strike" / "missile" / "hezbollah" / "hamas"
          → defense LONG (RTX, LMT primary)
      - "oil embargo" / "strait of hormuz" / "iran" / "opec"
          → energy LONG (XOM, CVX, USO primary)
      - "nuclear" / "war" / generic escalation
          → gold LONG (GLD safe haven)
      - "trade war" / "trump tariff" / "trump sanction" (non-iran)
          → broad SHORT-bias (skip — too noisy, requires direction context)

    Sizing per docs/STRATEGY.md §4.4 (geo bucket): $8k HIGH, $4k MEDIUM.
    Per-event MAX_TRADES_PER_RUN=2 cap prevents news-cluster overload.
    """
    signals: list[dict] = []
    seen_tickers: set[str] = set()
    DEFENSE_KW    = ("iran attack", "iran missile", "israel strike", "missile",
                     "hezbollah", "hamas", "middle east war")
    ENERGY_KW     = ("oil embargo", "strait of hormuz", "oil supply",
                     "iran ", "iran nuclear", "opec", "trump sanction iran")
    GOLD_KW       = ("nuclear", "war ", "tensions escalate", "diplomatic crisis")

    size_usd = SIZE_USD_HIGH_PRIORITY if top_priority == "HIGH" else SIZE_USD_MEDIUM_PRIORITY

    for item in news_items[:5]:    # process top-5 by score
        title_lower = (item.get("title") or "").lower()
        summary_lower = (item.get("summary") or "").lower()
        haystack = title_lower + " " + summary_lower

        triggered: list[tuple[str, str, str]] = []   # (bucket, ticker, strategy)

        if any(kw in haystack for kw in DEFENSE_KW):
            for t in ASSET_MAP["defense"][:2]:    # RTX + LMT primary
                triggered.append(("defense", t, "geo-defense"))
        if any(kw in haystack for kw in ENERGY_KW):
            for t in ASSET_MAP["energy"][:2]:     # XOM + CVX primary
                triggered.append(("energy", t, "geo-xom" if t in ("XOM","CVX") else "geo-energy"))
        if any(kw in haystack for kw in GOLD_KW):
            triggered.append(("gold", "GLD", "geo-gold"))

        for bucket, ticker, strategy in triggered:
            if ticker in seen_tickers:
                continue          # one trade per ticker per run
            seen_tickers.add(ticker)
            signals.append({
                "symbol":   ticker,
                "action":   "BUY",
                "size_usd": size_usd,
                "sl_pct":   GEO_SL_PCT,
                "tp_pct":   GEO_TP_PCT,
                "strategy": strategy,
                "score":    item.get("score", 0),
                "source":   item.get("source", "geo-news"),
                "headline": (item.get("title", "") or "")[:120],
                "url":      item.get("url", ""),
                "bucket":   bucket,
                "priority": top_priority,
            })
    return signals[:MAX_TRADES_PER_RUN]


def execute_geo_signal(signal: dict) -> bool:
    """
    Place geo-driven BUY via direct Alpaca REST. Same gate stack as
    defense-monitor: VIX + drawdown + concentration + PDT all checked
    inside execute_stock_signal / place_stock_bracket.

    Returns True iff Alpaca returned an order ID.
    """
    if not USE_ROUTINE:
        if not AUTO_EXECUTE:
            print(f"  AUTO_EXECUTE_GEO=false — signal {signal['symbol']} skipped (email-only)")
            return False
        # Pre-execute symbol guards (mirror defense-monitor::run_scan).
        sym = signal["symbol"]
        if has_open_position(sym):
            print(f"  >>> {signal['action']} {sym} pominięty (otwarta pozycja)")
            return False
        order = execute_stock_signal(signal)
        if order and order.get("id"):
            print(f"  Order {signal['action']} {sym}: id={order['id']} qty={order.get('qty')} @ ${order.get('limit_price')}")
            return True
        if order and order.get("deferred"):
            print(f"  Order {signal['action']} {sym}: DEFERRED ({order.get('reason')})")
            return False
        print(f"  Order {signal['action']} {sym}: REJECTED (Alpaca / quote unavailable)")
        return False

    # Legacy routine path (opt-in via USE_ROUTINE=true)
    if not CLOUDFLARE_WORKER_URL:
        print(f"  BRAK CLOUDFLARE_GEO_WORKER_URL — sygnał lokalnie: {signal}")
        return False
    try:
        resp = requests.post(CLOUDFLARE_WORKER_URL, json=signal, timeout=30)
        print(f"  Routine forward {signal['action']} {signal['symbol']}: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd routine forward: {e}")
        return False


def send_alert(news_items: list[dict], priority: str) -> bool:
    """
    DEPRECATED legacy alert path — kept for back-compat with USE_ROUTINE=true.
    Default v3.8.7+ flow uses _classify_news_to_signals + execute_geo_signal.
    """
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_GEO_WORKER_URL — pomijam wysyłanie")
        return False

    payload = {
        "type":       "geopolitical_alert",
        "priority":   priority,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "news_count": len(news_items),
        "asset_map":  ASSET_MAP,
        "news":       news_items[:10],
    }

    try:
        resp = requests.post(CLOUDFLARE_WORKER_URL, json=payload, timeout=30)
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

    # v3.8.7 (2026-05-16): direct execution path replaces deprecated routine.
    # USE_ROUTINE=true falls back to legacy Cloudflare Worker → Routine flow.
    if USE_ROUTINE:
        print(f"\n  USE_ROUTINE=true — sending to Claude Routine (legacy path)...")
        send_alert(relevant, top_priority)
        return

    # Direct execution: classify news → build signals → execute via Alpaca.
    signals = _classify_news_to_signals(relevant, top_priority)
    print(f"\n  Classified {len(signals)} trade signals from {len(relevant)} news items "
          f"(cap MAX_TRADES_PER_RUN={MAX_TRADES_PER_RUN}, AUTO_EXECUTE={AUTO_EXECUTE})")

    placed = 0
    for sig in signals:
        print(f"\n  >>> {sig['strategy']} {sig['action']} {sig['symbol']} "
              f"(bucket={sig['bucket']}, score={sig['score']}, ${sig['size_usd']:.0f})")
        print(f"      headline: {sig['headline'][:100]}")
        ok = execute_geo_signal(sig)
        try:
            notify_signal(sig, ok, reason="" if ok else "alpaca_reject")
        except Exception:
            pass
        if ok:
            placed += 1

    notify_summary("Geo Monitor", len(signals), placed)
    print(f"\n  Geo signals placed: {placed}/{len(signals)}")


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Geopolitical News Monitor")
    print(f"  Finnhub: {'✓' if FINNHUB_API_KEY else '✗'}")
    print(f"  NewsAPI: {'✓' if NEWSAPI_KEY else '✗ (opcjonalne)'}")
    print(f"  Worker URL: {'✓' if CLOUDFLARE_WORKER_URL else '✗'}")
    print("=" * 60)

    run_scan()

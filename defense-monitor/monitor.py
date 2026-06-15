"""
Defense Market Monitor — 30-min scan
Monitoruje rynek zbrojeniowy: DoD contracts, RSS feeds, NewsAPI.
Generuje sygnały LONG/SHORT dla akcji sektora obronnego.
"""

import os
import sys
import json
import time
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

# v3.22.0 — observability-only wiring into the canonical signal pipeline.
# emit_monitor_signal NEVER places trades; it forwards a SignalEvent to
# shared.signal_emitter.emit_signal_opportunity which persists via the
# opportunity ledger. NEVER imports alpaca_orders. NEVER calls the broker.
try:
    from monitor_signal_helper import emit_monitor_signal  # type: ignore
except Exception:
    try:
        from shared.monitor_signal_helper import emit_monitor_signal  # type: ignore
    except Exception:
        def emit_monitor_signal(*_a, **_kw):  # type: ignore
            return None

# v3.24 — monitor runtime diagnostics (ETAP 9). Fail-soft.
try:
    from monitor_runtime_diag import (  # type: ignore
        record_diag as _diag,
        DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
        DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
        DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
    )
except Exception:
    try:
        from shared.monitor_runtime_diag import (  # type: ignore
            record_diag as _diag,
            DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
            DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
            DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
        )
    except Exception:
        def _diag(*_a, **_kw):  # type: ignore
            return False
        DIAG_RAN = "RAN"; DIAG_INPUT_EMPTY = "INPUT_EMPTY"
        DIAG_NO_SIGNAL = "NO_SIGNAL"; DIAG_SIGNAL_DETECTED = "SIGNAL_DETECTED"
        DIAG_EMIT_ATTEMPTED = "EMIT_ATTEMPTED"
        DIAG_EMIT_SUCCESS = "EMIT_SUCCESS"; DIAG_EMIT_FAILED = "EMIT_FAILED"

# Email notifications (optional)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard, has_open_position, daily_drawdown_guard, get_account_status, concentration_ok
    from event_scoring import score_and_decide
    from market_data import compute_reaction_metrics
    from alpaca_orders import execute_stock_signal
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def has_open_position(_): return False
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def concentration_ok(_s, _n, equity=None): return (True, 0.0)
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub", "credibility": 60, "prob_shift": 60, "reaction": 50}
    def compute_reaction_metrics(_s): return None
    def execute_stock_signal(_s): return None

# Default: AUTO_EXECUTE via Alpaca REST. USE_ROUTINE=true -> legacy worker path.
USE_ROUTINE = os.environ.get("USE_ROUTINE", "false").lower() == "true"


# ─── Event-probability mapping (for scoring layer) ───────────────────────────

DEFENSE_SOURCE_TYPE_MAP = {
    "DoD Contracts":    "contract_award",
    "USASpending":      "contract_award",
    "Defense One":      "niche_outlet",
    "Breaking Defense": "niche_outlet",
    "Reuters":          "reuters_ap",
    "AP":               "reuters_ap",
    "AP News":          "reuters_ap",
}


def _map_event_source_type(source: str) -> str:
    return DEFENSE_SOURCE_TYPE_MAP.get(source, "major_outlet")


def _map_event_type(source: str, score: int) -> str:
    if source in ("DoD Contracts", "USASpending"):
        return "signed_contract"
    if score >= 3:
        return "policy_announced"
    return "threat_or_warning"


def _map_magnitude(score: int) -> str:
    if score >= 4:
        return "large"
    if score >= 2:
        return "normal"
    return "small"


def apply_event_scoring(signals: list[dict]) -> list[dict]:
    """
    For each candidate signal, attach event-probability scoring and filter:
      FOLLOW_REACTION       -> keep, send through
      IGNORE_EVENT / WAIT   -> drop with log (noise filter)
      CONTRARIAN_CANDIDATE  -> drop with log + email warning (manual review)

    Now uses real bar-data via compute_reaction_metrics(symbol) so
    CONTRARIAN_CANDIDATE actually fires on stop-hunt patterns. Falls back
    to placeholder values when Alpaca bars are unavailable.
    """
    kept = []
    for s in signals:
        symbol  = s.get("symbol", "")
        metrics = compute_reaction_metrics(symbol) if symbol else None
        if metrics:
            pma, vr, gap = metrics["price_move_atr"], metrics["volume_ratio"], metrics["gap_pct"]
        else:
            pma, vr, gap = 0.5, 1.0, 0.0   # fallback when bars unavailable
        scoring = score_and_decide(
            source_type     = _map_event_source_type(s.get("source", "")),
            event_type      = _map_event_type(s.get("source", ""), s.get("score", 0)),
            price_move_atr  = pma,
            volume_ratio    = vr,
            gap_pct         = gap,
            magnitude       = _map_magnitude(s.get("score", 0)),
        )
        s["scoring"]          = scoring
        s["reaction_metrics"] = metrics
        stance = scoring["stance"]
        if stance == "FOLLOW_REACTION":
            kept.append(s)
        elif stance == "CONTRARIAN_CANDIDATE":
            print(f"    [event-layer] {s['symbol']} {s['action']} -> CONTRARIAN_CANDIDATE, "
                  f"holding back: {scoring['rationale']}")
        else:
            print(f"    [event-layer] {s['symbol']} {s['action']} -> {stance}, "
                  f"dropped: {scoring['rationale']}")
    return kept

# ─── Konfiguracja ────────────────────────────────────────────────────────────

CLOUDFLARE_DEFENSE_WORKER_URL = os.environ.get("CLOUDFLARE_DEFENSE_WORKER_URL", "")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

# ─── Tickery ─────────────────────────────────────────────────────────────────

# US Big 5
TICKERS_BIG5 = ["LMT", "RTX", "NOC", "GD", "BA"]

# US Mid-cap
TICKERS_MIDCAP = ["KTOS", "PLTR", "AXON", "LDOS", "SAIC", "CACI"]

# ETFs (tylko LONG)
TICKERS_ETF = ["ITA", "XAR", "DFEN"]

# European ADRs (tylko LONG)
TICKERS_EUROPEAN = ["BAESY", "EADSY"]

ALL_TICKERS = TICKERS_BIG5 + TICKERS_MIDCAP + TICKERS_ETF + TICKERS_EUROPEAN

# ─── Parametry pozycji ────────────────────────────────────────────────────────

# v2.0 risk-on (was 2500/1500/1500/1000/2000/1000)
SIZE_BIG5_LONG     = 8000   # USD  (~3.2x)
SIZE_BIG5_SHORT    = 5000   # USD  (~3.3x)
SIZE_MIDCAP_LONG   = 5000   # USD  (~3.3x)
SIZE_MIDCAP_SHORT  = 4000   # USD  (4x)
SIZE_ETF_LONG      = 6000   # USD  (3x)
SIZE_EUROPEAN_LONG = 4000   # USD  (4x)

STOP_LOSS_PCT   = 0.03   # -3%
TAKE_PROFIT_PCT = 0.06   # +6%

# ─── Mapowanie: słowo kluczowe → ticker(y) ───────────────────────────────────

COMPANY_TICKER_MAP = {
    # Big 5
    "lockheed":   ["LMT"],
    "lmt":        ["LMT"],
    "raytheon":   ["RTX"],
    "rtx":        ["RTX"],
    "pratt":      ["RTX"],
    "collins":    ["RTX"],
    "northrop":   ["NOC"],
    "grumman":    ["NOC"],
    "noc":        ["NOC"],
    "general dynamics": ["GD"],
    "gd ":        ["GD"],
    "boeing":     ["BA"],
    "ba ":        ["BA"],

    # Mid-cap
    "kratos":     ["KTOS"],
    "ktos":       ["KTOS"],
    "palantir":   ["PLTR"],
    "pltr":       ["PLTR"],
    "axon":       ["AXON"],
    "taser":      ["AXON"],
    "leidos":     ["LDOS"],
    "ldos":       ["LDOS"],
    "saic":       ["SAIC"],
    "caci":       ["CACI"],

    # ETFs — broad defense news
    "pentagon":   ["ITA", "XAR"],
    "department of defense": ["ITA", "XAR"],
    "dod":        ["ITA", "XAR"],
    "nato":       ["ITA", "XAR", "DFEN"],
    "defense budget": ["ITA", "XAR", "DFEN"],
    "military spending": ["ITA", "XAR", "DFEN"],

    # European
    "bae systems": ["BAESY"],
    "baesy":      ["BAESY"],
    "airbus":     ["EADSY"],
    "eadsy":      ["EADSY"],
}

# ─── Słowa kluczowe sygnałów ──────────────────────────────────────────────────

LONG_KEYWORDS = [
    # Kontrakty / zamówienia
    "contract awarded", "contract award", "awarded contract",
    "billion contract", "million contract", "awarded $",
    "indefinite delivery", "idiq", "government contract",
    # Budżet / inwestycje
    "defense budget increase", "increased military spending",
    "supplemental funding", "defense authorization",
    "ndaa", "defense appropriations",
    "record defense budget", "highest ever defense",
    # NATO / sojusznicy
    "nato expansion", "nato spending", "2% gdp",
    "allies increase", "european defense fund",
    "rearmament",
    # Nowe programy
    "new weapons program", "next-generation", "hypersonic",
    "drone program", "missile defense", "space force",
    "f-35", "f-47", "b-21", "ngad",
    # Eskalacja
    "military escalation", "conflict escalation",
    "heightened tensions", "military buildup",
    "arms shipment", "weapons delivery",
    # Ogólne terminy obronne (pasują do newsów z Defense One / Breaking Defense)
    "military", "pentagon", "nato", "air force", "navy", "army",
    "drone", "drones", "missile", "missiles", "weapon", "weapons",
    "fighter jet", "bomber", "aircraft", "warship", "satellite",
    "defense", "defence", "warfare", "combat", "troops", "soldier",
    "airpower", "autonomous", "munition", "munitions", "radar",
    "artillery", "submarine", "carrier", "squadron",
]

SHORT_KEYWORDS = [
    # Deeskalacja
    "ceasefire", "peace deal", "peace agreement",
    "armistice", "negotiations", "diplomatic solution",
    "peace talks", "withdraw troops", "troop withdrawal",
    "end of conflict", "war ends",
    # Cięcia budżetowe
    "defense budget cut", "military spending cut",
    "reduced defense", "doge", "budget reduction",
    "contract cancelled", "program cancelled", "program terminated",
    "failed test", "test failure", "scrapped",
    "cost overrun", "investigation", "fraud",
    # Embarga / sankcje
    "arms embargo", "weapons ban",
]

# ─── Źródła RSS ───────────────────────────────────────────────────────────────

RSS_FEEDS = {
    "Defense One":      "https://www.defenseone.com/rss/all/",
    "Breaking Defense": "https://breakingdefense.com/feed/",
    "Reuters World":    "https://feeds.reuters.com/reuters/worldNews",
    "AP Defense":       "https://feeds.apnews.com/rss/apf-topnews",
}

DOD_CONTRACTS_URL  = "https://www.defense.gov/News/Contracts/"
DOD_RSS_URL        = "https://www.defense.gov/DesktopModules/ArticleCS/Feed.ashx?ContentType=1&Site=945&max=20"
USASPENDING_URL    = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# ─── Parsowanie DoD ──────────────────────────────────────────────────────────

def scrape_dod_contracts() -> list[str]:
    """
    Próbuje pobrać kontrakty DoD — kilka metod:
    1. RSS feed DoD (nie wymaga przeglądarki)
    2. Defense.gov z pełnymi nagłówkami
    3. USASpending API (publiczne, bez blokowania)
    """
    texts = []

    # Metoda 1: DoD RSS
    try:
        feed = feedparser.parse(DOD_RSS_URL)
        if feed.entries:
            for entry in feed.entries[:30]:
                t = f"{entry.get('title', '')} {entry.get('summary', '')}"
                if t.strip():
                    texts.append(t.strip())
            print(f"  DoD RSS: {len(texts)} wpisów")
            return texts
    except Exception as e:
        print(f"  DoD RSS błąd: {e}")

    # Metoda 2: defense.gov z pełnymi nagłówkami przeglądarki
    try:
        headers = {
            "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://www.google.com/",
        }
        resp = requests.get(DOD_CONTRACTS_URL, timeout=15, headers=headers)
        if resp.status_code == 200:
            # Prosta ekstrakcja tekstu z paragrafów
            import re
            paras = re.findall(r'<p[^>]*>(.*?)</p>', resp.text, re.DOTALL)
            for p in paras[:100]:
                clean = re.sub(r'<[^>]+>', '', p).strip()
                if len(clean) > 40:
                    texts.append(clean)
            print(f"  DoD HTML: {len(texts)} paragrafów")
            if texts:
                return texts
        else:
            print(f"  DoD HTML: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  DoD HTML błąd: {e}")

    # Metoda 3: USASpending.gov — publiczne API kontraktów DoD
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        payload = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],  # contracts
                "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
                "time_period": [{"start_date": week_ago, "end_date": today}],
                "award_amounts": [{"lower_bound": 10000000}],  # min $10M
            },
            "fields": ["Recipient Name", "Award Amount", "Description", "Awarding Agency"],
            "page": 1,
            "limit": 25,
            "sort": "Award Amount",
            "order": "desc",
        }
        resp = requests.post(USASPENDING_URL, json=payload, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            for award in data.get("results", []):
                recipient = award.get("Recipient Name", "")
                amount    = award.get("Award Amount", 0)
                desc      = award.get("Description", "")
                if recipient and amount:
                    texts.append(
                        f"contract awarded {recipient} ${amount:,.0f} {desc}"
                    )
            print(f"  USASpending: {len(texts)} kontraktów (min $10M)")
            return texts
    except Exception as e:
        print(f"  USASpending błąd: {e}")

    print("  DoD: brak danych ze wszystkich źródeł")
    return []


# ─── Pobieranie RSS ───────────────────────────────────────────────────────────

def fetch_rss_entries(max_age_hours: int = 6) -> list[dict]:
    """Pobiera wpisy RSS nie starsze niż max_age_hours"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    entries = []

    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                # Parsuj datę
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import calendar
                    pub = datetime.fromtimestamp(
                        calendar.timegm(entry.published_parsed), tz=timezone.utc
                    )

                if pub and pub < cutoff:
                    continue  # za stary

                text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                entries.append({
                    "source": source,
                    "title":  entry.get("title", ""),
                    "text":   text.lower(),
                    "url":    entry.get("link", ""),
                    "pub":    pub.isoformat() if pub else None,
                })
        except Exception as e:
            print(f"  RSS {source} błąd: {e}")

    print(f"  RSS: {len(entries)} wpisów z ostatnich {max_age_hours}h (łącznie bez filtra: sprawdzone)")
    # Jeśli 0 po filtrowaniu — spróbuj bez limitu dat (weź najnowsze 5 z każdego feed'a)
    if not entries:
        print("  RSS: brak wpisów z datą — biorę najnowsze bez filtra dat")
        for source, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                    entries.append({
                        "source": source,
                        "title":  entry.get("title", ""),
                        "text":   text.lower(),
                        "url":    entry.get("link", ""),
                        "pub":    None,
                    })
            except Exception:
                pass
        print(f"  RSS (bez filtra): {len(entries)} wpisów")
    return entries


# ─── NewsAPI ─────────────────────────────────────────────────────────────────

def fetch_newsapi_articles(max_age_hours: int = 24) -> list[dict]:
    """Pobiera artykuły z NewsAPI"""
    if not NEWSAPI_KEY:
        print("  NewsAPI: brak klucza NEWSAPI_KEY")
        return []

    from_time = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    # Prostsze zapytanie — plan darmowy ma ograniczenia złożoności
    query = "defense contract OR Lockheed OR Raytheon OR Northrop OR NATO OR Pentagon OR ceasefire"
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q":        query,
                "from":     from_time,
                "sortBy":   "publishedAt",
                "language": "en",
                "pageSize": 50,
                "apiKey":   NEWSAPI_KEY,
            },
            timeout=15,
        )
        data = resp.json()
        # Loguj status i ewentualny błąd API
        if resp.status_code != 200 or data.get("status") == "error":
            print(f"  NewsAPI błąd API: {data.get('code')} — {data.get('message')}")
            return []
        articles = []
        for a in data.get("articles", []):
            title   = a.get("title") or ""
            desc    = a.get("description") or ""
            content = a.get("content") or ""
            text    = f"{title} {desc} {content}".lower()
            articles.append({
                "source": a.get("source", {}).get("name", "NewsAPI"),
                "title":  title,
                "text":   text,
                "url":    a.get("url", ""),
                "pub":    a.get("publishedAt"),
            })
        print(f"  NewsAPI: {len(articles)} artykułów (total results: {data.get('totalResults', '?')})")
        return articles
    except Exception as e:
        print(f"  NewsAPI błąd: {e}")
        return []


# ─── Scoring ─────────────────────────────────────────────────────────────────

def score_text(text: str) -> tuple[int, int, list[str]]:
    """
    Zwraca (long_score, short_score, matched_keywords).
    Liczy ile słów kluczowych LONG i SHORT pasuje do tekstu.
    """
    text_lower = text.lower()
    long_hits  = [kw for kw in LONG_KEYWORDS  if kw in text_lower]
    short_hits = [kw for kw in SHORT_KEYWORDS if kw in text_lower]
    return len(long_hits), len(short_hits), long_hits + short_hits


def extract_tickers(text: str) -> list[str]:
    """Wyciąga tickery na podstawie mapowania słów kluczowych"""
    text_lower = text.lower()
    tickers = set()
    for keyword, ticker_list in COMPANY_TICKER_MAP.items():
        if keyword in text_lower:
            tickers.update(ticker_list)

    # Jeśli brak konkretnej firmy ale jest news obronny — użyj ETF
    if not tickers:
        defense_generic = [
            "defense", "military", "pentagon", "nato",
            "weapon", "missile", "drone", "fighter jet",
        ]
        if any(kw in text_lower for kw in defense_generic):
            tickers.update(["ITA", "XAR"])

    return list(tickers)


def get_size_usd(ticker: str, action: str) -> int:
    if ticker in TICKERS_BIG5:
        return SIZE_BIG5_LONG if action == "BUY" else SIZE_BIG5_SHORT
    if ticker in TICKERS_MIDCAP:
        return SIZE_MIDCAP_LONG if action == "BUY" else SIZE_MIDCAP_SHORT
    if ticker in TICKERS_ETF:
        return SIZE_ETF_LONG
    if ticker in TICKERS_EUROPEAN:
        return SIZE_EUROPEAN_LONG
    return 1000  # fallback


# ─── Główna logika skanowania ─────────────────────────────────────────────────

def analyze_items(items: list[dict]) -> list[dict]:
    """
    Analizuje listę itemów (RSS/NewsAPI/DoD).
    Każdy item: {source, title, text, url, pub}
    Zwraca listę sygnałów do wysłania.
    """
    signals = []
    seen_tickers_long  = set()
    seen_tickers_short = set()

    # DoD/USASpending — zweryfikowane źródło kontraktów → próg 1
    TRUSTED_SOURCES = {"DoD Contracts", "USASpending"}
    # Branżowe media obronne — każdy artykuł jest kontekstem sektorowym → próg 1 jeśli są tickery
    DEFENSE_MEDIA = {"Defense One", "Breaking Defense"}

    for item in items:
        long_score, short_score, keywords = score_text(item["text"])
        tickers = extract_tickers(item["text"])

        is_trusted     = item.get("source") in TRUSTED_SOURCES
        is_defense_media = item.get("source") in DEFENSE_MEDIA
        # Próg: DoD/USASpending=1, branżowe media obronne=1, inne=3
        long_threshold  = 1 if (is_trusted or is_defense_media) else 3
        short_threshold = 2  # zawsze wymagamy 2 dla shortów

        # Debug — pokaż co analizujemy
        if long_score > 0 or short_score > 0 or tickers:
            print(
                f"    [{item['source']}] L={long_score} S={short_score} "
                f"tickers={tickers} | {item['title'][:60]}"
            )

        # Dla zaufanych źródeł z sygnałem LONG — użyj ETF jako fallback
        if not tickers and is_trusted and long_score >= 1:
            tickers = ["ITA", "XAR"]

        if not tickers:
            continue

        # LONG: score >= próg i dominuje nad short
        if long_score >= long_threshold and long_score >= short_score:
            for ticker in tickers:
                if ticker in seen_tickers_long:
                    continue
                if ticker in TICKERS_ETF or ticker in TICKERS_EUROPEAN:
                    action = "BUY"
                else:
                    action = "BUY"

                size_usd    = get_size_usd(ticker, action)
                stop_loss   = None   # cena nieznana — Routine obliczy z rynku
                take_profit = None

                signals.append({
                    "symbol":    ticker,
                    "action":    action,
                    "strategy":  "defense-long",
                    "size_usd":  size_usd,
                    "sl_pct":    STOP_LOSS_PCT,
                    "tp_pct":    TAKE_PROFIT_PCT,
                    "score":     long_score,
                    "keywords":  keywords[:5],
                    "source":    item["source"],
                    "headline":  item["title"][:120],
                    "url":       item["url"],
                    "pub":       item.get("pub"),
                })
                seen_tickers_long.add(ticker)

        # SHORT: score >= 2 i dominuje nad long; tylko BIG5 + MIDCAP
        elif short_score >= short_threshold and short_score > long_score:
            for ticker in tickers:
                if ticker in TICKERS_ETF or ticker in TICKERS_EUROPEAN:
                    continue  # nie shortujemy ETF ani europejskich
                if ticker in seen_tickers_short:
                    continue

                size_usd = get_size_usd(ticker, "SELL_SHORT")
                signals.append({
                    "symbol":   ticker,
                    "action":   "SELL_SHORT",
                    "strategy": "defense-short",
                    "size_usd": size_usd,
                    "sl_pct":   STOP_LOSS_PCT,
                    "tp_pct":   TAKE_PROFIT_PCT,
                    "score":    short_score,
                    "keywords": keywords[:5],
                    "source":   item["source"],
                    "headline": item["title"][:120],
                    "url":      item["url"],
                    "pub":      item.get("pub"),
                })
                seen_tickers_short.add(ticker)

    return signals


# ─── Wysyłanie alertów ────────────────────────────────────────────────────────

def send_alert(alert: dict, retries: int = 2) -> bool:
    """
    Default: AUTO_EXECUTE via Alpaca REST (bracket order, SL/TP from sl_pct/tp_pct).
    USE_ROUTINE=true -> legacy Cloudflare Worker -> routine path with retry.
    """
    if not USE_ROUTINE:
        order = execute_stock_signal(alert)
        if order:
            print(f"  Order {alert['action']} {alert['symbol']} (score={alert['score']}): id={order.get('id')} qty={order.get('qty')} @ ${order.get('limit_price')}")
            return True
        print(f"  Order {alert['action']} {alert['symbol']}: REJECTED (Alpaca / quote unavailable)")
        return False

    # Legacy routine path (opt-in)
    if not CLOUDFLARE_DEFENSE_WORKER_URL:
        print(f"  BRAK CLOUDFLARE_DEFENSE_WORKER_URL — sygnał lokalnie: {alert}")
        return False
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                CLOUDFLARE_DEFENSE_WORKER_URL,
                json=alert,
                timeout=60,
            )
            print(f"  Routine forward {alert['action']} {alert['symbol']} (score={alert['score']}): HTTP {resp.status_code}")
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                wait = 30 * attempt  # 30s, potem 60s
                print(f"  Rate limit (429) — czekam {wait}s przed retry {attempt}/{retries}")
                time.sleep(wait)
                continue
            print(f"  Błąd HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"  Błąd wysyłania alertu (próba {attempt}): {e}")
            if attempt < retries:
                time.sleep(15)
    return False


# ─── Główna funkcja ──────────────────────────────────────────────────────────

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === DEFENSE MARKET MONITOR ===")
    _diag("defense-monitor", DIAG_RAN, {"now": now_str})

    # v2.0 safety net: account-level circuit breaker BEFORE VIX guard
    account = get_account_status()
    dd_status, _ = daily_drawdown_guard(account=account)
    if dd_status == "HALT":
        notify_summary("Defense Monitor", 0, 0)
        return

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Defense Monitor", 0, 0)
        return

    equity = account["equity"] if account else 0
    all_items = []

    # 1. DoD Contracts
    print("\n[DoD] Scrapuję kontrakty...")
    dod_texts = scrape_dod_contracts()
    if dod_texts:
        # Scal wszystkie kontrakty w jeden blok, by wykryć firmy i słowa kluczowe
        dod_combined = " ".join(dod_texts)
        all_items.append({
            "source": "DoD Contracts",
            "title":  f"DoD Contracts {now_str}",
            "text":   dod_combined,
            "url":    DOD_CONTRACTS_URL,
            "pub":    now_str,
        })
        # Dodatkowo każdy paragraf osobno (lepsze wykrywanie firm)
        for text in dod_texts:
            if len(text) > 30:  # ignoruj krótkie fragmenty
                all_items.append({
                    "source": "DoD Contracts",
                    "title":  text[:80],
                    "text":   text,
                    "url":    DOD_CONTRACTS_URL,
                    "pub":    now_str,
                })

    # 2. RSS Feeds
    print("\n[RSS] Pobieram feed'y...")
    rss_items = fetch_rss_entries(max_age_hours=1)
    all_items.extend(rss_items)

    # 3. NewsAPI
    print("\n[NewsAPI] Pobieram artykuły...")
    news_items = fetch_newsapi_articles(max_age_hours=1)
    all_items.extend(news_items)

    print(f"\n  Łącznie itemów do analizy: {len(all_items)}")
    if not all_items:
        _diag("defense-monitor", DIAG_INPUT_EMPTY,
              {"sources_tried": ["DoD", "RSS", "NewsAPI"]})

    # 4. Analiza i scoring
    raw_signals = analyze_items(all_items)
    print(f"\n  Sygnałów wstępnych: {len(raw_signals)}")

    # 4b. Event-probability layer — filtruje IGNORE/WAIT, wstrzymuje CONTRARIAN
    signals = apply_event_scoring(raw_signals)
    print(f"  Sygnałów po event-scoring: {len(signals)} (dropped {len(raw_signals) - len(signals)})")

    # 5. Wysyłanie alertów — max 1 na run (rate limit Routiny)
    MAX_ALERTS_PER_RUN = 1
    alerts_sent = 0

    # Sortuj: wyższy score najpierw
    signals.sort(key=lambda s: s["score"], reverse=True)

    # v3.10.1 (2026-05-27) — refactored to shared/news_signal_gate.py
    # Same one-line gate is wired in twitter/reddit/geo/politician monitors.
    try:
        from news_signal_gate import gate_news_signal, mark_signal_acted
        _sig_gate_available = True
    except ImportError:
        _sig_gate_available = False

    for signal in signals[:MAX_ALERTS_PER_RUN]:
        direction = signal["action"]
        if has_open_position(signal["symbol"]):
            print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} pominięty (otwarta pozycja)")
            continue

        if _sig_gate_available:
            strength = min(1.0, max(0.0, float(signal.get("score", 50)) / 100.0))
            v = gate_news_signal(
                symbol=signal["symbol"], side=direction,
                signal_strength=strength,
                headline=signal.get("headline", ""),
                source=signal.get("source", "defense-monitor"),
                published_at=signal.get("published_at") or signal.get("event_ts"),
                strategy="defense-news",
            )
            verdict_str = v.verdict.value
            if verdict_str == "BLOCK":
                print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} BLOCKED — {v.reason}")
                continue
            if verdict_str == "ALERT_ONLY":
                print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} ALERT_ONLY — {v.reason}")
                try: notify_signal(signal, alert_sent=True)
                except Exception: pass
                continue
            if verdict_str == "DOWNSIZE":
                print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} DOWNSIZED × {v.size_multiplier:.2f} — {v.reason}")
                size_mult *= v.size_multiplier
            mark_signal_acted(signal["symbol"], "defense-news")

        new_size = round(signal["size_usd"] * size_mult)
        ok, combined = concentration_ok(signal["symbol"], new_size, equity=equity)
        if not ok:
            print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} pominięty (concentration {combined:.1f}% > 40%)")
            continue
        signal["size_usd"] = new_size
        print(
            f"\n  >>> SYGNAŁ: {direction} {signal['symbol']} "
            f"(score={signal['score']}, source={signal['source']}, concentration={combined:.1f}%)"
        )
        print(f"      Headline: {signal['headline']}")
        print(f"      Keywords: {signal['keywords']}")
        # v3.17.0 (2026-06-04) — Feedback context + confidence_inputs (Task 5).
        # Wires instrument_profile + liquidity_sweep + lead_lag into the signal
        # before it reaches risk_officer (via execute_stock_signal). Fail-soft
        # at every step so a missing helper or stale data never blocks an alert.
        try:
            from market_data import get_daily_bars as _gdb
        except ImportError:
            try:
                from shared.market_data import get_daily_bars as _gdb  # type: ignore
            except ImportError:
                _gdb = None  # type: ignore
        try:
            from feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx
        except ImportError:
            try:
                from shared.feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx  # type: ignore
            except ImportError:
                def _build_feedback_ctx(**_kw):  # type: ignore
                    return {}
        try:
            from confidence_builder import build_confidence_inputs as _build_ci
        except ImportError:
            try:
                from shared.confidence_builder import build_confidence_inputs as _build_ci  # type: ignore
            except ImportError:
                def _build_ci(**_kw):  # type: ignore
                    return None
        _sym = signal["symbol"]
        try:
            _sym_bars = _gdb(_sym, days=35) if _gdb else None
        except Exception:
            _sym_bars = None
        try:
            _spy_b = _gdb("SPY", days=35) if _gdb else None
            _spy_cl = ([float(x) for x in _spy_b["close"]]
                        if (_spy_b and _spy_b.get("close")) else None)
        except Exception:
            _spy_cl = None
        try:
            _fb_ctx = _build_feedback_ctx(
                symbol=_sym, bars=_sym_bars, index_closes=_spy_cl,
            )
        except Exception:
            _fb_ctx = {}
        try:
            _norm_score = min(1.0, max(0.0, float(signal.get("score", 50)) / 100.0))
            signal["confidence_inputs"] = _build_ci(
                strategy=signal.get("strategy", "defense-news"),
                primary_score=_norm_score,
                bars=_sym_bars,
                account_status=account,
                source_type="dod_contract" if signal.get("source") == "DoD Contracts"
                              else "defense-news",
                source_confirmation_present=False,
                **_fb_ctx,
            )
        except Exception as _ci_e:
            print(f"      confidence_inputs build failed (non-fatal): {type(_ci_e).__name__}")
        # Pre-market gate: defense-monitor runs 24/7 (cron 0,30 * * * *)
        # but Alpaca stock orders need regular session (09:30-16:00 ET).
        # If market closed → email-only with QUEUED prefix; don't try
        # execute_stock_signal (which would fail at quote/bracket placement).
        try:
            from market_hours import is_us_market_open, minutes_to_next_open
        except ImportError:
            is_us_market_open = lambda: (True, "open")
            minutes_to_next_open = lambda: 0
        mkt_open, mkt_reason = is_us_market_open()
        if not mkt_open:
            mins = minutes_to_next_open()
            print(f"  Market {mkt_reason} ({mins}min to next open) — queueing {signal['symbol']} for open (email-only)")
            notify_signal(signal, alert_sent=False, reason=mkt_reason)
            continue

        _diag("defense-monitor", DIAG_SIGNAL_DETECTED,
              {"symbol": signal.get("symbol"),
               "score": signal.get("score")})
        _diag("defense-monitor", DIAG_EMIT_ATTEMPTED,
              {"symbol": signal.get("symbol"),
               "strategy": signal.get("strategy", "defense-news")})
        # v3.24 — observability emit BEFORE send_alert so the ledger captures
        # this entry-capable signal even if Alpaca rejects. NEVER places a
        # trade — emit_monitor_signal is observability-only.
        try:
            emit_monitor_signal(
                source_monitor="defense-monitor",
                strategy_id=signal.get("strategy", "defense-news"),
                symbol=signal["symbol"],
                asset_class="us_equity",
                side=("long" if str(signal.get("action", "BUY")).upper().startswith("BUY")
                      else "short"),
                action=signal.get("action", "BUY"),
                entry_capable=True,
                raw_signal={
                    "score":     signal.get("score"),
                    "headline":  (signal.get("headline") or "")[:200],
                    "source":    signal.get("source"),
                    "keywords":  signal.get("keywords", []),
                },
                confidence_inputs=signal.get("confidence_inputs")
                    or {"primary_score":
                            min(1.0, max(0.0,
                                float(signal.get("score", 50)) / 100.0))},
                risk_inputs={"size_usd": signal.get("size_usd", 8000)},
                market_regime={"regime": signal.get("regime", "NEUTRAL")},
                metadata={"audit_link": f"defense-{signal['symbol']}"},
            )
        except Exception:
            pass
        sent = send_alert(signal)
        if sent:
            alerts_sent += 1
            _diag("defense-monitor", DIAG_EMIT_SUCCESS,
                  {"symbol": signal.get("symbol")})
        else:
            _diag("defense-monitor", DIAG_EMIT_FAILED,
                  {"symbol": signal.get("symbol"),
                   "reason": "alpaca_reject"})
        # Pass reason="alpaca_reject" if send failed in regular session
        # (most common: risk-officer REJECT, quote unavailable, insufficient
        # buying power). Workflow log has specific cause.
        notify_signal(signal, sent, reason="" if sent else "alpaca_reject")
        if alerts_sent < MAX_ALERTS_PER_RUN:
            time.sleep(8)

    if len(signals) > MAX_ALERTS_PER_RUN:
        print(f"\n  Pominięto {len(signals) - MAX_ALERTS_PER_RUN} sygnałów (rate limit guard)")

    if not signals:
        _diag("defense-monitor", DIAG_NO_SIGNAL,
              {"raw_signals": len(raw_signals), "items": len(all_items)})

    notify_summary("Defense Monitor", len(signals), alerts_sent)
    print(f"\n  Wysłano alertów: {alerts_sent}")
    print(f"[{now_str}] === DEFENSE MONITOR ZAKOŃCZONY ===\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_scan()
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("defense-monitor", status="ok")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")


# ── v3.22.0 observability hook ──────────────────────────────────────────────
# Per the v3.22 signal-pipeline contract this monitor exposes a thin helper
# that the run loop calls once per scan even when no signal fires (so the
# operator can see "monitor ran, 0 candidates" in the opportunity ledger).
# emit_monitor_signal NEVER places trades — it only persists an observation
# row via shared.signal_emitter.emit_signal_opportunity.
def _v322_observe(symbol: str = "n/a", action: str = "NO_SIGNAL",
                  side: str = "n/a", asset_class: str = "us_equity",
                  raw_signal=None) -> None:
    try:
        emit_monitor_signal(
            source_monitor="defense-monitor",
            strategy_id="defense-news",
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            action=action,
            entry_capable=False,
            raw_signal=raw_signal or {},
        )
    except Exception:
        pass

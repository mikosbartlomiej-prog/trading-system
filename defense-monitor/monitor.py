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

# Email notifications (optional)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard, has_open_position
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def has_open_position(_): return False

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
            print(f"  Alert {alert['action']} {alert['symbol']} (score={alert['score']}): HTTP {resp.status_code}")
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                wait = 30 * attempt  # 30s, potem 60s
                print(f"  Rate limit (429) — czekam {wait}s przed retry {attempt}/{retries}")
                time.sleep(wait)
                continue
            # Inne błędy — nie retry
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

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Defense Monitor", 0, 0)
        return

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

    # 4. Analiza i scoring
    signals = analyze_items(all_items)
    print(f"\n  Sygnałów wygenerowanych: {len(signals)}")

    # 5. Wysyłanie alertów — max 1 na run (rate limit Routiny)
    MAX_ALERTS_PER_RUN = 1
    alerts_sent = 0

    # Sortuj: wyższy score najpierw
    signals.sort(key=lambda s: s["score"], reverse=True)

    for signal in signals[:MAX_ALERTS_PER_RUN]:
        direction = signal["action"]
        if has_open_position(signal["symbol"]):
            print(f"\n  >>> SYGNAŁ {direction} {signal['symbol']} pominięty (otwarta pozycja)")
            continue
        signal["size_usd"] = round(signal["size_usd"] * size_mult)
        print(
            f"\n  >>> SYGNAŁ: {direction} {signal['symbol']} "
            f"(score={signal['score']}, source={signal['source']})"
        )
        print(f"      Headline: {signal['headline']}")
        print(f"      Keywords: {signal['keywords']}")
        sent = send_alert(signal)
        if sent:
            alerts_sent += 1
        notify_signal(signal, sent)
        if alerts_sent < MAX_ALERTS_PER_RUN:
            time.sleep(8)

    if len(signals) > MAX_ALERTS_PER_RUN:
        print(f"\n  Pominięto {len(signals) - MAX_ALERTS_PER_RUN} sygnałów (rate limit guard)")

    notify_summary("Defense Monitor", len(signals), alerts_sent)
    print(f"\n  Wysłano alertów: {alerts_sent}")
    print(f"[{now_str}] === DEFENSE MONITOR ZAKOŃCZONY ===\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_scan()

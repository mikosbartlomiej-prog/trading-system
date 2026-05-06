"""
Defense Market Monitor — 30-min scan
Monitoruje rynek zbrojeniowy: DoD contracts, RSS feeds, NewsAPI.
Generuje sygnały LONG/SHORT dla akcji sektora obronnego.
"""

import os
import sys
import json
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

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

SIZE_BIG5_LONG     = 2500   # USD
SIZE_BIG5_SHORT    = 1500   # USD
SIZE_MIDCAP_LONG   = 1500   # USD
SIZE_MIDCAP_SHORT  = 1000   # USD
SIZE_ETF_LONG      = 2000   # USD
SIZE_EUROPEAN_LONG = 1000   # USD

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

DOD_CONTRACTS_URL = "https://www.defense.gov/News/Contracts/"

# ─── Parsowanie DoD ──────────────────────────────────────────────────────────

class DoDParser(HTMLParser):
    """Prosta ekstrakcja tekstów kontraktów z defense.gov"""
    def __init__(self):
        super().__init__()
        self.texts = []
        self._capture = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        if tag in ("p", "li") or "contract" in cls.lower():
            self._capture = True

    def handle_endtag(self, tag):
        if tag in ("p", "li"):
            self._capture = False

    def handle_data(self, data):
        if self._capture and data.strip():
            self.texts.append(data.strip())


def scrape_dod_contracts() -> list[str]:
    """Pobiera listę kontraktów z DoD z dzisiaj"""
    try:
        resp = requests.get(DOD_CONTRACTS_URL, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        parser = DoDParser()
        parser.feed(resp.text)
        # Bierz tylko ostatnie 60 kontraktów (dzisiaj)
        return parser.texts[:200]
    except Exception as e:
        print(f"  DoD scrape błąd: {e}")
        return []


# ─── Pobieranie RSS ───────────────────────────────────────────────────────────

def fetch_rss_entries(max_age_hours: int = 2) -> list[dict]:
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

    print(f"  RSS: {len(entries)} wpisów z ostatnich {max_age_hours}h")
    return entries


# ─── NewsAPI ─────────────────────────────────────────────────────────────────

def fetch_newsapi_articles(max_age_hours: int = 2) -> list[dict]:
    """Pobiera artykuły z NewsAPI"""
    if not NEWSAPI_KEY:
        print("  NewsAPI: brak klucza NEWSAPI_KEY")
        return []

    from_time = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    query = (
        "Lockheed OR Raytheon OR Northrop OR Boeing OR "
        '"defense contract" OR NATO OR Pentagon OR "military spending" OR '
        '"defense budget" OR "weapons program" OR "arms deal" OR '
        "ceasefire OR peacedeal OR rearmament"
    )
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
        resp.raise_for_status()
        data = resp.json()
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
        print(f"  NewsAPI: {len(articles)} artykułów")
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

    for item in items:
        long_score, short_score, keywords = score_text(item["text"])
        tickers = extract_tickers(item["text"])

        if not tickers:
            continue

        # LONG: long_score >= 2 i dominuje nad short
        if long_score >= 2 and long_score > short_score:
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

        # SHORT: short_score >= 2 i dominuje nad long; tylko BIG5 + MIDCAP
        elif short_score >= 2 and short_score > long_score:
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

def send_alert(alert: dict) -> bool:
    if not CLOUDFLARE_DEFENSE_WORKER_URL:
        print(f"  BRAK CLOUDFLARE_DEFENSE_WORKER_URL — sygnał lokalnie: {alert}")
        return False
    try:
        resp = requests.post(
            CLOUDFLARE_DEFENSE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Alert {alert['action']} {alert['symbol']} (score={alert['score']}): HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania alertu: {e}")
        return False


# ─── Główna funkcja ──────────────────────────────────────────────────────────

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === DEFENSE MARKET MONITOR ===")

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

    # 5. Wysyłanie alertów
    alerts_sent = 0
    for signal in signals:
        direction = signal["action"]
        print(
            f"\n  >>> SYGNAŁ: {direction} {signal['symbol']} "
            f"(score={signal['score']}, source={signal['source']})"
        )
        print(f"      Headline: {signal['headline']}")
        print(f"      Keywords: {signal['keywords']}")
        if send_alert(signal):
            alerts_sent += 1

    print(f"\n  Wysłano alertów: {alerts_sent}")
    print(f"[{now_str}] === DEFENSE MONITOR ZAKOŃCZONY ===\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_scan()

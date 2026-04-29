"""
Momentum Breakout Price Monitor — Finnhub edition
Strategia: cena przebija 20-dniowe maksimum + wolumen + RSI
Wysyla alerty do Cloudflare Worker co 5 minut podczas sesji gieldowej
"""

import os
import sys
import time
import requests
import schedule
import pytz
from datetime import datetime, timedelta

# ─── Konfiguracja ───────────────────────────────────────────────────────────

CLOUDFLARE_WORKER_URL = os.environ.get(
    "CLOUDFLARE_WORKER_URL",
    "https://tradingview-proxy.mikosbartlomiej.workers.dev"
)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# Tickery do monitorowania
TICKERS = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY"]

# Rozmiar pojedynczego trade (USD)
SIZE_USD = 500

# ─── Finnhub API ─────────────────────────────────────────────────────────────

def finnhub_get(endpoint, params):
    """Wywoluje Finnhub API"""
    params["token"] = FINNHUB_API_KEY
    response = requests.get(
        f"https://finnhub.io/api/v1{endpoint}",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_candles(ticker, days=30):
    """Pobiera dane OHLCV za ostatnie N dni"""
    now = int(datetime.now().timestamp())
    from_ts = int((datetime.now() - timedelta(days=days + 5)).timestamp())

    data = finnhub_get("/stock/candle", {
        "symbol": ticker,
        "resolution": "D",
        "from": from_ts,
        "to": now,
    })

    if data.get("s") != "ok" or not data.get("c"):
        return None

    return {
        "close":  data["c"],
        "high":   data["h"],
        "low":    data["l"],
        "open":   data["o"],
        "volume": data["v"],
        "time":   data["t"],
    }


# ─── Wskazniki techniczne ────────────────────────────────────────────────────

def calculate_rsi(closes, period=14):
    """Oblicza RSI"""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ─── Strategia ───────────────────────────────────────────────────────────────

def check_momentum_breakout(ticker):
    """
    Strategia Momentum Breakout:
    1. Cena dzisiaj > najwyzsze 20 dni (breakout)
    2. Wolumen dzisiaj > 1.5x sredni wolumen 20 dni (potwierdzenie)
    3. RSI(14) w przedziale 50-70 (momentum ale nie wykupiony)
    """
    try:
        candles = get_candles(ticker, days=35)
        if not candles or len(candles["close"]) < 22:
            print(f"  {ticker}: za malo danych ({len(candles['close']) if candles else 0} dni)")
            return None

        closes  = candles["close"]
        highs   = candles["high"]
        volumes = candles["volume"]

        current_price  = closes[-1]
        current_volume = volumes[-1]

        # 20-dniowe max i sredni wolumen (bez dzisiaj)
        high_20d   = max(highs[-21:-1])
        avg_volume = sum(volumes[-21:-1]) / 20

        # RSI
        current_rsi = calculate_rsi(closes)

        # Warunki
        price_breakout = current_price > high_20d
        volume_ok      = current_volume > avg_volume * 1.5
        rsi_ok         = current_rsi is not None and 50 <= current_rsi <= 70

        print(
            f"  {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol_ratio={current_volume/avg_volume:.2f}x RSI={current_rsi:.1f if current_rsi else 'N/A'} "
            f"| breakout={price_breakout} vol={volume_ok} rsi={rsi_ok}"
        )

        if price_breakout and volume_ok and rsi_ok:
            stop_loss   = round(current_price * 0.97, 2)
            take_profit = round(current_price * 1.05, 2)
            return {
                "symbol":     ticker,
                "action":     "BUY",
                "strategy":   "momentum-breakout",
                "price":      round(current_price, 2),
                "stop_loss":  stop_loss,
                "take_profit": take_profit,
                "size_usd":   SIZE_USD,
            }

    except Exception as e:
        print(f"  {ticker}: BLAD — {e}")

    return None


# ─── Wysylanie alertu ────────────────────────────────────────────────────────

def send_alert(alert):
    """Wysyla alert do Cloudflare Worker"""
    try:
        response = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Alert wyslany dla {alert['symbol']}: HTTP {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"  BLAD wysylania alertu: {e}")
        return False


# ─── Glowna petla ────────────────────────────────────────────────────────────

def is_market_open():
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


def run_checks():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not is_market_open():
        print(f"[{now_str}] Gielda zamknieta — pomijam sprawdzenie")
        return

    print(f"[{now_str}] Sprawdzam momentum breakout dla: {', '.join(TICKERS)}")

    for ticker in TICKERS:
        alert = check_momentum_breakout(ticker)
        if alert:
            print(f"  SYGNAL BREAKOUT: {ticker}!")
            send_alert(alert)
        time.sleep(1)

    print(f"  Nastepne sprawdzenie za 5 minut.\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    once_mode = "--once" in sys.argv

    print("=" * 55)
    print("  Momentum Breakout Monitor — start")
    print(f"  Tryb: {'jednorazowy (GitHub Actions)' if once_mode else 'ciagly (lokalny)'}")
    print(f"  Tickery: {', '.join(TICKERS)}")
    print(f"  Worker URL: {CLOUDFLARE_WORKER_URL}")
    print("=" * 55 + "\n")

    if not FINNHUB_API_KEY:
        print("BLAD: Brak FINNHUB_API_KEY w zmiennych srodowiskowych!")
        sys.exit(1)

    if once_mode:
        run_checks()
    else:
        run_checks()
        schedule.every(5).minutes.do(run_checks)
        while True:
            schedule.run_pending()
            time.sleep(30)

"""
Momentum Breakout Price Monitor
Strategia: cena przebija 20-dniowe maksimum + wolumen + RSI
Wysyla alerty do Cloudflare Worker co 5 minut podczas sesji gieldowej
"""

import os
import time
import json
import requests
import schedule
import pytz
import yfinance as yf
from datetime import datetime

# ─── Konfiguracja ───────────────────────────────────────────────────────────

CLOUDFLARE_WORKER_URL = os.environ.get(
    "CLOUDFLARE_WORKER_URL",
    "https://tradingview-proxy.mikosbartlomiej.workers.dev"
)

# Tickery do monitorowania (zgodne z tickers-whitelist.md w repo)
TICKERS = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY"]

# Rozmiar pojedynczego trade (USD) — zgodnie z CLAUDE.md max 5% equity
SIZE_USD = 500

# ─── Funkcje pomocnicze ──────────────────────────────────────────────────────

def is_market_open():
    """Sprawdza czy gielda US jest otwarta"""
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    # Weekend
    if now.weekday() >= 5:
        return False
    # Godziny sesji: 9:30 - 16:00 ET
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def calculate_rsi(series, period=14):
    """Oblicza RSI"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def check_momentum_breakout(ticker):
    """
    Strategia Momentum Breakout:
    1. Cena dzisiaj > najwyzsze 20 dni (breakout)
    2. Wolumen dzisiaj > 1.5x sredni wolumen 20 dni (potwierdzenie)
    3. RSI(14) w przedziale 50-70 (momentum ale nie wykupiony)

    Zwraca slownik alertu lub None jesli brak sygnalu.
    """
    try:
        data = yf.download(ticker, period="30d", interval="1d", progress=False, auto_adjust=True)

        if len(data) < 22:
            print(f"  {ticker}: za malo danych ({len(data)} dni)")
            return None

        current_price = float(data["Close"].iloc[-1])
        current_volume = float(data["Volume"].iloc[-1])

        # 20-dniowe maksimum (bez dzisiejszego dnia)
        high_20d = float(data["High"].iloc[-21:-1].max())

        # Sredni wolumen 20 dni (bez dzisiejszego)
        avg_volume = float(data["Volume"].iloc[-21:-1].mean())

        # RSI
        rsi_series = calculate_rsi(data["Close"])
        current_rsi = float(rsi_series.iloc[-1])

        # Warunki breakout
        price_breakout = current_price > high_20d
        volume_ok = current_volume > avg_volume * 1.5
        rsi_ok = 50 <= current_rsi <= 70

        print(
            f"  {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol_ratio={current_volume/avg_volume:.2f}x RSI={current_rsi:.1f} "
            f"| breakout={price_breakout} vol={volume_ok} rsi={rsi_ok}"
        )

        if price_breakout and volume_ok and rsi_ok:
            stop_loss = round(current_price * 0.97, 2)   # SL: -3%
            take_profit = round(current_price * 1.05, 2)  # TP: +5% => R:R ~1.67

            return {
                "symbol": ticker,
                "action": "BUY",
                "strategy": "momentum-breakout",
                "price": round(current_price, 2),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "size_usd": SIZE_USD,
            }

    except Exception as e:
        print(f"  {ticker}: BLAD — {e}")

    return None


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


# ─── Glowna petla sprawdzajaca ───────────────────────────────────────────────

def run_checks():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not is_market_open():
        print(f"[{now_str}] Gielda zamknieta — pomijam sprawdzenie")
        return

    print(f"[{now_str}] Sprawdzam momentum breakout dla: {', '.join(TICKERS)}")

    for ticker in TICKERS:
        alert = check_momentum_breakout(ticker)
        if alert:
            print(f"  🚀 SYGNAŁ BREAKOUT: {ticker}!")
            send_alert(alert)
        time.sleep(1)  # rate limiting yfinance

    print(f"  Nastepne sprawdzenie za 5 minut.\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Momentum Breakout Monitor — start")
    print(f"  Tickery: {', '.join(TICKERS)}")
    print(f"  Worker URL: {CLOUDFLARE_WORKER_URL}")
    print("=" * 55 + "\n")

    # Pierwsze sprawdzenie od razu
    run_checks()

    # Harmonogram: co 5 minut
    schedule.every(5).minutes.do(run_checks)

    while True:
        schedule.run_pending()
        time.sleep(30)

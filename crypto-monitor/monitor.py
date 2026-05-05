"""
Crypto Monitor — 24/7 BTC/ETH Price Monitor
Skanuje BTC/USD i ETH/USD co 30 minut, wykrywa breakouty i breakdowny
na 1h timeframe przez Alpaca Market Data API.
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA_URL   = "https://data.alpaca.markets"

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_CRYPTO_WORKER_URL", "")

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD"]

# Rozmiary pozycji (weekendy = połowa)
SIZE_LONG_WEEKDAY  = 250
SIZE_SHORT_WEEKDAY = 200
SIZE_LONG_WEEKEND  = 125
SIZE_SHORT_WEEKEND = 100

# Progi sygnałów
RSI_LONG_MIN  = 45
RSI_LONG_MAX  = 68
RSI_SHORT_MAX = 35

# ─── Alpaca Market Data API ───────────────────────────────────────────────────

def alpaca_data_get(endpoint: str, params: dict = None) -> dict:
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    resp = requests.get(
        f"{ALPACA_DATA_URL}{endpoint}",
        headers=headers,
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_crypto_bars(symbol: str, limit: int = 50) -> list[dict]:
    """
    Pobiera 1h świece dla symbolu crypto.
    Alpaca używa 'BTC/USD' w parametrach jako 'BTCUSD'.
    """
    alpaca_symbol = symbol.replace("/", "")  # BTC/USD → BTCUSD
    try:
        data = alpaca_data_get(
            f"/v1beta3/crypto/us/bars",
            {
                "symbols":   alpaca_symbol,
                "timeframe": "1H",
                "limit":     limit,
                "sort":      "asc",
            }
        )
        bars_data = data.get("bars", {}).get(alpaca_symbol, [])
        return bars_data
    except Exception as e:
        print(f"  {symbol} błąd pobierania bars: {e}")
        return []


# ─── Wskaźniki techniczne ─────────────────────────────────────────────────────

def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def is_weekend() -> bool:
    return datetime.now(timezone.utc).weekday() >= 5


# ─── Sygnały ─────────────────────────────────────────────────────────────────

def check_crypto_signal(symbol: str) -> dict | None:
    """
    Sprawdza sygnały dla danego crypto:
    LONG: cena > 20-świecowe max (1h) + wolumen + RSI 45-68
    SHORT: cena < 20-świecowe min (1h) + RSI < 35
    """
    bars = get_crypto_bars(symbol, limit=50)
    if len(bars) < 22:
        print(f"  {symbol}: za mało danych ({len(bars)} świec)")
        return None

    closes  = [float(b["c"]) for b in bars]
    highs   = [float(b["h"]) for b in bars]
    lows    = [float(b["l"]) for b in bars]
    volumes = [float(b["v"]) for b in bars]

    current_price  = closes[-1]
    current_volume = volumes[-1]

    high_20  = max(highs[-21:-1])
    low_20   = min(lows[-21:-1])
    avg_vol  = sum(volumes[-21:-1]) / 20

    rsi = calculate_rsi(closes)

    weekend = is_weekend()
    size_long  = SIZE_LONG_WEEKEND  if weekend else SIZE_LONG_WEEKDAY
    size_short = SIZE_SHORT_WEEKEND if weekend else SIZE_SHORT_WEEKDAY

    # LONG: breakout z 20-świecowego max
    if (current_price > high_20
            and current_volume > avg_vol * 2.0
            and rsi is not None and RSI_LONG_MIN <= rsi <= RSI_LONG_MAX):
        stop_loss   = round(current_price * 0.96, 2)   # -4%
        take_profit = round(current_price * 1.08, 2)   # +8%
        print(f"  LONG {symbol}: {current_price:.2f} > high20={high_20:.2f}, RSI={rsi:.1f}, vol={current_volume/avg_vol:.1f}x")
        return {
            "symbol":      symbol,
            "action":      "BUY",
            "strategy":    "crypto-momentum",
            "price":       round(current_price, 2),
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    size_long,
            "rsi":         round(rsi, 1) if rsi else None,
            "weekend":     weekend,
        }

    # SHORT: breakdown poniżej 20-świecowego min
    if (current_price < low_20
            and current_volume > avg_vol * 1.5
            and rsi is not None and rsi < RSI_SHORT_MAX):
        stop_loss   = round(current_price * 1.04, 2)   # +4% (short SL powyżej)
        take_profit = round(current_price * 0.92, 2)   # -8% (short TP poniżej)
        print(f"  SHORT {symbol}: {current_price:.2f} < low20={low_20:.2f}, RSI={rsi:.1f}, vol={current_volume/avg_vol:.1f}x")
        return {
            "symbol":      symbol,
            "action":      "SELL_SHORT",
            "strategy":    "crypto-breakdown",
            "price":       round(current_price, 2),
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    size_short,
            "rsi":         round(rsi, 1) if rsi else None,
            "weekend":     weekend,
        }

    print(
        f"  {symbol}: {current_price:.2f} | high20={high_20:.2f} low20={low_20:.2f} "
        f"RSI={rsi:.1f if rsi else 'N/A'} vol={current_volume/avg_vol:.1f}x — brak sygnału"
    )
    return None


# ─── Wysyłanie alertu ────────────────────────────────────────────────────────

def send_alert(alert: dict) -> bool:
    if not CLOUDFLARE_WORKER_URL:
        print(f"  BRAK CLOUDFLARE_CRYPTO_WORKER_URL — sygnał lokalnie: {alert}")
        return False
    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Alert {alert['action']} {alert['symbol']}: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania alertu: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    weekend_str = " [WEEKEND — size /2]" if is_weekend() else ""
    print(f"\n[{now_str}] === CRYPTO MONITOR{weekend_str} ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    alerts_sent = 0
    for symbol in CRYPTO_SYMBOLS:
        signal = check_crypto_signal(symbol)
        if signal:
            print(f"  >>> SYGNAŁ: {signal['action']} {symbol}!")
            send_alert(signal)
            alerts_sent += 1

    print(f"  Wysłano alertów: {alerts_sent}")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_scan()

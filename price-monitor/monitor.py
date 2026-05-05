"""
Momentum Breakout Price Monitor — Aggressive Edition
Strategia: LONG (momentum) + SHORT (overbought reversal)
Wyslaje alerty do Cloudflare Worker co 5 minut podczas sesji gieldowej
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

# Tickery do monitorowania (long + short candidates)
TICKERS_LONG  = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "META", "AMZN"]
TICKERS_SHORT = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "TSLA", "AMZN"]

# Lewarowane ETF — trackujemy osobno
TICKERS_LEVERAGED = ["TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO"]

# Rozmiary pozycji — AGGRESSIVE
SIZE_LONG      = 3000  # USD — long momentum
SIZE_SHORT     = 2000  # USD — short
SIZE_LEVERAGED = 1500  # USD — lewarowane ETF

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


def get_candles(ticker, days=35):
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
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(highs, lows, closes, period=14):
    """Average True Range — miara zmiennosci"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ─── Sygnaly LONG ────────────────────────────────────────────────────────────

def check_long_signal(ticker):
    """
    Momentum Breakout LONG:
    1. Cena > 20-dniowe max (breakout)
    2. Wolumen > 1.5x srednia 20d (potwierdzenie)
    3. RSI 50-70 (momentum, nie wykupiony)
    """
    try:
        candles = get_candles(ticker, days=35)
        if not candles or len(candles["close"]) < 22:
            return None

        closes  = candles["close"]
        highs   = candles["high"]
        lows    = candles["low"]
        volumes = candles["volume"]

        current_price  = closes[-1]
        current_volume = volumes[-1]

        high_20d   = max(highs[-21:-1])
        avg_volume = sum(volumes[-21:-1]) / 20
        rsi        = calculate_rsi(closes)
        atr        = calculate_atr(highs, lows, closes)

        price_breakout = current_price > high_20d
        volume_ok      = current_volume > avg_volume * 1.5
        rsi_ok         = rsi is not None and 50 <= rsi <= 70

        print(
            f"  LONG {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol={current_volume/avg_volume:.2f}x RSI={rsi:.1f if rsi else 'N/A'} "
            f"| breakout={price_breakout} vol={volume_ok} rsi={rsi_ok}"
        )

        if price_breakout and volume_ok and rsi_ok:
            atr_val     = atr or current_price * 0.02
            stop_loss   = round(current_price - 1.5 * atr_val, 2)
            take_profit = round(current_price + 2.5 * atr_val, 2)
            size        = SIZE_LEVERAGED if ticker in TICKERS_LEVERAGED else SIZE_LONG
            return {
                "symbol":      ticker,
                "action":      "BUY",
                "strategy":    "momentum-long",
                "price":       round(current_price, 2),
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "size_usd":    size,
                "rsi":         round(rsi, 1),
                "atr":         round(atr_val, 2),
            }

    except Exception as e:
        print(f"  {ticker} LONG error: {e}")

    return None


# ─── Sygnaly SHORT ───────────────────────────────────────────────────────────

def check_short_signal(ticker):
    """
    Overbought Reversal SHORT:
    1. RSI > 72 (ekstremalnie wykupiony)
    2. Cena blisko 20-dniowego max (resistance zone)
    3. Wolumen maleje < 0.8x srednia (zanikajacy impet)
    4. Cena < wczorajszego otwarcia (bearish intraday)
    """
    try:
        candles = get_candles(ticker, days=35)
        if not candles or len(candles["close"]) < 22:
            return None

        closes  = candles["close"]
        highs   = candles["high"]
        lows    = candles["low"]
        opens   = candles["open"]
        volumes = candles["volume"]

        current_price  = closes[-1]
        current_volume = volumes[-1]
        prev_open      = opens[-2]

        high_20d    = max(highs[-21:-1])
        avg_volume  = sum(volumes[-21:-1]) / 20
        rsi         = calculate_rsi(closes)
        atr         = calculate_atr(highs, lows, closes)

        rsi_overbought  = rsi is not None and rsi > 72
        near_resistance = current_price >= high_20d * 0.98   # w top 2% od 20d max
        volume_fading   = current_volume < avg_volume * 0.8
        bearish_candle  = current_price < prev_open           # close < prev open

        print(
            f"  SHORT {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol={current_volume/avg_volume:.2f}x RSI={rsi:.1f if rsi else 'N/A'} "
            f"| rsi_ob={rsi_overbought} resistance={near_resistance} "
            f"vol_fade={volume_fading} bearish={bearish_candle}"
        )

        # Wymagamy 3 z 4 warunkow (bardziej agresywne)
        conditions_met = sum([rsi_overbought, near_resistance, volume_fading, bearish_candle])
        if rsi_overbought and conditions_met >= 3:
            atr_val     = atr or current_price * 0.02
            stop_loss   = round(current_price + 1.5 * atr_val, 2)   # SL powyzej ceny (short)
            take_profit = round(current_price - 2.5 * atr_val, 2)   # TP ponizej ceny (short)
            return {
                "symbol":      ticker,
                "action":      "SELL_SHORT",
                "strategy":    "overbought-short",
                "price":       round(current_price, 2),
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "size_usd":    SIZE_SHORT,
                "rsi":         round(rsi, 1),
                "atr":         round(atr_val, 2),
                "conditions":  conditions_met,
            }

    except Exception as e:
        print(f"  {ticker} SHORT error: {e}")

    return None


# ─── Sygnaly lewarowanych ETF ─────────────────────────────────────────────────

def check_leveraged_signals():
    """
    Lewarowane ETF — trend following:
    TQQQ (3x QQQ long):  gdy QQQ w silnym uptrend (RSI 55-68)
    SQQQ (3x QQQ short): gdy QQQ w silnym downtrend (RSI < 35)
    SPXL (3x SPY long):  gdy SPY breakout
    SPXS (3x SPY short): gdy SPY sell-off
    """
    signals = []
    for ticker in TICKERS_LEVERAGED:
        sig = check_long_signal(ticker)
        if sig:
            signals.append(sig)
    return signals


# ─── Wysylanie alertu ────────────────────────────────────────────────────────

def send_alert(alert):
    """Wysyla alert do Cloudflare Worker"""
    try:
        response = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Alert wyslany {alert['action']} {alert['symbol']}: HTTP {response.status_code}")
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

    print(f"\n[{now_str}] === SKANOWANIE LONG + SHORT ===")
    alerts_sent = 0

    # LONG signals
    print(f"\n[LONG] Sprawdzam {', '.join(TICKERS_LONG)}")
    for ticker in TICKERS_LONG:
        signal = check_long_signal(ticker)
        if signal:
            print(f"  >>> SYGNAL LONG: {ticker}!")
            send_alert(signal)
            alerts_sent += 1
        time.sleep(0.5)

    # SHORT signals
    print(f"\n[SHORT] Sprawdzam {', '.join(TICKERS_SHORT)}")
    for ticker in TICKERS_SHORT:
        signal = check_short_signal(ticker)
        if signal:
            print(f"  >>> SYGNAL SHORT: {ticker}!")
            send_alert(signal)
            alerts_sent += 1
        time.sleep(0.5)

    # Lewarowane ETF
    print(f"\n[LEVERAGED] Sprawdzam {', '.join(TICKERS_LEVERAGED)}")
    for ticker in TICKERS_LEVERAGED:
        signal = check_long_signal(ticker)
        if signal:
            signal["strategy"] = "leveraged-etf"
            signal["size_usd"] = SIZE_LEVERAGED
            print(f"  >>> SYGNAL LEVERAGED: {ticker}!")
            send_alert(signal)
            alerts_sent += 1
        time.sleep(0.5)

    print(f"\n[{now_str}] Alerty wyslane: {alerts_sent}. Nastepne sprawdzenie za 5 minut.\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    once_mode = "--once" in sys.argv

    print("=" * 60)
    print("  Momentum Monitor — Aggressive Edition (LONG + SHORT)")
    print(f"  Tryb: {'jednorazowy (GitHub Actions)' if once_mode else 'ciagly (lokalny)'}")
    print(f"  LONG:     {', '.join(TICKERS_LONG)}")
    print(f"  SHORT:    {', '.join(TICKERS_SHORT)}")
    print(f"  LEVERAGED:{', '.join(TICKERS_LEVERAGED)}")
    print(f"  Worker URL: {CLOUDFLARE_WORKER_URL}")
    print("=" * 60 + "\n")

    if not FINNHUB_API_KEY:
        print("BLAD: Brak FINNHUB_API_KEY!")
        sys.exit(1)

    if once_mode:
        run_checks()
    else:
        run_checks()
        schedule.every(5).minutes.do(run_checks)
        while True:
            schedule.run_pending()
            time.sleep(30)

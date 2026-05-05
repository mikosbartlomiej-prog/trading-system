"""
Weekly Learning Loop — Trade Analyzer
Analizuje wyniki tradów z ostatnich 7 dni i wysyła do Claude Routine
która automatycznie aktualizuje pliki strategii w repo przez GitHub API.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_LEARNING_WORKER_URL", "")

# Repo do aktualizacji strategii (Claude Routine użyje GitHub API)
GITHUB_REPO_OWNER = "mikosbartlomiej"
GITHUB_REPO_NAME  = "trading-system"

# ─── Alpaca REST API ──────────────────────────────────────────────────────────

def alpaca_get(endpoint: str, params: dict = None) -> list | dict:
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    resp = requests.get(
        f"{ALPACA_BASE_URL}{endpoint}",
        headers=headers,
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_closed_orders_7d() -> list[dict]:
    """Pobiera zamknięte zlecenia z ostatnich 7 dni"""
    after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        orders = alpaca_get("/v2/orders", {
            "status": "closed",
            "after":  after,
            "limit":  500,
            "direction": "desc",
        })
        return orders if isinstance(orders, list) else []
    except Exception as e:
        print(f"  Błąd pobierania zleceń: {e}")
        return []


def get_account_activities_7d() -> list[dict]:
    """Pobiera aktywności konta (fills) z ostatnich 7 dni"""
    after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        activities = alpaca_get("/v2/account/activities", {
            "activity_type": "FILL",
            "after": after,
        })
        return activities if isinstance(activities, list) else []
    except Exception as e:
        print(f"  Błąd pobierania aktywności: {e}")
        return []


def get_portfolio_history_7d() -> dict:
    """Pobiera historię portfela z ostatnich 7 dni"""
    try:
        return alpaca_get("/v2/account/portfolio/history", {
            "period": "1W",
            "timeframe": "1D",
        })
    except Exception as e:
        print(f"  Błąd pobierania historii portfela: {e}")
        return {}


def get_account_info() -> dict:
    try:
        return alpaca_get("/v2/account")
    except Exception as e:
        print(f"  Błąd pobierania konta: {e}")
        return {}


# ─── Analiza tradów ───────────────────────────────────────────────────────────

def reconstruct_trades(orders: list[dict]) -> list[dict]:
    """
    Rekonstruuje pełne trady z listy zleceń.
    Paruje: zlecenie otwierające (BUY/SELL_SHORT) z zamykającym (SELL/BUY_TO_COVER).
    """
    # Grupuj po symbolu
    by_symbol = defaultdict(list)
    for order in orders:
        if order.get("status") == "filled" and order.get("filled_avg_price"):
            by_symbol[order["symbol"]].append(order)

    trades = []
    for symbol, sym_orders in by_symbol.items():
        # Sortuj po czasie fill
        sym_orders.sort(key=lambda o: o.get("filled_at", ""))

        open_orders = []
        for order in sym_orders:
            side = order.get("side", "")
            qty  = float(order.get("filled_qty", 0))
            price = float(order.get("filled_avg_price", 0))
            filled_at = order.get("filled_at", "")
            client_id = order.get("client_order_id", "")

            # Identyfikuj strategię z client_order_id (format: strategy-TICKER-ts)
            strategy = "unknown"
            if client_id and "-" in client_id:
                strategy = client_id.split("-")[0]

            if side in ("buy",):
                open_orders.append({
                    "side": "long",
                    "strategy": strategy,
                    "entry_price": price,
                    "entry_time": filled_at,
                    "qty": qty,
                })
            elif side in ("sell",) and open_orders:
                entry = open_orders.pop(0)
                pnl_pct = (price - entry["entry_price"]) / entry["entry_price"] * 100
                pnl_usd = (price - entry["entry_price"]) * entry["qty"]
                try:
                    entry_dt  = datetime.fromisoformat(entry["entry_time"].replace("Z", "+00:00"))
                    exit_dt   = datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
                    hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
                except Exception:
                    hold_hours = 0
                trades.append({
                    "symbol":       symbol,
                    "strategy":     entry["strategy"],
                    "direction":    "long",
                    "entry_price":  entry["entry_price"],
                    "exit_price":   price,
                    "qty":          entry["qty"],
                    "pnl_pct":      round(pnl_pct, 2),
                    "pnl_usd":      round(pnl_usd, 2),
                    "hold_hours":   round(hold_hours, 1),
                    "winner":       pnl_pct > 0,
                    "entry_time":   entry["entry_time"],
                    "exit_time":    filled_at,
                })
            elif side in ("sell_short",):
                open_orders.append({
                    "side": "short",
                    "strategy": strategy,
                    "entry_price": price,
                    "entry_time": filled_at,
                    "qty": qty,
                })
            elif side in ("buy_to_cover", "buy") and open_orders:
                # Zamknięcie shorta
                entry = open_orders.pop(0) if open_orders else None
                if entry:
                    pnl_pct = (entry["entry_price"] - price) / entry["entry_price"] * 100
                    pnl_usd = (entry["entry_price"] - price) * entry["qty"]
                    try:
                        entry_dt   = datetime.fromisoformat(entry["entry_time"].replace("Z", "+00:00"))
                        exit_dt    = datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
                        hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
                    except Exception:
                        hold_hours = 0
                    trades.append({
                        "symbol":      symbol,
                        "strategy":    entry["strategy"],
                        "direction":   "short",
                        "entry_price": entry["entry_price"],
                        "exit_price":  price,
                        "qty":         entry["qty"],
                        "pnl_pct":     round(pnl_pct, 2),
                        "pnl_usd":     round(pnl_usd, 2),
                        "hold_hours":  round(hold_hours, 1),
                        "winner":      pnl_pct > 0,
                        "entry_time":  entry["entry_time"],
                        "exit_time":   filled_at,
                    })

    return trades


def analyze_trades(trades: list[dict], portfolio_history: dict, account: dict) -> dict:
    """Generuje pełną analizę tygodnia"""

    if not trades:
        return {
            "week_summary": "Brak zamkniętych tradów w tym tygodniu",
            "trades_total": 0,
        }

    # Globalne metryki
    winners     = [t for t in trades if t["winner"]]
    losers      = [t for t in trades if not t["winner"]]
    win_rate    = len(winners) / len(trades) * 100 if trades else 0
    total_pnl   = sum(t["pnl_usd"] for t in trades)
    avg_win     = sum(t["pnl_pct"] for t in winners) / len(winners) if winners else 0
    avg_loss    = sum(t["pnl_pct"] for t in losers) / len(losers) if losers else 0
    profit_factor = abs(sum(t["pnl_usd"] for t in winners) / sum(t["pnl_usd"] for t in losers)) if losers else 999
    avg_hold    = sum(t["hold_hours"] for t in trades) / len(trades)

    # Metryki per strategia
    by_strategy = defaultdict(list)
    for t in trades:
        by_strategy[t["strategy"]].append(t)

    strategy_stats = {}
    for strat, strat_trades in by_strategy.items():
        wins = [t for t in strat_trades if t["winner"]]
        strategy_stats[strat] = {
            "trades":      len(strat_trades),
            "win_rate":    round(len(wins) / len(strat_trades) * 100, 1),
            "total_pnl":   round(sum(t["pnl_usd"] for t in strat_trades), 2),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in strat_trades) / len(strat_trades), 2),
            "avg_hold_h":  round(sum(t["hold_hours"] for t in strat_trades) / len(strat_trades), 1),
        }

    # Metryki per ticker
    by_ticker = defaultdict(list)
    for t in trades:
        by_ticker[t["symbol"]].append(t)

    ticker_stats = {}
    for ticker, ticker_trades in by_ticker.items():
        wins = [t for t in ticker_trades if t["winner"]]
        ticker_stats[ticker] = {
            "trades":      len(ticker_trades),
            "win_rate":    round(len(wins) / len(ticker_trades) * 100, 1),
            "total_pnl":   round(sum(t["pnl_usd"] for t in ticker_trades), 2),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in ticker_trades) / len(ticker_trades), 2),
        }

    # Najlepsze i najgorsze trady
    best_trade  = max(trades, key=lambda t: t["pnl_pct"])
    worst_trade = min(trades, key=lambda t: t["pnl_pct"])

    # Portfolio equity
    equity = float(account.get("equity", 0))
    start_equity = float(account.get("last_equity", equity))
    week_return = (equity - start_equity) / start_equity * 100 if start_equity else 0

    return {
        "period":          "7d",
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "github_repo":     f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}",
        "account": {
            "equity":       round(equity, 2),
            "week_return":  round(week_return, 2),
            "total_pnl":    round(total_pnl, 2),
        },
        "overall": {
            "trades_total":    len(trades),
            "win_rate":        round(win_rate, 1),
            "avg_win_pct":     round(avg_win, 2),
            "avg_loss_pct":    round(avg_loss, 2),
            "profit_factor":   round(profit_factor, 2),
            "avg_hold_hours":  round(avg_hold, 1),
            "winners":         len(winners),
            "losers":          len(losers),
        },
        "by_strategy":     strategy_stats,
        "by_ticker":       ticker_stats,
        "best_trade":      best_trade,
        "worst_trade":     worst_trade,
        "all_trades":      trades,
        "update_instructions": (
            "Na podstawie tych danych zaktualizuj pliki strategii w repo. "
            "Jeśli win_rate strategii < 40% → zmniejsz size_usd o 20%. "
            "Jeśli win_rate > 65% → zwiększ size_usd o 15% (max 2x oryginalny). "
            "Jeśli ticker ma ujemny total_pnl w 3+ tradach → rozważ usunięcie z whitelist. "
            "Zaktualizuj sekcję 'Historia i wyniki' w każdej strategii. "
            "Commituj zmiany z wiadomością: '[AI] Weekly strategy update YYYY-MM-DD'. "
            "Użyj GitHub API: PUT /repos/{owner}/{repo}/contents/{path}"
        ),
    }


# ─── Wysyłanie do Claude Routine ─────────────────────────────────────────────

def send_to_routine(analysis: dict) -> bool:
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_LEARNING_WORKER_URL")
        # W trybie bez workera — wydrukuj analizę lokalnie
        print("\n" + "=" * 60)
        print("  ANALIZA TYGODNIOWA (lokalnie):")
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
        return False

    payload = {
        "type":     "weekly_learning",
        "analysis": analysis,
    }
    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=payload,
            timeout=60,
        )
        print(f"  Analiza wysłana do Claude Routine: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def run_weekly_analysis():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === WEEKLY LEARNING LOOP ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    # Pobierz dane
    print("  Pobieranie danych z Alpaca (ostatnie 7 dni)...")
    orders            = get_closed_orders_7d()
    portfolio_history = get_portfolio_history_7d()
    account           = get_account_info()

    print(f"  Zleceń zamkniętych: {len(orders)}")

    # Rekonstruuj trady
    trades = reconstruct_trades(orders)
    print(f"  Zrekonstruowanych tradów: {len(trades)}")

    for t in trades:
        icon = "✅" if t["winner"] else "❌"
        print(f"  {icon} {t['symbol']:8s} {t['direction']:5s} {t['pnl_pct']:+.1f}% "
              f"${t['pnl_usd']:+.2f} ({t['hold_hours']:.1f}h) [{t['strategy']}]")

    # Analiza
    analysis = analyze_trades(trades, portfolio_history, account)

    # Podsumowanie
    if trades:
        ov = analysis["overall"]
        print(f"\n  === PODSUMOWANIE TYGODNIA ===")
        print(f"  Tradów: {ov['trades_total']}, Win rate: {ov['win_rate']}%")
        print(f"  Profit factor: {ov['profit_factor']}")
        print(f"  Avg zysk: {ov['avg_win_pct']:+.1f}%, Avg strata: {ov['avg_loss_pct']:+.1f}%")
        print(f"  Tygodniowy zwrot: {analysis['account']['week_return']:+.2f}%")

    # Wyślij do Claude Routine
    print(f"\n  Wysyłam do Claude Routine (Weekly Strategy Updater)...")
    send_to_routine(analysis)


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_weekly_analysis()

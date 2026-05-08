"""
CLI entry point for the backtest harness.

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \\
        python -m backtest.run \\
            --strategy momentum-long \\
            --tickers AAPL MSFT NVDA \\
            --days 180

Output:
    Per-ticker summary table + aggregate stats. Writes a JSON ledger
    to backtest/results/<strategy>-<YYYYMMDD-HHMM>.json.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data import fetch_daily_bars, date_range_days_ago
from strategies import (
    momentum_long_signal_at,
    momentum_long_loose_signal_at,
    overbought_short_signal_at,
)
from replay import replay


SIGNALS = {
    "momentum-long":        momentum_long_signal_at,
    "momentum-long-loose":  momentum_long_loose_signal_at,
    "overbought-short":     overbought_short_signal_at,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", choices=list(SIGNALS), required=True)
    p.add_argument("--tickers", nargs="+", required=True)
    p.add_argument("--days", type=int, default=180,
                    help="Calendar days of history to replay (default 180)")
    p.add_argument("--no-cache", action="store_true",
                    help="Bypass local bar cache (forces refresh from Alpaca)")
    args = p.parse_args()

    signal_fn = SIGNALS[args.strategy]
    start, end = date_range_days_ago(args.days)
    print(f"Backtest: strategy={args.strategy} window={start}..{end} tickers={args.tickers}")

    per_ticker = {}
    all_trades = []
    for ticker in args.tickers:
        print(f"\n--- {ticker} ---")
        bars = fetch_daily_bars(ticker, start, end, use_cache=not args.no_cache)
        if not bars:
            print(f"  no data — skipping")
            continue
        print(f"  {len(bars['close'])} bars loaded")
        result = replay(bars, signal_fn, ticker=ticker)
        per_ticker[ticker] = result
        all_trades.extend(result["trades"])
        s = result["summary"]
        print(f"  trades={s['n_trades']} wins={s['wins']} "
              f"win_rate={s['win_rate']*100:.0f}% "
              f"P&L=${s['total_pnl_usd']:,.2f} "
              f"avg/trade={s['avg_pnl_pct']:+.2f}%")

    # Aggregate
    print(f"\n{'='*60}\nAGGREGATE — strategy={args.strategy}, {len(args.tickers)} tickers, {args.days} days")
    if all_trades:
        wins = sum(1 for t in all_trades if t["winner"])
        total_pnl = sum(t["pnl_usd"] for t in all_trades)
        avg_pct   = sum(t["pnl_pct"] for t in all_trades) / len(all_trades)
        print(f"  n_trades:      {len(all_trades)}")
        print(f"  wins:          {wins} ({wins/len(all_trades)*100:.0f}%)")
        print(f"  total P&L:     ${total_pnl:,.2f}")
        print(f"  avg/trade:     {avg_pct:+.2f}%")
        print(f"  best trade:    {max(t['pnl_pct'] for t in all_trades):+.2f}%")
        print(f"  worst trade:   {min(t['pnl_pct'] for t in all_trades):+.2f}%")
    else:
        print(f"  no trades fired in this window")

    # Persist
    results_dir = os.path.join(HERE, "results")
    os.makedirs(results_dir, exist_ok=True)
    fname = f"{args.strategy}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    out = os.path.join(results_dir, fname)
    with open(out, "w") as f:
        json.dump({
            "strategy":  args.strategy,
            "window":    {"start": start, "end": end, "days": args.days},
            "tickers":   args.tickers,
            "per_ticker": per_ticker,
            "all_trades": all_trades,
        }, f, indent=2)
    print(f"\n  ledger written: {out}")


if __name__ == "__main__":
    main()

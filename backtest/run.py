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
from realism import RealismConfig, replay_with_realism, compute_rich_metrics


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
    # v3.10 (2026-05-27) — realism + walk-forward CLI extensions per intraday
    # directive 7: "Backtest ma służyć do selekcji hipotez, nie jako gwarancja
    # zysku. Domyślnie raportuj oba: idealized i realistic."
    p.add_argument("--mode", choices=["idealized", "realistic", "both"], default="both",
                    help="idealized (no slippage), realistic (slippage/gap/missed-runs), "
                         "or both (default — report both side-by-side)")
    p.add_argument("--walk-forward", type=int, default=0,
                    help="Walk-forward split count (0 = single-pass; ≥2 = N "
                         "non-overlapping folds reported separately)")
    p.add_argument("--asset-class", default="us_equity",
                    choices=["us_equity", "crypto", "us_option"],
                    help="For realism slippage tier (stocks/crypto/options)")
    args = p.parse_args()

    signal_fn = SIGNALS[args.strategy]
    start, end = date_range_days_ago(args.days)
    print(f"Backtest: strategy={args.strategy} window={start}..{end} tickers={args.tickers}")
    print(f"  mode={args.mode}  walk_forward={args.walk_forward or 'off'}  "
          f"asset_class={args.asset_class}")

    # Realism config — defaults aligned with Alpaca paper observed behavior
    realism_cfg = RealismConfig(
        slippage_bps=5.0,           # 0.05% stocks
        slippage_bps_crypto=20.0,
        slippage_bps_options=50.0,
        gap_penalty_pct=0.015,      # 1.5% gap-through on SL fills
        missed_run_pct=0.05,        # 5% bars skipped (GH cron-skip observed today)
        cost_per_trade_usd=0.0,     # Alpaca paper has zero commission
    )

    def _run_one(bars, ticker):
        out = {"ticker": ticker}
        if args.mode in ("idealized", "both"):
            out["idealized"] = replay(bars, signal_fn, ticker=ticker)
        if args.mode in ("realistic", "both"):
            out["realistic"] = replay_with_realism(
                bars, signal_fn, ticker=ticker,
                asset_class=args.asset_class, config=realism_cfg,
            )
        return out

    per_ticker: dict = {}
    all_trades_idealized: list = []
    all_trades_realistic: list = []

    for ticker in args.tickers:
        print(f"\n--- {ticker} ---")
        bars = fetch_daily_bars(ticker, start, end, use_cache=not args.no_cache)
        if not bars:
            print(f"  no data — skipping")
            continue
        n_bars = len(bars['close'])
        print(f"  {n_bars} bars loaded")

        if args.walk_forward >= 2:
            # Split bars into N non-overlapping folds; report per-fold + aggregate
            fold_size = n_bars // args.walk_forward
            ticker_folds = []
            for fold_i in range(args.walk_forward):
                start_i = fold_i * fold_size
                end_i = (fold_i + 1) * fold_size if fold_i < args.walk_forward - 1 else n_bars
                fold_bars = {k: (v[start_i:end_i] if isinstance(v, list) else v)
                             for k, v in bars.items()}
                if not fold_bars.get("close"):
                    continue
                fold_result = _run_one(fold_bars, ticker)
                ticker_folds.append({"fold": fold_i, "n_bars": end_i - start_i,
                                     **fold_result})
                ideal = fold_result.get("idealized")
                real = fold_result.get("realistic")
                if ideal:
                    s = ideal["summary"]
                    print(f"  fold{fold_i} idealized: n={s['n_trades']} "
                          f"wr={s['win_rate']*100:.0f}% pnl=${s['total_pnl_usd']:,.0f}")
                    all_trades_idealized.extend(ideal["trades"])
                if real:
                    s = real["summary"]
                    print(f"  fold{fold_i} realistic: n={s['n_trades']} "
                          f"wr={s['win_rate']*100:.0f}% pnl=${s['total_pnl_usd']:,.0f}")
                    all_trades_realistic.extend(real["trades"])
            per_ticker[ticker] = {"folds": ticker_folds}
        else:
            result = _run_one(bars, ticker)
            per_ticker[ticker] = result
            ideal = result.get("idealized")
            real = result.get("realistic")
            if ideal:
                s = ideal["summary"]
                print(f"  idealized: trades={s['n_trades']} "
                      f"wr={s['win_rate']*100:.0f}% "
                      f"pnl=${s['total_pnl_usd']:,.2f} "
                      f"avg/trade={s['avg_pnl_pct']:+.2f}%")
                all_trades_idealized.extend(ideal["trades"])
            if real:
                s = real["summary"]
                print(f"  realistic: trades={s['n_trades']} "
                      f"wr={s['win_rate']*100:.0f}% "
                      f"pnl=${s['total_pnl_usd']:,.2f} "
                      f"avg/trade={s['avg_pnl_pct']:+.2f}%")
                all_trades_realistic.extend(real["trades"])

    # Aggregate — side-by-side both modes
    print(f"\n{'='*60}\nAGGREGATE — strategy={args.strategy}, "
          f"{len(args.tickers)} tickers, {args.days} days")

    def _print_summary(label, trades):
        if not trades:
            print(f"  {label}: no trades fired")
            return
        wins = sum(1 for t in trades if t.get("winner"))
        total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
        avg_pct = sum(t.get("pnl_pct", 0) for t in trades) / len(trades)
        print(f"  {label}:")
        print(f"    n_trades:    {len(trades)}")
        print(f"    win_rate:    {wins}/{len(trades)} ({wins/len(trades)*100:.0f}%)")
        print(f"    total P&L:   ${total_pnl:,.2f}")
        print(f"    avg/trade:   {avg_pct:+.2f}%")
        print(f"    best trade:  {max(t.get('pnl_pct',0) for t in trades):+.2f}%")
        print(f"    worst trade: {min(t.get('pnl_pct',0) for t in trades):+.2f}%")
        # Rich metrics (profit factor, max drawdown)
        try:
            rich = compute_rich_metrics(trades)
            pf = rich.get("profit_factor")
            mdd = rich.get("max_drawdown_pct")
            if pf is not None:
                print(f"    profit_factor: {pf:.2f}")
            if mdd is not None:
                print(f"    max_drawdown: {mdd*100:+.2f}%")
        except Exception:
            pass

    if args.mode in ("idealized", "both"):
        _print_summary("IDEALIZED (no slippage/gap/missed)", all_trades_idealized)
    if args.mode in ("realistic", "both"):
        _print_summary("REALISTIC (slippage + gap + 5% missed runs)", all_trades_realistic)
    if args.mode == "both" and all_trades_idealized and all_trades_realistic:
        ideal_pnl = sum(t.get("pnl_usd", 0) for t in all_trades_idealized)
        real_pnl = sum(t.get("pnl_usd", 0) for t in all_trades_realistic)
        delta = real_pnl - ideal_pnl
        print(f"\n  realism delta: ${delta:,.2f} "
              f"({delta/abs(ideal_pnl)*100 if ideal_pnl else 0:+.1f}% of idealized)")
        print(f"  → use REALISTIC for go/no-go; IDEALIZED for upside ceiling")

    # Persist
    results_dir = os.path.join(HERE, "results")
    os.makedirs(results_dir, exist_ok=True)
    fname = f"{args.strategy}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    out = os.path.join(results_dir, fname)
    with open(out, "w") as f:
        json.dump({
            "strategy":  args.strategy,
            "window":    {"start": start, "end": end, "days": args.days},
            "mode":      args.mode,
            "walk_forward": args.walk_forward,
            "asset_class": args.asset_class,
            "tickers":   args.tickers,
            "per_ticker": per_ticker,
            "all_trades_idealized": all_trades_idealized,
            "all_trades_realistic": all_trades_realistic,
        }, f, indent=2)
    print(f"\n  ledger written: {out}")


if __name__ == "__main__":
    main()

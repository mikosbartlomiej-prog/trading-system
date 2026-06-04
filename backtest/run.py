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
from crypto_data import fetch_hourly_crypto_bars
from strategies import (
    momentum_long_signal_at,
    momentum_long_loose_signal_at,
    overbought_short_signal_at,
    crypto_momentum_signal_at,
    crypto_oversold_bounce_signal_at,
)
from replay import replay
from realism import RealismConfig, replay_with_realism, compute_rich_metrics


SIGNALS = {
    "momentum-long":            momentum_long_signal_at,
    "momentum-long-loose":      momentum_long_loose_signal_at,
    "overbought-short":         overbought_short_signal_at,
    "crypto-momentum":          crypto_momentum_signal_at,
    "crypto-oversold-bounce":   crypto_oversold_bounce_signal_at,
}

# Strategies that need hourly crypto bars instead of daily stock bars.
CRYPTO_STRATEGIES = {"crypto-momentum", "crypto-oversold-bounce"}


def _explain_no_signal_crypto(idx: int, bars: dict, strategy: str) -> str:
    """
    Return a short human-readable reason why the crypto signal did NOT
    fire at bar `idx`. Used by --explain-zero-fires when the strategy
    produces 0 trades and the operator wants to see WHY.
    """
    from strategies import (
        _rsi,
        _crypto_24h_move_pct,
        _crypto_avg_vol_safe,
        CRYPTO_RSI_LONG_MIN,
        CRYPTO_RSI_LONG_MAX_DEFAULT,
        CRYPTO_VOL_MULT_DEFAULT,
        CRYPTO_LOOKBACK_BARS,
        CRYPTO_MOMENTUM_24H_MIN_PCT,
        CRYPTO_MOMENTUM_24H_MAX_PCT,
        CRYPTO_OVERSOLD_RSI_MAX,
        CRYPTO_OVERSOLD_MIN_MOVE_PCT,
        CRYPTO_OVERSOLD_VOL_FLOOR,
    )

    if idx < 25:
        return "need 25+ bars"
    closes  = bars["close"][:idx + 1]
    highs   = bars["high"][:idx + 1]
    volumes = bars["volume"][:idx + 1]

    cur = closes[-1]
    cur_vol = volumes[-1]
    rsi = _rsi(closes)
    move_24h = _crypto_24h_move_pct(closes)
    high_20 = max(highs[-(CRYPTO_LOOKBACK_BARS + 1):-1]) if len(highs) > CRYPTO_LOOKBACK_BARS else None
    if _crypto_avg_vol_safe(volumes):
        avg_vol = sum(volumes[-(CRYPTO_LOOKBACK_BARS + 1):-1]) / CRYPTO_LOOKBACK_BARS
    else:
        return "avg-vol unsafe (too few non-zero bars)"

    if strategy == "crypto-momentum":
        if move_24h is None:
            return "no 24h move (insufficient history)"
        if not (CRYPTO_MOMENTUM_24H_MIN_PCT <= abs(move_24h) <= CRYPTO_MOMENTUM_24H_MAX_PCT):
            return f"24h={move_24h:+.2f}% outside [{CRYPTO_MOMENTUM_24H_MIN_PCT},{CRYPTO_MOMENTUM_24H_MAX_PCT}]"
        if high_20 is None or cur <= high_20:
            return f"no breakout (cur={cur:.2f} <= 20-high={high_20:.2f if high_20 else 0})"
        if cur_vol <= avg_vol * CRYPTO_VOL_MULT_DEFAULT:
            return f"vol={cur_vol/avg_vol:.2f}x < {CRYPTO_VOL_MULT_DEFAULT}x"
        if rsi is None:
            return "rsi insufficient"
        if not (CRYPTO_RSI_LONG_MIN <= rsi <= CRYPTO_RSI_LONG_MAX_DEFAULT):
            return f"rsi={rsi:.1f} outside [{CRYPTO_RSI_LONG_MIN},{CRYPTO_RSI_LONG_MAX_DEFAULT}]"
        return "passes filter (signal should have fired)"

    if strategy == "crypto-oversold-bounce":
        if rsi is None:
            return "rsi insufficient"
        if rsi > CRYPTO_OVERSOLD_RSI_MAX:
            return f"rsi={rsi:.1f} > {CRYPTO_OVERSOLD_RSI_MAX} (not oversold)"
        if move_24h is None:
            return "no 24h move (insufficient history)"
        if move_24h < CRYPTO_OVERSOLD_MIN_MOVE_PCT:
            return f"24h={move_24h:+.2f}% < {CRYPTO_OVERSOLD_MIN_MOVE_PCT}% (catastrophe)"
        if len(closes) < 4:
            return "need 4+ bars for stabilization rule"
        recent_avg = sum(closes[-3:]) / 3.0
        baseline = closes[-4]
        if recent_avg < baseline:
            return f"not stabilizing (avg3={recent_avg:.2f} < closes[-4]={baseline:.2f})"
        floor = avg_vol * (CRYPTO_VOL_MULT_DEFAULT * CRYPTO_OVERSOLD_VOL_FLOOR)
        if cur_vol <= floor:
            return f"vol={cur_vol:.0f} <= floor={floor:.0f}"
        return "passes filter (signal should have fired)"

    return "unknown strategy"


def _explain_zero_fires(bars: dict, signal_fn, strategy: str,
                          ticker: str, limit: int = 25) -> list[str]:
    """
    Run signal_fn across all bars, collect per-bar rejection reasons when
    signal returns None. Cap at `limit` distinct reason×idx samples so the
    log doesn't explode for a 4320-bar window.

    Returns formatted strings ["idx=120 t=... reason=..."] for printing.
    """
    out: list[str] = []
    n = len(bars["close"])
    # Sample evenly across the bar window — first 5 + middle 10 + last 10.
    if n <= limit:
        sample_indices = list(range(25, n))
    else:
        sample_indices = list(range(25, min(30, n)))                          # first 5
        mid_start = n // 2 - 5
        sample_indices += list(range(max(25, mid_start), min(n, mid_start + 10)))  # middle 10
        sample_indices += list(range(max(25, n - 10), n))                     # last 10
    sample_indices = sorted(set(sample_indices))[:limit]

    for idx in sample_indices:
        sig = signal_fn(idx, bars)
        if sig is not None:
            continue
        reason = _explain_no_signal_crypto(idx, bars, strategy)
        ts = bars.get("time", [None]*n)[idx] if idx < len(bars.get("time", [])) else "?"
        out.append(f"idx={idx} t={ts} → {reason}")
    return out


# v3.16.0 (2026-06-04) — event-driven strategies route through event_replay
# instead of bar replay. Caller selects via --strategy geo-defense etc.
EVENT_STRATEGY_NAMES = ("geo-defense", "geo-energy", "geo-gold", "geo-all")


def _run_event_backtest(strategy: str, start_iso: str, end_iso: str,
                          tickers: list, use_cache: bool) -> int:
    """Phase 1 MVP event-backtest path. Returns process exit code."""
    from event_strategies import EVENT_STRATEGIES
    from event_replay import replay_events, strategy_set_for
    from event_data import fetch_events_for_range, DEFAULT_DEFENSE_PREFIXES

    classifier = EVENT_STRATEGIES.get(strategy)
    if classifier is None:
        print(f"unknown event strategy: {strategy}")
        return 2

    print(f"Event backtest: strategy={strategy} window={start_iso}..{end_iso} "
          f"tickers={tickers}")
    print(f"  (MVP: results ADVISORY ONLY; statistical power threshold n>=50 not enforced)")

    # Fetch events.
    events = fetch_events_for_range(start_iso, end_iso,
                                      DEFAULT_DEFENSE_PREFIXES,
                                      use_cache=use_cache)
    print(f"  events_loaded: {len(events)}")
    if not events:
        print("  no events in window — exiting (advisory)")
        return 0

    # Market-data callback: bar-aligned, cached by `backtest.data`.
    def _market_data_fn(symbol: str):
        return fetch_daily_bars(symbol, start_iso, end_iso, use_cache=use_cache)

    result = replay_events(
        events,
        classifier_fn=classifier,
        market_data_fn=_market_data_fn,
        strategy_filter=strategy_set_for(strategy),
    )
    trades = result["trades"]
    summary = result["summary"]
    print(f"  trades: {summary['n_trades']}  wr: {summary['win_rate']*100:.0f}%  "
          f"pnl: ${summary['total_pnl_usd']:,.2f}  avg/trade: {summary['avg_pnl_pct']:+.2f}%")
    print(f"  debug: {result['debug']}")

    # Persist (same shape as bar replay).
    results_dir = os.path.join(HERE, "results")
    os.makedirs(results_dir, exist_ok=True)
    fname = f"{strategy}-event-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    out = os.path.join(results_dir, fname)
    with open(out, "w") as f:
        json.dump({
            "strategy":     strategy,
            "mode":         "event_driven",
            "readiness":    "MVP_IN_PROGRESS",
            "window":       {"start": start_iso, "end": end_iso},
            "tickers_hint": tickers,
            "trades":       trades,
            "summary":      summary,
            "debug":        result["debug"],
        }, f, indent=2)
    print(f"  ledger written: {out}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True,
                    help="bar strategy (momentum-long/...) or event strategy "
                         "(geo-defense/geo-energy/geo-gold/geo-all)")
    p.add_argument("--tickers", nargs="*", default=[],
                    help="tickers (bar mode); ignored for event mode "
                         "(market-data fetched per signal)")
    p.add_argument("--start", default=None,
                    help="event mode: window start YYYY-MM-DD (alt to --days)")
    p.add_argument("--end", default=None,
                    help="event mode: window end YYYY-MM-DD (default today)")
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
    # v3.16 (2026-06-04) — crypto-specific args
    p.add_argument("--hours", type=int, default=4320,
                    help="For crypto strategies: hourly bars window "
                         "(default 4320 = 180 days × 24h). Ignored for stock "
                         "strategies which use --days.")
    p.add_argument("--explain-zero-fires", action="store_true",
                    help="When the strategy produces 0 trades, print per-bar "
                         "rejection reasons (rate-limited to the first 25). "
                         "Crypto strategies only.")
    args = p.parse_args()

    # v3.16.0 — dispatch event-driven strategies to event_replay.
    if args.strategy in EVENT_STRATEGY_NAMES:
        if args.start and args.end:
            start_iso, end_iso = args.start, args.end
        elif args.start:
            start_iso = args.start
            end_iso = datetime.now(timezone.utc).date().isoformat()
        else:
            start_iso, end_iso = date_range_days_ago(args.days)
        rc = _run_event_backtest(args.strategy, start_iso, end_iso,
                                  args.tickers, use_cache=not args.no_cache)
        sys.exit(rc)

    if args.strategy not in SIGNALS:
        p.error(f"unknown strategy {args.strategy!r}; choose from "
                f"{list(SIGNALS) + list(EVENT_STRATEGY_NAMES)}")
    if not args.tickers:
        p.error("--tickers required for bar-driven strategies")

    signal_fn = SIGNALS[args.strategy]
    is_crypto = args.strategy in CRYPTO_STRATEGIES
    # Auto-promote asset-class for crypto strategies (operator-friendly default)
    if is_crypto and args.asset_class == "us_equity":
        args.asset_class = "crypto"

    if is_crypto:
        start, end = (None, None)
        window_label = f"hours={args.hours}"
    else:
        start, end = date_range_days_ago(args.days)
        window_label = f"window={start}..{end}"

    print(f"Backtest: strategy={args.strategy} {window_label} tickers={args.tickers}")
    print(f"  mode={args.mode}  walk_forward={args.walk_forward or 'off'}  "
          f"asset_class={args.asset_class}  hourly={is_crypto}")

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
        if is_crypto:
            bars = fetch_hourly_crypto_bars(
                ticker, hours=args.hours, use_cache=not args.no_cache
            )
        else:
            bars = fetch_daily_bars(ticker, start, end, use_cache=not args.no_cache)
        if not bars:
            print(f"  no data — skipping")
            continue
        n_bars = len(bars['close'])
        print(f"  {n_bars} bars loaded")

        # --explain-zero-fires: pre-scan to surface per-bar rejection reasons
        # when (a) crypto strategy AND (b) operator opted in. Helpful for
        # diagnosing 14-day STRAT-002 observation gaps.
        if args.explain_zero_fires and is_crypto:
            preview = _explain_zero_fires(
                bars, signal_fn, args.strategy, ticker, limit=25,
            )
            if preview:
                print(f"  zero-fire diagnostic ({len(preview)} sampled bars):")
                for line in preview:
                    print(f"    {line}")

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

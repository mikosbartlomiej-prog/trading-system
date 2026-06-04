"""v3.16.0 (2026-06-04) — Event-driven backtest replay loop.

Distinct from `backtest/replay.py` (bar-driven walk-forward). Here the
inputs are a list of historical events (e.g. from GDELT or NewsAPI archive)
+ a classifier function + a market-data lookup callback.

WHY A NEW MODULE
----------------
Bar-driven momentum strategies iterate per-bar. Event-driven strategies
iterate per-event:
  1. classifier(event) → list[GeoSignal]
  2. for each signal, fetch bars at event_date → simulate fill at next session open
  3. simulate bracket SL/TP using subsequent bars
  4. emit trade ledger row with same shape as bar replay

Output ledger shape MATCHES bar replay so `realism.compute_rich_metrics`
and run.py report logic work without modification.

NO LOOKAHEAD INVARIANT
----------------------
Entry price = NEXT bar's open (one bar AFTER event detection).
Exits walk forward from entry_idx + 1, never peek beyond max bar.
Tests assert this invariant.

FAIL-SOFT
---------
Missing bars / unknown ticker / invalid event → skip; never raise.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Iterable, Any

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.abspath(os.path.join(HERE, "..", "shared"))
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)


# Default position size — matches strategies/aggressive-momentum.md baseline.
DEFAULT_POSITION_SIZE_USD = 6_000.0
MAX_HOLD_DAYS_DEFAULT = 10


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bar_date(time_str: str) -> Optional[str]:
    """Extract YYYY-MM-DD from a bar time string. Fail-soft → None."""
    if not time_str:
        return None
    try:
        # Alpaca format: "2026-04-01T04:00:00Z"
        return time_str.split("T")[0][:10]
    except Exception:
        return None


def _find_next_bar_idx(bars: dict, event_date_iso: str) -> Optional[int]:
    """Index of the first bar AFTER `event_date_iso`.

    Returns None when no later bar is in range (event happened after window).
    Preserves no-lookahead: we never use the bar ON the event day, only AFTER.
    """
    times = bars.get("time", [])
    if not times:
        return None
    for idx, t in enumerate(times):
        d = _bar_date(t)
        if d is None:
            continue
        if d > event_date_iso:
            return idx
    return None


# ─── Replay loop ──────────────────────────────────────────────────────────────

def replay_events(events,
                   classifier_fn: Callable,
                   market_data_fn: Callable[[str], Optional[dict]],
                   *,
                   position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
                   max_hold_days: int = MAX_HOLD_DAYS_DEFAULT,
                   strategy_filter: Optional[set] = None,
                   ) -> dict:
    """Replay a sequence of historical events through the geo classifier.

    Args:
        events: iterable of historical events. Each must expose `.headline`,
                `.summary` (optional), `.day` (YYYY-MM-DD), `.source_url`
                (or attribute-style access). Falls back to dict-style.
        classifier_fn: callable matching
                ``classify_event_to_signals(headline, summary, source_type,
                detected_at_iso=...)`` → list[GeoSignal].
        market_data_fn: callable that maps `symbol → bars_dict` (Alpaca-shape).
                The same callable is invoked once per unique ticker; caller
                is responsible for caching.
        position_size_usd: notional per trade (matches geo strategy baseline).
        max_hold_days: time-stop in days (force exit if neither SL nor TP).
        strategy_filter: optional whitelist of strategy names. Other signals dropped.

    Returns:
        dict with keys ``trades``, ``summary``, ``debug``. Trade rows share
        the shape produced by `backtest.replay.replay` so report logic reuses.
    """
    trades: list = []
    rejected_events: int = 0
    rejected_signals: int = 0
    bars_cache: dict = {}

    for ev in events:
        # Pull fields with attribute-or-dict access (so dataclass + plain dict both work).
        headline = _get(ev, "headline", "")
        summary  = _get(ev, "summary", "")
        day      = _get(ev, "day", "") or _get(ev, "detected_at_iso", "")[:10]
        source_url = _get(ev, "source_url", "")
        detected_at_iso = _get(ev, "detected_at_iso", "") or f"{day}T00:00:00+00:00"

        if not headline or not day:
            rejected_events += 1
            continue

        # Classify event → signals.
        try:
            signals = classifier_fn(
                headline=headline,
                summary=summary,
                source_type=_get(ev, "source_type", "major_outlet"),
                detected_at_iso=detected_at_iso,
            )
        except Exception:
            rejected_events += 1
            continue

        if not signals:
            continue

        for sig in signals:
            strategy = _get(sig, "strategy", "")
            if strategy_filter and strategy not in strategy_filter:
                rejected_signals += 1
                continue
            tickers = _get(sig, "primary_tickers", ())
            if not tickers:
                rejected_signals += 1
                continue
            symbol = tickers[0]

            # Fetch bars (cache by symbol).
            if symbol not in bars_cache:
                try:
                    bars_cache[symbol] = market_data_fn(symbol)
                except Exception:
                    bars_cache[symbol] = None
            bars = bars_cache[symbol]
            if not bars or not bars.get("close"):
                rejected_signals += 1
                continue

            entry_idx = _find_next_bar_idx(bars, day)
            if entry_idx is None or entry_idx >= len(bars.get("close", [])):
                rejected_signals += 1
                continue

            trade = _simulate_trade(
                bars=bars,
                entry_idx=entry_idx,
                signal=sig,
                ticker=symbol,
                position_size_usd=position_size_usd,
                max_hold_days=max_hold_days,
                event_day=day,
                event_headline=headline,
                source_url=source_url,
            )
            if trade is not None:
                trades.append(trade)

    summary = _summarize(trades)
    return {
        "trades":   trades,
        "summary":  summary,
        "debug": {
            "n_events_processed":  len(list(events)) if hasattr(events, "__len__") else None,
            "rejected_events":     rejected_events,
            "rejected_signals":    rejected_signals,
            "unique_symbols":      sorted(bars_cache.keys()),
        },
    }


def _simulate_trade(
    bars: dict,
    entry_idx: int,
    signal,
    ticker: str,
    position_size_usd: float,
    max_hold_days: int,
    event_day: str,
    event_headline: str,
    source_url: str,
) -> Optional[dict]:
    """Open at next-bar-open, walk forward until SL/TP/max_hold. No lookahead."""
    closes = bars["close"]
    highs  = bars["high"]
    lows   = bars["low"]
    opens  = bars["open"]
    times  = bars["time"]
    n = len(closes)

    if entry_idx >= n:
        return None

    # Entry at next-bar OPEN.
    entry_price = float(opens[entry_idx])
    if entry_price <= 0:
        return None

    sl_pct = float(_get(signal, "sl_pct", -5.0)) / 100.0
    tp_pct = float(_get(signal, "tp_pct", 10.0)) / 100.0
    side   = _get(signal, "side", "BUY")
    direction = "long" if side.upper() == "BUY" else "short"

    if direction == "long":
        stop_loss   = entry_price * (1 + sl_pct)
        take_profit = entry_price * (1 + tp_pct)
    else:
        stop_loss   = entry_price * (1 - sl_pct)
        take_profit = entry_price * (1 - tp_pct)

    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    end_idx = min(n, entry_idx + 1 + max_hold_days)
    for idx in range(entry_idx + 1, end_idx):
        day_high = highs[idx]
        day_low  = lows[idx]
        if direction == "long":
            if day_low <= stop_loss:
                exit_idx, exit_price, exit_reason = idx, stop_loss, "SL"
                break
            if day_high >= take_profit:
                exit_idx, exit_price, exit_reason = idx, take_profit, "TP"
                break
        else:
            if day_high >= stop_loss:
                exit_idx, exit_price, exit_reason = idx, stop_loss, "SL"
                break
            if day_low <= take_profit:
                exit_idx, exit_price, exit_reason = idx, take_profit, "TP"
                break

    # Time-stop at max_hold if neither SL nor TP hit.
    if exit_idx is None:
        last_idx = min(end_idx - 1, n - 1)
        if last_idx <= entry_idx:
            return None
        exit_idx, exit_reason = last_idx, "TIME"
        exit_price = float(closes[last_idx])

    qty = position_size_usd / entry_price
    if direction == "long":
        pnl_usd = (exit_price - entry_price) * qty
        pnl_pct = (exit_price / entry_price - 1) * 100
    else:
        pnl_usd = (entry_price - exit_price) * qty
        pnl_pct = (1 - exit_price / entry_price) * 100

    return {
        "ticker":      ticker,
        "strategy":    _get(signal, "strategy", "geo-unknown"),
        "direction":   direction,
        "entry_date":  times[entry_idx],
        "exit_date":   times[exit_idx],
        "entry_price": round(entry_price, 4),
        "exit_price":  round(exit_price, 4),
        "stop_loss":   round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "pnl_usd":     round(pnl_usd, 2),
        "pnl_pct":     round(pnl_pct, 2),
        "hold_days":   exit_idx - entry_idx,
        "exit_reason": exit_reason,
        "winner":      pnl_usd > 0,
        "event_day":   event_day,
        "event_headline": (event_headline or "")[:160],
        "event_source_url": source_url,
    }


def _summarize(trades: list) -> dict:
    """Aggregate stats — same shape as bar replay's summarize()."""
    if not trades:
        return {
            "n_trades":      0,
            "wins":          0,
            "losses":        0,
            "win_rate":      0.0,
            "total_pnl_usd": 0.0,
            "avg_pnl_pct":   0.0,
            "best_pct":      0.0,
            "worst_pct":     0.0,
            "avg_hold_days": 0.0,
        }
    wins   = [t for t in trades if t["winner"]]
    losses = [t for t in trades if not t["winner"]]
    pcts   = [t["pnl_pct"] for t in trades]
    return {
        "n_trades":      len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades), 3),
        "total_pnl_usd": round(sum(t["pnl_usd"] for t in trades), 2),
        "avg_pnl_pct":   round(sum(pcts) / len(pcts), 2),
        "best_pct":      round(max(pcts), 2),
        "worst_pct":     round(min(pcts), 2),
        "avg_hold_days": round(sum(t["hold_days"] for t in trades) / len(trades), 1),
    }


def _get(obj: Any, attr: str, default=None):
    """Attribute-OR-dict accessor (works for dataclasses + dicts + Mappings)."""
    if obj is None:
        return default
    if hasattr(obj, attr):
        try:
            return getattr(obj, attr)
        except Exception:
            return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return default


# ─── Strategy-bucket filter helpers ───────────────────────────────────────────

GEO_STRATEGY_SETS = {
    "geo-defense": {"geo-defense"},
    "geo-energy":  {"geo-energy", "geo-xom"},
    "geo-gold":    {"geo-gold"},
    "geo-all":     {"geo-defense", "geo-energy", "geo-gold", "geo-xom"},
}


def strategy_set_for(name: str) -> set:
    """Convenience: map CLI --strategy arg to internal strategy whitelist set."""
    return set(GEO_STRATEGY_SETS.get(name, {name}))


__all__ = [
    "replay_events",
    "DEFAULT_POSITION_SIZE_USD",
    "MAX_HOLD_DAYS_DEFAULT",
    "GEO_STRATEGY_SETS",
    "strategy_set_for",
]

from __future__ import annotations  # v3.11.3 part 2: PEP 604 on Py 3.9.

"""
Daily Learning Loop — Analyzer

Runs once per day after US market close. Reads Alpaca order history,
reconstructs trades, computes per-strategy / per-asset / per-source
performance, calls adapter to produce new state, writes:
  - state.json          (current adapted parameters, machine-readable)
  - rationale.md        (append-only narrative)
  - history/<date>.md   (per-day full report)

The workflow then commits these back to main, so git history IS the
audit log (every adaptation visible via `git log -- learning-loop/`).

Routine bypass (v2.2): no longer forwards anything to Claude Routine.
LLM scope shrinks to manual chat / opt-in via USE_ROUTINE.
"""

import json
import os
import subprocess
import sys
import requests
from collections import defaultdict
from datetime import datetime, timezone, timedelta


def _git_current_branch() -> str:
    """Best-effort detection of the workflow's branch (used in LLM payload)."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "main"

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

LEARNING_DIR     = os.path.dirname(os.path.abspath(__file__))
STATE_PATH       = os.path.join(LEARNING_DIR, "state.json")
RATIONALE_PATH   = os.path.join(LEARNING_DIR, "rationale.md")
HISTORY_DIR      = os.path.join(LEARNING_DIR, "history")

sys.path.insert(0, LEARNING_DIR)
from adapter    import adapt          # noqa: E402
from llm_client import (              # noqa: E402
    call_routine, call_senior_pm_round1, call_challenger,
    call_senior_pm_revise, safe_apply_overrides,
    append_heuristic_proposals, route_proposals,
)

HEURISTIC_PROPOSALS_PATH = os.path.join(LEARNING_DIR, "heuristic_proposals.md")


# ─── Alpaca helpers ──────────────────────────────────────────────────────────

def _alpaca_get(endpoint: str, params: dict | None = None):
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    r = requests.get(f"{ALPACA_BASE_URL}{endpoint}", headers=headers,
                     params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_orders_window(after_iso: str) -> list[dict]:
    """All orders (any status) submitted after `after_iso` UTC."""
    try:
        orders = _alpaca_get("/v2/orders", {
            "status":    "all",
            "after":     after_iso,
            "limit":     500,
            "direction": "desc",
        })
        return orders if isinstance(orders, list) else []
    except Exception as e:
        print(f"  /v2/orders error: {e}")
        return []


def get_account() -> dict:
    try:
        return _alpaca_get("/v2/account")
    except Exception as e:
        print(f"  /v2/account error: {e}")
        return {}


# ─── Trade reconstruction ────────────────────────────────────────────────────

import re as _re_strategy_parse

# Alpaca auto-generates UUIDs for bracket child orders (SL + TP legs)
# when the parent uses bracket. These look like
# `cda058d6-1d5f-4b67-a222-ca7c9b29a9ae` (8-4-4-4-12 hex). Without this
# detection, the fallback "-".join(parts[:-2]) below treated them as
# valid "strategy" names — polluting state.json with fake strategies
# each day (7 pruned 2026-05-16, 3 on 05-15, 1 on 05-14, growing).
_UUID_RE = _re_strategy_parse.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    _re_strategy_parse.IGNORECASE,
)


# v3.11.3 part 2 (2026-05-30) — symbol-based fallback attribution.
# Activated when client_order_id parse returns 'unknown' (legacy GTC
# LIMITs from pre-tagging era, untagged manual orders, Alpaca bracket
# UUIDs). Maps the symbol to its most likely originating strategy so
# fill_rate / per-strategy stats stop being polluted by 'unknown'.
#
# Conservative: only map symbols where there's exactly ONE plausible
# strategy. Multi-strategy symbols (SPY, QQQ, AMD shared between
# allocator and momentum-long) stay 'unknown' to avoid mis-attribution.
SYMBOL_STRATEGY_MAP = {
    # Geo single-name plays (geo-monitor _classify_news_to_signals)
    "XOM":  "geo-xom",
    "CVX":  "geo-energy",
    "RTX":  "geo-defense",
    "LMT":  "geo-defense",
    "GLD":  "geo-gold",
    # Crypto only one source (crypto-monitor) — covers oversold-bounce +
    # momentum + breakdown, but they're rare enough that bucketing
    # together under crypto-monitor parent is OK if exact tag missing.
    # Crypto symbols already typed via "/" — handled differently.
}


def _attribute_via_symbol(symbol: str) -> str:
    """Symbol-based fallback when client_order_id parse fails.

    Returns mapped strategy or 'unattributed' (renamed from 'unknown'
    for clarity — distinguishes pre-tagging-era orders from genuine
    parse errors).
    """
    if not symbol:
        return "unknown"
    sym_upper = symbol.upper().replace("/", "")
    return SYMBOL_STRATEGY_MAP.get(sym_upper, "unknown")


def _strategy_from_client_id(client_order_id: str, symbol: str = "") -> str:
    """
    client_order_id formats:
      ENTRY:  "<strategy>-<symbol_clean>-<HHMMSSmmm>"
              (shared/alpaca_orders.py format)
      EXIT new (LLM proposal 2026-05-11, TP attribution fix):
              "exit-<reason>-<strategy>-<symbol_clean>-<HHMMSSmmm>"
      EXIT legacy (pre-2026-05-12):
              "exit-<reason>-<symbol_clean>-<HHMMSSmmm>"
              -> returns 'unknown' (no strategy embedded; caller should
                 fall back to per-symbol entry lookup).
      AUTO-GENERATED UUID (Alpaca bracket child orders or untagged calls):
              "<uuid-8-4-4-4-12>"  -> returns 'unknown' (NOT a real strategy).

    Strategy names may contain hyphens (e.g. "momentum-long"), so we
    can't simply split on '-'. We locate the symbol marker and take
    everything before it.

    v3.8.5 (2026-05-16): UUID pattern detection added to stop fake
    strategy pollution. Previously, Alpaca-auto-generated bracket-child
    UUIDs were parsed as 3-hyphen-segment "strategies" and polluted
    state.json (cumulative 11+ fake entries across 3 days).

    v3.11.3 part 2 (2026-05-30) — SYMBOL-BASED FALLBACK ATTRIBUTION:
    when parser returns 'unknown' AND symbol is known, look up symbol in
    SYMBOL_STRATEGY_MAP. Maps long-lived GTC LIMITs from pre-attribution
    era to their likely strategy (XOM→geo-xom, CVX→geo-energy, etc.).
    Drives fill_rate.unknown 37% → real per-strategy fill rates. From
    LLM proposal 2026-05-28.
    """
    if not client_order_id:
        return _attribute_via_symbol(symbol)

    cid = client_order_id

    # FIRST: detect Alpaca auto-generated UUIDs (bracket children).
    if _UUID_RE.match(cid):
        return _attribute_via_symbol(symbol)   # UUID = auto-assigned; try symbol fallback

    # Detect EXIT format: strip the "exit-<reason>-" prefix so the
    # remaining structure matches ENTRY format.
    is_exit = cid.lower().startswith("exit-")
    if is_exit:
        # Strip 'exit-' then strip the reason segment.
        # Known reasons: tp, sl, neardth, regime, trail, emergency
        # Defensive: strip exactly one '-'-separated token after 'exit-'.
        body = cid[5:]  # after 'exit-'
        dash = body.find("-")
        if dash < 0:
            return _attribute_via_symbol(symbol)
        # body[dash+1:] is now <maybe-strategy>-<sym>-<ts>
        rest = body[dash + 1:]
    else:
        rest = cid

    def _uuidish(name: str) -> bool:
        """True if name has 8-hex-dash-4-hex-dash-4-hex shape anywhere."""
        return bool(_re_strategy_parse.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", name, _re_strategy_parse.IGNORECASE,
        ))

    if symbol:
        sym_clean = symbol.replace("/", "")
        marker = f"-{sym_clean}-"
        idx = rest.find(marker)
        if idx > 0:
            candidate = rest[:idx]
            if _uuidish(candidate):
                return _attribute_via_symbol(symbol)  # stitched UUID + symbol
            return candidate
        # New exit format may include strategy; older exit format jumps
        # straight to symbol — detect by checking if rest STARTS with the
        # symbol (then no strategy embedded).
        if rest.startswith(sym_clean + "-"):
            return _attribute_via_symbol(symbol)  # legacy exit pre-2026-05-12

    # Fallback: strip last 2 segments (timestamp + symbol)
    parts = rest.split("-")
    if len(parts) >= 3:
        candidate = "-".join(parts[:-2])
        if _uuidish(candidate):
            # Try symbol-based fallback before giving up
            return _attribute_via_symbol(symbol)
        return candidate
    # All parse paths exhausted → symbol-based fallback last chance
    return _attribute_via_symbol(symbol)


def reconstruct_trades(orders: list[dict]) -> list[dict]:
    """
    Pair each open with a corresponding close to compute per-trade P&L.

    We distinguish opens from closes by `client_order_id` prefix:
    entries are tagged by the entry monitors with the strategy name
    (e.g. "momentum-long-AAPL-130000123", "options-momentum-NVDA-..."),
    closes are tagged by exit-monitor / options-exit-monitor with an
    "exit-" prefix (e.g. "exit-emergency-googl", "exit-tp-aapl-...").

    Within each symbol, we FIFO-pair opens with closes. The trade's
    direction comes from the open (long if it was a buy entry, short
    if it was sell_short). This is more reliable than dispatching on
    Alpaca side= alone, because Alpaca uses side="buy" both to open a
    long AND to cover a short.
    """
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for o in orders:
        if o.get("status") == "filled" and o.get("filled_avg_price"):
            by_symbol[o["symbol"]].append(o)

    trades = []
    for symbol, sym_orders in by_symbol.items():
        sym_orders.sort(key=lambda x: x.get("filled_at", ""))
        opens: list[dict] = []
        for o in sym_orders:
            side  = o.get("side", "")
            qty   = float(o.get("filled_qty", 0))
            price = float(o.get("filled_avg_price", 0))
            ts    = o.get("filled_at", "")
            strat = _strategy_from_client_id(o.get("client_order_id", ""), symbol)

            if _is_close(o):
                # Match against the earliest unpaired open for this symbol.
                # Orphan close (open from before the 24h window) is skipped.
                if not opens:
                    continue
                e = opens.pop(0)
                trades.append(_make_trade(symbol, e["side"], e, price, ts))
            else:
                # Entry order. Direction inferred from Alpaca side:
                #   buy / buy_to_open       -> long
                #   sell_short / sell       -> short  (paper Alpaca returns
                #                              sell when opening a short on a
                #                              non-held symbol)
                if side in ("sell_short", "sell"):
                    direction = "short"
                else:
                    direction = "long"
                opens.append({
                    "side":        direction,
                    "strategy":    strat,
                    "entry_price": price,
                    "entry_time":  ts,
                    "qty":         qty,
                })
    return trades


def _is_close(order: dict) -> bool:
    """
    Detect close orders. Patterns:

    1. Explicit tagging by exit-monitor / options-exit-monitor:
       client_order_id starts with 'exit-' (e.g. 'exit-emergency-*',
       'exit-tp-*', 'exit-sl-*').
    2. Alpaca bracket-order child legs (auto-created by Alpaca when a
       parent is placed with order_class=bracket):
       client_order_id ends with '_take_profit' or '_stop_loss'.
    3. Operational closes by allocator / one-shot scripts (v3.8.6):
       'alloc-exit-*', 'alloc-reduce-*', 'op-correction-*',
       'emergency-close-*'. These reduce positions but are tagged
       differently from strategy exits.
    4. Position-intent fallback: Alpaca sets order.position_intent =
       'sell_to_close' / 'buy_to_close' for orders that explicitly close
       a position (via DELETE /v2/positions endpoint). This catches
       cases #3 even without prefix recognition.

    Anything else is treated as an entry.
    """
    cid = (order.get("client_order_id") or "").lower()
    if cid.startswith("exit-"):
        return True
    if cid.endswith("_take_profit") or cid.endswith("_stop_loss"):
        return True
    if (cid.startswith("alloc-exit-")
            or cid.startswith("alloc-reduce-")
            or cid.startswith("op-correction-")
            or cid.startswith("emergency-close-")
            or cid.startswith("operational-correction-")):
        return True
    intent = (order.get("position_intent") or "").lower()
    if intent in ("sell_to_close", "buy_to_close"):
        return True
    return False


def _make_trade(symbol, direction, entry, exit_price, exit_time) -> dict:
    if direction == "long":
        pl_pct = (exit_price - entry["entry_price"]) / entry["entry_price"] * 100
        pl_usd = (exit_price - entry["entry_price"]) * entry["qty"]
    else:
        pl_pct = (entry["entry_price"] - exit_price) / entry["entry_price"] * 100
        pl_usd = (entry["entry_price"] - exit_price) * entry["qty"]
    try:
        e_dt = datetime.fromisoformat(entry["entry_time"].replace("Z", "+00:00"))
        x_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
        hold = (x_dt - e_dt).total_seconds() / 3600
    except Exception:
        hold = 0
    return {
        "symbol":      symbol,
        "strategy":    entry["strategy"],
        "direction":   direction,
        "entry_price": entry["entry_price"],
        "exit_price":  exit_price,
        "qty":         entry["qty"],
        "pnl_pct":     round(pl_pct, 2),
        "pnl_usd":     round(pl_usd, 2),
        "hold_hours":  round(hold, 1),
        "winner":      pl_pct > 0,
        "entry_time":  entry["entry_time"],
        "exit_time":   exit_time,
    }


# ─── Stats aggregation ───────────────────────────────────────────────────────

ASSET_CLASS_BY_SYMBOL = {}  # populated dynamically — we infer from symbol


def _asset_class(symbol: str) -> str:
    if "/" in symbol:
        return "crypto"
    if len(symbol) > 7 and any(ch.isdigit() for ch in symbol):
        return "options"
    if symbol in ("TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU",
                   "SOXL", "SOXS", "FAS", "FAZ", "TNA", "TZA"):
        return "leveraged_etf"
    return "stocks"


def compute_strategy_stats(trades: list[dict], orders_all: list[dict],
                            equity: float) -> dict:
    """
    Per-strategy roll-up: trades_7d, win_rate_7d, pnl_usd_7d,
    consecutive_losses, plus long/short P&L splits for options bias.

    SINGLE-LEG ATTRIBUTION (proposal #6 from 2026-05-09 LLM, fix for
    by_strategy=empty 4 days running): also include strategies that
    have OPEN entries (filled buy/sell_short orders not yet paired
    with a close in the 24h window). For those strategies emit
    placeholder stats with `open_positions_7d` count so the LLM /
    adapter at least knows the strategy IS active. Without this, any
    multi-day held position keeps the strategy invisible to learning.
    """
    strat_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        strat_trades[t["strategy"]].append(t)

    # NEW: count entry-side fills per strategy from raw orders, even
    # when no matching close exists in the window.
    strat_opens: dict[str, int] = defaultdict(int)
    for o in orders_all:
        if o.get("status") != "filled" or not o.get("filled_avg_price"):
            continue
        cid = (o.get("client_order_id") or "").lower()
        # Skip closes (exit-* prefix or bracket child suffix)
        if cid.startswith("exit-") or cid.endswith(("_take_profit", "_stop_loss")):
            continue
        strat = _strategy_from_client_id(o.get("client_order_id", ""),
                                          o.get("symbol", ""))
        if strat == "unknown":
            continue
        strat_opens[strat] += 1

    out = {}
    all_strategies = set(strat_trades.keys()) | set(strat_opens.keys())
    for strat in all_strategies:
        ts = strat_trades.get(strat, [])
        wins = [t for t in ts if t["winner"]]
        long_pl  = sum(t["pnl_usd"] for t in ts if t["direction"] == "long")
        short_pl = sum(t["pnl_usd"] for t in ts if t["direction"] == "short")

        # Consecutive losses from end of list (most recent)
        ts_sorted = sorted(ts, key=lambda x: x.get("exit_time", ""), reverse=True)
        consec = 0
        for t in ts_sorted:
            if t["winner"]:
                break
            consec += 1

        # Open positions = total entries on this strategy minus those that
        # matched to a close (= len(ts), each completed trade consumed one
        # open). Negative would be weird; clamp to 0.
        opens_total      = strat_opens.get(strat, 0)
        opens_unmatched  = max(0, opens_total - len(ts))

        out[strat] = {
            "trades_7d":         len(ts),
            "open_positions_7d": opens_unmatched,
            "win_rate_7d":       round(len(wins) / len(ts), 3) if ts else 0.0,
            "pnl_usd_7d":        round(sum(t["pnl_usd"] for t in ts), 2),
            "trades_lifetime":   len(ts),
            "win_rate_lifetime": round(len(wins) / len(ts), 3) if ts else 0.0,
            "pnl_usd_lifetime":  round(sum(t["pnl_usd"] for t in ts), 2),
            "consecutive_losses": consec,
            "pnl_long_7d":  round(long_pl, 2),
            "pnl_short_7d": round(short_pl, 2),
        }
    return out


def compute_asset_stats(trades: list[dict]) -> dict:
    by_class = defaultdict(list)
    for t in trades:
        by_class[_asset_class(t["symbol"])].append(t)
    out = {}
    for cls, ts in by_class.items():
        wins = [t for t in ts if t["winner"]]
        out[cls] = {
            "trades_7d":   len(ts),
            "win_rate_7d": round(len(wins) / len(ts), 3) if ts else 0.0,
            "pnl_usd_7d":  round(sum(t["pnl_usd"] for t in ts), 2),
        }
    return out


def compute_fill_rate(orders: list[dict]) -> dict:
    """
    Per-strategy fill / cancel / reject stats — answers 'why didn't it fill'.

    LLM proposal 2026-05-11 (entry cancellations audit): breaks out
    canceled vs expired (DAY orders expiring at 20:00 UTC are different
    from manually-canceled / SL-triggered cancels). Plus tracks
    avg_minutes_to_cancel so we can see if cancels happen instantly
    (rejection-like) vs after sitting at limit for hours (limit too tight).

    v3.8.8 (2026-05-18): added 'other' status counter (held / pending /
    accepted / new / partially_filled) plus a 'sample_open_ids' list
    that surfaces up to 5 client_order_ids per strategy whose orders
    are still in non-terminal state. Senior PM has been flagging
    'fill_rate.unknown = 6 placed / 0 outcomes' for 3 days running —
    open orders sitting beyond their TIF window were undiagnosable
    without seeing the IDs. This adds operator visibility without
    changing aggregate behavior.
    """
    by_strat = defaultdict(lambda: defaultdict(int))
    cancel_durations: dict[str, list[float]] = defaultdict(list)
    open_samples: dict[str, list[str]] = defaultdict(list)
    open_symbols: dict[str, list[str]] = defaultdict(list)
    for o in orders:
        strat = _strategy_from_client_id(o.get("client_order_id", ""), o.get("symbol", ""))
        by_strat[strat]["placed"] += 1
        st = o.get("status", "unknown")
        if st == "filled":
            by_strat[strat]["filled"] += 1
        elif st == "expired":
            by_strat[strat]["expired"] += 1
            by_strat[strat]["canceled"] += 1   # legacy aggregate
        elif st == "canceled":
            by_strat[strat]["canceled"] += 1
            by_strat[strat]["manually_canceled"] += 1
        elif st == "rejected":
            by_strat[strat]["rejected"] += 1
        else:
            # Non-terminal state — held / pending / accepted / new /
            # partially_filled / done_for_day. These are the "ghost"
            # orders Senior PM has been calling out — they consume
            # buying-power without ever resolving to a P&L outcome.
            by_strat[strat]["other"] += 1
            by_strat[strat][f"open_status_{st}"] += 1
            cid = o.get("client_order_id") or ""
            sym = o.get("symbol") or ""
            if len(open_samples[strat]) < 5:
                # Truncate timestamp segment for readability — strategy +
                # symbol are the diagnostic signal.
                open_samples[strat].append(cid[:60])
                open_symbols[strat].append(sym)
        # Time-to-cancel: submitted_at -> canceled_at / expired_at
        if st in ("canceled", "expired"):
            try:
                sub = o.get("submitted_at") or o.get("created_at")
                end = o.get("canceled_at") or o.get("expired_at") or o.get("updated_at")
                if sub and end:
                    sub_dt = datetime.fromisoformat(sub.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    delta_min = (end_dt - sub_dt).total_seconds() / 60
                    if delta_min >= 0:
                        cancel_durations[strat].append(delta_min)
            except (ValueError, AttributeError):
                pass

    out = {}
    for strat, counts in by_strat.items():
        placed = counts["placed"]
        durations = cancel_durations.get(strat) or []
        # v3.11.3 part 2 (2026-05-30) — LLM proposal 2026-05-29:
        # "fill_rate.unknown 37% generates false 'limits too tight' alert
        # when in fact orders are open-GTC waiting for market." Compute
        # fill_rate_closed = filled / (filled + canceled + expired + rejected),
        # ignoring OPEN orders. This eliminates false alerts for GTC setups.
        # Keep legacy `fill_rate` for backward compat (callers consuming
        # the old key still work).
        filled_ct   = counts.get("filled", 0)
        canceled_ct = counts.get("canceled", 0)
        expired_ct  = counts.get("expired", 0)
        rejected_ct = counts.get("rejected", 0)
        open_pending = counts.get("other", 0)
        closed_total = filled_ct + canceled_ct + expired_ct + rejected_ct
        fill_rate_closed = round(filled_ct / closed_total, 3) if closed_total else None
        entry = {
            "placed":     placed,
            "filled":     filled_ct,
            "canceled":   canceled_ct,
            "expired":    expired_ct,
            "manually_canceled": counts.get("manually_canceled", 0),
            "rejected":   rejected_ct,
            "other":      open_pending,
            # Legacy: filled / placed (overcounts as denominator includes OPEN)
            "fill_rate":  round(filled_ct / placed, 3) if placed else 0.0,
            # v3.11.3: fill_rate ignoring open-GTC (true fill quality)
            "fill_rate_closed": fill_rate_closed,
            "open_pending":     open_pending,
            "avg_minutes_to_cancel": round(sum(durations) / len(durations), 1) if durations else None,
            "max_minutes_to_cancel": round(max(durations), 1) if durations else None,
        }
        # Surface non-terminal statuses for diagnostics
        for k, v in counts.items():
            if k.startswith("open_status_"):
                entry[k] = v
        if open_samples.get(strat):
            entry["sample_open_ids"]     = open_samples[strat]
            entry["sample_open_symbols"] = open_symbols[strat]
        out[strat] = entry
    return out


def compute_tp_hit_rate(orders: list[dict]) -> dict:
    """
    Per-strategy take-profit hit rate.

    For each TP-exit order (client_order_id prefix `exit-tp-`), attribute
    it to the entry strategy of the *most recent non-exit order on the
    same symbol* within the window. Then per strategy:

      tp_placed   — TP exits attempted
      tp_filled   — TP exits that actually filled (price reached target)
      tp_unfilled — TP exits canceled/expired/still-open
      tp_hit_rate — filled / placed

    Answers the LLM's diagnostic question: "when we placed a TP, how
    often did the market actually deliver?" A persistent low hit-rate
    means the static TP target is too aggressive vs realised price moves
    and the strategy should switch to trailing-stop or tighter target.

    NB: this metric only sees TP exits emitted with the `exit-tp-` prefix
    (today: options-exit-monitor). Stock/crypto exits routed through the
    Exit Handler routine are not yet tagged this way; they'll start
    contributing once that routine is updated. Until then, expect this
    dict to be sparse for the first ~week of data.
    """
    # symbol -> entry strategy of latest non-exit fill in window
    entry_strategy_by_symbol: dict[str, str] = {}
    for o in sorted(orders, key=lambda x: x.get("filled_at") or x.get("submitted_at") or ""):
        cid = (o.get("client_order_id") or "").lower()
        if cid.startswith("exit-"):
            continue
        sym = o.get("symbol", "")
        if not sym:
            continue
        entry_strategy_by_symbol[sym] = _strategy_from_client_id(
            o.get("client_order_id", ""), sym,
        )

    by_strat: dict[str, dict[str, int]] = defaultdict(
        lambda: {"placed": 0, "filled": 0, "unfilled": 0}
    )
    for o in orders:
        cid = (o.get("client_order_id") or "").lower()
        # Two patterns count as a TP order:
        #   1. our explicit 'exit-tp-' tagging (options-exit-monitor)
        #   2. Alpaca bracket-order TP child legs ('*_take_profit' suffix)
        is_tp = cid.startswith("exit-tp-") or cid.endswith("_take_profit")
        if not is_tp:
            continue
        sym = o.get("symbol", "")
        # NEW (LLM proposal 2026-05-11 TP attribution fix):
        # Prefer strategy embedded in exit client_order_id over per-symbol
        # lookup. Falls back to lookup only when parser returns 'unknown'
        # (legacy exits pre-2026-05-12).
        strat = _strategy_from_client_id(o.get("client_order_id", ""), sym)
        if strat == "unknown" and sym:
            strat = entry_strategy_by_symbol.get(sym, "unknown")
        by_strat[strat]["placed"] += 1
        if o.get("status") == "filled":
            by_strat[strat]["filled"] += 1
        else:
            by_strat[strat]["unfilled"] += 1

    out = {}
    for strat, counts in by_strat.items():
        placed = counts["placed"]
        out[strat] = {
            "tp_placed":   placed,
            "tp_filled":   counts["filled"],
            "tp_unfilled": counts["unfilled"],
            "tp_hit_rate": round(counts["filled"] / placed, 3) if placed else 0.0,
        }
    return out


# ─── RSI snapshot for LLM macro context (LLM proposal 2026-05-11) ───────────
#
# When the LLM asks "is strategy X dormant or broken?", it currently has to
# guess from "0 trades in 12 days". RSI snapshot answers the question
# directly: if BTC RSI(14) stayed between 35-65 the whole period,
# crypto-momentum/crypto-breakdown were CORRECTLY DORMANT (their thresholds
# are >70 / <30 by design). If RSI hit 75 and we have 0 entries, something
# IS broken.
#
# Cheap: 3 daily-bar fetches (SPY stock, BTC/USD crypto, ETH/USD crypto),
# each ~30 calendar days. Runs once per daily-learning cron (21:00 UTC).

def _rsi_from_closes(closes: list[float], period: int = 14) -> float | None:
    """Standard Wilder's RSI(14). Returns None if insufficient data."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    # Wilder's smoothing
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 1)


def _fetch_crypto_daily_closes(symbol: str, days: int = 30) -> list[float]:
    """Fetch crypto daily closes via Alpaca v1beta3."""
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return []
    start = (datetime.now(timezone.utc) - timedelta(days=days + 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = requests.get(
            "https://data.alpaca.markets/v1beta3/crypto/us/bars",
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            params={
                "symbols":   symbol,
                "timeframe": "1Day",
                "start":     start,
                "limit":     1000,
                "sort":      "asc",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        bars = (data.get("bars") or {}).get(symbol) \
            or (data.get("bars") or {}).get(symbol.replace("/", "")) \
            or []
        return [float(b.get("c", 0)) for b in bars if b.get("c")]
    except Exception as e:
        print(f"  RSI: crypto fetch {symbol} error: {e}")
        return []


def compute_rsi_snapshot() -> dict:
    """
    Per-symbol RSI(14) over last ~12 trading days. Reveals whether market
    has reached extremes that should have triggered strategies.

    Returns:
      {
        "SPY":     {today: 47.3, min_12d: 41.2, max_12d: 58.4, regime: "neutral"},
        "BTC/USD": {today: 52.1, min_12d: 48.0, max_12d: 61.2, regime: "neutral"},
        "ETH/USD": {today: 49.5, min_12d: 44.1, max_12d: 56.3, regime: "neutral"},
      }
    Regime: "overbought" (today >= 70), "oversold" (today <= 30),
            "neutral" otherwise. Per-symbol min/max over 12 days lets
            the LLM see if EVER hit a threshold (not just today).

    Returns {} if data unavailable (callers tolerate missing field).
    """
    try:
        # Lazy import — avoid circular if shared imports analyzer.
        sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
        from market_data import get_daily_bars  # noqa: E402
    except ImportError:
        return {}

    out: dict[str, dict] = {}

    # SPY via stock endpoint
    spy_bars = get_daily_bars("SPY", days=30)
    if spy_bars and spy_bars.get("close"):
        closes = spy_bars["close"][-15:]   # 15 closes = 14 deltas → RSI(14)
        rsi_today = _rsi_from_closes(closes)
        # Compute rolling RSI over last 12 trading days
        rsi_series = []
        for i in range(max(15, len(closes) - 12), len(closes) + 1):
            window = closes[max(0, i - 15):i]
            r = _rsi_from_closes(window)
            if r is not None:
                rsi_series.append(r)
        if rsi_today is not None:
            out["SPY"] = {
                "today":  rsi_today,
                "min_12d": round(min(rsi_series), 1) if rsi_series else rsi_today,
                "max_12d": round(max(rsi_series), 1) if rsi_series else rsi_today,
                "regime": "overbought" if rsi_today >= 70 else
                          "oversold"   if rsi_today <= 30 else "neutral",
            }

    # Crypto via v1beta3
    for sym in ("BTC/USD", "ETH/USD"):
        closes = _fetch_crypto_daily_closes(sym, days=30)
        if len(closes) < 15:
            continue
        closes = closes[-15:]
        rsi_today = _rsi_from_closes(closes)
        rsi_series = []
        for i in range(max(15, len(closes) - 12), len(closes) + 1):
            window = closes[max(0, i - 15):i]
            r = _rsi_from_closes(window)
            if r is not None:
                rsi_series.append(r)
        if rsi_today is not None:
            out[sym] = {
                "today":  rsi_today,
                "min_12d": round(min(rsi_series), 1) if rsi_series else rsi_today,
                "max_12d": round(max(rsi_series), 1) if rsi_series else rsi_today,
                "regime": "overbought" if rsi_today >= 70 else
                          "oversold"   if rsi_today <= 30 else "neutral",
            }
    return out


# ─── Equity-gap + ETH-oversold alerts (v3.8.9, 2026-05-21) ─────────────────


def compute_equity_gap_alert(today_stats, prev_equity):
    """
    LLM-flagged 2026-05-18: "Analyzer ślepy na źródło returnu". When
    daily equity moves > $500 in absolute value but cumulative_trades=0,
    flag the gap so operator + LLM can investigate.

    Returns:
      {
        "delta_usd":           +/-N,
        "prev_equity":         95387.0,
        "current_equity":      94800.0,
        "attributed_trades":   0,
        "severity":            "WARN" | "INFO",
        "message":             "Equity dropped $587 with 0 attributed trades…"
      }
    OR None when no gap (delta < $500 OR attributed trades > 0).
    """
    try:
        eq = float(today_stats.get("equity", 0))
        prev = float(prev_equity or 0)
    except (TypeError, ValueError):
        return None
    if eq <= 0 or prev <= 0:
        return None

    delta = eq - prev
    if abs(delta) < 500:
        return None

    attributed = int(today_stats.get("cumulative_trades", 0))
    if attributed > 0:
        # Trades closed and attributed — gap explained by strategy P&L.
        return None

    severity = "WARN" if abs(delta) >= 1000 else "INFO"
    direction = "increased" if delta > 0 else "dropped"
    return {
        "delta_usd":         round(delta, 2),
        "prev_equity":       round(prev, 2),
        "current_equity":    round(eq, 2),
        "attributed_trades": attributed,
        "severity":          severity,
        "message": (
            f"Equity {direction} ${abs(delta):,.0f} (${prev:,.0f} → ${eq:,.0f}) "
            f"with 0 attributed closed trades. Likely sources: open-position "
            f"mark-to-market, unfilled LIMITs, allocator order side-effects, "
            f"or stale attribution. Cross-check positions tab + recent orders."
        ),
    }


def compute_oversold_alerts(rsi_snapshot: dict, threshold: float = 30.0) -> list[dict]:
    """
    LLM-flagged 2026-05-18: flag crypto RSI < 30 as potential pre-signal.
    Returns one alert per oversold symbol from rsi_snapshot.

    Symmetric: also flags overbought (RSI > 75) as fade-the-trend warning
    for short-side strategies (relevant to options-momentum PUT setups).
    """
    alerts: list[dict] = []
    if not rsi_snapshot:
        return alerts
    for sym, rsi_data in rsi_snapshot.items():
        rsi_today = rsi_data.get("today")
        if rsi_today is None:
            continue
        if rsi_today <= threshold:
            alerts.append({
                "symbol":   sym,
                "rsi":      rsi_today,
                "regime":   "oversold",
                "kind":     "pre-signal",
                "message": (
                    f"{sym} RSI={rsi_today:.1f} ≤ {threshold:.0f} — deep oversold. "
                    f"Statistically high bounce probability. "
                    f"crypto-momentum / momentum-long should watch for entry."
                ),
            })
        elif rsi_today >= 75:
            alerts.append({
                "symbol":   sym,
                "rsi":      rsi_today,
                "regime":   "overbought",
                "kind":     "fade-risk",
                "message": (
                    f"{sym} RSI={rsi_today:.1f} ≥ 75 — overbought, fade-the-trend "
                    f"risk for new long entries. Options PUT entries blocked "
                    f"by v3.8.6 regime gate; broader long-side caution warranted."
                ),
            })
    return alerts


# ─── Position audit (2026-05-13 — proposal from 2026-05-10) ─────────────────

def compute_position_audit(positions: list[dict], orders: list[dict]) -> list[dict]:
    """
    Flag positions that should have exit orders but don't.

    Per LLM Senior PM proposal 2026-05-10 (revisited 2026-05-13):
      "(pnl_pct >= tp_threshold AND no exit order) OR
       (pnl_pct <= sl_threshold AND no exit order)"

    Thresholds (configurable later via aggressive_profile.json):
      - Options: TP +80% (entry*1.80), SL -50% (entry*0.50), emergency -12%
      - Stocks/ETFs/crypto: TP +10%, SL -8%, emergency -12%

    Returns list of suspect positions:
      [{symbol, asset_class, side, pl_pct, market_value, reason, has_exit_order, ...}]

    Empty list when nothing suspicious — Senior PM ignores in payload.
    Non-empty rationale.md gets a 'position-audit:' line per suspect.
    """
    if not positions:
        return []

    # Build symbol → "has open exit order" map by scanning open orders
    open_exit_symbols = set()
    for o in orders:
        if o.get("status") not in ("new", "open", "accepted", "pending_new", "pending_replace"):
            continue
        cid = (o.get("client_order_id") or "").lower()
        if cid.startswith("exit-"):
            open_exit_symbols.add(o.get("symbol", ""))

    audit: list[dict] = []
    for p in positions:
        sym       = p.get("symbol", "")
        ac        = p.get("asset_class") or _asset_class(sym)
        side      = p.get("side", "long")
        try:
            pl_pct = float(p.get("unrealized_plpc", 0) or 0)
        except (TypeError, ValueError):
            pl_pct = 0.0
        mv = float(p.get("market_value", 0) or 0)

        # Per-asset-class thresholds
        if ac == "us_option":
            tp_thresh, sl_thresh, em_thresh = 0.80, -0.50, -0.12
        else:
            tp_thresh, sl_thresh, em_thresh = 0.10, -0.08, -0.12

        has_exit = sym in open_exit_symbols

        suspect = False
        reason  = ""
        if pl_pct >= tp_thresh and not has_exit:
            suspect = True
            reason  = f"pl {pl_pct:+.1%} >= TP {tp_thresh:+.0%} but NO exit order"
        elif pl_pct <= em_thresh and not has_exit:
            suspect = True
            reason  = f"pl {pl_pct:+.1%} <= emergency {em_thresh:+.0%} but NO exit order"
        elif pl_pct <= sl_thresh and not has_exit:
            suspect = True
            reason  = f"pl {pl_pct:+.1%} <= SL {sl_thresh:+.0%} but NO exit order"

        if suspect:
            audit.append({
                "symbol":          sym,
                "asset_class":     ac,
                "side":            side,
                "pl_pct":          round(pl_pct, 4),
                "market_value":    round(mv, 2),
                "has_exit_order":  has_exit,
                "reason":          reason,
            })
    return audit


# ─── State I/O ───────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"  state.json corrupted ({e}); starting fresh")
        return {}


def save_state(state: dict) -> None:
    # v3.8.6 (2026-05-16): refresh legacy daily_peak from runtime_state so
    # state.json doesn't drift to stale dates. peak_tracker.py reads from
    # runtime_state.json::intraday_governor at runtime, but state.json's
    # daily_peak field was a pre-v3.5 snapshot that nothing kept updated —
    # we observed dates 2 days behind. Back-compat readers (LLM payload,
    # heuristic_proposals lookup) get current data now.
    try:
        try:
            from runtime_state import read_section
        except ImportError:
            import sys, os as _os
            sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
            from runtime_state import read_section  # type: ignore
        ig = read_section("intraday_governor") or {}
        if ig:
            state["daily_peak"] = {
                "date":          ig.get("date"),
                "peak_pl_usd":   ig.get("intraday_peak_pnl"),
                "peak_pl_pct":   ig.get("intraday_peak_pnl_pct"),
                "peak_at":       ig.get("peak_at"),
                "peak_equity":   ig.get("intraday_peak_equity"),
                "current_pl_usd":   ig.get("current_intraday_pnl"),
                "current_equity":   ig.get("current_equity"),
                "retrace_from_peak": ig.get("giveback_pct_of_peak"),
                "verdict":          ig.get("pnl_state"),
                "verdict_at":       ig.get("last_update_at"),
                "alerts_sent":      ig.get("alerts_sent") or {},
                "source":           "runtime_state.intraday_governor (v3.8.6 sync)",
            }
    except Exception as e:
        print(f"  daily_peak sync skipped ({type(e).__name__}: {e})")

    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _tail_rationale(n: int = 20) -> list[str]:
    """Return last N bullet entries from rationale.md (for LLM context)."""
    try:
        with open(RATIONALE_PATH) as f:
            content = f.read()
    except FileNotFoundError:
        return []
    bullets = [ln.lstrip("- ").strip() for ln in content.splitlines() if ln.startswith("- ")]
    return bullets[-n:] if len(bullets) > n else bullets


def append_rationale(lines: list[str]) -> None:
    if not lines:
        return
    blob = "\n".join(f"- {ln}" for ln in lines) + "\n\n"
    try:
        with open(RATIONALE_PATH) as f:
            existing = f.read()
    except FileNotFoundError:
        existing = "# Learning Loop — Rationale Log\n\n"

    # Insert new entries after the title block (top of file)
    if "## " in existing:
        head, _, body = existing.partition("## ")
        new_content = head + blob + "## " + body
    else:
        new_content = existing + blob

    with open(RATIONALE_PATH, "w") as f:
        f.write(new_content)


def write_history_report(date_iso: str, today_stats: dict,
                          new_state: dict, rationale: list[str]) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, f"{date_iso}.md")
    eq      = today_stats.get("equity", 0)
    cum_pl  = new_state.get("cumulative", {}).get("total_pnl_usd", 0)
    starting = new_state.get("cumulative", {}).get("starting_equity") or eq
    roi = ((eq - starting) / starting * 100) if starting else 0
    lines = [
        f"# Learning report — {date_iso}",
        "",
        f"**Equity:** ${eq:,.2f} (starting: ${starting:,.2f}; cumulative ROI: {roi:+.2f}%)",
        f"**Cumulative trades:** {new_state.get('cumulative', {}).get('total_trades', 0)}",
        f"**Cumulative P&L:** ${cum_pl:,.2f}",
        "",
        "## Rationale of changes today",
        "",
    ]
    for r in rationale:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## Per-strategy summary")
    lines.append("")
    lines.append("| Strategy | Trades 7d | Win rate | P&L $ | Multiplier | Enabled | Side bias |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, s in new_state.get("strategies", {}).items():
        lines.append(
            f"| {name} | {s.get('trades_7d', 0)} | "
            f"{s.get('win_rate_7d', 0)*100:.0f}% | "
            f"${s.get('pnl_usd_7d', 0):,.2f} | "
            f"{s.get('size_multiplier', 1.0):.2f} | "
            f"{'yes' if s.get('enabled', True) else 'NO'} | "
            f"{s.get('side_bias') or '-'} |"
        )
    lines.append("")
    lines.append("## Asset class breakdown")
    lines.append("")
    lines.append("| Class | Trades | Win rate | P&L $ |")
    lines.append("|---|---|---|---|")
    for cls, s in new_state.get("asset_classes", {}).items():
        lines.append(f"| {cls} | {s.get('trades_7d', 0)} | "
                     f"{s.get('win_rate_7d', 0)*100:.0f}% | "
                     f"${s.get('pnl_usd_7d', 0):,.2f} |")
    lines.append("")

    # Take-profit hit rate (10-day data collect for trailing-stop decision)
    tp_hr = today_stats.get("tp_hit_rate", {})
    if tp_hr:
        lines.append("## TP hit rate (per strategy, 24h window)")
        lines.append("")
        lines.append("> Tracking how often static take-profit targets actually filled.")
        lines.append("> If hit_rate stays low (< 30%) after 10 days, switch to trailing stop.")
        lines.append("")
        lines.append("| Strategy | TP placed | Filled | Unfilled | Hit rate |")
        lines.append("|---|---|---|---|---|")
        for strat, s in tp_hr.items():
            lines.append(
                f"| {strat} | {s['tp_placed']} | {s['tp_filled']} | "
                f"{s['tp_unfilled']} | {s['tp_hit_rate']*100:.0f}% |"
            )
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


# ─── Challenger filter (round-3-failed fallback) ─────────────────────────────

def _apply_challenger_filter(draft1: dict, critique: dict) -> dict:
    """
    Apply Challenger's REJECTED verdicts to Senior PM's draft 1 when
    round 3 (Senior PM revision) is unavailable.

    This is a minimal safety net — we drop overrides + heuristic
    proposals that the Challenger explicitly REJECTED, but we don't
    try to apply MODIFIED suggestions (that's Senior PM's job in
    round 3, and without their judgement we play conservative).

    Returns a copy of `draft1` with rejected items removed.
    """
    if not isinstance(draft1, dict) or not isinstance(critique, dict):
        return draft1 or {}

    log = critique.get("challenge_log") or []
    rejected_refs: set[str] = {
        (entry.get("original_proposal") or "").strip().lower()
        for entry in log
        if isinstance(entry, dict) and entry.get("decision") == "REJECTED"
    }
    rejected_refs.discard("")
    if not rejected_refs:
        return draft1

    filtered = json.loads(json.dumps(draft1))  # deep copy

    # Drop matching strategy overrides. Match is substring against
    # `original_proposal` ref (Challenger uses free-form strings like
    # "state_overrides.strategies.options-momentum.size_multiplier 1.0->0.6").
    strats = (filtered.get("state_overrides") or {}).get("strategies") or {}
    for strat_name in list(strats.keys()):
        for ref in rejected_refs:
            if strat_name.lower() in ref:
                del strats[strat_name]
                break

    # Drop matching heuristic proposals (match against title)
    proposals = filtered.get("new_heuristic_proposals") or []
    kept = []
    for p in proposals:
        if not isinstance(p, dict):
            kept.append(p)
            continue
        title = (p.get("title") or "").strip().lower()
        if not title:
            kept.append(p)
            continue
        if any(title in ref or ref in title for ref in rejected_refs):
            continue   # rejected
        kept.append(p)
    filtered["new_heuristic_proposals"] = kept

    return filtered


# ─── Main ────────────────────────────────────────────────────────────────────

def run():
    now = datetime.now(timezone.utc)
    date_iso = now.date().isoformat()
    print(f"\n[{now.isoformat()}] === DAILY LEARNING LOOP ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: brak ALPACA_API_KEY / ALPACA_SECRET_KEY")
        sys.exit(1)

    # Window: last 24 hours.
    after = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"  Fetching orders since {after}...")
    orders = get_orders_window(after)
    print(f"  Orders in window: {len(orders)}")

    account = get_account()
    equity  = float(account.get("equity", 0))
    print(f"  Equity: ${equity:,.2f}")

    trades = reconstruct_trades(orders)
    print(f"  Reconstructed trades: {len(trades)}")
    for t in trades:
        icon = "✅" if t["winner"] else "❌"
        print(f"    {icon} {t['symbol']:8s} {t['direction']:5s} "
              f"{t['pnl_pct']:+.1f}% ${t['pnl_usd']:+.2f} "
              f"({t['hold_hours']:.1f}h) [{t['strategy']}]")

    # Today stats (input to adapter).
    # Note 2026-05-13: many fields are 24h-window scoped — see `window_hours`
    # field below. State.json holds lifetime ground truth — see
    # `lifetime_from_state` field. This eliminates the Challenger Q2 critique
    # (Senior PM round 1 confused 24h with lifetime).
    open_positions_snapshot = []
    try:
        from risk_guards import get_open_positions
        open_positions_snapshot = get_open_positions() or []
    except Exception as _e:
        print(f"  open_positions snapshot failed: {_e}")

    # Pull lifetime numbers from prior state for the LLM payload.
    _prior_state = load_state()
    lifetime_from_state = {}
    for sname, sdata in (_prior_state.get("strategies") or {}).items():
        if isinstance(sdata, dict):
            lifetime_from_state[sname] = {
                "trades_lifetime":      sdata.get("trades_lifetime", 0),
                "pnl_usd_lifetime":     sdata.get("pnl_usd_lifetime", 0),
                "consecutive_losses":   sdata.get("consecutive_losses", 0),
                "win_rate_lifetime":    sdata.get("win_rate_lifetime"),
            }

    # Position audit — flag positions that should have exit orders but don't.
    # See compute_position_audit below.
    position_audit = compute_position_audit(open_positions_snapshot, orders)

    rsi_snapshot = compute_rsi_snapshot()

    today_stats = {
        "as_of":             date_iso,
        "window_hours":      24,                             # all *_24h fields scoped here
        "equity":            equity,
        "starting_equity":   float(account.get("last_equity", equity) or equity),
        "by_strategy":       compute_strategy_stats(trades, orders, equity),
        "by_asset_class":    compute_asset_stats(trades),
        "by_source":         {},   # placeholder for future per-source attribution
        "fill_rate":         compute_fill_rate(orders),
        "tp_hit_rate":       compute_tp_hit_rate(orders),  # 10-day data-collect for trailing-stop decision
        "rsi_snapshot":      rsi_snapshot,                  # macro context for LLM "dormant vs broken" check
        # 2026-05-13 fixes:
        "open_positions":    open_positions_snapshot,         # full portfolio snapshot — fills "60% blind spot"
        "lifetime_from_state": lifetime_from_state,           # ground truth vs 24h window
        "position_audit":    position_audit,                  # SUSPECT positions missing exit orders
        "cumulative_trades": len(trades),
        "cumulative_pnl_usd": round(sum(t["pnl_usd"] for t in trades), 2),
    }

    # v3.8.9 (2026-05-21): equity-gap + oversold alerts. Both surface to
    # LLM payload + rationale.md so Senior PM has visibility into
    # "analyzer ślepy na źródło returnu" (LLM-flagged 2026-05-19).
    prior_state_for_alerts = load_state()
    prev_eq_for_alert = float(prior_state_for_alerts.get("peak_equity") or 0)
    equity_gap = compute_equity_gap_alert(today_stats, prev_eq_for_alert)
    if equity_gap:
        today_stats["equity_gap_alert"] = equity_gap
    oversold = compute_oversold_alerts(rsi_snapshot)
    if oversold:
        today_stats["rsi_alerts"] = oversold

    # Load prior state, run deterministic adapter
    old_state = load_state()
    new_state, rationale = adapt(old_state, today_stats)

    # ── LLM augmentation — 3-round dialog (fail-soft) ──────────────────────
    #
    #   Round 1: Senior PM produces draft analysis
    #   Round 2: Challenger critiques the draft
    #   Round 3: Senior PM revises with FINAL WORD, reading the critique
    #
    # Fail-soft cascade:
    #   - Round 1 fails → keep deterministic baseline only
    #   - Round 2 fails → apply Round 1 unfiltered (no challenge happened)
    #   - Round 3 fails → apply Round 1 with Challenger filter
    #     (drop any state_override the Challenger marked REJECTED)
    #
    # LLM is strictly additive — never blocks the loop.
    target_branch = os.environ.get("GITHUB_REF_NAME") or _git_current_branch()
    base_payload = {
        "today_stats":             today_stats,
        "proposed_state":          new_state,
        "deterministic_rationale": rationale,
        "recent_rationale_tail":   _tail_rationale(20),
        "target_branch":           target_branch,
    }

    # v3.8.5 (2026-05-16): Silent-day optimization. Skip Challenger + Revise
    # (rounds 2+3) when the day has 0 fills + 0 new heuristic proposals from
    # draft1 — no material content for Challenger to challenge, draft1 is
    # safe to apply unfiltered. Saves 2/3 of routine budget on quiet days.
    # Anthropic uses rolling 24h window so saving calls protects the
    # next day's budget too.
    cumulative_trades = int((today_stats or {}).get("cumulative_trades", 0))
    trades_24h_total  = sum(
        int(s.get("trades_7d", 0)) for s in (today_stats.get("strategies") or {}).values()
    )
    is_silent_day = (cumulative_trades == 0 and trades_24h_total == 0)
    if is_silent_day:
        print(f"\n  [Silent-day optimization] cumulative_trades=0 + trades_24h=0 — "
              f"will skip Challenger/Revise to conserve Anthropic budget.")

    print("\n  [Round 1/3] Calling Senior PM for draft analysis...")
    draft1 = call_senior_pm_round1(base_payload)

    critique = None
    llm_resp = None  # final round-3 (or fall-back round-1) output applied below

    if draft1 is None:
        print("  [Round 1/3] Senior PM unavailable — skipping rounds 2 & 3, "
              "falling back to deterministic baseline only")
    elif is_silent_day:
        # Silent day → apply draft1 directly; no Challenger needed.
        # (Acceptable risk: draft1 has no human-flagged edge cases.
        # If a non-trivial proposal lands, daily-learning next day can
        # still run full 3-round dialog.)
        print("  [Round 1/3] Silent day — applying Senior PM draft 1 directly, "
              "skipping rounds 2+3 to conserve budget")
        llm_resp = draft1
    else:
        print(f"  [Round 1/3] Senior PM draft received "
              f"(confidence={draft1.get('confidence', '?')}, "
              f"{len((draft1.get('state_overrides') or {}).get('strategies') or {})} strategy overrides, "
              f"{len(draft1.get('new_heuristic_proposals') or [])} heuristic proposals)")

        print("\n  [Round 2/3] Calling Challenger for critique...")
        critique = call_challenger({
            "today_stats":     today_stats,
            "senior_pm_draft": draft1,
            "target_branch":   target_branch,
        })

        if critique is None:
            print("  [Round 2/3] Challenger unavailable — skipping round 3, "
                  "applying Senior PM's draft 1 unfiltered")
            llm_resp = draft1
        else:
            cs = critique.get("stats") or {}
            print(f"  [Round 2/3] Challenger critique received "
                  f"(reviewed={cs.get('total_proposals_reviewed', '?')}, "
                  f"survived={cs.get('survived', '?')}, "
                  f"modified={cs.get('modified', '?')}, "
                  f"rejected={cs.get('rejected', '?')}, "
                  f"confidence={critique.get('confidence_in_critique', '?')})")

            print("\n  [Round 3/3] Calling Senior PM for FINAL revision...")
            revised = call_senior_pm_revise({
                "today_stats":         today_stats,
                "your_previous_draft": draft1,
                "challenger_critique": critique,
                "target_branch":       target_branch,
            })

            if revised is None:
                print("  [Round 3/3] Senior PM revision unavailable — applying "
                      "draft 1 with Challenger REJECTED filter")
                llm_resp = _apply_challenger_filter(draft1, critique)
            else:
                rev_log = revised.get("revision_log") or []
                print(f"  [Round 3/3] Senior PM revision received "
                      f"(confidence={revised.get('confidence', '?')}, "
                      f"{len(rev_log)} revision_log entries)")
                llm_resp = revised

    llm_narrative_lines: list[str] = []

    if llm_resp:
        # v3.22.1 — record successful LLM run so the consecutive_failures
        # counter resets and any pending REVIEW_LLM_OUTAGE doesn't keep
        # re-enqueuing.
        try:
            sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
            from llm_availability import record_run as _llm_record_run  # noqa: E402
            _llm_record_run(success=True, reason="senior_pm_ok")
        except Exception as _e:
            print(f"  llm_availability.record_run failed: {_e}")
        # Apply overrides (whitelist-enforced)
        overrides = llm_resp.get("state_overrides") or {}
        new_state, applied = safe_apply_overrides(new_state, overrides)
        if applied:
            print("  LLM overrides applied:")
            for line in applied:
                print(f"    {line}")
            llm_narrative_lines.extend(applied)

        # Anti-overfitting validation (spec §G): block aggressive parameter
        # changes that aren't backed by enough trades. The validator returns
        # a merged state where rejected fields are reset to old values. Any
        # rejections are logged into rationale.md so future runs can see
        # WHY the loop didn't move size/disable/bias even though the LLM
        # proposed it.
        try:
            from validation import validate_adaptation  # noqa: E402
            old_state_for_check = json.loads(json.dumps(state))  # the pre-adapter state
            v_result = validate_adaptation(
                old_state=old_state_for_check,
                new_state=new_state,
                today_stats=today_stats,
            )
            new_state = v_result["validated_state"]
            if v_result["accepted"]:
                print("  Validator accepted:")
                for line in v_result["accepted"]:
                    print(f"    · {line}")
                    llm_narrative_lines.append(f"{date_iso} · validator accept: {line}")
            if v_result["rejected"]:
                print("  Validator REJECTED (sample-size or step-bound):")
                for entry in v_result["rejected"]:
                    msg = (f"{entry['strategy']}.{entry['field']} "
                           f"{entry['old']} -> {entry['new']} :: {entry['reason']}")
                    print(f"    · {msg}")
                    llm_narrative_lines.append(f"{date_iso} · validator reject: {msg}")
            if v_result.get("second_run"):
                llm_narrative_lines.append(
                    f"{date_iso} · validator: second daily run blocked — kept old state"
                )
        except Exception as e:
            print(f"  Validator unavailable ({type(e).__name__}: {e}); applying raw overrides")

        # Append narrative
        narr = llm_resp.get("narrative") or ""
        regime = llm_resp.get("regime_assessment", "?")
        edge = llm_resp.get("edge_assessment", "")
        confidence = llm_resp.get("confidence", "?")
        if narr:
            llm_narrative_lines.insert(
                0,
                f"{date_iso} · LLM[{confidence}] regime={regime}: {narr.strip()}"
            )
        if edge:
            llm_narrative_lines.append(f"{date_iso} · LLM edge: {edge.strip()}")

        # Surface Challenger stats + Senior PM revision_log so the dialog is
        # auditable in rationale.md / history report.
        if critique:
            cs = critique.get("stats") or {}
            llm_narrative_lines.append(
                f"{date_iso} · Challenger reviewed "
                f"{cs.get('total_proposals_reviewed', 0)} proposals: "
                f"{cs.get('survived', 0)} survived, "
                f"{cs.get('modified', 0)} modified, "
                f"{cs.get('rejected', 0)} rejected "
                f"(confidence={critique.get('confidence_in_critique', '?')})"
            )
            for q in (critique.get("open_questions_for_senior_pm") or [])[:3]:
                llm_narrative_lines.append(f"{date_iso} · Challenger Q: {q}")

        for entry in (llm_resp.get("revision_log") or [])[:10]:
            if not isinstance(entry, dict):
                continue
            llm_narrative_lines.append(
                f"{date_iso} · revision: "
                f"[{entry.get('your_disposition', '?')}] "
                f"{entry.get('original_proposal', '?')} -> "
                f"{entry.get('final_value', '?')} "
                f"({entry.get('reasoning', '')})"
            )

        # Route heuristic proposals into the three-lane architecture:
        #   Lane 1 (state_overrides) — already applied above
        #   Lane 2 (auto_pr)         — create a PR for adapter.py heuristics
        #   Lane 3 (backlog)         — append structured entry to
        #                              heuristic_proposals.md
        # See STRATEGY.md §5.6 and learning-loop/lane2_pr.py for details.
        proposals = llm_resp.get("new_heuristic_proposals") or []
        if proposals:
            base_branch = (
                os.environ.get("GITHUB_REF_NAME")
                or _git_current_branch()
                or "main"
            )
            try:
                routed = route_proposals(proposals, base_branch=base_branch)
            except Exception as e:
                # Routing should never crash the daily run — fall back to
                # legacy queue so proposals aren't silently lost.
                print(f"  Lane router error ({type(e).__name__}: {e}); "
                      f"falling back to flat queue")
                routed = {"auto_pr_attempted": False, "auto_pr_url": None,
                          "backlog_added": append_heuristic_proposals(
                              [str(p) for p in proposals], HEURISTIC_PROPOSALS_PATH),
                          "rejected": []}

            if routed.get("auto_pr_url"):
                line = (f"  Lane 2 PR opened: {routed['auto_pr_url']}")
                print(line)
                llm_narrative_lines.append(
                    f"{date_iso} · LLM auto-PR: {routed['auto_pr_url']}"
                )
                # Email the operator so the PR doesn't sit unnoticed
                try:
                    sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
                    from notify import notify_pr_open  # noqa: E402
                    title = next((p.get("title", "(no title)") for p in proposals
                                  if isinstance(p, dict) and p.get("lane") == "auto_pr"),
                                 "(no title)")
                    risk = next((p.get("risk", "?") for p in proposals
                                 if isinstance(p, dict) and p.get("lane") == "auto_pr"),
                                "?")
                    notify_pr_open(routed["auto_pr_url"], title, "auto_pr", risk)
                except Exception as e:
                    print(f"  notify_pr_open failed: {e}")
            elif routed.get("auto_pr_attempted"):
                print(f"  Lane 2: auto-PR attempted but failed — see log; "
                      f"proposal moved to backlog")
            if routed.get("backlog_added"):
                print(f"  Lane 3: queued {routed['backlog_added']} proposal(s) "
                      f"-> heuristic_proposals.md")
            for r in routed.get("rejected", []):
                print(f"  proposal rejected: {r}")

    else:
        llm_narrative_lines.append(
            f"{date_iso} · LLM unavailable (skipped) — deterministic adapter only"
        )
        # v3.22.1 (2026-06-07) — record LLM availability + escalate to
        # operator action queue after 2 consecutive failures. NEVER
        # auto-clears the LLM override lock (operator-only).
        try:
            sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
            from llm_availability import record_run as _llm_record_run  # noqa: E402
            _llm_record_run(success=False, reason="senior_pm_unavailable")
        except Exception as _e:
            print(f"  llm_availability.record_run failed: {_e}")

    # Merge deterministic + LLM rationale into one log entry block
    full_rationale = llm_narrative_lines + rationale

    # Position audit findings → rationale (so operator + future LLM see them)
    for s in (today_stats.get("position_audit") or []):
        full_rationale.append(
            f"{date_iso} · position-audit: {s['symbol']} {s['reason']} "
            f"(mv=${s['market_value']:.0f})"
        )

    # v3.8.9 (2026-05-21): equity-gap + RSI alerts → rationale
    eg = today_stats.get("equity_gap_alert")
    if eg:
        full_rationale.append(
            f"{date_iso} · equity-gap [{eg['severity']}]: {eg['message']}"
        )
    for a in (today_stats.get("rsi_alerts") or []):
        full_rationale.append(
            f"{date_iso} · rsi-alert [{a['regime']}]: {a['message']}"
        )

    # Peak-tracker snapshot → rationale (so weekly retro sees intraday volatility)
    try:
        from peak_tracker import get_peak, summarize as _peak_summary
        p = get_peak()
        if p and p.get("peak_pl_usd", 0) >= 500:   # only log meaningful peaks
            full_rationale.append(
                f"{date_iso} · peak-tracker: {_peak_summary(p)}"
            )
    except Exception:
        pass

    # Lifetime peak_equity persistence (v3.0 TODO #1, 2026-05-14):
    # max_drawdown_guard reads state['peak_equity'] as the baseline for
    # -12% defensive / -20% full-stop thresholds. Previously this key was
    # never written, so the guard fell back to acct.last_equity (yesterday's
    # close) — a fast moving baseline that masks real lifetime drawdowns.
    # Update each daily-learning run: peak_equity = max(prior, today's equity).
    try:
        today_eq = float(account.get("equity") or 0)
        prior_peak = float(old_state.get("peak_equity") or 0)
        new_peak = max(prior_peak, today_eq)
        if new_peak > 0:
            new_state["peak_equity"] = new_peak
            if new_peak > prior_peak + 0.01:
                full_rationale.append(
                    f"{date_iso} · peak_equity advanced ${prior_peak:,.0f} -> ${new_peak:,.0f}"
                )
    except Exception:
        pass

    save_state(new_state)
    append_rationale(full_rationale)
    write_history_report(date_iso, today_stats, new_state, full_rationale)

    # ── Account-Aware Capital Deployment (v3.1 NEW 2026-05-12) ─────────
    # Post-learning-loop hook: compute target allocation for next trading
    # day, save plan to learning-loop/allocations/<date>.json. Auto-exec
    # gated by config.auto_execute_rebalance (default OFF — plan-only).
    try:
        sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
        from allocator import AccountAwareAllocator  # noqa: E402
        print("\n  [allocator] computing daily allocation plan...")
        alloc = AccountAwareAllocator()
        plan = alloc.compute_daily_plan(today_stats=today_stats,
                                          new_state=new_state)
        plan_path = alloc.save_plan(plan, date_iso)
        if plan_path:
            print(f"  [allocator] plan saved: {os.path.basename(plan_path)}")
        # Summary line
        actionable = [o for o in plan.get("rebalance_orders", [])
                      if o.get("action") != "HOLD"]
        print(f"  [allocator] regime={plan.get('market_regime')}, "
              f"invested_before={plan.get('invested_ratio_before'):.2%}, "
              f"invested_target={plan.get('invested_ratio_after_target'):.2%}, "
              f"orders={len(actionable)} actionable, "
              f"reason: {plan.get('allocation_reason', '?')}")
        # Append top 3 order summaries to rationale
        if actionable:
            for o in sorted(actionable, key=lambda x: abs(x.get('delta', 0)), reverse=True)[:3]:
                full_rationale.append(
                    f"{date_iso} · allocator: {o['action']} {o['symbol']} "
                    f"${o.get('delta', 0):+.0f} ({o.get('reason', '')})"
                )
        # Email the plan to operator (always, regardless of auto-exec).
        # Fail-soft: don't break learning loop if email backend is down.
        try:
            sys.path.insert(0, os.path.join(LEARNING_DIR, "..", "shared"))
            from notify import notify_allocation_plan
            notify_allocation_plan(plan)
        except Exception as ne:
            print(f"  [allocator] email_plan skipped ({type(ne).__name__}: {ne})")
        if alloc.cfg.get("auto_execute_rebalance", False):
            print("  [allocator] auto_execute_rebalance=true — invoking execute_orders()")
            exec_results = alloc.execute_orders(plan["rebalance_orders"])
            try:
                from notify import notify_allocation_execution
                notify_allocation_execution(plan.get("date", date_iso), exec_results)
            except Exception as ne:
                print(f"  [allocator] email_exec skipped ({type(ne).__name__}: {ne})")
    except Exception as e:
        print(f"  [allocator] error ({type(e).__name__}: {e}) — skipped, learning loop continues")

    print("\n  Rationale combined (LLM + deterministic):")
    for r in full_rationale:
        print(f"    · {r}")
    print(f"\n  Wrote: state.json, history/{date_iso}.md, rationale.md")
    print(f"  Strategies in state: {len(new_state.get('strategies', {}))}")
    print(f"  Workflow will commit + push these files back to main.")


if __name__ == "__main__":
    run()

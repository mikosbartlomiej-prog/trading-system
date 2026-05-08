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
    call_routine, safe_apply_overrides, append_heuristic_proposals,
    route_proposals,
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

def _strategy_from_client_id(client_order_id: str, symbol: str = "") -> str:
    """
    client_order_id format set in shared/alpaca_orders.py:
       "<strategy>-<symbol_clean>-<HHMMSSmmm>"
    where symbol_clean is the symbol with '/' stripped.
    Strategy names may contain hyphens (e.g. "momentum-long"), so we
    can't simply split on '-'. We locate the symbol marker and take
    everything before it.
    """
    if not client_order_id:
        return "unknown"
    if symbol:
        sym_clean = symbol.replace("/", "")
        marker = f"-{sym_clean}-"
        idx = client_order_id.find(marker)
        if idx > 0:
            return client_order_id[:idx]
    # Fallback: strip last 2 segments (timestamp + symbol)
    parts = client_order_id.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-2])
    return parts[0] if parts else "unknown"


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
    Detect close orders. Two patterns:

    1. Explicit tagging by exit-monitor / options-exit-monitor:
       client_order_id starts with 'exit-' (e.g. 'exit-emergency-*',
       'exit-tp-*', 'exit-sl-*').
    2. Alpaca bracket-order child legs (auto-created by Alpaca when a
       parent is placed with order_class=bracket):
       client_order_id ends with '_take_profit' or '_stop_loss'.
       These are standard Alpaca naming for bracket children.

    Anything else is treated as an entry.
    """
    cid = (order.get("client_order_id") or "").lower()
    if cid.startswith("exit-"):
        return True
    if cid.endswith("_take_profit") or cid.endswith("_stop_loss"):
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
    """Per-strategy roll-up: trades_7d, win_rate_7d, pnl_usd_7d,
    consecutive_losses, plus long/short P&L splits for options bias."""
    strat_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        strat_trades[t["strategy"]].append(t)

    out = {}
    for strat, ts in strat_trades.items():
        wins = [t for t in ts if t["winner"]]
        # Lifetime: this analyzer reads only the window, so lifetime accumulator
        # is the responsibility of state.json (added across days).
        # For first run, lifetime == window. Subsequent runs, adapter merges.
        long_pl  = sum(t["pnl_usd"] for t in ts if t["direction"] == "long")
        short_pl = sum(t["pnl_usd"] for t in ts if t["direction"] == "short")

        # Consecutive losses from end of list (most recent)
        ts_sorted = sorted(ts, key=lambda x: x.get("exit_time", ""), reverse=True)
        consec = 0
        for t in ts_sorted:
            if t["winner"]:
                break
            consec += 1

        out[strat] = {
            "trades_7d":        len(ts),
            "win_rate_7d":      round(len(wins) / len(ts), 3) if ts else 0.0,
            "pnl_usd_7d":       round(sum(t["pnl_usd"] for t in ts), 2),
            "trades_lifetime":  len(ts),    # first-run; merged with state in adapter
            "win_rate_lifetime":round(len(wins) / len(ts), 3) if ts else 0.0,
            "pnl_usd_lifetime": round(sum(t["pnl_usd"] for t in ts), 2),
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
    """Per-strategy fill / cancel / reject stats — answers 'why didn't it fill'."""
    by_strat = defaultdict(lambda: defaultdict(int))
    for o in orders:
        strat = _strategy_from_client_id(o.get("client_order_id", ""), o.get("symbol", ""))
        by_strat[strat]["placed"] += 1
        st = o.get("status", "unknown")
        if st == "filled":
            by_strat[strat]["filled"] += 1
        elif st in ("canceled", "expired"):
            by_strat[strat]["canceled"] += 1
        elif st == "rejected":
            by_strat[strat]["rejected"] += 1
        else:
            by_strat[strat]["other"] += 1
    out = {}
    for strat, counts in by_strat.items():
        placed = counts["placed"]
        out[strat] = {
            "placed":    placed,
            "filled":    counts.get("filled", 0),
            "canceled":  counts.get("canceled", 0),
            "rejected":  counts.get("rejected", 0),
            "fill_rate": round(counts.get("filled", 0) / placed, 3) if placed else 0.0,
        }
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

    # Today stats (input to adapter)
    today_stats = {
        "as_of":             date_iso,
        "equity":            equity,
        "starting_equity":   float(account.get("last_equity", equity) or equity),
        "by_strategy":       compute_strategy_stats(trades, orders, equity),
        "by_asset_class":    compute_asset_stats(trades),
        "by_source":         {},   # placeholder for future per-source attribution
        "fill_rate":         compute_fill_rate(orders),
        "tp_hit_rate":       compute_tp_hit_rate(orders),  # 10-day data-collect for trailing-stop decision
        "cumulative_trades": len(trades),
        "cumulative_pnl_usd": round(sum(t["pnl_usd"] for t in trades), 2),
    }

    # Load prior state, run deterministic adapter
    old_state = load_state()
    new_state, rationale = adapt(old_state, today_stats)

    # ── LLM augmentation step (fail-soft) ──────────────────────────────────
    # The deterministic adapter has produced a baseline new_state + rationale.
    # We now ask the LLM (Senior PM persona, see routine-prompts.md) to:
    #   1. Validate / second-guess the adapter's output
    #   2. Apply selective overrides where the adapter missed something
    #   3. Write a richer narrative for rationale.md
    #   4. Suggest new heuristics for future adapter versions
    #
    # If the LLM call fails (USE_LLM_LEARNING=false / 429 / no creds /
    # bad JSON), we keep the deterministic baseline. LLM is strictly
    # additive — never blocks the loop.
    print("\n  Calling LLM annotator (Senior PM review)...")
    llm_payload = {
        "type":                    "daily_learning_annotation",
        "today_stats":             today_stats,
        "proposed_state":          new_state,
        "deterministic_rationale": rationale,
        "recent_rationale_tail":   _tail_rationale(20),
        "target_branch":           os.environ.get("GITHUB_REF_NAME") or _git_current_branch(),
    }
    llm_resp = call_routine(llm_payload)
    llm_narrative_lines: list[str] = []

    if llm_resp:
        # Apply overrides (whitelist-enforced)
        overrides = llm_resp.get("state_overrides") or {}
        new_state, applied = safe_apply_overrides(new_state, overrides)
        if applied:
            print("  LLM overrides applied:")
            for line in applied:
                print(f"    {line}")
            llm_narrative_lines.extend(applied)

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

    # Merge deterministic + LLM rationale into one log entry block
    full_rationale = llm_narrative_lines + rationale

    save_state(new_state)
    append_rationale(full_rationale)
    write_history_report(date_iso, today_stats, new_state, full_rationale)

    print("\n  Rationale combined (LLM + deterministic):")
    for r in full_rationale:
        print(f"    · {r}")
    print(f"\n  Wrote: state.json, history/{date_iso}.md, rationale.md")
    print(f"  Strategies in state: {len(new_state.get('strategies', {}))}")
    print(f"  Workflow will commit + push these files back to main.")


if __name__ == "__main__":
    run()

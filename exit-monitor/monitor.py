"""
Exit Monitor — Hourly Position Manager
Sprawdza otwarte pozycje co godzinę i wysyla do Claude Routine decyzję exit/hold.
Używa Alpaca REST API bezpośrednio (bez MCP — GitHub Actions nie ma dostępu do MCP).
"""

from __future__ import annotations  # v3.11.3: PEP 604 (`X | Y`) parseable on Py 3.9.

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_exit, notify_summary
except ImportError:
    def notify_exit(*a, **k): pass
    def notify_summary(*a, **k): pass

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"   # paper trading

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_EXIT_WORKER_URL", "")

# Progi dla exit decyzji — Claude Routine dostanie te dane i podejmie decyzję
# v2.0 risk-on — looser thresholds, more patience, harder catastrophic stop
EXIT_THRESHOLDS = {
    "quick_profit_pct":      10.0,   # v2: was 3.0 — let winners run more
    "quick_profit_window_h":  6,     # v2: window for "quick" extended from 4h to 6h
    "time_decay_hours":       24,    # v2: was 6 — more patience for thesis to play out
    "flat_pnl_pct":           3.0,   # v2: was 1.0 — wider "flat" definition
    "leveraged_decay_hours":  96,    # v2: was 48 — 3× ETFs allowed to run
    "crypto_decay_hours":     48,    # v2: was 12 — give crypto room
    "crypto_decay_min_pl":    5.0,   # v2: was 3 — min profit to keep holding past decay
    "emergency_loss_pct":    -12.0,  # v2: was -5 — daily catastrophic, NOT per-trade SL
}

# ─── Alpaca REST API ──────────────────────────────────────────────────────────

def alpaca_get(endpoint: str) -> dict | list:
    """Wywołuje Alpaca REST API"""
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    resp = requests.get(
        f"{ALPACA_BASE_URL}{endpoint}",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _emergency_close_window_ok(ep: dict) -> bool:
    """
    True iff this position's asset class is currently tradeable.

    Pulled out so callers can DEFER (skip routine fallback) instead of
    routing market-closed cases to a routine that can't trade either —
    avoiding noisy "auth fail" reports when the real reason is "market
    closed, retry after open".
    """
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from instrument_windows import can_trade_now, _infer_asset_class
        symbol = ep.get("symbol", "")
        asset_class = _infer_asset_class(symbol)
        ok, reason = can_trade_now(symbol, asset_class=asset_class)
        if not ok:
            print(f"  emergency-close {symbol} ({asset_class}): deferred — {reason}")
            return False
        return True
    except ImportError:
        return True


# v3.13.3 (2026-06-02) — PDT-aware cooldown for repeated CLOSE attempts.
# When PDT guard BLOCKs a CLOSE_FLAT recommendation, exit-monitor was
# retrying every 5 min (cron) → 36 audit events in single day for one
# position. Cooldown: silence audit + log noise for (symbol, rec) for
# 60 min after a PDT block. Emergency closes BYPASS this — different
# code path uses is_emergency=True which short-circuits.
_PDT_BLOCK_COOLDOWN: dict = {}    # key: "SYM|REC|DECISION" → last block ts
PDT_BLOCK_COOLDOWN_S = 3600       # 60 min


def place_emergency_close(ep: dict) -> dict | None:
    """
    Close an exit-flagged position via Alpaca direct REST.

    Strategy (v3.4.3, 2026-05-13 — extended v3.8.7, 2026-05-16):
      0. PRE-MARKET guard (v3.8.7): if current UTC < 13:30 (market closed),
         options orders cannot fill. POST /v2/orders MARKET pre-market is
         rejected by Alpaca for options. DELETE /v2/positions also waits
         for market open. Behavior: skip placement, queue to runtime_state
         for next session pickup by morning-allocator or auto-retry on
         next exit-monitor cron after 13:30 UTC.
      1. PRIMARY: DELETE /v2/positions/{symbol} — canonical close endpoint
         that bypasses options buying-power checks (the failure mode that
         hit QQQ260518P00714000 2026-05-13: "insufficient options buying
         power for cash-secured put" returned 403 on POST sell_to_close).
         DELETE explicitly references existing position → no buying-power
         requirement → reliable closure.
      2. FALLBACK: POST /v2/orders MARKET sell — used when DELETE returns
         non-2xx (e.g. position already closed by concurrent run).

    Bypasses the Claude.ai routine path entirely because the routine
    sandbox uses different (invalid) Alpaca keys that return 401.

    `ep` is the enriched-position dict from `enrich_position()`. Returns
    the Alpaca order JSON on success, None on failure or pre-market defer.

    Reason tag in client_order_id:
      profit-lock | emergency | flat | decay
    (so analyzer can attribute close reasons separately).
    """
    import urllib.parse
    symbol = ep.get("symbol", "")
    qty    = abs(float(ep.get("qty", 0)))
    side   = ep.get("side", "long")
    if qty <= 0 or not symbol:
        return None

    # v3.8.7 (2026-05-16): pre-market emergency close defer.
    # Options pre-market: Alpaca rejects with "market closed for options"
    # (paper). Equity pre-market MARKET orders queue but may slip widely
    # at open. Defer to first cron after 13:30 UTC for clean execution.
    # asset_class detected from symbol shape (option = 15+ chars w/ digits).
    asset_class = ep.get("asset_class", "")
    now_utc = datetime.now(timezone.utc)
    is_premarket = (
        now_utc.weekday() < 5 and (
            now_utc.hour < 13 or (now_utc.hour == 13 and now_utc.minute < 30)
        )
    )
    is_weekend_premarket = (now_utc.weekday() >= 5)
    if (asset_class in ("us_option", "us_equity") and (is_premarket or is_weekend_premarket)
            and "/" not in symbol):
        slot = "weekend" if is_weekend_premarket else f"pre-market ({now_utc.hour:02d}:{now_utc.minute:02d} UTC)"
        print(f"  emergency-close {symbol} ({asset_class}): deferred — {slot}, "
              f"will retry post 13:30 UTC")
        # Queue marker for downstream observability (next cron re-evaluates).
        return {"deferred": True, "reason": "pre_market_emergency_close",
                "symbol": symbol, "queued_at": now_utc.isoformat()}

    # Note: trade-window check is done by caller via _emergency_close_window_ok
    # so blocked positions can be DEFERRED (skip routine fallback). Kept here
    # as a defensive no-op safety in case the helper is bypassed.

    # Reason tag for client_order_id (analyzer attribution).
    rec = ep.get("recommendation", "CLOSE_EMERGENCY")
    reason_tag = {
        "PROFIT_LOCK":     "profit-lock",
        "CLOSE_EMERGENCY": "emergency",
        "CLOSE_FLAT":      "flat",
        "CLOSE_DECAY":     "decay",
    }.get(rec, "emergency")

    # PDT pre-close gate v3.8 — recommendation → intent + emergency flag.
    # Emergency recommendations (CLOSE_EMERGENCY, PROFIT_LOCK) bypass DEFER —
    # defensive necessity, must always proceed. Discretionary recommendations
    # (CLOSE_FLAT, CLOSE_DECAY) use intent="intraday" since exit-monitor is
    # acting on same-session signals; the PDT engine then checks whether the
    # position was opened today (true day-trade) or carried over (free close).
    asset_class = ep.get("asset_class", "")
    if asset_class != "crypto":
        is_emergency_close = rec in ("CLOSE_EMERGENCY", "PROFIT_LOCK")
        # v3.8 intent semantics: emergency closes labeled INTENT_EMERGENCY
        # for audit clarity; non-emergencies labeled INTENT_INTRADAY.
        close_intent = "emergency" if is_emergency_close else "intraday"
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
            from pdt_guard import evaluate_order as _pdt_eval, record_decision as _pdt_audit
            pdt_size = abs(float(ep.get("market_value") or 0)) or qty * float(ep.get("current_price") or 0)
            close_side = "sell" if side == "long" else "buy"
            pv = _pdt_eval(
                action="CLOSE", symbol=symbol, side=close_side, size_usd=pdt_size,
                intent=close_intent, is_emergency=is_emergency_close,
            )
            if pv["decision"] != "ALLOW":
                # v3.13.3 (2026-06-02) — PDT-aware cooldown to prevent
                # spam. Live incident 2026-06-01: exit-monitor tried
                # CLOSE_FLAT on RTX×12, LMT×21, GLD×2, QQQ×1 every 5min
                # for hours, all PDT_BLOCKed (dt=17). 36 audit events.
                # Record audit once per (symbol, recommendation) per hour;
                # subsequent skip is silent log only.
                _now = datetime.now(timezone.utc)
                _cooldown_key = f"{symbol}|{rec}|{pv.get('decision')}"
                _last = _PDT_BLOCK_COOLDOWN.get(_cooldown_key)
                _within_cooldown = (_last is not None
                                     and (_now - _last).total_seconds() < PDT_BLOCK_COOLDOWN_S)
                if not _within_cooldown:
                    _pdt_audit(pv, action="CLOSE", symbol=symbol,
                               extra={"recommendation": rec, "asset_class": asset_class,
                                       "intent": close_intent})
                    _PDT_BLOCK_COOLDOWN[_cooldown_key] = _now
                    if pv["decision"] == "DEFER":
                        print(f"  pdt-guard DEFER {symbol} ({rec}): {pv['reason']}")
                    else:  # BLOCK
                        print(f"  pdt-guard BLOCK {symbol} ({rec}): {pv['reason']}")
                else:
                    # Already blocked recently — silent skip (no audit spam)
                    print(f"  pdt-guard {pv['decision']} {symbol} ({rec}): "
                          f"silent (cooldown {PDT_BLOCK_COOLDOWN_S}s active)")
                return None
        except Exception as e:
            print(f"  pdt-guard unavailable for {symbol} ({type(e).__name__}: {e}) — proceeding")
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = symbol.replace("/", "").replace(" ", "")
    client_order_id = f"exit-{reason_tag}-{safe_sym}-{ts}"

    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

    # PRIMARY: DELETE /v2/positions/{symbol} — bypasses buying-power bug
    enc_sym = urllib.parse.quote(symbol, safe="")
    try:
        r = requests.delete(
            f"{ALPACA_BASE_URL}/v2/positions/{enc_sym}",
            headers=headers,
            timeout=15,
        )
        if r.status_code in (200, 201, 207):
            body = r.json()
            print(f"  {reason_tag}-close DELETE OK: {symbol} → order_id={body.get('id','?')}")
            # Annotate body with our intended client_order_id for downstream parsing
            body["_client_order_intent"] = client_order_id
            return body
        if r.status_code == 404:
            print(f"  {reason_tag}-close DELETE 404: {symbol} not in positions (already closed)")
            return None
        # Non-success — log and try fallback
        print(f"  {reason_tag}-close DELETE error {r.status_code}: {r.text[:200]} — trying POST fallback")
    except Exception as e:
        print(f"  {reason_tag}-close DELETE exception: {e} — trying POST fallback")

    # FALLBACK: route through safe_close (v3.9.10) — pre-flight position check,
    # eliminates risk of MARKET sell creating naked short if position
    # disappeared between DELETE 404 and POST. Also emits audit JSONL.
    close_side = "sell" if side == "long" else "buy"
    is_crypto = "/" in symbol
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
        from alpaca_orders import safe_close  # type: ignore
    except ImportError:
        print(f"  {reason_tag}-close safe_close import failed — refusing POST fallback")
        return None
    sc = safe_close(
        symbol=symbol,
        intent_qty=float(qty),
        intent_side=close_side,
        reason_tag=f"exit-{reason_tag}",
        order_type="market",
        time_in_force="gtc" if is_crypto else "day",
        is_crypto=is_crypto,
        allow_market=True,
    )
    if sc["status"] == "placed":
        return {"id": sc["alpaca_order_id"], "status": "accepted",
                "symbol": symbol, "qty": sc["actual_qty"]}
    print(f"  {reason_tag}-close POST {sc['status']}: {sc['reason']}")
    return None


def get_open_positions() -> list[dict]:
    """Pobiera wszystkie otwarte pozycje"""
    try:
        positions = alpaca_get("/v2/positions")
        return positions if isinstance(positions, list) else []
    except Exception as e:
        print(f"  Błąd pobierania pozycji: {e}")
        return []


def get_account_info() -> dict:
    """Pobiera informacje o koncie"""
    try:
        return alpaca_get("/v2/account")
    except Exception as e:
        print(f"  Błąd pobierania konta: {e}")
        return {}


def get_recent_orders(limit: int = 50) -> list[dict]:
    """Pobiera ostatnie zlecenia (do identyfikacji strategii)"""
    try:
        after = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        orders = alpaca_get(f"/v2/orders?status=all&limit={limit}&after={after}")
        return orders if isinstance(orders, list) else []
    except Exception as e:
        print(f"  Błąd pobierania zleceń: {e}")
        return []


# ─── Analiza pozycji ──────────────────────────────────────────────────────────

def enrich_position(pos: dict, orders: list[dict]) -> dict:
    """
    Wzbogaca pozycję o dodatkowe informacje:
    - czas trzymania
    - strategia źródłowa (z client_order_id)
    - rekomendacja wstępna
    """
    symbol        = pos.get("symbol", "")
    qty           = float(pos.get("qty", 0))
    side          = pos.get("side", "long")  # "long" or "short"
    entry_price   = float(pos.get("avg_entry_price", 0))
    current_price = float(pos.get("current_price", 0))
    unrealized_pl = float(pos.get("unrealized_pl", 0))
    unrealized_plpc = float(pos.get("unrealized_plpc", 0)) * 100  # w %

    # Znajdź zlecenie otwierające (najnowsze fill dla tego symbolu)
    strategy = "unknown"
    entry_time = None
    for order in sorted(orders, key=lambda o: o.get("filled_at") or "", reverse=True):
        if order.get("symbol") == symbol and order.get("filled_at"):
            client_id = order.get("client_order_id", "")
            # Format: strategy-TICKER-timestamp
            if "-" in client_id:
                strategy = client_id.split("-")[0]
            try:
                entry_time = datetime.fromisoformat(order["filled_at"].replace("Z", "+00:00"))
            except Exception:
                pass
            break

    # Czas trzymania
    now = datetime.now(timezone.utc)
    hold_hours = 0
    if entry_time:
        hold_hours = (now - entry_time).total_seconds() / 3600

    # Wstępna rekomendacja (Claude Routine podejmie ostateczną decyzję)
    recommendation = "HOLD"
    reasons = []

    # IntradayProfitGovernor (v3.5, 2026-05-14) — replaces ad-hoc peak_tracker
    # consult with the full 7-state FSM. Pulls last-persisted snapshot
    # (run_exit_check() refreshes it via shared.intraday_governor.update()
    # right at the top of every cron tick).
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from intraday_governor import (
            get_snapshot,
            STATE_PROFIT_LOCK, STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN,
            STATE_GIVEBACK_WARN,
            position_mfe_action,
        )
        _ig = get_snapshot()
        _ig_state = _ig.pnl_state
        _ig_peak  = _ig.intraday_peak_pnl
        _ig_giveback = _ig.giveback_pct_of_peak
    except (ImportError, Exception):
        _ig = None
        _ig_state = ""
        _ig_peak = 0.0
        _ig_giveback = 0.0
        STATE_PROFIT_LOCK = "PROFIT_LOCK"          # type: ignore[assignment]
        STATE_DEFEND_DAY = "DEFEND_DAY"            # type: ignore[assignment]
        STATE_RED_DAY_AFTER_GREEN = "RED_DAY_AFTER_GREEN"  # type: ignore[assignment]
        STATE_GIVEBACK_WARN = "GIVEBACK_WARN"      # type: ignore[assignment]
        position_mfe_action = lambda _p: {"action": "HOLD", "reduce_pct": 0.0, "reason": "", "mfe_peak": 0.0, "mfe_retrace": 0.0}  # type: ignore[assignment]

    asset_class = (pos.get("asset_class") or "us_equity").lower()
    is_option   = asset_class == "us_option"

    # Position-level MFE → harvest decision (independent of portfolio state,
    # but fires AT LEAST as aggressively when portfolio is already retracing).
    mfe_decision = position_mfe_action({
        "symbol":         symbol,
        "unrealized_plpc": unrealized_plpc / 100.0,  # decimal for governor
    })

    if _ig_state == STATE_RED_DAY_AFTER_GREEN:
        # Day already turned red after green peak — close every intraday
        # position aggressively. Options first (premium decays fastest),
        # then anything else not explicitly held as a hedge.
        recommendation = "PROFIT_LOCK"  # reuses existing direct-close router below
        reasons.append(
            f"RED_DAY_AFTER_GREEN: peak ${_ig_peak:+.0f} → current "
            f"${(_ig.current_intraday_pnl if _ig else 0):+.0f} ({_ig_giveback:.0%} giveback) — "
            f"close intraday positions"
        )
    elif _ig_state == STATE_DEFEND_DAY:
        # Defend day: harvest winners ≥+5% (loose), close weak positions,
        # options first.
        if is_option or unrealized_plpc >= 5.0 or mfe_decision["action"] in ("REDUCE", "HARVEST"):
            recommendation = "PROFIT_LOCK"
            reasons.append(
                f"DEFEND_DAY: peak ${_ig_peak:+.0f} retrace {_ig_giveback:.0%} — "
                f"flatten this {'option' if is_option else 'position'} now"
            )
    elif _ig_state == STATE_PROFIT_LOCK and (unrealized_plpc >= 8.0 or is_option):
        # Aggressive harvest: any winner >=8% gets flagged. Options always
        # flagged (premium decays faster than stocks; even small green
        # options should be locked).
        recommendation = "PROFIT_LOCK"
        reasons.append(
            f"PROFIT_LOCK: peak ${_ig_peak:+.0f} retrace {_ig_giveback:.0%}, "
            f"this winner {unrealized_plpc:.1f}% — harvest now"
        )
    elif _ig_state == STATE_GIVEBACK_WARN and mfe_decision["action"] == "HARVEST":
        # WARN tier: tighten stops by harvesting positions whose own MFE
        # already says "take it" (per-position rule wins).
        recommendation = "PROFIT_LOCK"
        reasons.append(
            f"GIVEBACK_WARN + position MFE harvest ({mfe_decision['reason']})"
        )
    elif mfe_decision["action"] == "HARVEST":
        # Position-level harvest even if portfolio is calm — a single
        # position that peaked +20% and gave back 25% is a strict-win
        # turning into a partial-win, lock it.
        recommendation = "PROFIT_LOCK"
        reasons.append(f"position MFE: {mfe_decision['reason']}")

    if recommendation == "PROFIT_LOCK":
        # Done — skip the legacy heuristics below.
        pass
    elif unrealized_plpc <= EXIT_THRESHOLDS["emergency_loss_pct"]:
        recommendation = "CLOSE_EMERGENCY"
        reasons.append(f"strata {unrealized_plpc:.1f}% przekracza próg awaryjny")

    elif unrealized_plpc >= EXIT_THRESHOLDS["quick_profit_pct"] and hold_hours < EXIT_THRESHOLDS["quick_profit_window_h"]:
        recommendation = "CONSIDER_TP"
        reasons.append(f"szybki zysk {unrealized_plpc:.1f}% w {hold_hours:.1f}h")

    elif strategy in ("leveraged-etf",) and hold_hours >= EXIT_THRESHOLDS["leveraged_decay_hours"]:
        recommendation = "CLOSE_DECAY"
        reasons.append(f"lewarowane ETF trzymane {hold_hours:.1f}h (próg: {EXIT_THRESHOLDS['leveraged_decay_hours']}h)")

    elif symbol in ("BTC/USD", "ETH/USD") and hold_hours >= EXIT_THRESHOLDS["crypto_decay_hours"] and unrealized_plpc < EXIT_THRESHOLDS["crypto_decay_min_pl"]:
        recommendation = "CLOSE_DECAY"
        reasons.append(f"crypto trzymane {hold_hours:.1f}h bez ≥3% zysku")

    elif hold_hours >= EXIT_THRESHOLDS["time_decay_hours"] and abs(unrealized_plpc) < EXIT_THRESHOLDS["flat_pnl_pct"]:
        recommendation = "CLOSE_FLAT"
        reasons.append(f"pozycja płaska ({unrealized_plpc:.1f}%) po {hold_hours:.1f}h")

    # v3.11.3 (2026-05-30) — intraday-trend escalation (ITM / Spec §12).
    # Only escalates benign HOLD/CLOSE_FLAT to CLOSE_FLAT when the
    # intraday-trend module reports REVERSAL_CONFIRMED. NEVER downgrades
    # an already-flagged emergency/profit-lock decision. Fail-soft: if
    # the module is unavailable or returns stale=True, leave recommendation
    # alone (so a data outage cannot trigger spurious closes).
    if recommendation in ("HOLD", "CLOSE_FLAT") and asset_class == "us_equity":
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
            from intraday_trend import intraday_trend_state, REVERSAL_CONFIRMED  # type: ignore
            ts = intraday_trend_state(symbol, side=side)
            if ts.get("state") == REVERSAL_CONFIRMED and not ts.get("stale"):
                if recommendation == "HOLD":
                    recommendation = "CLOSE_FLAT"
                reasons.append(f"intraday REVERSAL_CONFIRMED: {ts.get('reason','')}")
        except Exception as _e:
            # Module missing or bad input — silently keep prior recommendation.
            pass

    return {
        "symbol":          symbol,
        "qty":             qty,
        "side":            side,
        "strategy":        strategy,
        "entry_price":     entry_price,
        "current_price":   current_price,
        "unrealized_pl":   round(unrealized_pl, 2),
        "unrealized_plpc": round(unrealized_plpc, 2),
        "hold_hours":      round(hold_hours, 1),
        "recommendation":  recommendation,
        "reasons":         reasons,
    }


# ─── Wysyłanie do Claude Routine ─────────────────────────────────────────────

def send_to_routine(positions: list[dict], account: dict) -> bool:
    """Wysyła dane pozycji do Cloudflare Worker → Claude Routine"""
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_EXIT_WORKER_URL — pomijam wysyłanie")
        return False

    # Statystyki konta
    equity          = float(account.get("equity", 0))
    cash            = float(account.get("cash", 0))
    daily_pl        = float(account.get("equity", 0)) - float(account.get("last_equity", equity))
    daily_pl_pct    = (daily_pl / float(account.get("last_equity", equity or 1))) * 100 if equity else 0

    payload = {
        "type":            "exit_monitor",
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "account": {
            "equity":       round(equity, 2),
            "cash":         round(cash, 2),
            "daily_pl":     round(daily_pl, 2),
            "daily_pl_pct": round(daily_pl_pct, 2),
        },
        "positions":       positions,
        "thresholds":      EXIT_THRESHOLDS,
        "summary": {
            "total_positions":    len(positions),
            "needs_attention":    sum(1 for p in positions if p["recommendation"] != "HOLD"),
            "total_unrealized_pl": round(sum(p["unrealized_pl"] for p in positions), 2),
        }
    }

    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=payload,
            timeout=30,
        )
        print(f"  Payload wysłany do Claude Routine: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def run_exit_check():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === EXIT MONITOR ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    # Pobierz dane
    print("  Pobieranie pozycji i konta...")
    account   = get_account_info()
    positions = get_open_positions()
    orders    = get_recent_orders()

    print(f"  Otwartych pozycji: {len(positions)}")
    print(f"  Equity: ${float(account.get('equity', 0)):,.2f}")

    # ── IntradayProfitGovernor — full 7-state FSM update ─────────────────
    # v3.5 (2026-05-14) supersedes v3.3 peak_tracker. The new module stores
    # state in learning-loop/runtime_state.json (separate from state.json so
    # this 5-min monitor can finally persist across cron ticks via a small
    # post-step in the workflow YAML — `contents: write` + `git push` of
    # ONLY runtime_state.json with GITHUB_TOKEN; no proxy block).
    #
    # Solves the +$5,000 → -$2,000 giveback pattern: as retrace ratchets
    # through the FSM tiers, this loop adds DEFEND_DAY and RED_DAY_AFTER_
    # GREEN actions that block new entries, harvest winners and close
    # options first. See docs/INTRADAY_PROTECTION.md for the contract.
    intraday_snap = None
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from intraday_governor import (
            update as ig_update,
            summarize as ig_summarize,
            mark_alert_sent as ig_mark_alert_sent,
            alert_already_sent as ig_alert_already_sent,
            STATE_GIVEBACK_WARN, STATE_PROFIT_LOCK,
            STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN,
        )
        # Pass account_status-like dict (exit-monitor's get_account_info has the fields)
        intraday_snap = ig_update({
            "equity":       float(account.get("equity", 0) or 0),
            "last_equity":  float(account.get("last_equity", 0) or 0),
        })
        print(f"  {ig_summarize(intraday_snap)}")

        # Email alerts at each level — dedup per UTC day. Each level sends
        # at most once: WARN → PROFIT_LOCK → DEFEND_DAY → RED_DAY_AFTER_GREEN.
        state = intraday_snap.pnl_state
        notify_levels = []
        if state in (STATE_GIVEBACK_WARN, STATE_PROFIT_LOCK,
                     STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN):
            notify_levels.append(state)
        # Legacy alias so existing notify_peak_retrace WARN/PROFIT_LOCK
        # subscribers (operators with email filters) keep working.
        legacy_level = (
            "PROFIT_LOCK" if state in (STATE_PROFIT_LOCK, STATE_DEFEND_DAY,
                                         STATE_RED_DAY_AFTER_GREEN)
            else "WARN"   if state == STATE_GIVEBACK_WARN
            else None
        )
        for level in notify_levels:
            if ig_alert_already_sent(level):
                continue
            try:
                from notify import notify_intraday_state, notify_peak_retrace
                ok = notify_intraday_state(intraday_snap, level=level)
                # Send the legacy peak-retrace email exactly once per session
                # at the first WARN/LOCK crossing, so existing inbox filters
                # don't go quiet.
                if ok and legacy_level and not ig_alert_already_sent(f"legacy:{legacy_level}"):
                    try:
                        # Synthesise legacy peak dict from snapshot for back-compat
                        legacy_peak = {
                            "peak_pl_usd":       intraday_snap.intraday_peak_pnl,
                            "current_pl_usd":    intraday_snap.current_intraday_pnl,
                            "peak_at":           intraday_snap.peak_at,
                            "peak_equity":       intraday_snap.intraday_peak_equity,
                            "current_equity":    intraday_snap.current_equity,
                            "retrace_from_peak": intraday_snap.giveback_pct_of_peak,
                        }
                        notify_peak_retrace(legacy_peak, level=legacy_level)
                        ig_mark_alert_sent(f"legacy:{legacy_level}")
                    except Exception as e:
                        print(f"  legacy peak-retrace email skipped: {e}")
                if ok:
                    ig_mark_alert_sent(level)
                    print(f"  [INTRADAY-ALERT] {level} email sent")
            except Exception as e:
                print(f"  intraday_governor notify failed: {e}")
    except Exception as e:
        print(f"  intraday_governor unavailable ({type(e).__name__}: {e}) — skip")

    if not positions:
        print("  Brak otwartych pozycji — nic do sprawdzenia")
        return

    # Wzbogać pozycje o analizę
    enriched = []
    flagged  = []
    for pos in positions:
        ep = enrich_position(pos, orders)
        enriched.append(ep)
        if ep["recommendation"] != "HOLD":
            flagged.append(ep)
        status_icon = "⚠️" if ep["recommendation"] != "HOLD" else "✅"
        print(
            f"  {status_icon} {ep['symbol']:8s} {ep['side']:5s} "
            f"P&L: {ep['unrealized_plpc']:+.1f}% "
            f"({ep['hold_hours']:.1f}h) → {ep['recommendation']}"
            + (f" [{', '.join(ep['reasons'])}]" if ep['reasons'] else "")
        )

    # Email per flagged position (recommendation != HOLD)
    for ep in flagged:
        reason = "; ".join(ep["reasons"]) if ep["reasons"] else ep["recommendation"]
        notify_exit(ep["symbol"], ep["recommendation"], reason, ep["unrealized_plpc"])

    # ── EMERGENCY + PROFIT_LOCK EXITS: bypass routine, place MARKET directly ─
    # CLOSE_EMERGENCY: position breaches -12% stop. Time-critical.
    # PROFIT_LOCK: daily P&L retraced 50%+ from peak >=$1k. Lock unrealized
    #              gains now before further reversal.
    # CLOSE_FLAT: long-hold flat position — close to free margin.
    # CLOSE_DECAY: leveraged ETF / crypto past time-decay window.
    # All four → direct REST via place_emergency_close (DELETE primary,
    # POST fallback). Routine ONLY used for CONSIDER_TP (less critical;
    # LLM evaluates if profit worth taking now or letting run).
    #
    # v3.4.5 (2026-05-14): trade-window-blocked positions are DEFERRED
    # (not routed to routine). The routine sandbox uses different Alpaca
    # keys (401 auth fail) and also cannot trade options outside market
    # hours — so falling back produces noisy "auth fail" reports without
    # accomplishing anything. Better to log "deferred" and let next cron
    # tick (post-market-open) retry.
    direct_recs = ("CLOSE_EMERGENCY", "PROFIT_LOCK", "CLOSE_FLAT", "CLOSE_DECAY")
    direct_close = [ep for ep in flagged if ep["recommendation"] in direct_recs]
    other_flagged = [ep for ep in flagged if ep["recommendation"] not in direct_recs]
    emergency = direct_close
    closed_directly = 0
    deferred_count = 0
    for ep in emergency:
        # Trade-window pre-check: skip both DELETE and routine fallback if
        # market closed for this instrument's asset class (e.g. options
        # outside 13:30-20:00 UTC).
        if not _emergency_close_window_ok(ep):
            deferred_count += 1
            continue
        result = place_emergency_close(ep)
        if result:
            print(f"  {ep['recommendation']} closed directly: {ep['symbol']} qty={ep['qty']} "
                  f"id={result.get('id', '?')}")
            closed_directly += 1
        else:
            print(f"  {ep['recommendation']} close FAILED for {ep['symbol']} — "
                  f"falling back to routine")
            other_flagged.append(ep)  # routine as last resort

    # Routine call only for non-emergency flagged positions (mostly CONSIDER_TP)
    if other_flagged:
        print(f"\n  Wysyłam do Claude Routine Exit Handler ({len(other_flagged)} flagged, "
              f"{closed_directly} closed directly, {deferred_count} deferred)...")
        send_to_routine(enriched, account)
    elif emergency:
        print(f"\n  {closed_directly} closed directly via REST, "
              f"{deferred_count} deferred (market closed) — no routine call needed")
    else:
        print(f"\n  Wszystkie pozycje HOLD — pomijam routine call (oszczędzam budget).")

    notify_summary("Exit Monitor", len(flagged), len(flagged))


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_exit_check()
    # v3.13.3 — heartbeat ping (READINESS-1). Fail-soft.
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("exit-monitor", status="ok")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")

"""
Direct Alpaca REST order placement.

Replaces the routine-based execution path that was burning the 15-call
daily Anthropic Routines budget. Each monitor now places orders directly
via /v2/orders, mirroring the options-monitor pattern that's been live
since 2026-05-06.

Helpers cover three asset classes:

  place_stock_bracket(symbol, side, qty, entry, sl, tp, strategy)
      Bracket order for stocks/ETFs (Alpaca paper supports brackets).
      side: "buy" (long) or "sell_short" (short)

  place_crypto_order(symbol, side, qty, entry, strategy)
      Simple limit order for BTC/USD, ETH/USD. Alpaca crypto does NOT
      support bracket — TP/SL must be managed separately by exit-monitor.

  place_simple_buy(symbol, qty, limit_price, strategy)
      Simple limit BUY for options (Alpaca paper rejects bracket on
      options — already used by options-monitor).

  get_latest_quote(symbol)
      Single-quote snapshot for SL/TP price computation. Returns
      {bid, ask, mid} or None.

All helpers fail-open: API failure returns None, caller falls through
to email-only / log path. Same fail-open philosophy as risk_guards.
"""

import os
import urllib.parse
import requests
from datetime import datetime, timezone

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"


def _fetch_account() -> dict | None:
    """Best-effort /v2/account for portfolio-risk gate. Returns None on failure."""
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_positions() -> list[dict]:
    if not _headers()["APCA-API-KEY-ID"]:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _fetch_open_orders() -> list[dict]:
    if not _headers()["APCA-API-KEY-ID"]:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                         headers=_headers(), params={"status": "open"}, timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _portfolio_risk_gate(symbol: str, side: str, size_usd: float,
                         asset_class: str) -> tuple[bool, list[str], list[str]]:
    """
    Portfolio-level pre-trade gate (spec §D). Returns (ok, failed, warnings).
    Fail-open on missing inputs — same contract as shared/risk_guards.py.
    """
    try:
        try:
            from portfolio_risk import evaluate_portfolio_risk
        except ImportError:
            from shared.portfolio_risk import evaluate_portfolio_risk  # type: ignore
        verdict = evaluate_portfolio_risk(
            proposed_trade = {
                "symbol":      symbol,
                "side":        side,
                "size_usd":    size_usd,
                "asset_class": asset_class,
            },
            account = _fetch_account(),
            positions = _fetch_positions(),
            open_orders = _fetch_open_orders(),
        )
        return verdict["decision"] == "APPROVE", verdict.get("failed", []), verdict.get("warnings", [])
    except Exception as e:  # pragma: no cover
        return True, [], [f"portfolio-risk unavailable ({type(e).__name__}: {e})"]


def _intraday_governor_gate(symbol: str, side: str, size_usd: float,
                            asset_class: str,
                            score: float | None = None) -> tuple[bool, str]:
    """
    IntradayProfitGovernor pre-trade gate. Returns (allow, reason).

    Logic:
      - RED_DAY_AFTER_GREEN / DEFEND_DAY     → BLOCK (deterministic giveback protection)
      - PROFIT_LOCK + score < override       → BLOCK (high-score override is ratchet exit)
      - Account state unavailable            → BLOCK (spec §G fail-closed for new entries)
      - else                                 → ALLOW

    Audit-only: emits a BLOCK_NEW_ENTRIES_INTRADAY event when blocking.
    Fail-open on import error so the governor module being unavailable
    cannot freeze trading (defence in depth: this is layered on top of
    risk_officer + portfolio_risk_gate).
    """
    try:
        try:
            from runtime_config import intraday_protection_enabled
        except ImportError:
            from shared.runtime_config import intraday_protection_enabled  # type: ignore
        if not intraday_protection_enabled():
            return True, "intraday_protection_disabled"
        try:
            from intraday_governor import (
                block_new_entries, emit_audit, get_snapshot,
                EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
            )
        except ImportError:
            from shared.intraday_governor import (   # type: ignore
                block_new_entries, emit_audit, get_snapshot,
                EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
            )
        block, reason = block_new_entries(symbol=symbol, score=score)
        if block:
            try:
                emit_audit(
                    EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
                    get_snapshot(),
                    action="reject_entry",
                    reason=reason,
                    affected_symbols=[symbol],
                )
            except Exception:  # pragma: no cover
                pass
        return (not block), reason
    except Exception as e:  # pragma: no cover
        return True, f"intraday-governor unavailable ({type(e).__name__}: {e})"


def _pdt_gate(symbol: str, side: str, size_usd: float,
              asset_class: str, intent: str = "swing") -> tuple[bool, str]:
    """
    PDT pre-trade gate v3.8 — intent-aware. Returns (allow, reason).

    Default intent="swing" means caller intends to hold ≥1 session. This
    matches every entry-monitor's default behavior (price-monitor opens
    swing positions, options-monitor's contracts hold 7-30 DTE, crypto
    is exempt regardless). Callers doing planned same-day flips MUST
    explicitly pass intent="intraday" so the guard can DEFER in
    RESTRICTED+ states (where the planned close would burn the saved
    DT budget).

    Logic for OPEN actions:
      - LOCKED with BP OK + swing intent  → ALLOW (no DT impact)
      - LOCKED with BP insufficient       → BLOCK (broker would reject)
      - RESTRICTED + intraday intent      → DEFER (planned close = DT)
      - All other combinations            → ALLOW

    Emits non-ALLOW decisions to journal/autonomy/. Fail-open if module
    unavailable — layered above risk_officer which catches absolute BP-
    insufficient case anyway.
    """
    try:
        try:
            from pdt_guard import evaluate_order, record_decision
        except ImportError:
            from shared.pdt_guard import evaluate_order, record_decision  # type: ignore
        action = "OPEN"  # all calls to this gate are entry-side
        verdict = evaluate_order(
            action=action, symbol=symbol, side=side, size_usd=size_usd,
            intent=intent, is_emergency=False,
        )
        decision = verdict.get("decision", "ALLOW")
        reason   = verdict.get("reason", "")
        if decision != "ALLOW":
            record_decision(verdict, action=action, symbol=symbol,
                            extra={"asset_class": asset_class, "size_usd": size_usd,
                                    "intent": intent})
        return (decision == "ALLOW"), reason
    except Exception as e:  # pragma: no cover
        return True, f"pdt-guard unavailable ({type(e).__name__}: {e})"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _client_order_id(strategy: str, symbol: str) -> str:
    """Per-strategy client_order_id so exit-monitor can identify origin."""
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = symbol.replace("/", "").replace(" ", "")
    return f"{strategy}-{safe_sym}-{ts}"


# ─── Quote / spot price ───────────────────────────────────────────────────────

def get_latest_quote(symbol: str) -> dict | None:
    """
    Returns {bid, ask, mid} for `symbol`, or None on failure.

    Used by entry monitors that need a current spot price to compute
    SL/TP from percentage thresholds.
    """
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes/latest",
            headers=_headers(),
            params={"feed": "iex"},
            timeout=10,
        )
        r.raise_for_status()
        q = r.json().get("quote", {})
        bid = float(q.get("bp", 0))
        ask = float(q.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  quote {symbol} error: {e}")
        return None


def get_latest_crypto_quote(symbol: str) -> dict | None:
    """Returns {bid, ask, mid} for crypto symbol like 'BTC/USD'."""
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v1beta3/crypto/us/latest/quotes",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json().get("quotes", {}).get(symbol, {})
        bid = float(d.get("bp", 0))
        ask = float(d.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  crypto quote {symbol} error: {e}")
        return None


# ─── Order placement ──────────────────────────────────────────────────────────

def place_stock_bracket(symbol: str, side: str, qty: int,
                        entry_price: float, stop_loss: float,
                        take_profit: float,
                        strategy: str = "auto") -> dict | None:
    """
    Place a bracket order for stocks/ETFs.

    side:        "buy" (long) or "sell_short" (short)
    qty:         integer shares (>= 1)
    entry_price: limit price for entry leg
    stop_loss:   absolute price for SL leg
    take_profit: absolute price for TP leg
    strategy:    used in client_order_id prefix

    Returns the Alpaca order JSON on success, None on failure (incl.
    risk-officer REJECT — see shared.risk_officer.evaluate_trade).
    """
    if qty < 1 or entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        print(f"  bracket reject: qty={qty} entry={entry_price} sl={stop_loss} tp={take_profit}")
        return None
    if side not in ("buy", "sell_short"):
        print(f"  bracket reject: bad side '{side}'")
        return None

    # Per-instrument trading window gate (final guard right before POST).
    # Most callers also gate upstream in execute_stock_signal — this is the
    # belt-and-braces check that catches direct callers (allocator, etc.).
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="us_equity")
    if not ok:
        print(f"  bracket reject {symbol}: trade-window — {reason}")
        return None

    # Portfolio-level risk gate (spec §D). Runs BEFORE risk-officer so a
    # symbol+bucket+gross check happens even if USE_RISK_OFFICER=false.
    pr_ok, pr_failed, pr_warns = _portfolio_risk_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price, asset_class="us_equity",
    )
    if not pr_ok:
        print(f"  PORTFOLIO-RISK REJECT {symbol}: {'; '.join(pr_failed)}")
        return None
    for w in pr_warns:
        print(f"  portfolio-risk warn: {w}")

    # IntradayProfitGovernor gate (spec §11 entry-monitor gating). Blocks
    # new entries during DEFEND_DAY / RED_DAY_AFTER_GREEN and below-score
    # entries during PROFIT_LOCK. Audit event written if blocked.
    ig_score = None  # caller may pass score via kwargs (future); see place_simple_buy
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price,
        asset_class="us_equity", score=ig_score,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol}: {ig_reason}")
        return None

    # PDT gate — preventive layer above risk_officer's BP check. Blocks new
    # entries when account is in LOCKED state (BP < required) so monitors
    # don't keep spamming Alpaca with 403-bound orders.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price,
        asset_class="us_equity",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol}: {pdt_reason}")
        return None

    # Risk-officer gate (opt-out via USE_RISK_OFFICER=false). Hard violations
    # block the trade; soft warnings are logged but don't reject. Fail-soft
    # if the officer module is unavailable for any reason — proceed to place.
    try:
        from risk_officer import evaluate_trade  # noqa: E402
        verdict = evaluate_trade({
            "symbol":      symbol,
            "action":      "BUY" if side == "buy" else "SELL_SHORT",
            "size_usd":    qty * entry_price,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "strategy":    strategy,
        })
        if verdict.get("decision") == "REJECT":
            print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
            for f in verdict.get("checks_failed", []):
                print(f"    - {f}")
            return None
        if verdict.get("warnings"):
            print(f"  risk-officer warnings ({symbol}):")
            for w in verdict["warnings"]:
                print(f"    - {w}")
    except Exception as e:
        print(f"  risk-officer unavailable ({type(e).__name__}: {e}); proceeding")

    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(entry_price, 2)),
        "time_in_force":  "day",
        "order_class":    "bracket",
        "take_profit":    {"limit_price": str(round(take_profit, 2))},
        "stop_loss":      {"stop_price":  str(round(stop_loss, 2))},
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca bracket error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca bracket exception: {e}")
        return None


def place_crypto_order(symbol: str, side: str, qty: float,
                       limit_price: float,
                       strategy: str = "auto") -> dict | None:
    """
    Place a simple limit order for crypto (Alpaca crypto does NOT support
    bracket / OCO).

    SL/TP must be managed separately — exit-monitor's crypto thresholds
    (CRYPTO_DECAY_HOURS=48 in v2.0, plus per-position trailing) handle
    exit timing.
    """
    if qty <= 0 or limit_price <= 0:
        return None
    if side not in ("buy", "sell"):
        return None

    # Per-instrument trading window gate.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="crypto")
    if not ok:
        print(f"  crypto reject {symbol}: trade-window — {reason}")
        return None

    # Portfolio-level risk gate (spec §D).
    pr_ok, pr_failed, pr_warns = _portfolio_risk_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price, asset_class="crypto",
    )
    if not pr_ok:
        print(f"  PORTFOLIO-RISK REJECT {symbol}: {'; '.join(pr_failed)}")
        return None
    for w in pr_warns:
        print(f"  portfolio-risk warn: {w}")

    # IntradayProfitGovernor gate — same contract as stocks. Crypto trades
    # 24/7 so this is especially important after a red close on Friday
    # ratcheted us into DEFEND_DAY: weekend crypto entries would otherwise
    # silently rebuild exposure we just spent the session reducing.
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price,
        asset_class="crypto", score=None,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol}: {ig_reason}")
        return None

    # PDT gate (crypto exempt from PDT rule, but BP-locked state still
    # blocks here when buying_power < size_usd). Allows clean refusal
    # before broker 403s.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price,
        asset_class="crypto",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol}: {pdt_reason}")
        return None

    # Risk-officer gate. Crypto orders don't carry SL/TP at the broker
    # (Alpaca crypto = simple limit only); we pass the strategy-level
    # values so the officer can validate R:R and per-trade size.
    try:
        from risk_officer import evaluate_trade  # noqa: E402
        # For crypto, look up SL/TP from strategy defaults if available.
        # If caller didn't compute them, the officer treats no-TP as a
        # soft-warning trailing-exit assumption (won't reject).
        verdict = evaluate_trade({
            "symbol":      symbol,
            "action":      "BUY" if side == "buy" else "SELL_SHORT",
            "size_usd":    qty * limit_price,
            "entry_price": limit_price,
            "stop_loss":   limit_price * 0.93 if side == "buy" else limit_price * 1.07,
            "take_profit": limit_price * 1.20 if side == "buy" else limit_price * 0.80,
            "strategy":    strategy,
        })
        if verdict.get("decision") == "REJECT":
            print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
            for f in verdict.get("checks_failed", []):
                print(f"    - {f}")
            return None
        if verdict.get("warnings"):
            print(f"  risk-officer warnings ({symbol}):")
            for w in verdict["warnings"]:
                print(f"    - {w}")
    except Exception as e:
        print(f"  risk-officer unavailable ({type(e).__name__}: {e}); proceeding")

    payload = {
        "symbol":         symbol,
        "qty":            str(qty),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "gtc",   # crypto requires gtc
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca crypto order error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca crypto order exception: {e}")
        return None


def place_simple_buy(symbol: str, qty: int, limit_price: float,
                     strategy: str = "auto",
                     score: float | None = None) -> dict | None:
    """
    Simple limit BUY for instruments that don't support brackets.
    Used by options-monitor (Alpaca paper rejects bracket on options).

    `score` is the entry signal's composite score [0..1]. When the intraday
    governor is in PROFIT_LOCK, scores below profit_lock_min_score_override
    (default 0.65) are blocked — only very high-conviction setups punch
    through. Pass score=None to be treated as "low conviction" (blocked).
    """
    if qty < 1 or limit_price <= 0:
        return None

    # Per-instrument trading window gate (options trade only during regular
    # equity session).
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="us_option")
    if not ok:
        print(f"  simple_buy reject {symbol}: trade-window — {reason}")
        return None

    # IntradayProfitGovernor gate. Options are reduced FIRST in PROFIT_LOCK
    # cascade so new options entries during a giveback are particularly
    # contraindicated (they bleed fast and worsen the very state we're
    # protecting against).
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side="buy", size_usd=qty * limit_price,
        asset_class="us_option", score=score,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol} (options): {ig_reason}")
        return None

    # PDT gate — options ARE subject to PDT and burn day-trade count fast.
    # When account is RESTRICTED, opening options is allowed but the
    # exit-monitor will defer same-day closes via its own pdt_guard check.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side="buy", size_usd=qty * limit_price,
        asset_class="us_option",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol} (options): {pdt_reason}")
        return None

    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           "buy",
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "day",
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca simple buy error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca simple buy exception: {e}")
        return None


# ─── High-level signal-to-order adapter ───────────────────────────────────────

def execute_stock_signal(signal: dict) -> dict | None:
    """
    Convert a monitor's signal dict into a bracket order via Alpaca.

    Expected `signal` shape (matches what monitors produce today):
      {
        "symbol":      "RTX",
        "action":      "BUY" | "SELL_SHORT",
        "size_usd":    8000,
        "stop_loss":   absolute_price OR None (then we use sl_pct),
        "take_profit": absolute_price OR None,
        "sl_pct":      e.g. -5.0  (used when stop_loss is None)
        "tp_pct":      e.g. +12.0
        "strategy":    name string
      }

    Returns Alpaca order on success, None on any failure (caller falls
    through to email-only logging).
    """
    sym       = signal["symbol"]
    action    = signal["action"]
    size_usd  = float(signal.get("size_usd", 0))
    strategy  = signal.get("strategy", "auto")

    if size_usd <= 0:
        print(f"  {sym}: size_usd={size_usd} -> skip")
        return None

    # Per-instrument trading window gate (v3.2 — single source of truth in
    # config/instrument_windows.json). Checks (1) per-symbol pause and
    # (2) market hours. Replaces the old inline is_us_market_open call.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(sym, asset_class="us_equity")
    if not ok:
        print(f"  {sym}: trade-window blocked — {reason}")
        return {"deferred": True, "reason": reason, "symbol": sym}

    side = "buy" if action.upper() == "BUY" else "sell_short"

    # If signal already has absolute SL/TP, use them. Else compute from %.
    sl_abs = signal.get("stop_loss")
    tp_abs = signal.get("take_profit")
    entry  = None

    if sl_abs and tp_abs:
        # Need a fresh entry price. Use mid of latest quote.
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        entry = q["mid"]
    else:
        # Fallback path: SL/TP given as percentages
        sl_pct = float(signal.get("sl_pct", 0))
        tp_pct = float(signal.get("tp_pct", 0))
        if not sl_pct or not tp_pct:
            print(f"  {sym}: missing SL/TP -> skip")
            return None
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        entry = q["mid"]
        if side == "buy":
            sl_abs = entry * (1 + sl_pct / 100.0)   # sl_pct is negative
            tp_abs = entry * (1 + tp_pct / 100.0)
        else:
            sl_abs = entry * (1 - sl_pct / 100.0)
            tp_abs = entry * (1 - tp_pct / 100.0)

    qty = max(1, int(size_usd / entry))

    return place_stock_bracket(
        symbol      = sym,
        side        = side,
        qty         = qty,
        entry_price = entry,
        stop_loss   = round(sl_abs, 2),
        take_profit = round(tp_abs, 2),
        strategy    = strategy,
    )


def execute_crypto_signal(signal: dict) -> dict | None:
    """
    Crypto entry: simple limit at mid. SL/TP managed by exit-monitor
    crypto thresholds (Alpaca crypto = no bracket support).
    """
    sym      = signal["symbol"]
    action   = signal["action"]
    size_usd = float(signal.get("size_usd", 0))
    strategy = signal.get("strategy", "crypto-momentum")

    if size_usd <= 0:
        return None

    # Per-instrument trading window gate. Crypto is 24/7 so default-allow,
    # but per-symbol pause (instrument_overrides) still applies.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(sym, asset_class="crypto")
    if not ok:
        print(f"  {sym}: trade-window blocked — {reason}")
        return {"deferred": True, "reason": reason, "symbol": sym}

    side = "buy" if action.upper() in ("BUY", "BUY_TO_OPEN") else "sell"

    q = get_latest_crypto_quote(sym)
    if not q:
        print(f"  {sym}: crypto quote unavailable -> skip")
        return None
    entry = q["mid"]
    qty = round(size_usd / entry, 4)
    if qty <= 0:
        return None

    return place_crypto_order(
        symbol      = sym,
        side        = side,
        qty         = qty,
        limit_price = entry,
        strategy    = strategy,
    )

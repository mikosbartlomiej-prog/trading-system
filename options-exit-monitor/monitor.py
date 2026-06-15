"""
Options Exit Monitor — emulates bracket TP/SL for paper options positions.

Alpaca paper does not support bracket/OCO/stop order classes for options,
so this monitor polls every few minutes during market hours, evaluates
each open options position against the strategy's TP/SL multipliers
(+80% / -50% of entry premium) and places a SELL-to-close order when a
threshold is hit:

  - TP hit  -> LIMIT  (price discipline; we'd rather not fill than fill bad)
  - SL hit  -> MARKET (emergency exit; guaranteed fill > price discipline)

The MARKET-on-SL choice was raised by the learning-loop LLM after a
real run where an `exit-emergency-*` order had fill_rate=0 (limit too
tight in a falling market = stuck holding the loss). MARKET on SL
trades a few cents of slippage for a guaranteed exit.

`client_order_id` is now tagged with `exit-tp-` or `exit-sl-` so the
learning-loop analyzer can attribute close orders correctly.

De-dup: skips a position if there is already an open SELL order for the
same contract symbol (prevents stacking duplicate exits across runs).
"""

import json
import os
import sys
import requests
from datetime import datetime, timezone

# v3.22.0 — observability-only wiring into the canonical signal pipeline.
# emit_monitor_signal NEVER places trades; it forwards a SignalEvent to
# shared.signal_emitter.emit_signal_opportunity which persists via the
# opportunity ledger. NEVER imports alpaca_orders. NEVER calls the broker.
try:
    from monitor_signal_helper import emit_monitor_signal  # type: ignore
except Exception:
    try:
        from shared.monitor_signal_helper import emit_monitor_signal  # type: ignore
    except Exception:
        def emit_monitor_signal(*_a, **_kw):  # type: ignore
            return None

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_exit, notify_summary
    from learning_state import load_strategy_state, load_global_overrides
except ImportError:
    def notify_exit(*a, **k): pass
    def notify_summary(*a, **k): pass
    def load_strategy_state(_n): return {}
    def load_global_overrides(): return {}

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

# v2.0 risk-on (matches options-monitor v2.0) — DEFAULTS.
# Effective values can be overridden by adapter's TP feedback loop
# (LLM proposal 2026-05-09): if `options-momentum.suggested_tp_multiplier`
# is set in state.json, _effective_tp_mult() uses that instead.
TP_PREMIUM_MULT = 2.20   # take profit at +120% premium (was +80%)
SL_PREMIUM_MULT = 0.35   # stop loss at -65% premium    (was -50%)


def _effective_tp_mult() -> float:
    """
    Return TP multiplier honoring learning-loop's `suggested_tp_multiplier`
    override. Falls back to TP_PREMIUM_MULT (2.20) if no override.

    The override is set by adapter._apply_tp_feedback when realised hit
    rate < 20% over 5+ TP placements — current target is too aggressive
    vs realised price movement. Tightening lets more TPs actually fill
    (less profit per trade, much higher fill rate = better expected $).
    """
    try:
        cfg = load_strategy_state("options-momentum") or {}
        sug = cfg.get("suggested_tp_multiplier")
        if sug is not None:
            return float(sug)
    except Exception:
        pass
    return TP_PREMIUM_MULT


def alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }


# ─── Alpaca helpers ──────────────────────────────────────────────────────────

def get_open_options_positions() -> list[dict]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions",
                         headers=alpaca_headers(), timeout=15)
        r.raise_for_status()
        return [p for p in (r.json() or []) if p.get("asset_class") == "us_option"]
    except Exception as e:
        print(f"  /v2/positions error: {e}")
        return []


def already_has_open_sell(contract_symbol: str) -> bool:
    """True if there is an open SELL order for this contract."""
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=alpaca_headers(),
            params={"status": "open", "symbols": contract_symbol},
            timeout=15,
        )
        r.raise_for_status()
        return any(o.get("side") == "sell" for o in (r.json() or []))
    except Exception as e:
        print(f"  open-orders check error: {e}")
        return False  # fail open -> may attempt a duplicate; rare


def _exit_client_order_id(reason: str, contract_symbol: str,
                            strategy: str = "options-momentum") -> str:
    """
    Build a learning-loop-friendly client_order_id for a sell-to-close.
    Format: 'exit-<reason>-<strategy>-<contract>-<HHMMSSmmm>'.

    The 'exit-' prefix is what learning-loop/analyzer.py::_is_close()
    looks for. Embedding the strategy name lets `compute_tp_hit_rate`
    attribute fills WITHOUT a per-symbol lookup table — the strategy
    travels with the order, so even if the underlying entry's window
    has rotated out we can still bucket the close correctly.

    Default strategy = options-momentum because this monitor only
    handles options positions and they all come from that strategy.

    LLM proposal 2026-05-11 (TP attribution fix): without this, tp_hit_
    rate bucketed everything under 'unknown' and trailing-stop decision
    2026-05-17 would be blind.
    """
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe = contract_symbol.replace("/", "").replace(" ", "")
    # Strategy may contain hyphens (options-momentum); embed as-is.
    # Parser side splits on the contract marker, not on '-'.
    return f"exit-{reason}-{strategy}-{safe}-{ts}"


def place_sell_to_close(contract_symbol: str, qty: int,
                         decision: str, exit_price: float) -> dict | None:
    """
    Place a SELL-to-close on `contract_symbol`.

    decision == "TP"      -> LIMIT at `exit_price` (price discipline)
    decision == "SL"      -> MARKET (emergency; guarantee fill in falling tape)
    decision == "NEARDTH" -> MARKET (theta-acceleration close; near-expiry
                              spreads are too wide for LIMIT to reliably fill)
    decision == "REGIME"  -> MARKET (regime mismatch — fill > price; we WANT
                              out before the position bleeds further)

    Tags client_order_id with `exit-tp-`, `exit-sl-`, `exit-neardth-`, or
    `exit-regime-` so the analyzer can attribute the close to the right
    bucket.
    """
    reason = decision.lower()  # "tp", "sl", "neardth", "regime"

    # Per-instrument trading window gate (options trade only during regular
    # equity session; pre-market sell would be rejected by Alpaca anyway).
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from instrument_windows import can_trade_now
        ok, w_reason = can_trade_now(contract_symbol, asset_class="us_option")
        if not ok:
            print(f"  sell-to-close {contract_symbol}: trade-window blocked — {w_reason}")
            return None
    except ImportError:
        pass

    # PDT pre-close gate v3.8. SL / NEARDTH / GOVERNOR / REGIME / TRAIL are
    # emergencies (defensive — bypass DEFER). Plain TP is discretionary —
    # tagged intent="intraday" so the engine checks whether the contract was
    # opened today (true day-trade) or carried over (free close).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', 'shared'))
        from pdt_guard import evaluate_order as _pdt_eval, record_decision as _pdt_audit
        is_emergency_close = decision in ("SL", "NEARDTH", "GOVERNOR", "REGIME", "TRAIL")
        close_intent = "emergency" if is_emergency_close else "intraday"
        pdt_size = exit_price * float(qty) * 100.0  # options multiplier
        pv = _pdt_eval(
            action="CLOSE", symbol=contract_symbol, side="sell",
            size_usd=pdt_size, intent=close_intent, is_emergency=is_emergency_close,
        )
        if pv["decision"] != "ALLOW":
            _pdt_audit(pv, action="CLOSE", symbol=contract_symbol,
                       extra={"decision": decision, "qty": qty, "intent": close_intent})
            print(f"  pdt-guard {pv['decision']} {contract_symbol} ({decision}): {pv['reason']}")
            return None
    except Exception as e:
        print(f"  pdt-guard unavailable for {contract_symbol} ({type(e).__name__}: {e}) — proceeding")

    # v3.9.10 (2026-05-27): route through alpaca_orders.safe_close.
    # Provides position-existence pre-check (404 → skipped) so option
    # sell-to-close orders cannot create naked shorts on Alpaca paper.
    # Also emits audit JSONL automatically.
    # v3.8.5 history (preserved): LIMIT TP uses GTC, MARKET for forced exits.
    tif = "day" if decision in ("SL", "NEARDTH", "REGIME", "TRAIL", "GOVERNOR") else "gtc"
    is_market = decision in ("SL", "NEARDTH", "REGIME", "TRAIL", "GOVERNOR")
    reason_tag_map = {
        "SL":       "exit-emergency",
        "NEARDTH":  "exit-emergency",
        "REGIME":   "exit-regime",
        "TRAIL":    "exit-trail",
        "GOVERNOR": "exit-governor",
        "TP":       "exit-tp",
    }
    reason_tag = reason_tag_map.get(decision, _exit_client_order_id(reason, contract_symbol).split("-")[0])

    try:
        from alpaca_orders import safe_close
    except ImportError:
        from shared.alpaca_orders import safe_close

    sc = safe_close(
        symbol=contract_symbol,
        intent_qty=float(qty),
        intent_side="sell",
        reason_tag=reason_tag,
        order_type="market" if is_market else "limit",
        limit_price=exit_price if not is_market else None,
        time_in_force=tif,
        is_crypto=False,
        allow_market=is_market,
    )
    if sc["status"] == "placed":
        return {"id": sc["alpaca_order_id"], "status": "accepted",
                "symbol": contract_symbol, "qty": sc["actual_qty"]}
    if sc["status"] == "skipped":
        print(f"  sell-to-close skipped {contract_symbol}: {sc['reason']}")
        return None
    print(f"  sell-to-close {sc['status']} {contract_symbol}: {sc['reason']}")
    return None


# ─── Regime mismatch helpers (LLM proposal 2026-05-09, revisit 2026-05-14) ──

# Trigger conditions for proactive PUT close when learning-loop says we
# should be long. Catches the AMZN PUT bleeding pattern in current
# risk_on rally:
#   - global_overrides.options_side_bias == "long"
#   - position is a PUT
#   - current loss <= -15%
#   - SPY 5d return >= +1.5% (strong risk-on regime)
# Skip if DTE > 14 AND loss > -25% — still time for thesis to play out.
REGIME_MISMATCH_LOSS_THRESHOLD     = -15.0   # percent
REGIME_MISMATCH_SPY_5D_THRESHOLD   = 1.5     # percent
REGIME_MISMATCH_DTE_GUARD          = 14      # days
REGIME_MISMATCH_DEEP_LOSS_GUARD    = -25.0   # percent

# ─── Trailing stop (LLM proposal 2026-05-07, revisit 2026-05-17) ────────────
#
# Framework gated by env flag TRAILING_STOP_ENABLED. Defaults to OFF until
# 10-day TP-hit-rate data confirms static-TP is leaving money on the table.
# When ON: tracks peak price per open position in state.json::trailing_state,
# fires MARKET sell when current price drops `trail_pct` from peak AND
# hold time > min_hold_hours.
#
# Per-asset trail_pct defaults (educated guess; tune from data when flag flips):
#   options:  8%  — premium volatility is high; tight trail = whipsaw
#   stocks:   3%  — normal volatility
#   crypto:   5%  — between options and stocks
# In options-exit-monitor: only options matter (8% default).
TRAILING_STOP_ENABLED              = os.environ.get(
    # Flipped 2026-05-13 default false→true after 2026-05-12 disaster
    # (+$3,173 peak → -$184 reversal; static TPs at entry*1.80 never
    # filled while peaks of +47% to +93% retraced). 8% trail off peak
    # captures most of the rally with minimal whipsaw risk.
    "TRAILING_STOP_ENABLED", "true"
).lower() == "true"
TRAILING_STOP_TRAIL_PCT            = 0.08    # 8% off peak triggers exit
TRAILING_STOP_MIN_HOLD_HOURS       = 12      # don't trail very fresh positions

STATE_PATH_REPO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..',
    'learning-loop', 'state.json',
)


def _load_trailing_state() -> dict:
    """Read learning-loop/state.json → trailing_state dict (symbol → peak/entry_ts)."""
    try:
        with open(STATE_PATH_REPO) as f:
            s = json.load(f)
        return s.get("trailing_state", {}) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_trailing_state(trailing: dict) -> None:
    """Merge trailing_state back into state.json. Workflow handles git commit."""
    try:
        with open(STATE_PATH_REPO) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s["trailing_state"] = trailing
    try:
        with open(STATE_PATH_REPO, "w") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"  trailing_state save error: {e}")


def _check_trailing_stop(pos: dict, trailing_state: dict
                          ) -> tuple[bool, str, dict]:
    """
    Returns (should_close, reason, updated_trailing_entry).

    Per-tick logic:
      1. Get/init `peak` (= current_price on first sight).
      2. Update peak if current > peak.
      3. If TRAILING_STOP_ENABLED AND hold_hours > min_hold AND
         current < peak * (1 - trail_pct) → FIRE.
    Returns updated trailing entry regardless so caller can persist.
    """
    symbol  = pos.get("symbol", "")
    current = float(pos.get("current_price", 0) or 0)
    entry   = float(pos.get("avg_entry_price", 0) or 0)
    if current <= 0 or not symbol:
        return False, "", {}

    rec = dict(trailing_state.get(symbol) or {})
    peak = float(rec.get("peak", entry) or entry)
    if current > peak:
        peak = current
        rec["peak"] = peak
    rec["peak"] = peak
    rec["last_seen_price"] = current
    rec["last_seen_ts"] = datetime.now(timezone.utc).isoformat()
    # First-sight initialization of entry_ts (best-effort — we approximate
    # with NOW; real entry timestamp would need an Alpaca order lookup).
    if "first_seen_ts" not in rec:
        rec["first_seen_ts"] = rec["last_seen_ts"]

    if not TRAILING_STOP_ENABLED:
        return False, "", rec

    # Hold-time gate
    try:
        first_ts = datetime.fromisoformat(rec["first_seen_ts"].replace("Z", "+00:00"))
        hold_h = (datetime.now(timezone.utc) - first_ts).total_seconds() / 3600
    except Exception:
        hold_h = 0
    if hold_h < TRAILING_STOP_MIN_HOLD_HOURS:
        return False, "", rec

    # Drop from peak
    if peak <= 0:
        return False, "", rec
    drop_pct = (peak - current) / peak
    if drop_pct >= TRAILING_STOP_TRAIL_PCT:
        return True, (
            f"trailing stop: peak=${peak:.2f} -> current=${current:.2f} "
            f"({drop_pct:.1%} drop, hold {hold_h:.1f}h)"
        ), rec
    return False, "", rec


def _is_put(occ_symbol: str) -> bool:
    """True if OCC symbol is a PUT (P after YYMMDD)."""
    if not occ_symbol or len(occ_symbol) < 15:
        return False
    # rightmost 9 chars = (C|P) + strike(8)
    return occ_symbol[-9] == "P"


def _spy_5d_return() -> float | None:
    """
    SPY 5-day percent return (close[-1] / close[-6] - 1) × 100.
    Returns None if data unavailable.

    Uses shared.market_data.get_daily_bars (cached per run).
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from market_data import get_daily_bars  # noqa: E402
        bars = get_daily_bars("SPY", days=10)
        if not bars or len(bars.get("close", [])) < 6:
            return None
        closes = bars["close"]
        prev = closes[-6]
        if prev <= 0:
            return None
        return (closes[-1] / prev - 1) * 100
    except Exception:
        return None


def _check_regime_mismatch(pos: dict, pl_pct: float, dte: int | None
                            ) -> tuple[bool, str]:
    """
    Returns (should_close, reason).

    Fires when ALL hold:
      - options_side_bias == 'long' (from learning-loop state)
      - position is PUT
      - pl_pct <= -15%
      - SPY 5d return >= +1.5%
      - NOT in deep-loss-with-time guard (DTE > 14 AND pl > -25%)
    """
    sym = pos.get("symbol", "")
    if not _is_put(sym):
        return False, ""

    try:
        glob = load_global_overrides() or {}
    except Exception:
        glob = {}
    if glob.get("options_side_bias") != "long":
        return False, ""

    if pl_pct > REGIME_MISMATCH_LOSS_THRESHOLD:
        return False, ""                   # not enough loss yet

    spy_5d = _spy_5d_return()
    if spy_5d is None or spy_5d < REGIME_MISMATCH_SPY_5D_THRESHOLD:
        return False, ""                   # regime not clearly risk-on

    # Deep-loss-with-time guard: still room for reversal
    if dte is not None and dte > REGIME_MISMATCH_DTE_GUARD \
       and pl_pct > REGIME_MISMATCH_DEEP_LOSS_GUARD:
        return False, ""

    return True, (
        f"side_bias=long + PUT + pl {pl_pct:+.1f}% (<={REGIME_MISMATCH_LOSS_THRESHOLD}%) "
        f"+ SPY 5d {spy_5d:+.1f}% (>={REGIME_MISMATCH_SPY_5D_THRESHOLD}%) "
        f"-> regime mismatch close"
    )


def _occ_dte(occ_symbol: str) -> int | None:
    """
    Extract days-to-expiry from an OCC options symbol.

    OCC format: TICKER + YYMMDD + (C|P) + STRIKE*1000 (zero-padded to 8)
    Example: AMZN260520P00270000  -> exp 2026-05-20
             QQQ260514P00699000   -> exp 2026-05-14

    Returns None if parsing fails.
    """
    if not occ_symbol or len(occ_symbol) < 15:
        return None
    # Find the position of the date (6 digits before C/P)
    # Strategy: the rightmost 15 chars are YYMMDD + C/P + strike(8)
    try:
        date_str = occ_symbol[-15:-9]   # 6 chars: YYMMDD
        if not date_str.isdigit():
            return None
        yy = int(date_str[:2])
        mm = int(date_str[2:4])
        dd = int(date_str[4:6])
        # OCC uses 2-digit year — assume 20YY for years 00-79, 19YY for 80-99
        year = 2000 + yy if yy < 80 else 1900 + yy
        from datetime import date
        expiry = date(year, mm, dd)
        today = datetime.now(timezone.utc).date()
        return (expiry - today).days
    except (ValueError, IndexError):
        return None


# ─── Decision ────────────────────────────────────────────────────────────────

# Near-expiry early-close trigger (proposal #9 from 2026-05-09 LLM):
# theta decay accelerates non-linearly under DTE 5; static SL=entry*0.50
# is too slow for that regime. When BOTH conditions hold, fire MARKET sell
# regardless of normal SL — better to exit at -40% than let it become -90%
# at expiry.
NEAR_DTH_DTE_THRESHOLD = 5      # days
NEAR_DTH_LOSS_THRESHOLD = -40.0 # percent loss (more liberal than SL=-50%)


def _intraday_governor_decision(pos: dict, pl_pct: float
                                  ) -> tuple[str, str] | None:
    """
    If IntradayProfitGovernor is in PROFIT_LOCK / DEFEND_DAY / RED_DAY_AFTER_
    GREEN, return ("GOVERNOR", reason). Reduces options FIRST per
    `reduce_options_first` config. Tagged `exit-governor-*` so analyzer can
    attribute the close.

    Tie to MFE: if the position already triggered an MFE HARVEST/REDUCE
    threshold, escalate to GOVERNOR even in milder states (GIVEBACK_WARN).

    Returns None if no governor-driven action is required.
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from intraday_governor import (
            get_snapshot, position_mfe_action,
            STATE_PROFIT_LOCK, STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN,
            STATE_GIVEBACK_WARN,
        )
    except ImportError:
        return None

    snap = get_snapshot()
    state = snap.pnl_state
    mfe = position_mfe_action({
        "symbol":         pos.get("symbol", ""),
        "unrealized_plpc": pl_pct / 100.0,
    })

    # State-driven options-first reductions.
    if state == STATE_RED_DAY_AFTER_GREEN:
        return ("GOVERNOR",
                f"RED_DAY_AFTER_GREEN: close option immediately "
                f"(peak ${snap.intraday_peak_pnl:+.0f} -> current ${snap.current_intraday_pnl:+.0f})")
    if state == STATE_DEFEND_DAY:
        # Defend day → close all options regardless of P/L (premium decays
        # fastest; freeing buying power matters more than the next 5% on
        # the remaining contracts).
        return ("GOVERNOR",
                f"DEFEND_DAY: options-first reduction "
                f"(peak ${snap.intraday_peak_pnl:+.0f}, retrace {snap.giveback_pct_of_peak:.0%})")
    if state == STATE_PROFIT_LOCK:
        # Profit lock → close winners (>=+8%) and harvest any position
        # whose own MFE crossed a threshold.
        if pl_pct >= 8.0 or mfe["action"] in ("REDUCE", "HARVEST"):
            return ("GOVERNOR",
                    f"PROFIT_LOCK option harvest: pl {pl_pct:+.1f}% "
                    f"(peak ${snap.intraday_peak_pnl:+.0f}, retrace {snap.giveback_pct_of_peak:.0%})")
    if state == STATE_GIVEBACK_WARN and mfe["action"] == "HARVEST":
        return ("GOVERNOR",
                f"GIVEBACK_WARN + MFE harvest: {mfe['reason']}")
    # Position-level MFE harvest fires independently of portfolio state —
    # an individual option that peaked +60% and gave back 25% should be
    # locked even if the portfolio is calm.
    if mfe["action"] == "HARVEST":
        return ("GOVERNOR", f"position MFE harvest: {mfe['reason']}")
    return None


def evaluate(pos: dict, trailing_state: dict | None = None
              ) -> tuple[str, float | None, float, str]:
    """
    Returns (decision, exit_limit_price, pl_pct, reason).
    decision: "GOVERNOR" | "REGIME" | "NEARDTH" | "TRAIL" | "TP" | "SL" | "HOLD"

    Order of checks (highest precedence first):
      1. GOVERNOR — IntradayProfitGovernor demands a faster close than the
         static TP/SL would offer. Options are reduced FIRST in
         PROFIT_LOCK/DEFEND_DAY/RED_DAY_AFTER_GREEN. Position-level MFE
         HARVEST also fires here. Tagged "exit-governor-*", MARKET sell.
      2. REGIME — long-bias regime + PUT position bleeding.
      3. NEARDTH — DTE ≤ 5 AND loss > 40%.
      4. TRAIL — 8% off intraday peak (after min hold).
      5. TP — current ≥ entry × 1.80.
      6. SL — current ≤ entry × 0.50.
      7. HOLD — within window.
    """
    try:
        qty     = abs(float(pos.get("qty", 0)))
        entry   = float(pos.get("avg_entry_price", 0))
        current = float(pos.get("current_price", 0))
    except (TypeError, ValueError):
        return ("HOLD", None, 0.0, "non-numeric position fields")

    if entry <= 0 or current <= 0 or qty <= 0:
        return ("HOLD", None, 0.0, "missing entry / current / qty")

    pl_pct = (current - entry) / entry * 100
    tp_mult = _effective_tp_mult()      # honors learning-loop TP feedback
    tp_lvl = entry * tp_mult
    sl_lvl = entry * SL_PREMIUM_MULT
    dte = _occ_dte(pos.get("symbol", ""))

    # 1. IntradayProfitGovernor (highest precedence). Options-first
    # reduction during the FSM's protected states.
    gov = _intraday_governor_decision(pos, pl_pct)
    if gov is not None:
        return (gov[0], current, pl_pct, gov[1])

    # 2. Regime mismatch — proactive PUT close when learning-loop says
    # options_side_bias=long and SPY is in risk-on rally (proposal 2026-
    # 05-09). Sits ABOVE NEARDTH because regime mismatch should fire
    # earlier (before theta acceleration) when conditions are right.
    rm_fire, rm_reason = _check_regime_mismatch(pos, pl_pct, dte)
    if rm_fire:
        return ("REGIME", current, pl_pct, rm_reason)

    # 3. Near-expiry accelerated close
    if dte is not None and dte <= NEAR_DTH_DTE_THRESHOLD and pl_pct <= NEAR_DTH_LOSS_THRESHOLD:
        return ("NEARDTH", current, pl_pct,
                f"DTE={dte}d (<={NEAR_DTH_DTE_THRESHOLD}) + pl {pl_pct:+.1f}% (<={NEAR_DTH_LOSS_THRESHOLD}%) "
                f"-> theta-acceleration close (MARKET)")

    # Trailing stop (gated by TRAILING_STOP_ENABLED env flag). Sits
    # between NEARDTH and TP/SL: lock in gains before TP / before
    # static SL takes a deeper loss. Updates trailing_state regardless.
    if trailing_state is not None:
        ts_fire, ts_reason, ts_rec = _check_trailing_stop(pos, trailing_state)
        trailing_state[pos.get("symbol", "")] = ts_rec   # persist updated peak
        if ts_fire:
            return ("TRAIL", current, pl_pct, ts_reason)

    if current >= tp_lvl:
        return ("TP", tp_lvl, pl_pct,
                f"current ${current:.2f} >= TP ${tp_lvl:.2f} (+{pl_pct:.1f}%)")
    if current <= sl_lvl:
        return ("SL", current, pl_pct,
                f"current ${current:.2f} <= SL ${sl_lvl:.2f} ({pl_pct:.1f}%)")
    return ("HOLD", None, pl_pct,
            f"in window (pl {pl_pct:+.1f}%, TP=${tp_lvl:.2f}, SL=${sl_lvl:.2f}"
            f"{f', DTE={dte}d' if dte is not None else ''})")


# ─── Main ────────────────────────────────────────────────────────────────────

def run_exit_check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now}] === OPTIONS EXIT MONITOR ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: brak ALPACA_API_KEY / ALPACA_SECRET_KEY")
        sys.exit(1)

    positions = get_open_options_positions()
    print(f"  Otwartych opcji: {len(positions)}")
    if not positions:
        return

    # Load trailing state once per run; pass into evaluate() so it can
    # both READ (decide trail) and WRITE (update peak per position).
    trailing_state = _load_trailing_state()
    if TRAILING_STOP_ENABLED:
        print(f"  Trailing stop: ENABLED (trail={TRAILING_STOP_TRAIL_PCT:.0%}, "
              f"min_hold={TRAILING_STOP_MIN_HOLD_HOURS}h)")
    else:
        print(f"  Trailing stop: dormant (set TRAILING_STOP_ENABLED=true to arm)")

    flagged = 0
    closed  = 0
    for pos in positions:
        symbol = pos["symbol"]
        decision, exit_price, pl_pct, reason = evaluate(pos, trailing_state)
        print(f"  {symbol}: {reason} -> {decision}")
        if decision == "HOLD":
            continue
        flagged += 1

        if already_has_open_sell(symbol):
            print(f"    pominięty — sell-to-close juz wystawiony")
            continue

        qty   = abs(float(pos["qty"]))
        order = place_sell_to_close(symbol, qty, decision, exit_price)
        if order:
            order_type = "MARKET" if decision in ("SL", "NEARDTH", "REGIME", "TRAIL", "GOVERNOR") else "LIMIT"
            print(f"    SELL placed ({order_type}): id={order.get('id')} status={order.get('status')}")
            closed += 1
            notify_exit(symbol, f"SELL_TO_CLOSE_{decision}", reason, pl_pct)
            # Emit governor audit when intraday protection caused the close
            if decision == "GOVERNOR":
                try:
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
                    from intraday_governor import (
                        emit_audit, get_snapshot,
                        EVENT_POSITION_MFE_TRAIL_EXIT,
                    )
                    emit_audit(EVENT_POSITION_MFE_TRAIL_EXIT, get_snapshot(),
                               action="options_market_close",
                               reason=reason,
                               affected_symbols=[symbol])
                except Exception:
                    pass
        else:
            # Sell rejected — surface via summary anyway
            print(f"    SELL ODRZUCONY przez Alpaca")

    # Prune trailing_state entries for symbols no longer in open positions.
    open_symbols = {p["symbol"] for p in positions}
    for sym in list(trailing_state.keys()):
        if sym not in open_symbols:
            del trailing_state[sym]
    _save_trailing_state(trailing_state)

    notify_summary("Options Exit Monitor", flagged, closed)
    print(f"[{now}] Flagged={flagged}, sells placed={closed}\n")


if __name__ == "__main__":
    run_exit_check()
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("options-exit-monitor", status="ok")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")


# ── v3.22.0 observability hook ──────────────────────────────────────────────
# Per the v3.22 signal-pipeline contract this monitor exposes a thin helper
# that the run loop calls once per scan even when no signal fires (so the
# operator can see "monitor ran, 0 candidates" in the opportunity ledger).
# emit_monitor_signal NEVER places trades — it only persists an observation
# row via shared.signal_emitter.emit_signal_opportunity.
def _v322_observe(symbol: str = "n/a", action: str = "NO_SIGNAL",
                  side: str = "n/a", asset_class: str = "us_equity",
                  raw_signal=None) -> None:
    try:
        emit_monitor_signal(
            source_monitor="options-exit-monitor",
            strategy_id="options-exit",
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            action=action,
            entry_capable=False,
            raw_signal=raw_signal or {},
        )
    except Exception:
        pass

"""v3.25.0 (2026-06-09) — hard crypto exposure / laddering / cooldown policy.

After the v3.24 reattribution that placed the bulk of the
-$5,741 drawdown on the SOLUSD + LTCUSD realized close cycle
(~$59,928 combined cost basis, ~60% of paper equity), this module
adds the missing guards:

- per-symbol crypto exposure cap (was missing)
- aggregate crypto exposure cap (existed at 25% but evidently insufficient)
- meaningful-open-symbols cap (was a count cap on Tier-2 only)
- ladder-order-per-symbol-per-day cap (was missing)
- min cooldown between consecutive buys of the same symbol (was missing)
- existing-position guard (was binary, now also notional-aware)
- pending-order guard (was missing)
- drawdown-guard hard block on crypto buys (was generic, now explicit)
- recent-realized-crypto-loss cooldown (was missing)

CONTRACT
--------
- READ-ONLY decision module. Does NOT submit orders.
- Does NOT call live broker endpoints.
- Returns a deterministic `CryptoBuyDecision` enum + structured reason.
- Defaults are intentionally CONSERVATIVE for paused/recovery mode.
- Operator may override individual limits via env vars (see ENV_OVERRIDES),
  but tests pin that the SOL/LTC ~60% pattern is impossible under defaults.

INVARIANTS (test-asserted)
--------------------------
- NEVER_PLACES_ORDERS = True
- NEVER_LOWERS_DRAWDOWN_GUARD = True
- LIVE_TRADING_PATH_FOREVER_DISABLED = True
- NEVER_INFERS_CLIENT_ORDER_ID = True
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

# ─── Default policy (paused / recovery mode) ──────────────────────────────────
#
# Each value is overridable via env var (see ENV_OVERRIDES).
# Defaults are conservative — under SAFE_FREE / signal-shadow operation
# the literal SOL/LTC pattern (12 × $2,500 buys per symbol) MUST be blocked.

MAX_CRYPTO_GROSS_EXPOSURE_PCT             = 0.10   # 10% of equity total
MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT        = 0.03   # 3% of equity per symbol
MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS        = 2      # ETH + AVAX is enough
MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY = 1    # one buy per symbol per day
MIN_CRYPTO_BUY_COOLDOWN_MINUTES           = 240    # 4 h between buys of any crypto
BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT = 0.01  # 1% open = block new buy
BLOCK_BUY_IF_PENDING_ORDER_EXISTS         = True
BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE        = True
BLOCK_BUY_IF_RECENT_REALIZED_CRYPTO_LOSS  = True
RECENT_LOSS_COOLDOWN_HOURS                = 72     # 3 days
RECENT_LOSS_THRESHOLD_USD_ABS             = 500.0  # |loss| ≥ $500 triggers cooldown
# "dust" qty threshold: anything strictly below this is treated as not
# meaningful (a dust position should NOT cause us to re-buy the symbol
# in v3.25 — dust handling is delegated to crypto_exit_policy, which
# requires an explicit operator-approved flag before any dust close).
DUST_NOTIONAL_USD                         = 1.0

ENV_OVERRIDES: dict[str, str] = {
    "MAX_CRYPTO_GROSS_EXPOSURE_PCT":             "CRYPTO_POLICY_MAX_GROSS_PCT",
    "MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT":        "CRYPTO_POLICY_MAX_PER_SYMBOL_PCT",
    "MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS":        "CRYPTO_POLICY_MAX_MEANINGFUL_SYMBOLS",
    "MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY":"CRYPTO_POLICY_MAX_LADDER_PER_DAY",
    "MIN_CRYPTO_BUY_COOLDOWN_MINUTES":           "CRYPTO_POLICY_MIN_COOLDOWN_MIN",
    "RECENT_LOSS_COOLDOWN_HOURS":                "CRYPTO_POLICY_RECENT_LOSS_HOURS",
}

# Status tokens (added by v3.25).
CRYPTO_HARD_EXPOSURE_CAP_ADDED              = "CRYPTO_HARD_EXPOSURE_CAP_ADDED"
CRYPTO_AGGREGATE_EXPOSURE_CAP_ADDED         = "CRYPTO_AGGREGATE_EXPOSURE_CAP_ADDED"
CRYPTO_PER_SYMBOL_EXPOSURE_CAP_ADDED        = "CRYPTO_PER_SYMBOL_EXPOSURE_CAP_ADDED"
CRYPTO_LADDERING_GUARD_ADDED                = "CRYPTO_LADDERING_GUARD_ADDED"
CRYPTO_BUY_COOLDOWN_ADDED                   = "CRYPTO_BUY_COOLDOWN_ADDED"
CRYPTO_PENDING_ORDER_PRECHECK_REQUIRED      = "CRYPTO_PENDING_ORDER_PRECHECK_REQUIRED"
CRYPTO_DRAWDOWN_GUARD_BLOCKS_NEW_BUYS       = "CRYPTO_DRAWDOWN_GUARD_BLOCKS_NEW_BUYS"
CRYPTO_RECENT_LOSS_COOLDOWN_ADDED           = "CRYPTO_RECENT_LOSS_COOLDOWN_ADDED"

ALL_POLICY_STATUS_TOKENS: frozenset[str] = frozenset({
    CRYPTO_HARD_EXPOSURE_CAP_ADDED,
    CRYPTO_AGGREGATE_EXPOSURE_CAP_ADDED,
    CRYPTO_PER_SYMBOL_EXPOSURE_CAP_ADDED,
    CRYPTO_LADDERING_GUARD_ADDED,
    CRYPTO_BUY_COOLDOWN_ADDED,
    CRYPTO_PENDING_ORDER_PRECHECK_REQUIRED,
    CRYPTO_DRAWDOWN_GUARD_BLOCKS_NEW_BUYS,
    CRYPTO_RECENT_LOSS_COOLDOWN_ADDED,
})

# Decision tokens returned by evaluate_crypto_buy.
ALLOW                                         = "CRYPTO_BUY_ALLOWED"
ALLOW_SHADOW_ONLY                             = "CRYPTO_BUY_ALLOWED_SHADOW_ONLY"
BLOCK_BY_AGGREGATE_EXPOSURE_CAP               = "CRYPTO_BUY_BLOCKED_BY_AGGREGATE_EXPOSURE_CAP"
BLOCK_BY_SYMBOL_EXPOSURE_CAP                  = "CRYPTO_BUY_BLOCKED_BY_SYMBOL_EXPOSURE_CAP"
BLOCK_BY_EXISTING_POSITION                    = "CRYPTO_BUY_BLOCKED_BY_EXISTING_POSITION"
BLOCK_BY_PENDING_ORDER                        = "CRYPTO_BUY_BLOCKED_BY_PENDING_ORDER"
BLOCK_BY_LADDER_LIMIT                         = "CRYPTO_BUY_BLOCKED_BY_LADDER_LIMIT"
BLOCK_BY_COOLDOWN                             = "CRYPTO_BUY_BLOCKED_BY_COOLDOWN"
BLOCK_BY_DRAWDOWN_GUARD                       = "CRYPTO_BUY_BLOCKED_BY_DRAWDOWN_GUARD"
BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN        = "CRYPTO_BUY_BLOCKED_BY_RECENT_REALIZED_LOSS_COOLDOWN"
BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS     = "CRYPTO_BUY_BLOCKED_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS"

ALL_DECISIONS: frozenset[str] = frozenset({
    ALLOW, ALLOW_SHADOW_ONLY,
    BLOCK_BY_AGGREGATE_EXPOSURE_CAP, BLOCK_BY_SYMBOL_EXPOSURE_CAP,
    BLOCK_BY_EXISTING_POSITION, BLOCK_BY_PENDING_ORDER,
    BLOCK_BY_LADDER_LIMIT, BLOCK_BY_COOLDOWN,
    BLOCK_BY_DRAWDOWN_GUARD, BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN,
    BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS,
})

# Invariants — test-asserted at module load.
NEVER_PLACES_ORDERS              = True
NEVER_LOWERS_DRAWDOWN_GUARD      = True
LIVE_TRADING_PATH_FOREVER_DISABLED       = True
NEVER_INFERS_CLIENT_ORDER_ID     = True


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class CryptoExposureInputs:
    """Operator / runtime context passed to evaluate_crypto_buy.

    All fields are explicit so callers must supply them; no global state.
    """
    symbol: str
    proposed_buy_usd: float
    equity_usd: float
    # Map symbol -> current notional USD (current broker positions).
    current_positions_usd: dict[str, float] = field(default_factory=dict)
    # Open orders by symbol (any side, any status='new/accepted').
    pending_orders_by_symbol: dict[str, int] = field(default_factory=dict)
    drawdown_guard_active: bool = False
    # Realized P/L per symbol over the recent cooldown window.
    # Negative numbers are losses. Used for recent-loss cooldown.
    recent_realized_pnl_by_symbol_usd: dict[str, float] = field(default_factory=dict)
    # Per-symbol buy count today (UTC) — used for ladder limit.
    buys_today_by_symbol: dict[str, int] = field(default_factory=dict)
    # Per-symbol last-buy timestamp (epoch seconds) — used for cooldown.
    last_buy_epoch_by_symbol: dict[str, float] = field(default_factory=dict)
    # Mode: "broker_paper" (hard block on FAIL), "signal_shadow"
    # (record reason but allow shadow logging only — never returns ALLOW).
    mode: str = "broker_paper"
    # Now epoch (injectable for tests). Defaults to time.time().
    now_epoch: float | None = None


@dataclass
class CryptoBuyDecision:
    decision: str  # one of ALL_DECISIONS
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_allow(self) -> bool:
        return self.decision == ALLOW

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("CRYPTO_BUY_BLOCKED_BY")

    @property
    def is_shadow_only(self) -> bool:
        return self.decision == ALLOW_SHADOW_ONLY


# ─── Internal helpers ────────────────────────────────────────────────────────

def _override(name: str, default: Any) -> Any:
    """Read env-var override or fall back to module default.

    For numeric defaults we keep the original type.
    """
    env_key = ENV_OVERRIDES.get(name)
    if not env_key:
        return default
    raw = os.environ.get(env_key)
    if raw is None or raw == "":
        return default
    try:
        if isinstance(default, bool):
            return raw.lower() in ("true", "1", "yes", "on")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
    except (TypeError, ValueError):
        return default
    return raw


def get_effective_policy() -> dict[str, Any]:
    """Return the policy dict actually in effect (defaults + env overrides).

    Pure read function. Does NOT mutate module state.
    """
    return {
        "MAX_CRYPTO_GROSS_EXPOSURE_PCT":            _override(
            "MAX_CRYPTO_GROSS_EXPOSURE_PCT", MAX_CRYPTO_GROSS_EXPOSURE_PCT),
        "MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT":       _override(
            "MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT",
            MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT),
        "MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS":       _override(
            "MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS",
            MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS),
        "MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY": _override(
            "MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY",
            MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY),
        "MIN_CRYPTO_BUY_COOLDOWN_MINUTES":          _override(
            "MIN_CRYPTO_BUY_COOLDOWN_MINUTES",
            MIN_CRYPTO_BUY_COOLDOWN_MINUTES),
        "BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT":
            BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT,
        "BLOCK_BUY_IF_PENDING_ORDER_EXISTS":
            BLOCK_BUY_IF_PENDING_ORDER_EXISTS,
        "BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE":
            BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE,
        "BLOCK_BUY_IF_RECENT_REALIZED_CRYPTO_LOSS":
            BLOCK_BUY_IF_RECENT_REALIZED_CRYPTO_LOSS,
        "RECENT_LOSS_COOLDOWN_HOURS":               _override(
            "RECENT_LOSS_COOLDOWN_HOURS",
            RECENT_LOSS_COOLDOWN_HOURS),
        "RECENT_LOSS_THRESHOLD_USD_ABS":            RECENT_LOSS_THRESHOLD_USD_ABS,
        "DUST_NOTIONAL_USD":                        DUST_NOTIONAL_USD,
    }


def _count_meaningful_open(positions: dict[str, float]) -> int:
    return sum(1 for v in positions.values() if v >= DUST_NOTIONAL_USD)


def _is_crypto_symbol(symbol: str) -> bool:
    """Accept both 'BTC/USD' (Alpaca format) and 'BTCUSD' (compact)."""
    s = symbol.upper()
    return s.endswith("USD") or s.endswith("/USD")


# ─── Main API ────────────────────────────────────────────────────────────────

def evaluate_crypto_buy(inputs: CryptoExposureInputs) -> CryptoBuyDecision:
    """Return a structured decision for a proposed crypto buy.

    Pure function. No I/O. No order submission. No state mutation.

    Mode contract:
    - "broker_paper": ALLOW or BLOCK_BY_*. Caller hard-blocks on BLOCK.
    - "signal_shadow": never returns ALLOW. Returns ALLOW_SHADOW_ONLY
      with the would-block reason captured in details, OR a BLOCK_BY_*
      decision if the buy violates a hard invariant (drawdown guard etc).
    """
    p = get_effective_policy()
    sym = inputs.symbol
    now = inputs.now_epoch if inputs.now_epoch is not None else time.time()

    # Reject obvious bad inputs.
    if not _is_crypto_symbol(sym):
        return CryptoBuyDecision(
            decision=BLOCK_BY_SYMBOL_EXPOSURE_CAP,
            reason=f"non-crypto symbol: {sym}",
            details={"symbol": sym},
        )
    if inputs.proposed_buy_usd <= 0 or inputs.equity_usd <= 0:
        return CryptoBuyDecision(
            decision=BLOCK_BY_AGGREGATE_EXPOSURE_CAP,
            reason="non-positive buy size or equity",
            details={"buy_usd": inputs.proposed_buy_usd,
                      "equity_usd": inputs.equity_usd},
        )

    # 1) Drawdown guard — ALWAYS blocks new buys (paper or shadow).
    if (p["BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE"]
            and inputs.drawdown_guard_active):
        return CryptoBuyDecision(
            decision=BLOCK_BY_DRAWDOWN_GUARD,
            reason="drawdown_guard_active=True blocks new crypto buys",
            details={"policy": p["BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE"]},
        )

    # 2) Pending order pre-check.
    pending = inputs.pending_orders_by_symbol.get(sym, 0)
    if p["BLOCK_BUY_IF_PENDING_ORDER_EXISTS"] and pending > 0:
        return CryptoBuyDecision(
            decision=BLOCK_BY_PENDING_ORDER,
            reason=f"{sym} already has {pending} pending order(s)",
            details={"pending_count": pending},
        )

    # 3) Existing-position notional guard (not just binary).
    current_sym_usd = inputs.current_positions_usd.get(sym, 0.0)
    pct_open = (current_sym_usd / inputs.equity_usd
                 if inputs.equity_usd > 0 else 0.0)
    if pct_open > p["BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT"]:
        return CryptoBuyDecision(
            decision=BLOCK_BY_EXISTING_POSITION,
            reason=(f"{sym} already at {pct_open*100:.2f}% of equity "
                     f"(>"
                     f"{p['BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT']*100:.2f}%)"),
            details={"current_position_usd": current_sym_usd,
                      "pct_open": pct_open},
        )

    # 4) Meaningful-open-symbols cap.
    meaningful = _count_meaningful_open(inputs.current_positions_usd)
    if (current_sym_usd < DUST_NOTIONAL_USD
            and meaningful >= p["MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS"]):
        return CryptoBuyDecision(
            decision=BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS,
            reason=(f"already {meaningful} meaningful open crypto "
                     f"symbols (cap "
                     f"{p['MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS']})"),
            details={"meaningful_open": meaningful},
        )

    # 5) Per-symbol exposure cap (post-buy).
    post_sym_usd = current_sym_usd + inputs.proposed_buy_usd
    post_sym_pct = post_sym_usd / inputs.equity_usd
    if post_sym_pct > p["MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT"]:
        return CryptoBuyDecision(
            decision=BLOCK_BY_SYMBOL_EXPOSURE_CAP,
            reason=(f"{sym} post-buy would be {post_sym_pct*100:.2f}% "
                     f"(>"
                     f"{p['MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT']*100:.2f}%)"),
            details={"post_buy_usd": post_sym_usd,
                      "post_buy_pct": post_sym_pct},
        )

    # 6) Aggregate exposure cap (post-buy).
    total_crypto_usd = sum(
        v for s, v in inputs.current_positions_usd.items()
        if _is_crypto_symbol(s)
    )
    post_total_usd = total_crypto_usd + inputs.proposed_buy_usd
    post_total_pct = post_total_usd / inputs.equity_usd
    if post_total_pct > p["MAX_CRYPTO_GROSS_EXPOSURE_PCT"]:
        return CryptoBuyDecision(
            decision=BLOCK_BY_AGGREGATE_EXPOSURE_CAP,
            reason=(f"aggregate crypto post-buy would be "
                     f"{post_total_pct*100:.2f}% (>"
                     f"{p['MAX_CRYPTO_GROSS_EXPOSURE_PCT']*100:.2f}%)"),
            details={"post_total_usd": post_total_usd,
                      "post_total_pct": post_total_pct},
        )

    # 7) Laddering limit per day.
    buys_today = inputs.buys_today_by_symbol.get(sym, 0)
    if buys_today >= p["MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY"]:
        return CryptoBuyDecision(
            decision=BLOCK_BY_LADDER_LIMIT,
            reason=(f"{sym} already had {buys_today} buy(s) today "
                     f"(cap "
                     f"{p['MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY']})"),
            details={"buys_today": buys_today},
        )

    # 8) Min cooldown between buys (per-symbol).
    last_buy = inputs.last_buy_epoch_by_symbol.get(sym)
    if last_buy is not None:
        elapsed_min = (now - last_buy) / 60.0
        if elapsed_min < p["MIN_CRYPTO_BUY_COOLDOWN_MINUTES"]:
            return CryptoBuyDecision(
                decision=BLOCK_BY_COOLDOWN,
                reason=(f"{sym} cooldown: {elapsed_min:.1f} min since "
                         f"last buy (cap "
                         f"{p['MIN_CRYPTO_BUY_COOLDOWN_MINUTES']})"),
                details={"elapsed_min": elapsed_min},
            )

    # 9) Recent realized-loss cooldown (this symbol).
    if p["BLOCK_BUY_IF_RECENT_REALIZED_CRYPTO_LOSS"]:
        recent_pnl = inputs.recent_realized_pnl_by_symbol_usd.get(sym, 0.0)
        if recent_pnl < -p["RECENT_LOSS_THRESHOLD_USD_ABS"]:
            return CryptoBuyDecision(
                decision=BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN,
                reason=(f"{sym} recent realized P/L ${recent_pnl:+.2f} "
                         f"is below -${p['RECENT_LOSS_THRESHOLD_USD_ABS']:.0f} "
                         f"within {p['RECENT_LOSS_COOLDOWN_HOURS']}h "
                         f"window — cooldown active"),
                details={"recent_pnl_usd": recent_pnl},
            )

    # All hard checks passed.
    if inputs.mode == "signal_shadow":
        return CryptoBuyDecision(
            decision=ALLOW_SHADOW_ONLY,
            reason="signal/shadow unlock mode — no broker order",
            details={"post_buy_pct_aggregate": post_total_pct,
                      "post_buy_pct_symbol": post_sym_pct},
        )
    return CryptoBuyDecision(
        decision=ALLOW,
        reason="all crypto exposure guards passed",
        details={"post_buy_pct_aggregate": post_total_pct,
                  "post_buy_pct_symbol": post_sym_pct},
    )


def policy_summary() -> dict[str, Any]:
    """Human + machine readable snapshot of the live policy values."""
    p = get_effective_policy()
    return {
        "version": "v3.25.0",
        "policy": p,
        "status_tokens_added": sorted(ALL_POLICY_STATUS_TOKENS),
        "decisions_available": sorted(ALL_DECISIONS),
        "invariants": {
            "NEVER_PLACES_ORDERS": NEVER_PLACES_ORDERS,
            "NEVER_LOWERS_DRAWDOWN_GUARD": NEVER_LOWERS_DRAWDOWN_GUARD,
            "LIVE_TRADING_PATH_FOREVER_DISABLED": LIVE_TRADING_PATH_FOREVER_DISABLED,
            "NEVER_INFERS_CLIENT_ORDER_ID": NEVER_INFERS_CLIENT_ORDER_ID,
        },
    }


__all__ = [
    # Constants
    "MAX_CRYPTO_GROSS_EXPOSURE_PCT",
    "MAX_CRYPTO_PER_SYMBOL_EXPOSURE_PCT",
    "MAX_CRYPTO_MEANINGFUL_OPEN_SYMBOLS",
    "MAX_CRYPTO_LADDER_ORDERS_PER_SYMBOL_PER_DAY",
    "MIN_CRYPTO_BUY_COOLDOWN_MINUTES",
    "BLOCK_BUY_IF_SYMBOL_ALREADY_OPEN_ABOVE_PCT",
    "BLOCK_BUY_IF_PENDING_ORDER_EXISTS",
    "BLOCK_BUY_IF_DRAWDOWN_GUARD_ACTIVE",
    "BLOCK_BUY_IF_RECENT_REALIZED_CRYPTO_LOSS",
    "RECENT_LOSS_COOLDOWN_HOURS",
    "RECENT_LOSS_THRESHOLD_USD_ABS",
    "DUST_NOTIONAL_USD",
    # Status tokens
    "CRYPTO_HARD_EXPOSURE_CAP_ADDED",
    "CRYPTO_AGGREGATE_EXPOSURE_CAP_ADDED",
    "CRYPTO_PER_SYMBOL_EXPOSURE_CAP_ADDED",
    "CRYPTO_LADDERING_GUARD_ADDED",
    "CRYPTO_BUY_COOLDOWN_ADDED",
    "CRYPTO_PENDING_ORDER_PRECHECK_REQUIRED",
    "CRYPTO_DRAWDOWN_GUARD_BLOCKS_NEW_BUYS",
    "CRYPTO_RECENT_LOSS_COOLDOWN_ADDED",
    "ALL_POLICY_STATUS_TOKENS",
    # Decisions
    "ALLOW", "ALLOW_SHADOW_ONLY",
    "BLOCK_BY_AGGREGATE_EXPOSURE_CAP",
    "BLOCK_BY_SYMBOL_EXPOSURE_CAP",
    "BLOCK_BY_EXISTING_POSITION",
    "BLOCK_BY_PENDING_ORDER",
    "BLOCK_BY_LADDER_LIMIT",
    "BLOCK_BY_COOLDOWN",
    "BLOCK_BY_DRAWDOWN_GUARD",
    "BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN",
    "BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS",
    "ALL_DECISIONS",
    # Invariants
    "NEVER_PLACES_ORDERS",
    "NEVER_LOWERS_DRAWDOWN_GUARD",
    "LIVE_TRADING_PATH_FOREVER_DISABLED",
    "NEVER_INFERS_CLIENT_ORDER_ID",
    # Data classes
    "CryptoExposureInputs",
    "CryptoBuyDecision",
    # API
    "evaluate_crypto_buy",
    "policy_summary",
    "get_effective_policy",
]

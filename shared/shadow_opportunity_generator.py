"""v3.27.0 (2026-06-09) — REAL_MARKET_DATA shadow opportunity generator.

Consumes ``MarketSnapshot`` + daily bars from
``shared/market_data_provider.py`` and produces shadow opportunity
records using the PURE strategy functions in ``backtest/strategies.py``.

CONTRACT
--------
- READ-ONLY. Does NOT submit orders.
- Does NOT import ``shared/alpaca_orders.py`` (asserted by test).
- Emits a record ONLY when the snapshot's ``data_quality`` is
  ``REAL_MARKET_DATA``.
- ``NO_MARKET_DATA`` / ``STALE_MARKET_DATA`` / ``PROVIDER_ERROR``
  return ``None`` (collector treats this as halt-path).
- Every emitted record carries ``evidence_quality=REAL_MARKET_DATA``,
  ``broker_execution_enabled=false``, ``broker_order_submitted=false``.
- ``would_block`` reflects the v3.25 crypto exposure policy +
  drawdown-guard decision at this moment; ``would_trade`` reflects the
  raw strategy signal.

INVARIANTS (test-asserted)
--------------------------
- NEVER_SUBMITS_ORDERS = True
- NEVER_IMPORTS_ALPACA_ORDERS = True
- NEVER_FABRICATES_OPPORTUNITY = True
- ONLY_EMITS_FOR_REAL_MARKET_DATA = True
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

# Invariants.
NEVER_SUBMITS_ORDERS              = True
NEVER_IMPORTS_ALPACA_ORDERS       = True
NEVER_FABRICATES_OPPORTUNITY      = True
ONLY_EMITS_FOR_REAL_MARKET_DATA   = True


# ─── Strategy registry ───────────────────────────────────────────────────────
#
# Each entry maps a strategy name to a pure ``signal_at(idx, bars)``
# callable from ``backtest/strategies.py``. v3.27 keeps the registry
# tight: 1 stock + 1 crypto strategy. Future iterations can extend it.

# v3.22 — module-level version stamp so tests can pin the registry.
REGISTRY_VERSION = "v3.22.0"


def _strategy_registry() -> dict[str, dict[str, Any]]:
    try:
        from backtest.strategies import (
            momentum_long_signal_at,
            momentum_long_loose_signal_at,
            overbought_short_signal_at,
            crypto_momentum_signal_at,
            crypto_oversold_bounce_signal_at,
        )
    except ImportError:  # pragma: no cover
        return {}
    return {
        "momentum-long": {
            "asset_class": "us_equity",
            "signal_at":   momentum_long_signal_at,
            "default_size_usd": 1000.0,
        },
        "momentum-long-loose": {
            "asset_class": "us_equity",
            "signal_at":   momentum_long_loose_signal_at,
            "default_size_usd": 1000.0,
        },
        "overbought-short": {
            "asset_class": "us_equity",
            "signal_at":   overbought_short_signal_at,
            "default_size_usd": 1000.0,
        },
        "crypto-momentum": {
            "asset_class": "crypto",
            "signal_at":   crypto_momentum_signal_at,
            "default_size_usd": 500.0,
        },
        "crypto-oversold-bounce": {
            "asset_class": "crypto",
            "signal_at":   crypto_oversold_bounce_signal_at,
            "default_size_usd": 500.0,
        },
        # v3.22 observe-only entries — no pure daily-bar helper, but
        # we still want them to show up in the registry so the
        # universe map covers the live monitor set. The shadow runner
        # skips would-trade emission for observe_only entries.
        "geo-defense": {
            "asset_class": "us_equity",
            "signal_at":   None,
            "observe_only": True,
            "default_size_usd": 1000.0,
        },
        "options-momentum": {
            "asset_class": "us_option",
            "signal_at":   None,
            "observe_only": True,
            "default_size_usd": 500.0,
        },
    }


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class GeneratedOpportunity:
    symbol: str
    asset_class: str
    strategy: str
    side: str
    would_trade: bool
    would_block: bool
    block_reasons: list[str] = field(default_factory=list)
    sizing_preview: dict[str, Any] = field(default_factory=dict)
    exposure_policy_result: dict[str, Any] = field(default_factory=dict)
    drawdown_guard_state: dict[str, Any] = field(default_factory=dict)
    entry_shadow_price: float | None = None
    audit_trace_id: str = ""
    raw_signal: dict[str, Any] = field(default_factory=dict)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _evaluate_block(
    *,
    strategy: str,
    symbol: str,
    asset_class: str,
    proposed_usd: float,
    equity_usd: float,
    drawdown_guard_active: bool,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Run v3.25 crypto exposure / drawdown guard as WOULD-BLOCK only.

    Returns (would_block, reasons, exposure_policy_result_dict).
    Never submits orders. For non-crypto symbols, only the drawdown
    guard is consulted.
    """
    reasons: list[str] = []
    exposure_result: dict[str, Any] = {
        "decision": "WOULD_NOT_EVALUATE",
        "reason": "non-crypto symbol; only drawdown guard applies",
        "details": {},
    }
    if drawdown_guard_active:
        reasons.append("CRYPTO_BUY_BLOCKED_BY_DRAWDOWN_GUARD"
                        if asset_class == "crypto"
                        else "EQUITY_BUY_BLOCKED_BY_DRAWDOWN_GUARD")
    if asset_class == "crypto":
        try:
            try:
                from crypto_exposure_policy import (
                    CryptoExposureInputs, evaluate_crypto_buy,
                )
            except ImportError:
                from shared.crypto_exposure_policy import (
                    CryptoExposureInputs, evaluate_crypto_buy,
                )
            inputs = CryptoExposureInputs(
                symbol=symbol,
                proposed_buy_usd=float(proposed_usd),
                equity_usd=float(equity_usd),
                current_positions_usd={},
                pending_orders_by_symbol={},
                drawdown_guard_active=drawdown_guard_active,
                mode="signal_shadow",
            )
            decision = evaluate_crypto_buy(inputs)
            exposure_result = {
                "decision": decision.decision,
                "reason": decision.reason,
                "details": decision.details or {},
            }
            if decision.is_blocked:
                reasons.append(decision.decision)
        except Exception as e:
            exposure_result = {
                "decision": "POLICY_UNAVAILABLE",
                "reason": f"{type(e).__name__}: {e}",
                "details": {},
            }
    return (len(reasons) > 0), reasons, exposure_result


def _audit_trace_id() -> str:
    return f"v3270-shadow-{uuid.uuid4().hex[:10]}"


# ─── Main API ────────────────────────────────────────────────────────────────

def generate_for_snapshot(
    snapshot: dict[str, Any] | Any,
    *,
    bars: list[dict] | None = None,
    strategy: str | None = None,
    equity_usd: float = 100_000.0,
    drawdown_guard_active: bool = False,
) -> GeneratedOpportunity | None:
    """Produce a shadow opportunity from a market snapshot.

    Returns ``None`` when:
    - ``snapshot.data_quality`` is not ``REAL_MARKET_DATA``,
    - no strategy is registered for the snapshot's asset class,
    - the strategy returns no signal (no opportunity to record),
    - bars are missing for a strategy that needs them.

    Never fabricates a fake signal. Never submits orders.
    """
    if hasattr(snapshot, "as_dict"):
        snap = snapshot.as_dict()
    else:
        snap = dict(snapshot)

    if snap.get("data_quality") != "REAL_MARKET_DATA":
        return None

    asset_class = snap.get("asset_class") or "us_equity"
    symbol = snap.get("symbol") or ""
    price = snap.get("price")
    if not symbol or price is None or price <= 0:
        return None

    reg = _strategy_registry()
    if not reg:
        return None
    # Pick a strategy for this asset class.
    candidates = [(n, cfg) for n, cfg in reg.items()
                   if cfg["asset_class"] == asset_class]
    if not candidates:
        return None
    if strategy is not None:
        candidates = [(n, cfg) for n, cfg in candidates if n == strategy]
        if not candidates:
            return None
    strategy_name, cfg = candidates[0]

    if bars is None or len(bars) < 22:
        # Strategy needs daily bars (and at least ATR-window worth).
        return None

    try:
        raw_signal = cfg["signal_at"](len(bars) - 1, {symbol: bars})
    except Exception:
        return None
    if not raw_signal:
        return None

    proposed_usd = float(
        raw_signal.get("size_usd") or cfg["default_size_usd"])
    side = "buy" if str(raw_signal.get("action") or "BUY").upper() in (
        "BUY", "BUY_TO_OPEN", "LONG") else "sell"

    would_block, block_reasons, exposure_policy = _evaluate_block(
        strategy=strategy_name,
        symbol=symbol,
        asset_class=asset_class,
        proposed_usd=proposed_usd,
        equity_usd=equity_usd,
        drawdown_guard_active=drawdown_guard_active,
    )

    drawdown_guard_state = {
        "active":        bool(drawdown_guard_active),
        "threshold_pct": -3.0,
        "current_pct":   0.0,
    }
    sizing_preview = {
        "proposed_usd": proposed_usd,
        "equity_usd":   float(equity_usd),
        "proposed_qty": None,
        "limit_price":  float(price),
        "entry_shadow_price": float(price),
        "stop_loss":    raw_signal.get("stop_loss"),
        "take_profit":  raw_signal.get("take_profit"),
    }

    return GeneratedOpportunity(
        symbol=symbol,
        asset_class=asset_class,
        strategy=strategy_name,
        side=side,
        would_trade=True,
        would_block=would_block,
        block_reasons=block_reasons,
        sizing_preview=sizing_preview,
        exposure_policy_result=exposure_policy,
        drawdown_guard_state=drawdown_guard_state,
        entry_shadow_price=float(price),
        audit_trace_id=_audit_trace_id(),
        raw_signal=raw_signal,
    )


def generate_for_universe(
    snapshots: Iterable[Any],
    *,
    bars_by_symbol: dict[str, list[dict]] | None = None,
    equity_usd: float = 100_000.0,
    drawdown_guard_active: bool = False,
) -> list[GeneratedOpportunity]:
    """Run ``generate_for_snapshot`` over a list of snapshots.

    Returns the list of generated opportunities. Skipped snapshots
    (no real data / no signal) are not in the list.
    """
    bars_by_symbol = bars_by_symbol or {}
    out: list[GeneratedOpportunity] = []
    for snap in snapshots:
        sym = (snap.symbol
                if hasattr(snap, "symbol")
                else (snap.get("symbol") if isinstance(snap, dict)
                       else None))
        if not sym:
            continue
        opp = generate_for_snapshot(
            snap, bars=bars_by_symbol.get(sym),
            equity_usd=equity_usd,
            drawdown_guard_active=drawdown_guard_active,
        )
        if opp is not None:
            out.append(opp)
    return out


def to_shadow_record(
    opp: GeneratedOpportunity,
    *,
    timestamp_iso: str,
) -> dict[str, Any]:
    """Convert a ``GeneratedOpportunity`` into a v3.26.1 schema record.

    Hard-coded: ``broker_execution_enabled=False``,
    ``broker_order_submitted=False``, ``evidence_quality=REAL_MARKET_DATA``.
    """
    return {
        "version":           "v3.27.0",
        "timestamp":         timestamp_iso,
        "symbol":            opp.symbol,
        "asset_class":       opp.asset_class,
        "strategy":          opp.strategy,
        "decision_type":     "entry",
        "side":              opp.side,
        "would_trade":       bool(opp.would_trade),
        "would_block":       bool(opp.would_block),
        "block_reasons":     list(opp.block_reasons),
        "sizing_preview":    opp.sizing_preview,
        "exposure_policy_result": opp.exposure_policy_result,
        "drawdown_guard_state":   opp.drawdown_guard_state,
        "broker_execution_enabled": False,
        "broker_order_submitted":   False,
        "outcome_tracking_status":  "PENDING",
        "audit_trace_id":    opp.audit_trace_id,
        "evidence_quality":  "REAL_MARKET_DATA",
    }


def policy_summary() -> dict[str, Any]:
    reg = _strategy_registry()
    strategy_details: dict[str, dict[str, Any]] = {}
    for name, cfg in reg.items():
        strategy_details[name] = {
            "asset_class":      cfg.get("asset_class"),
            "observe_only":     bool(cfg.get("observe_only", False)),
            "has_signal_at":    callable(cfg.get("signal_at")),
            "default_size_usd": cfg.get("default_size_usd"),
        }
    return {
        "version":              "v3.27.0",
        "registry_version":     REGISTRY_VERSION,
        "strategies_registered": sorted(reg.keys()),
        "strategy_details":     strategy_details,
        "invariants": {
            "NEVER_SUBMITS_ORDERS": NEVER_SUBMITS_ORDERS,
            "NEVER_IMPORTS_ALPACA_ORDERS": NEVER_IMPORTS_ALPACA_ORDERS,
            "NEVER_FABRICATES_OPPORTUNITY": NEVER_FABRICATES_OPPORTUNITY,
            "ONLY_EMITS_FOR_REAL_MARKET_DATA": ONLY_EMITS_FOR_REAL_MARKET_DATA,
        },
    }


__all__ = [
    # Invariants
    "NEVER_SUBMITS_ORDERS",
    "NEVER_IMPORTS_ALPACA_ORDERS",
    "NEVER_FABRICATES_OPPORTUNITY",
    "ONLY_EMITS_FOR_REAL_MARKET_DATA",
    # Data class
    "GeneratedOpportunity",
    # API
    "generate_for_snapshot",
    "generate_for_universe",
    "to_shadow_record",
    "policy_summary",
]

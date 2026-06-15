"""v3.22.0 (2026-06-15) — ETAP 4 — Thin per-monitor wrapper around
``emit_signal_opportunity``.

WHY
---
v3.22 phase 4 wires every monitor through ``shared/signal_emitter.py``.
Each monitor calls this helper with a small, monitor-friendly kwargs
dict, and the helper builds the canonical ``SignalEvent`` and routes
through ``emit_signal_opportunity``. The result: ONE write-point per
monitor, ZERO chance of monitors drifting into bespoke ledger formats.

This module is OBSERVABILITY ONLY. It NEVER places trades. It NEVER
imports ``alpaca_orders``. It NEVER calls the broker. Failures are
swallowed and logged — the calling monitor must never crash because of
a ledger problem.

PUBLIC API
----------
    emit_monitor_signal(
        source_monitor: str,
        strategy_id:    str,
        symbol:         str,
        asset_class:    str,
        side:           str,
        action:         str,
        *,
        entry_capable:  bool = False,
        raw_signal:     dict | None = None,
        confidence_inputs: dict | None = None,
        risk_inputs:    dict | None = None,
        market_regime:  dict | str | None = None,
        universe_status: dict | str | None = None,
        rejection_reasons: list | None = None,
        metadata:       dict | None = None,
        timestamp_iso:  str | None = None,
        pipeline:       str = "monitor",
        evidence_source:str = "PAPER",
    ) -> dict | None

Returns the dict produced by ``emit_signal_opportunity`` on success,
``None`` on import failure. Never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_ALLOWED_ACTIONS = {
    "BUY", "SELL", "SELL_SHORT", "HOLD", "NO_SIGNAL",
    "REJECT", "HALTED", "DETECTED", "BLOCKED",
}
_ALLOWED_SIDES = {"long", "short", "flat", "n/a"}


def _safe_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_regime(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {"regime": str(value)}


def _normalize_universe(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {"status": str(value)}


def _normalize_action(action: str | None) -> str:
    if not action:
        return "NO_SIGNAL"
    a = str(action).strip().upper()
    if a in _ALLOWED_ACTIONS:
        return a
    # Map common aliases.
    if a in ("BUY_TO_OPEN", "BUY_TO_COVER"):
        return "BUY"
    if a in ("SELL_TO_CLOSE", "SELL_TO_OPEN", "SELL_TO_OPEN_PUT"):
        return "SELL"
    if a in ("APPROVE",):
        return "BUY"
    return "DETECTED"


def _normalize_side(side: str | None, action: str) -> str:
    if side:
        s = str(side).strip().lower()
        if s in _ALLOWED_SIDES:
            return s
    if action in ("BUY",):
        return "long"
    if action in ("SELL_SHORT",):
        return "short"
    if action in ("SELL",):
        return "short"
    return "n/a"


def emit_monitor_signal(
    source_monitor: str,
    strategy_id:    str,
    symbol:         str,
    asset_class:    str,
    side:           str | None,
    action:         str | None,
    *,
    entry_capable:  bool = False,
    raw_signal:     dict | None = None,
    confidence_inputs: dict | None = None,
    risk_inputs:    dict | None = None,
    market_regime:  Any = None,
    universe_status: Any = None,
    rejection_reasons: list | None = None,
    metadata:       dict | None = None,
    timestamp_iso:  str | None = None,
    pipeline:       str = "monitor",
    evidence_source:str = "PAPER",
) -> dict | None:
    """Build a SignalEvent and route through emit_signal_opportunity.

    Fail-soft. Returns the emit result dict on success, ``None`` on
    failure. Never raises.
    """
    try:
        try:
            from signal_emitter import emit_signal_opportunity  # type: ignore
            from signal_event import SignalEvent, build_signal_id  # type: ignore
        except ImportError:
            from shared.signal_emitter import emit_signal_opportunity  # type: ignore
            from shared.signal_event import SignalEvent, build_signal_id  # type: ignore
    except Exception:
        return None

    try:
        ts = timestamp_iso or _safe_ts()
        normalized_action = _normalize_action(action)
        normalized_side = _normalize_side(side, normalized_action)
        sid = build_signal_id(strategy_id, symbol, ts, source_monitor)

        payload = dict(raw_signal or {})
        if rejection_reasons:
            payload.setdefault("rejection_reasons", list(rejection_reasons))

        meta = dict(metadata or {})

        ev = SignalEvent(
            signal_id        = sid,
            strategy_id      = strategy_id,
            symbol           = symbol,
            asset_class      = asset_class or "",
            side             = normalized_side,
            action           = normalized_action,
            timestamp_iso    = ts,
            source_monitor   = source_monitor,
            pipeline         = pipeline,
            evidence_source  = evidence_source,
            entry_capable    = bool(entry_capable),
            raw_signal       = payload,
            market_regime    = _normalize_regime(market_regime),
            confidence_inputs= dict(confidence_inputs or {}),
            risk_inputs      = dict(risk_inputs or {}),
            universe_status  = _normalize_universe(universe_status),
            pre_open_flags   = {},
            metadata         = meta,
        )
        return emit_signal_opportunity(ev)
    except Exception as e:
        # Observability layer never breaks the monitor.
        try:
            print(f"  emit_monitor_signal failed (non-fatal): "
                  f"{type(e).__name__}: {e}")
        except Exception:
            pass
        return None


__all__ = ["emit_monitor_signal"]

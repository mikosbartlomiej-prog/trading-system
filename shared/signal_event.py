"""v3.22.0 (2026-06-15) — ETAP 1 — SignalEvent: the canonical signal carrier.

WHY
---
v3.20.0 shipped the opportunity ledger (record_opportunity), and v3.22
needs a single canonical signal type so every monitor — price, crypto,
options, defense, geo, twitter, reddit, politician, etc. — emits the
same shape of event to the ledger. Without this, monitors invent their
own ad-hoc dicts and the ledger fills with inconsistent rows that the
learning loop can't reason over.

This module defines `SignalEvent` — a frozen dataclass that captures
ONE signal observation from ONE monitor at ONE moment in time. It is a
PURE DATA CARRIER. It does not place trades. It does not call the
broker. It does not even compute confidence — that is the emitter's
job (see shared/signal_emitter.py).

HARD SAFETY
-----------
NEVER places trades. NEVER imports alpaca_orders. NEVER imports any
broker module. Pure data carrier — the v3.22 contract is that this
file is loadable under any sandbox / no-network test harness.

CONTRACT
--------
- Frozen dataclass — once constructed, immutable. Prevents mutation
  between validation and ledger write.
- `validate(event)` is a pure function returning a list of error strings.
  Empty list = valid. Callers (the emitter) decide whether to proceed.
- entry_capable=True signals MUST carry both confidence_inputs and
  risk_inputs (downstream gating depends on them).
- entry_capable=False signals (observe-only telemetry, HALTED/REJECT
  audit rows) can omit those without validation error.
- pipeline must be one of:  monitor | shadow | paper | replay | backtest
  ("live" intentionally NOT allowed — live trading is unsupported).
- action must be one of:    BUY | SELL | SELL_SHORT | HOLD | NO_SIGNAL |
                            REJECT | HALTED | DETECTED | BLOCKED
- side must be one of:      long | short | flat | n/a

FREE OPERATION
--------------
Zero runtime cost. No external API. No paid services. No network.

EXAMPLES
--------
    >>> from shared.signal_event import SignalEvent, validate, build_signal_id
    >>> sid = build_signal_id("momentum-long", "AAPL",
    ...                       "2026-06-15T13:30:00Z", "price-monitor")
    >>> event = SignalEvent(
    ...     signal_id=sid,
    ...     strategy_id="momentum-long",
    ...     symbol="AAPL",
    ...     asset_class="us_equity",
    ...     side="long",
    ...     action="BUY",
    ...     timestamp_iso="2026-06-15T13:30:00Z",
    ...     source_monitor="price-monitor",
    ...     pipeline="monitor",
    ...     evidence_source="PAPER",
    ...     entry_capable=False,
    ... )
    >>> validate(event)
    []
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any

# Try to import the EvidenceSource enum; fall back to a string set so the
# module remains usable even if shared.evidence_source is unavailable in
# stripped-down test sandboxes. The validate() check uses the fallback
# string list when the enum is missing.
try:
    from evidence_source import EvidenceSource  # type: ignore
    _HAS_EVIDENCE_SOURCE = True
except ImportError:
    try:
        from shared.evidence_source import EvidenceSource  # type: ignore
        _HAS_EVIDENCE_SOURCE = True
    except ImportError:
        _HAS_EVIDENCE_SOURCE = False
        EvidenceSource = None  # type: ignore


# ─── Closed enums ─────────────────────────────────────────────────────────────


# Pipelines allowed. "live" is intentionally OMITTED — live trading is
# unsupported in this repo and never will be enabled via a SignalEvent.
ALLOWED_PIPELINES: frozenset[str] = frozenset({
    "monitor",
    "shadow",
    "paper",
    "replay",
    "backtest",
})

# Actions a SignalEvent can carry. "DETECTED" and "BLOCKED" allow
# observe-only telemetry rows from gates that intercept signals before
# they reach the broker layer.
ALLOWED_ACTIONS: frozenset[str] = frozenset({
    "BUY",
    "SELL",
    "SELL_SHORT",
    "HOLD",
    "NO_SIGNAL",
    "REJECT",
    "HALTED",
    "DETECTED",
    "BLOCKED",
})

ALLOWED_SIDES: frozenset[str] = frozenset({
    "long",
    "short",
    "flat",
    "n/a",
})


# Fallback evidence-source strings (used when shared.evidence_source not
# importable). Mirrors the canonical enum in shared/evidence_source.py.
_FALLBACK_EVIDENCE_SOURCES: frozenset[str] = frozenset({
    "BACKTEST",
    "REPLAY",
    "PAPER",
})


# ─── The SignalEvent ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalEvent:
    """Canonical signal carrier emitted by every monitor.

    Fields are intentionally generic so that one shape covers price,
    crypto, options, news, social, and political event monitors.
    """

    signal_id:         str
    strategy_id:       str
    symbol:            str
    asset_class:       str
    side:              str
    action:            str
    timestamp_iso:     str
    source_monitor:    str
    pipeline:          str
    evidence_source:   str
    entry_capable:     bool
    raw_signal:        dict = field(default_factory=dict)
    market_regime:     dict = field(default_factory=dict)
    confidence_inputs: dict = field(default_factory=dict)
    risk_inputs:       dict = field(default_factory=dict)
    universe_status:   dict = field(default_factory=dict)
    pre_open_flags:    dict = field(default_factory=dict)
    metadata:          dict = field(default_factory=dict)


# ─── Validation ──────────────────────────────────────────────────────────────


def _evidence_source_allowed(value: Any) -> bool:
    if value is None:
        return False
    if _HAS_EVIDENCE_SOURCE and EvidenceSource is not None:
        try:
            if isinstance(value, EvidenceSource):
                return True
        except Exception:
            pass
        try:
            EvidenceSource(value)  # type: ignore[misc]
            return True
        except Exception:
            pass
    if isinstance(value, str):
        return value.strip().upper() in _FALLBACK_EVIDENCE_SOURCES
    return False


def validate(event: SignalEvent) -> list[str]:
    """Return a list of error strings for a SignalEvent. [] = valid.

    Pure function. Never raises. Never mutates `event`.
    """
    errors: list[str] = []

    if not isinstance(event, SignalEvent):
        return ["event must be a SignalEvent instance"]

    # 1. Required non-empty string fields.
    required = {
        "signal_id":      event.signal_id,
        "strategy_id":    event.strategy_id,
        "symbol":         event.symbol,
        "timestamp_iso":  event.timestamp_iso,
        "source_monitor": event.source_monitor,
    }
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name} must be a non-empty string")

    # 2. Pipeline enum.
    if event.pipeline not in ALLOWED_PIPELINES:
        errors.append(
            f"pipeline={event.pipeline!r} not in ALLOWED_PIPELINES "
            f"({sorted(ALLOWED_PIPELINES)})"
        )

    # 3. Action enum.
    if event.action not in ALLOWED_ACTIONS:
        errors.append(
            f"action={event.action!r} not in ALLOWED_ACTIONS "
            f"({sorted(ALLOWED_ACTIONS)})"
        )

    # 4. Side enum.
    if event.side not in ALLOWED_SIDES:
        errors.append(
            f"side={event.side!r} not in ALLOWED_SIDES "
            f"({sorted(ALLOWED_SIDES)})"
        )

    # 5. Evidence source must be a known value.
    if not _evidence_source_allowed(event.evidence_source):
        errors.append(
            f"evidence_source={event.evidence_source!r} not recognised "
            f"(expected one of {sorted(_FALLBACK_EVIDENCE_SOURCES)})"
        )

    # 6. entry_capable contract.
    if event.entry_capable:
        if not isinstance(event.confidence_inputs, dict) or not event.confidence_inputs:
            errors.append(
                "entry_capable=True requires non-empty confidence_inputs dict"
            )
        if not isinstance(event.risk_inputs, dict) or not event.risk_inputs:
            errors.append(
                "entry_capable=True requires non-empty risk_inputs dict"
            )

    # 7. asset_class must be a string (may be empty for some observe events).
    if not isinstance(event.asset_class, str):
        errors.append("asset_class must be a string")

    return errors


# ─── Helpers ─────────────────────────────────────────────────────────────────


def build_signal_id(strategy_id: str, symbol: str,
                    timestamp_iso: str, source_monitor: str) -> str:
    """Deterministic short signal id.

    Format: "{strategy_id}:{symbol}:{ts_short}:{src_short}" where ts_short
    is a short hash of timestamp_iso and src_short is a short hash of
    source_monitor. Stable across runs given identical inputs.
    """
    def _short(s: str, n: int = 8) -> str:
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
        return digest[:n]

    strat = (strategy_id or "?").strip() or "?"
    sym   = (symbol or "?").strip() or "?"
    ts    = (timestamp_iso or "").strip()
    src   = (source_monitor or "").strip()

    return f"{strat}:{sym}:{_short(ts)}:{_short(src, 6)}"


def to_dict(event: SignalEvent) -> dict:
    """JSON-safe dict representation of a SignalEvent.

    Defensive copies of all dict fields so that downstream mutation can
    never leak back into the frozen event.
    """
    if not isinstance(event, SignalEvent):
        raise TypeError("to_dict expects a SignalEvent instance")
    d = asdict(event)
    # Ensure all dict fields are independent copies.
    for key in (
        "raw_signal",
        "market_regime",
        "confidence_inputs",
        "risk_inputs",
        "universe_status",
        "pre_open_flags",
        "metadata",
    ):
        d[key] = dict(d.get(key) or {})
    return d


def from_dict(d: dict) -> SignalEvent:
    """Reconstruct a SignalEvent from a dict. Validates first.

    Raises ValueError with the validation errors if the resulting event
    does not pass `validate(...)`.
    """
    if not isinstance(d, dict):
        raise TypeError("from_dict expects a dict")

    event = SignalEvent(
        signal_id         = str(d.get("signal_id", "")),
        strategy_id       = str(d.get("strategy_id", "")),
        symbol            = str(d.get("symbol", "")),
        asset_class       = str(d.get("asset_class", "")),
        side              = str(d.get("side", "")),
        action            = str(d.get("action", "")),
        timestamp_iso     = str(d.get("timestamp_iso", "")),
        source_monitor    = str(d.get("source_monitor", "")),
        pipeline          = str(d.get("pipeline", "")),
        evidence_source   = str(d.get("evidence_source", "")),
        entry_capable     = bool(d.get("entry_capable", False)),
        raw_signal        = dict(d.get("raw_signal") or {}),
        market_regime     = dict(d.get("market_regime") or {}),
        confidence_inputs = dict(d.get("confidence_inputs") or {}),
        risk_inputs       = dict(d.get("risk_inputs") or {}),
        universe_status   = dict(d.get("universe_status") or {}),
        pre_open_flags    = dict(d.get("pre_open_flags") or {}),
        metadata          = dict(d.get("metadata") or {}),
    )
    errs = validate(event)
    if errs:
        raise ValueError(f"Invalid SignalEvent: {errs}")
    return event


__all__ = [
    "SignalEvent",
    "ALLOWED_PIPELINES",
    "ALLOWED_ACTIONS",
    "ALLOWED_SIDES",
    "validate",
    "build_signal_id",
    "to_dict",
    "from_dict",
]

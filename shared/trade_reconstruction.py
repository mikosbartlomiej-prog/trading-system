"""v3.23.0 (2026-06-08) — Trade reconstruction repair.

After 2026-06-08 audit revealed:
- state.json::cumulative.total_trades = 0
- BUT journal/autonomy/2026-06-04.jsonl contains 7 safe_close events
- AND learning-loop/allocations/2026-06-04.execution.json shows 8 BUY fills

The existing learning-loop/analyzer.py::reconstruct_trades couldn't
FIFO-pair the BUYs with the safe_close exits because the matching
logic used client_order_id prefix conventions that didn't span
both flows. The strategies looked SILENT 64 days even though
positions were opening and closing.

This module is a deterministic FIFO lot matcher with explicit
status enum so downstream callers (analyzer, ranking, edge_gate)
can distinguish:

- a closed trade with realized P&L (when both prices are known)
- a closed trade with PRICE_MISSING (one side has no fill price)
- an unmatched open (lot still on disk)
- an unmatched close (orphan close — no matching open)
- a broker-side close inferred (no local safe_close but dashboard
  confirms not-open)

CONTRACT
--------
- READ-ONLY. No trades placed. No state mutations.
- No fake P&L when data is missing.
- No treating unmatched opens as closed without evidence.
- No treating closed dashboard-missing positions as open without
  evidence.
- Returns a single TradeReconstructionReport dict that callers can
  feed to docs/JSON renderers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ─── Status enum (closed) ────────────────────────────────────────────────────

TRADE_CLOSED_WITH_PNL              = "TRADE_CLOSED_WITH_PNL"
TRADE_CLOSED_PRICE_MISSING         = "TRADE_CLOSED_PRICE_MISSING"
TRADE_BROKER_SIDE_CLOSE_INFERRED   = "TRADE_BROKER_SIDE_CLOSE_INFERRED"
TRADE_UNMATCHED_OPEN               = "TRADE_UNMATCHED_OPEN"
TRADE_UNMATCHED_CLOSE              = "TRADE_UNMATCHED_CLOSE"
TRADE_PARTIAL_CLOSE                = "TRADE_PARTIAL_CLOSE"

ALL_TRADE_STATUSES: frozenset[str] = frozenset({
    TRADE_CLOSED_WITH_PNL,
    TRADE_CLOSED_PRICE_MISSING,
    TRADE_BROKER_SIDE_CLOSE_INFERRED,
    TRADE_UNMATCHED_OPEN,
    TRADE_UNMATCHED_CLOSE,
    TRADE_PARTIAL_CLOSE,
})

# Invariants — test-asserted.
NEVER_PLACES_ORDERS               = True
NEVER_INVENTS_PRICES              = True
NEVER_MARKS_OPEN_AS_CLOSED_WITHOUT_EVIDENCE = True


# ─── Data shapes ─────────────────────────────────────────────────────────────


@dataclass
class Lot:
    """One open lot per FIFO matching pass."""
    symbol: str
    qty: float
    open_price: float | None
    open_ts: str
    open_source: str           # e.g. "allocator-rebalance", "safe_close" (for short)
    open_client_order_id: str | None = None


@dataclass
class Trade:
    """A reconstructed (open, close) pair OR an unmatched entry."""
    symbol: str
    status: str
    qty: float = 0.0
    open_price: float | None = None
    open_ts: str | None = None
    open_source: str | None = None
    close_price: float | None = None
    close_ts: str | None = None
    close_source: str | None = None
    realized_pnl_usd: float | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol":            self.symbol,
            "status":            self.status,
            "qty":               self.qty,
            "open_price":        self.open_price,
            "open_ts":           self.open_ts,
            "open_source":       self.open_source,
            "close_price":       self.close_price,
            "close_ts":          self.close_ts,
            "close_source":      self.close_source,
            "realized_pnl_usd":  self.realized_pnl_usd,
            "notes":             self.notes,
        }


@dataclass
class TradeReconstructionReport:
    trades: list[Trade] = field(default_factory=list)
    unmatched_opens: list[Lot] = field(default_factory=list)
    unmatched_closes: list[dict] = field(default_factory=list)
    broker_side_close_inferred: list[Trade] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trades":            [t.to_dict() for t in self.trades],
            "unmatched_opens":   [{
                "symbol":        l.symbol,
                "qty":           l.qty,
                "open_price":    l.open_price,
                "open_ts":       l.open_ts,
                "open_source":   l.open_source,
            } for l in self.unmatched_opens],
            "unmatched_closes":  list(self.unmatched_closes),
            "broker_side_close_inferred": [t.to_dict() for t in self.broker_side_close_inferred],
            "metrics":           dict(self.metrics),
        }


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float | None = None) -> float | None:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _is_open_event(event: dict) -> bool:
    """Order/audit event that opens a position (BUY for long)."""
    et = (event.get("event_type") or event.get("decision_type") or "").upper()
    if et in ("OPEN_POSITION", "PLACE_BRACKET"):
        return True
    side = (event.get("side") or event.get("action") or "").lower()
    status = (event.get("status") or event.get("decision") or "").lower()
    src = (event.get("source") or event.get("actor") or "").lower()
    return (
        side in ("buy", "buy_to_open")
        and status in ("placed", "filled")
        and src in ("allocator-rebalance", "allocator", "place_stock_bracket",
                     "options-momentum")
    )


def _is_close_event(event: dict) -> bool:
    """Audit event that closes a position (safe_close / CLOSE_POSITION)."""
    et = (event.get("event_type") or event.get("decision_type") or "").upper()
    if et == "CLOSE_POSITION":
        return True
    actor = (event.get("actor") or "").lower()
    if actor == "safe_close":
        return True
    return False


def _symbol(event: dict) -> str:
    s = event.get("symbol")
    if s:
        return str(s).upper().strip()
    affected = event.get("affected_symbols")
    if isinstance(affected, list) and affected:
        return str(affected[0]).upper().strip()
    return ""


# ─── Main reconstruction (deterministic FIFO) ────────────────────────────────


def reconstruct_v323(
    *,
    open_events: list[dict],
    close_events: list[dict],
    dashboard_not_open_symbols: list[str] | None = None,
    has_audit_safe_close: dict[str, bool] | None = None,
) -> TradeReconstructionReport:
    """Pair opens with closes using per-symbol FIFO. Pure function.

    Inputs:
    - open_events: list of dicts with at least symbol, qty, fill_price,
      timestamp, source. Filtered upstream via _is_open_event if raw.
    - close_events: same shape but for closes.
    - dashboard_not_open_symbols: optional list of symbols the operator
      confirmed are NOT open on the dashboard. Used to infer broker-side
      closes for opens that have no matching close in audit.
    - has_audit_safe_close: optional {symbol -> bool} hint to mark
      verified vs inferred status.

    Output: TradeReconstructionReport with trades, unmatched opens,
    unmatched closes, and per-symbol broker-side-close inferences.
    """
    dashboard_not_open = set(s.upper() for s in (dashboard_not_open_symbols or []))
    safe_close_seen = dict(has_audit_safe_close or {})

    # Per-symbol FIFO queues of open lots.
    lots: dict[str, list[Lot]] = {}
    for ev in open_events:
        sym = _symbol(ev)
        if not sym:
            continue
        qty = _safe_float(ev.get("qty") or ev.get("quantity"))
        if qty is None or qty <= 0:
            continue
        open_price = _safe_float(ev.get("fill_price") or ev.get("price")
                                    or ev.get("limit_price") or ev.get("ref_price"))
        lots.setdefault(sym, []).append(Lot(
            symbol=sym,
            qty=qty,
            open_price=open_price,
            open_ts=str(ev.get("timestamp") or ev.get("ts") or ""),
            open_source=str(ev.get("source") or ev.get("actor")
                              or ev.get("strategy") or "unknown"),
            open_client_order_id=ev.get("client_order_id"),
        ))

    trades: list[Trade] = []
    unmatched_closes: list[dict] = []

    # Walk close events in timestamp order and FIFO-pair against lots.
    sorted_closes = sorted(
        close_events,
        key=lambda e: str(e.get("timestamp") or e.get("ts") or ""),
    )

    for ev in sorted_closes:
        sym = _symbol(ev)
        if not sym:
            continue
        qty = _safe_float(ev.get("qty") or ev.get("quantity"))
        if qty is None or qty <= 0:
            continue
        close_price = _safe_float(ev.get("fill_price") or ev.get("price")
                                     or ev.get("limit_price"))
        close_ts = str(ev.get("timestamp") or ev.get("ts") or "")
        close_source = str(ev.get("source") or ev.get("actor") or "safe_close")

        remaining = qty
        while remaining > 0 and lots.get(sym):
            head = lots[sym][0]
            take = min(head.qty, remaining)
            realized = None
            if (close_price is not None and head.open_price is not None):
                realized = round((close_price - head.open_price) * take, 4)
            status = (
                TRADE_CLOSED_WITH_PNL if realized is not None
                else TRADE_CLOSED_PRICE_MISSING
            )
            # Mark partial when only part of a lot is consumed.
            if take < head.qty:
                status = TRADE_PARTIAL_CLOSE
            trades.append(Trade(
                symbol=sym,
                status=status,
                qty=take,
                open_price=head.open_price,
                open_ts=head.open_ts,
                open_source=head.open_source,
                close_price=close_price,
                close_ts=close_ts,
                close_source=close_source,
                realized_pnl_usd=realized,
                notes="paired via FIFO" if status != TRADE_CLOSED_PRICE_MISSING
                       else "paired via FIFO; close_price OR open_price missing",
            ))
            head.qty -= take
            remaining -= take
            if head.qty <= 1e-9:
                lots[sym].pop(0)
        if remaining > 0:
            unmatched_closes.append({
                "symbol":       sym,
                "qty_remaining": remaining,
                "close_price":  close_price,
                "close_ts":     close_ts,
                "close_source": close_source,
                "status":       TRADE_UNMATCHED_CLOSE,
            })

    # Anything left in lots is unmatched_open OR broker-side-closed.
    unmatched_opens: list[Lot] = []
    broker_side_inferred: list[Trade] = []
    for sym, queue in lots.items():
        for lot in queue:
            if sym in dashboard_not_open and not safe_close_seen.get(sym, False):
                broker_side_inferred.append(Trade(
                    symbol=sym,
                    status=TRADE_BROKER_SIDE_CLOSE_INFERRED,
                    qty=lot.qty,
                    open_price=lot.open_price,
                    open_ts=lot.open_ts,
                    open_source=lot.open_source,
                    close_price=None,
                    close_ts=None,
                    close_source="BROKER_SIDE_CLOSE_INFERRED_FROM_DASHBOARD",
                    realized_pnl_usd=None,
                    notes=(
                        "Dashboard confirms NOT open + no local safe_close in audit "
                        "→ bracket SL/TP child likely fired at broker. "
                        "Requires Alpaca order history for close price."
                    ),
                ))
            else:
                unmatched_opens.append(lot)

    # Metrics.
    closed_with_pnl_count = sum(
        1 for t in trades if t.status == TRADE_CLOSED_WITH_PNL
    )
    closed_price_missing_count = sum(
        1 for t in trades if t.status == TRADE_CLOSED_PRICE_MISSING
    )
    partial_count = sum(1 for t in trades if t.status == TRADE_PARTIAL_CLOSE)

    metrics = {
        "open_events_seen":              len(open_events),
        "close_events_seen":             len(close_events),
        "lots_paired":                   len(trades),
        "closed_with_pnl":               closed_with_pnl_count,
        "closed_price_missing":          closed_price_missing_count,
        "partial_closes":                partial_count,
        "broker_side_close_inferred":    len(broker_side_inferred),
        "unmatched_opens":               len(unmatched_opens),
        "unmatched_closes":              len(unmatched_closes),
        "reconstructed_closed_trades_count": len(trades) + len(broker_side_inferred),
    }

    return TradeReconstructionReport(
        trades=trades,
        unmatched_opens=unmatched_opens,
        unmatched_closes=unmatched_closes,
        broker_side_close_inferred=broker_side_inferred,
        metrics=metrics,
    )


# ─── Helper for reading audit JSONL ──────────────────────────────────────────


def filter_open_events_from_audit(events: list[dict]) -> list[dict]:
    """Return events that look like position-opening fills."""
    return [e for e in events if _is_open_event(e)]


def filter_close_events_from_audit(events: list[dict]) -> list[dict]:
    """Return events that look like position-closing actions."""
    return [e for e in events if _is_close_event(e)]


__all__ = [
    "TRADE_CLOSED_WITH_PNL", "TRADE_CLOSED_PRICE_MISSING",
    "TRADE_BROKER_SIDE_CLOSE_INFERRED",
    "TRADE_UNMATCHED_OPEN", "TRADE_UNMATCHED_CLOSE",
    "TRADE_PARTIAL_CLOSE",
    "ALL_TRADE_STATUSES",
    "NEVER_PLACES_ORDERS", "NEVER_INVENTS_PRICES",
    "NEVER_MARKS_OPEN_AS_CLOSED_WITHOUT_EVIDENCE",
    "Lot", "Trade", "TradeReconstructionReport",
    "reconstruct_v323",
    "filter_open_events_from_audit",
    "filter_close_events_from_audit",
]

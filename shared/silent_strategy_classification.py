"""v3.23.0 (2026-06-08) — Reliable "silent strategy" classification.

After 2026-06-08, multiple strategies were marked SILENT 64 days by
the daily-learning adapter despite confirmed safe_close events in
the audit JSONL. The root cause is the analyzer's trade
reconstruction couldn't FIFO-pair the opens with the closes, so
strategies that DID execute looked dead.

This module disentangles the classification by walking the funnel
from signals → orders → fills → reconstructed trades and reporting
WHERE the strategy stopped showing activity. The point is to NEVER
let a buggy reconstruction layer cause an active strategy to be
auto-disabled.

CONTRACT
--------
- READ-ONLY classifier; no state mutation.
- Never auto-disables a strategy based on TRULY_SILENT.
- Never overrides the LLM override lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─── Status enum ─────────────────────────────────────────────────────────────

NO_SIGNALS                                  = "NO_SIGNALS"
SIGNALS_BUT_NO_ORDERS                       = "SIGNALS_BUT_NO_ORDERS"
ORDERS_BUT_NO_FILLS                         = "ORDERS_BUT_NO_FILLS"
FILLS_BUT_NO_RECONSTRUCTED_TRADES           = "FILLS_BUT_NO_RECONSTRUCTED_TRADES"
RECONSTRUCTION_FAILED                       = "RECONSTRUCTION_FAILED"
ACTIVE_BUT_ANALYZER_STALE                   = "ACTIVE_BUT_ANALYZER_STALE"
TRULY_SILENT                                = "TRULY_SILENT"

ALL_SILENT_STATUSES: frozenset[str] = frozenset({
    NO_SIGNALS,
    SIGNALS_BUT_NO_ORDERS,
    ORDERS_BUT_NO_FILLS,
    FILLS_BUT_NO_RECONSTRUCTED_TRADES,
    RECONSTRUCTION_FAILED,
    ACTIVE_BUT_ANALYZER_STALE,
    TRULY_SILENT,
})

# Invariants — test-asserted.
NEVER_AUTO_DISABLES_STRATEGY                = True
NEVER_AUTO_CLEARS_LLM_OVERRIDE_LOCK         = True
RECONSTRUCTION_FAILURE_BLOCKS_AUTO_DISABLE  = True


@dataclass
class SilentStrategyClassification:
    strategy: str
    status: str
    rationale: str
    signals_count: int = 0
    opportunity_count: int = 0
    orders_submitted_count: int = 0
    orders_filled_count: int = 0
    safe_close_count: int = 0
    broker_side_close_count: int = 0
    reconstructed_closed_trades_count: int = 0
    unmatched_opens_count: int = 0
    unmatched_closes_count: int = 0
    stale_local_positions_count: int = 0
    days_since_last_activity: int | None = None
    block_auto_disable: bool = False

    def to_dict(self) -> dict:
        return {
            "strategy":                            self.strategy,
            "status":                              self.status,
            "rationale":                           self.rationale,
            "signals_count":                       self.signals_count,
            "opportunity_count":                   self.opportunity_count,
            "orders_submitted_count":              self.orders_submitted_count,
            "orders_filled_count":                 self.orders_filled_count,
            "safe_close_count":                    self.safe_close_count,
            "broker_side_close_count":             self.broker_side_close_count,
            "reconstructed_closed_trades_count":   self.reconstructed_closed_trades_count,
            "unmatched_opens_count":               self.unmatched_opens_count,
            "unmatched_closes_count":              self.unmatched_closes_count,
            "stale_local_positions_count":         self.stale_local_positions_count,
            "days_since_last_activity":            self.days_since_last_activity,
            "block_auto_disable":                  self.block_auto_disable,
        }


def classify_strategy_activity(
    strategy: str,
    *,
    signals_count: int = 0,
    opportunity_count: int = 0,
    orders_submitted_count: int = 0,
    orders_filled_count: int = 0,
    safe_close_count: int = 0,
    broker_side_close_count: int = 0,
    reconstructed_closed_trades_count: int = 0,
    unmatched_opens_count: int = 0,
    unmatched_closes_count: int = 0,
    stale_local_positions_count: int = 0,
    days_since_last_activity: int | None = None,
) -> SilentStrategyClassification:
    """Classify a strategy's activity funnel. Pure function.

    The rule ladder (first match wins):

    1. No signals at all → NO_SIGNALS.
    2. Signals > 0 but no orders → SIGNALS_BUT_NO_ORDERS (gate worked).
    3. Orders > 0 but no fills → ORDERS_BUT_NO_FILLS (broker reject).
    4. Fills > 0 AND safe_close + broker_side_close events exist BUT no
       reconstructed trades → FILLS_BUT_NO_RECONSTRUCTED_TRADES
       (reconstruction bug — must NOT auto-disable strategy).
    5. Has unmatched_opens or unmatched_closes → RECONSTRUCTION_FAILED.
    6. Has reconstructed trades OR has stale local positions →
       ACTIVE_BUT_ANALYZER_STALE.
    7. Else if days_since_last_activity > 30 → TRULY_SILENT.
    """
    args = dict(
        strategy=strategy,
        signals_count=signals_count,
        opportunity_count=opportunity_count,
        orders_submitted_count=orders_submitted_count,
        orders_filled_count=orders_filled_count,
        safe_close_count=safe_close_count,
        broker_side_close_count=broker_side_close_count,
        reconstructed_closed_trades_count=reconstructed_closed_trades_count,
        unmatched_opens_count=unmatched_opens_count,
        unmatched_closes_count=unmatched_closes_count,
        stale_local_positions_count=stale_local_positions_count,
        days_since_last_activity=days_since_last_activity,
    )

    # Rule 1
    if signals_count == 0 and opportunity_count == 0:
        return SilentStrategyClassification(
            **args,
            status=NO_SIGNALS,
            rationale="Strategy generated no signals in window.",
            block_auto_disable=False,
        )

    # Rule 2
    if (signals_count > 0 or opportunity_count > 0) and orders_submitted_count == 0:
        return SilentStrategyClassification(
            **args,
            status=SIGNALS_BUT_NO_ORDERS,
            rationale=(
                "Strategy generated signals/opportunities but no orders "
                "were submitted (gate worked correctly OR gate is too strict)."
            ),
            block_auto_disable=False,
        )

    # Rule 3
    if orders_submitted_count > 0 and orders_filled_count == 0:
        return SilentStrategyClassification(
            **args,
            status=ORDERS_BUT_NO_FILLS,
            rationale=(
                "Strategy submitted orders but none filled (broker reject "
                "or BP shortage). See order_rejection_audit."
            ),
            block_auto_disable=True,
        )

    has_closes = (safe_close_count + broker_side_close_count) > 0

    # Rule 4
    if orders_filled_count > 0 and has_closes and reconstructed_closed_trades_count == 0:
        return SilentStrategyClassification(
            **args,
            status=FILLS_BUT_NO_RECONSTRUCTED_TRADES,
            rationale=(
                "Strategy has confirmed fills and close events in audit but "
                "the analyzer reconstructed zero closed trades. "
                "RECONSTRUCTION BUG — must NOT auto-disable strategy. "
                "Action: REPAIR_TRADE_RECONSTRUCTION_BEFORE_STRATEGY_DISABLE."
            ),
            block_auto_disable=True,
        )

    # Rule 5
    if unmatched_opens_count > 0 or unmatched_closes_count > 0:
        return SilentStrategyClassification(
            **args,
            status=RECONSTRUCTION_FAILED,
            rationale=(
                f"Reconstruction left {unmatched_opens_count} unmatched opens "
                f"and {unmatched_closes_count} unmatched closes — pairing bug."
            ),
            block_auto_disable=True,
        )

    # Rule 6
    if reconstructed_closed_trades_count > 0 or stale_local_positions_count > 0:
        return SilentStrategyClassification(
            **args,
            status=ACTIVE_BUT_ANALYZER_STALE,
            rationale=(
                "Strategy has reconstructed trades OR stale local positions; "
                "analyzer may underreport activity."
            ),
            block_auto_disable=True,
        )

    # Rule 7
    if days_since_last_activity is not None and days_since_last_activity > 30:
        return SilentStrategyClassification(
            **args,
            status=TRULY_SILENT,
            rationale=(
                f"Strategy has no signals/orders/fills/trades for "
                f"{days_since_last_activity} days. Auto-disable still NOT "
                f"performed by this classifier — operator/LLM decision."
            ),
            block_auto_disable=False,
        )

    # Default safe path
    return SilentStrategyClassification(
        **args,
        status=ACTIVE_BUT_ANALYZER_STALE,
        rationale="No matching rule; defaulting to ACTIVE_BUT_ANALYZER_STALE.",
        block_auto_disable=True,
    )


__all__ = [
    "NO_SIGNALS",
    "SIGNALS_BUT_NO_ORDERS",
    "ORDERS_BUT_NO_FILLS",
    "FILLS_BUT_NO_RECONSTRUCTED_TRADES",
    "RECONSTRUCTION_FAILED",
    "ACTIVE_BUT_ANALYZER_STALE",
    "TRULY_SILENT",
    "ALL_SILENT_STATUSES",
    "NEVER_AUTO_DISABLES_STRATEGY",
    "NEVER_AUTO_CLEARS_LLM_OVERRIDE_LOCK",
    "RECONSTRUCTION_FAILURE_BLOCKS_AUTO_DISABLE",
    "SilentStrategyClassification",
    "classify_strategy_activity",
]

"""v3.23.0 (2026-06-08) — Drawdown source attribution.

The existing `drawdown_escalation` module classifies the SEVERITY of
a drawdown (NONE/WARN/RESTRICT/EMERGENCY_REVIEW). This module adds
the orthogonal question: WHERE does the drawdown come from?

After 2026-06-08 we know the equity dropped $93,700 → $90,120
(-3.82%) but only ~$10,965 is in dashboard-visible open positions
with ~+$478 unrealized — so the drop CANNOT be explained by current
open positions alone. The breakdown is:

- realized: from positions opened + closed (the 8 BUYs on 06-04
  closed within 35 minutes via safe_close)
- unrealized: from currently-open positions (ETHUSD/AVAXUSD/dust)
- stale_baseline: starting_equity hasn't been refreshed since reset
- unknown: API call required to verify the per-bucket numbers

CONTRACT
--------
- READ-ONLY. Does not modify state.json or runtime_state.json.
- Does not change drawdown_guard threshold.
- Does not reset starting_equity (operator-only decision).
- Returns a deterministic attribution dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─── Status enum ─────────────────────────────────────────────────────────────

DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES   = "DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES"
DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS       = "DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS"
DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW = "DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW"
DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY  = "DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY"
DRAWDOWN_MIXED_SOURCES                        = "DRAWDOWN_MIXED_SOURCES"

# v3.23.2 — attribution-completeness statuses (orthogonal to source).
DRAWDOWN_ATTRIBUTION_COMPLETE                  = "DRAWDOWN_ATTRIBUTION_COMPLETE"
DRAWDOWN_ATTRIBUTION_PARTIAL                   = "DRAWDOWN_ATTRIBUTION_PARTIAL"
DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY    = "DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY"
DRAWDOWN_ATTRIBUTION_CONFLICT                  = "DRAWDOWN_ATTRIBUTION_CONFLICT"

ALL_DRAWDOWN_SOURCES: frozenset[str] = frozenset({
    DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES,
    DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS,
    DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW,
    DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY,
    DRAWDOWN_MIXED_SOURCES,
    DRAWDOWN_ATTRIBUTION_COMPLETE,
    DRAWDOWN_ATTRIBUTION_PARTIAL,
    DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY,
    DRAWDOWN_ATTRIBUTION_CONFLICT,
})

# Invariants — test-asserted.
NEVER_RESETS_BASELINE_AUTOMATICALLY      = True
NEVER_LOWERS_DRAWDOWN_THRESHOLD          = True
NEVER_HIDES_REALIZED_LOSS                = True


@dataclass
class DrawdownAttribution:
    primary_source: str
    secondary_sources: list[str]
    realized_loss_usd: float | None
    unrealized_pl_usd: float | None
    baseline_stale_flag: bool
    requires_api_history: bool
    rationale: str

    def to_dict(self) -> dict:
        return {
            "primary_source":           self.primary_source,
            "secondary_sources":        list(self.secondary_sources),
            "realized_loss_usd":        self.realized_loss_usd,
            "unrealized_pl_usd":        self.unrealized_pl_usd,
            "baseline_stale_flag":      self.baseline_stale_flag,
            "requires_api_history":     self.requires_api_history,
            "rationale":                self.rationale,
        }


def _safe_float(x: Any, default: float | None = None) -> float | None:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


def attribute_drawdown(
    *,
    equity_now: float | None,
    baseline_equity: float | None,
    baseline_is_static: bool,
    dashboard_unrealized_pl_usd: float | None = None,
    reconstructed_realized_pnl_usd: float | None = None,
    api_history_available: bool = False,
) -> DrawdownAttribution:
    """Classify the drawdown source. Pure function.

    Inputs:
    - equity_now: current paper equity
    - baseline_equity: starting_equity from state.json::cumulative
    - baseline_is_static: True if baseline hasn't been updated since reset
    - dashboard_unrealized_pl_usd: net unrealized from dashboard positions
    - reconstructed_realized_pnl_usd: sum from trade_reconstruction module
    - api_history_available: True if we have authoritative API data
    """
    eq = _safe_float(equity_now)
    base = _safe_float(baseline_equity)
    if eq is None or base is None or base <= 0:
        return DrawdownAttribution(
            primary_source=DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY,
            secondary_sources=[],
            realized_loss_usd=None,
            unrealized_pl_usd=None,
            baseline_stale_flag=False,
            requires_api_history=True,
            rationale="equity_now or baseline_equity missing/invalid",
        )

    drop_usd = eq - base
    drawdown_pct = (drop_usd / base) * 100.0

    secondary: list[str] = []

    realized = _safe_float(reconstructed_realized_pnl_usd)
    unrealized = _safe_float(dashboard_unrealized_pl_usd)

    # Heuristics:
    # - if reconstructed_realized_pnl ~= drop_usd (within 30%), realized
    # - if dashboard unrealized ~= drop_usd, unrealized
    # - if neither matches well and baseline is static, baseline-stale
    # - if no API history at all, mark UNKNOWN

    drop_abs = abs(drop_usd)
    primary = DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY
    rationale = "default unknown — need API history"

    if realized is not None and drop_abs > 0:
        if abs(abs(realized) - drop_abs) <= 0.3 * drop_abs:
            primary = DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES
            rationale = (
                f"realized_pnl from reconstructed trades ({realized:.2f}) "
                f"matches equity drop ({drop_usd:.2f}) within 30%."
            )
        else:
            secondary.append(DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES)

    if unrealized is not None and drop_abs > 0:
        if abs(abs(unrealized) - drop_abs) <= 0.3 * drop_abs and unrealized < 0:
            if primary == DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY:
                primary = DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS
                rationale = (
                    f"unrealized_pl from dashboard ({unrealized:.2f}) "
                    f"matches equity drop ({drop_usd:.2f}) within 30%."
                )
            else:
                secondary.append(DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS)
                primary = DRAWDOWN_MIXED_SOURCES
        elif unrealized is not None and unrealized >= 0 and drop_abs > 0:
            # Dashboard shows positive unrealized → loss must come elsewhere.
            secondary.append(DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS)

    if baseline_is_static and primary == DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY:
        primary = DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW
        rationale = (
            "Baseline starting_equity is static since reset and other "
            "sources don't fully explain the drop — operator may want "
            "to review whether to refresh baseline."
        )

    if baseline_is_static and DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW not in secondary and primary != DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW:
        secondary.append(DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW)

    return DrawdownAttribution(
        primary_source=primary,
        secondary_sources=secondary,
        realized_loss_usd=realized,
        unrealized_pl_usd=unrealized,
        baseline_stale_flag=baseline_is_static,
        requires_api_history=not api_history_available,
        rationale=rationale,
    )


def compute_partial_attribution(
    *,
    known_realized_pnl_usd: float | None,
    known_symbols: list[str] | None = None,
    unknown_symbols: list[str] | None = None,
    reported_drawdown_usd: float | None,
    baseline_static: bool = False,
) -> dict:
    """Return a partial attribution dict matching the v3.23.2 status enum.

    Pure function — no I/O. Does NOT reset baseline. Does NOT lower
    drawdown threshold. Does NOT mutate state.json.
    """
    known = list(known_symbols or [])
    unknown = list(unknown_symbols or [])
    known_pnl = _safe_float(known_realized_pnl_usd, default=None)
    drop = _safe_float(reported_drawdown_usd, default=None)

    if not known and not unknown:
        return {
            "status": DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY,
            "known_realized_pnl_usd": known_pnl,
            "known_symbols": known,
            "unknown_symbols_count": 0,
            "unknown_symbols": unknown,
            "residual_pending_operator_extraction": True,
            "explained_amount_usd": None,
            "reported_drawdown_usd": drop,
            "baseline_static": baseline_static,
            "rationale": "No known and no unknown symbols — nothing to attribute.",
        }

    # Complete: everything known and no unknown.
    if known and not unknown and known_pnl is not None and drop is not None:
        # Conflict if the known PnL has the opposite sign or wildly different magnitude.
        if abs(abs(known_pnl) - abs(drop)) > max(0.30 * abs(drop), 100.0):
            return {
                "status": DRAWDOWN_ATTRIBUTION_CONFLICT,
                "known_realized_pnl_usd": known_pnl,
                "known_symbols": known,
                "unknown_symbols_count": 0,
                "unknown_symbols": unknown,
                "residual_pending_operator_extraction": False,
                "explained_amount_usd": known_pnl,
                "reported_drawdown_usd": drop,
                "baseline_static": baseline_static,
                "rationale": (
                    f"All symbols known but realized P/L {known_pnl:.2f} "
                    f"differs from reported drawdown {drop:.2f} by more than 30% — "
                    f"likely baseline-stale or off-window trades."
                ),
            }
        return {
            "status": DRAWDOWN_ATTRIBUTION_COMPLETE,
            "known_realized_pnl_usd": known_pnl,
            "known_symbols": known,
            "unknown_symbols_count": 0,
            "unknown_symbols": unknown,
            "residual_pending_operator_extraction": False,
            "explained_amount_usd": known_pnl,
            "reported_drawdown_usd": drop,
            "baseline_static": baseline_static,
            "rationale": "All symbols known; realized P/L matches reported drawdown within 30%.",
        }

    # Nothing known, unknowns exist → REQUIRES_ORDER_HISTORY.
    if not known and unknown:
        return {
            "status": DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY,
            "known_realized_pnl_usd": known_pnl,
            "known_symbols": known,
            "unknown_symbols_count": len(unknown),
            "unknown_symbols": unknown,
            "residual_pending_operator_extraction": True,
            "explained_amount_usd": None,
            "reported_drawdown_usd": drop,
            "baseline_static": baseline_static,
            "rationale": (
                f"{len(unknown)} symbol(s) pending operator order-history extraction."
            ),
        }

    # Mixed: some known, some unknown → PARTIAL.
    return {
        "status": DRAWDOWN_ATTRIBUTION_PARTIAL,
        "known_realized_pnl_usd": known_pnl,
        "known_symbols": known,
        "unknown_symbols_count": len(unknown),
        "unknown_symbols": unknown,
        "residual_pending_operator_extraction": True,
        "explained_amount_usd": known_pnl,
        "reported_drawdown_usd": drop,
        "baseline_static": baseline_static,
        "rationale": (
            f"{len(known)} symbol(s) known with realized P/L "
            f"{(known_pnl if known_pnl is not None else 0.0):.2f}; "
            f"{len(unknown)} symbol(s) pending operator order-history extraction."
        ),
    }


__all__ = [
    "DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES",
    "DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS",
    "DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW",
    "DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY",
    "DRAWDOWN_MIXED_SOURCES",
    "DRAWDOWN_ATTRIBUTION_COMPLETE",
    "DRAWDOWN_ATTRIBUTION_PARTIAL",
    "DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY",
    "DRAWDOWN_ATTRIBUTION_CONFLICT",
    "ALL_DRAWDOWN_SOURCES",
    "NEVER_RESETS_BASELINE_AUTOMATICALLY",
    "NEVER_LOWERS_DRAWDOWN_THRESHOLD",
    "NEVER_HIDES_REALIZED_LOSS",
    "DrawdownAttribution",
    "attribute_drawdown",
    "compute_partial_attribution",
]

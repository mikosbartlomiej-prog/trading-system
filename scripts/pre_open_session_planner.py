#!/usr/bin/env python3
"""v3.18.0 (2026-06-04) — Pre-open session planner.

WHY
---
Runs ~30 min before market open (cron `0 13 * * 1-5`). For each enabled
strategy + symbol in the current watchlist:
  1. Fetch pre-market context via shared/pre_market_data.get_pre_market_context.
  2. Analyze via shared/pre_open_behavior.analyze_pre_open.
  3. Persist per-symbol plan in learning-loop/runtime_state.json::pre_open_plan
     via shared/pre_open_plan.store_plan.

Monitors read the plan during the session via
`shared.pre_open_plan.get_plan_for_symbol(symbol)` and add the per-symbol
penalty/booster into confidence_inputs.

CRITICAL CONSTRAINTS
--------------------
- This script NEVER places orders.
- NEVER raises confidence by more than +0.05 (enforced in pre_open_plan).
- NEVER modifies risk limits or strategy state.
- Pre-market data unavailable → entry = "no_data" warning, no boost.
- Fail-soft at every layer: any fetch/parse/store error is logged and
  skipped, but the planner always exits 0.

USAGE
-----
  python3 scripts/pre_open_session_planner.py
  python3 scripts/pre_open_session_planner.py --symbols AAPL MSFT SPY
  python3 scripts/pre_open_session_planner.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Add shared/ to sys.path so we can import without package qualifier.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)


# ─── Watchlist resolution ─────────────────────────────────────────────────────

def _load_watchlist_symbols(symbols_arg: list[str] | None) -> list[str]:
    """Return the list of symbols to plan for.

    Precedence:
      1. --symbols CLI argument.
      2. config/watchlists.json buckets (all enabled).
      3. Hard-coded conservative fallback (SPY, QQQ).
    """
    if symbols_arg:
        return sorted({s.upper() for s in symbols_arg if s})

    syms: set[str] = set()
    wl_path = os.path.join(_REPO_ROOT, "config", "watchlists.json")
    try:
        with open(wl_path, encoding="utf-8") as f:
            data = json.load(f) or {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            tickers = v.get("tickers") or v.get("symbols") or []
            if isinstance(tickers, list):
                for t in tickers:
                    if isinstance(t, str) and t:
                        syms.add(t.upper())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    if not syms:
        return ["SPY", "QQQ"]
    return sorted(syms)


# ─── Per-symbol planning ─────────────────────────────────────────────────────

def _plan_one_symbol(symbol: str) -> dict:
    """Build one plan entry. Always fail-soft.

    Returns the dict that pre_open_plan.store_plan will sanitize again
    (defense-in-depth).
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Step 1: pre-market context (Yahoo → Nasdaq cascade in shared/pre_market_data)
    ctx = {}
    try:
        try:
            from pre_market_data import get_pre_market_context
        except ImportError:
            from shared.pre_market_data import get_pre_market_context  # type: ignore
        ctx = get_pre_market_context(symbol) or {}
    except Exception:
        ctx = {}

    bars = ctx.get("pre_market_bars") or []
    prev_close = ctx.get("prev_session_close")
    prev_high  = ctx.get("prev_session_high")
    prev_low   = ctx.get("prev_session_low")
    source = ctx.get("source") or "unavailable"
    warnings = list(ctx.get("warnings") or [])

    # Step 2: analyze
    analysis = None
    try:
        try:
            from pre_open_behavior import analyze_pre_open
        except ImportError:
            from shared.pre_open_behavior import analyze_pre_open  # type: ignore
        analysis = analyze_pre_open(
            pre_market_bars=bars,
            prev_session_close=prev_close,
            prev_session_high=prev_high,
            prev_session_low=prev_low,
        )
    except Exception as e:
        warnings.append(f"analyze_error:{type(e).__name__}")
        analysis = None

    if analysis is None or getattr(analysis, "insufficient_data", True):
        return {
            "symbol":                symbol,
            "label":                 "INSUFFICIENT_DATA",
            "gap_pct":               None,
            "warnings":              warnings + ["no_data"],
            "confidence_adjustment": 0.0,
            "source":                source,
            "rationale":             "pre_market_data_unavailable_normal_session",
            "generated_at":          now_iso,
        }

    # Map analyzer label → warnings list (consumed by confidence_builder)
    label = analysis.label
    label_warnings: list[str] = []
    if label in ("GAP_UP_STRONG_PRE_OPEN", "GAP_DOWN_STRONG_PRE_OPEN"):
        label_warnings.append("pre_market_gap_strong")
    elif label in ("GAP_UP_WEAK_PRE_OPEN", "GAP_DOWN_WEAK_PRE_OPEN"):
        label_warnings.append("pre_market_gap_weak")
    if label == "LOW_VOLUME_FAKE_MOVE":
        label_warnings.append("pre_market_low_volume_fake_move")
    if label == "HIGH_REL_VOLUME":
        label_warnings.append("pre_market_volume_anomaly")
    if analysis.direction_changes >= 3:
        label_warnings.append("pre_market_choppy_direction_changes")

    return {
        "symbol":                symbol,
        "label":                 label,
        "gap_pct":               analysis.gap_pct,
        "warnings":              warnings + label_warnings,
        # pre_open_plan.store_plan clamps to [-0.10, +0.05] — defense in depth
        "confidence_adjustment": analysis.confidence_adjustment,
        "source":                source,
        "rationale":             analysis.rationale,
        "generated_at":          now_iso,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="Override watchlist with explicit symbols")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan to stdout, do NOT persist")
    ap.add_argument("--plan-date", default=None,
                    help="Override plan date (default UTC today)")
    args = ap.parse_args(argv)

    symbols = _load_watchlist_symbols(args.symbols)
    if not symbols:
        print("[pre-open-planner] no symbols to plan; exiting 0")
        return 0

    print(f"[pre-open-planner] planning {len(symbols)} symbols")
    per_symbol: dict[str, dict] = {}
    overall_warnings: list[str] = []
    summary_counts: dict[str, int] = {}

    for sym in symbols:
        try:
            entry = _plan_one_symbol(sym)
        except Exception as e:
            entry = {
                "symbol":                sym,
                "label":                 "INSUFFICIENT_DATA",
                "gap_pct":               None,
                "warnings":              [f"planner_error:{type(e).__name__}"],
                "confidence_adjustment": 0.0,
                "source":                "unavailable",
                "rationale":             "exception_during_planning",
                "generated_at":          datetime.now(timezone.utc)
                                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        per_symbol[sym] = entry
        lbl = entry.get("label", "INSUFFICIENT_DATA")
        summary_counts[lbl] = summary_counts.get(lbl, 0) + 1

    # Aggregate warnings if data source unavailable for most symbols
    no_data = sum(1 for e in per_symbol.values()
                  if "no_data" in (e.get("warnings") or []))
    if no_data >= max(1, len(symbols) // 2):
        overall_warnings.append("pre_market_data_unavailable_majority")

    plan_date = args.plan_date or datetime.now(timezone.utc).date().isoformat()

    if args.dry_run:
        print(json.dumps({
            "plan_date":       plan_date,
            "symbols_planned": len(per_symbol),
            "summary_counts":  summary_counts,
            "warnings":        overall_warnings,
            "per_symbol":      per_symbol,
        }, indent=2, default=str))
        return 0

    # v3.19.0 — derive v2 session-level fields from per-symbol entries.
    v2_fields = _build_v2_session_fields(per_symbol)

    # Persist
    try:
        try:
            from pre_open_plan import store_plan_v2
        except ImportError:
            from shared.pre_open_plan import store_plan_v2  # type: ignore
        # Ensure STATE_WRITE_ACTOR is acceptable
        os.environ.setdefault("STATE_WRITE_ACTOR", "pre-open-planner")
        store_plan_v2(
            plan_date_iso=plan_date,
            per_symbol_plan=per_symbol,
            actor="pre-open-planner",
            overall_warnings=overall_warnings,
            **v2_fields,
        )
    except Exception as e:
        # Fail-soft: print, but exit 0 — planner must not break the chain.
        print(f"[pre-open-planner] store_plan failed: {e}")
        return 0

    print(f"[pre-open-planner] stored plan for {len(per_symbol)} symbols; "
          f"summary={summary_counts}; warnings={overall_warnings}; "
          f"do_not_trade={len(v2_fields.get('do_not_trade_list') or [])}; "
          f"observe_only={len(v2_fields.get('observe_only_list') or [])}")
    return 0


def _build_v2_session_fields(per_symbol: dict[str, dict]) -> dict:
    """Derive session-level v2 fields from per-symbol plan entries.

    Conservative: no symbol enters do_not_trade UNLESS its label is a
    strong gap or low-volume-fake-move; observe_only catches weaker
    flags. Adjustments NEVER raise confidence (caller path enforces
    this via pre_open_plan.apply_pre_open_caps).
    """
    high_risk: list[str] = []
    do_not_trade: list[str] = []
    observe_only: list[str] = []
    event_risk: list[str] = []
    liquidity: list[str] = []
    gap: list[str] = []
    stale_data: list[str] = []
    caps_per_symbol: dict[str, float] = {}

    for sym, entry in (per_symbol or {}).items():
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or ""
        warnings = entry.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = []

        # Strong pre-market gap → do-not-trade (operator can override).
        if label in ("GAP_UP_STRONG_PRE_OPEN", "GAP_DOWN_STRONG_PRE_OPEN"):
            do_not_trade.append(sym)
            gap.append(f"{sym}:{label}")
            caps_per_symbol[sym] = 0.0

        # Low-volume fake move → observe only.
        elif label == "LOW_VOLUME_FAKE_MOVE":
            observe_only.append(sym)
            liquidity.append(f"{sym}:low_volume_fake")
            caps_per_symbol[sym] = min(caps_per_symbol.get(sym, 1.0), 0.45)

        # Weak gap → cap to 0.65, mark high-risk.
        elif label in ("GAP_UP_WEAK_PRE_OPEN", "GAP_DOWN_WEAK_PRE_OPEN"):
            high_risk.append(sym)
            gap.append(f"{sym}:{label}")
            caps_per_symbol[sym] = min(caps_per_symbol.get(sym, 1.0), 0.65)

        # High relative volume → high-risk (likely catalyst).
        elif label == "HIGH_REL_VOLUME":
            high_risk.append(sym)
            event_risk.append(f"{sym}:high_rel_volume")

        # Insufficient data → mark for observability (no auto-reject).
        if label == "INSUFFICIENT_DATA" or "no_data" in warnings:
            stale_data.append(sym)

    objectives = [
        "validate fills against paper expectations",
        "monitor for stale-data symbols flagged in plan",
    ]
    if do_not_trade:
        objectives.append(
            f"avoid entries on {len(do_not_trade)} gap-flagged symbols")

    return {
        "expected_regime":              "NEUTRAL",
        "high_risk_symbols":            sorted(set(high_risk)),
        "do_not_trade_list":            sorted(set(do_not_trade)),
        "observe_only_list":            sorted(set(observe_only)),
        "strategy_warnings":            {},
        "confidence_caps_per_strategy": {},
        "confidence_caps_per_symbol":   caps_per_symbol,
        "event_risk_warnings":          event_risk,
        "liquidity_warnings":           liquidity,
        "gap_warnings":                 gap,
        "stale_data_warnings":          sorted(set(stale_data)),
        "daily_experiment_objectives":  objectives,
    }


if __name__ == "__main__":
    sys.exit(main())

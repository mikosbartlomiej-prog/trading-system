"""v3.16.0 (2026-06-04) — Event-driven strategy wrappers for the backtest harness.

Thin façade around `shared.geo_classifier.classify_event_to_signals` that
forces output to a single bucket (defense / energy / gold). Each strategy
function exposes the same callable signature so the harness CLI can swap
strategies via `--strategy <name>`.

CONTRACT
--------
Each wrapper signature mirrors the live classifier so it can be passed
straight to `backtest.event_replay.replay_events`:

    fn(headline, summary, source_type, *, detected_at_iso="", **kw) -> list[GeoSignal]

Wrappers filter to one strategy bucket. Caller still gets the same GeoSignal
dataclass so downstream replay logic doesn't need to know which strategy ran.

LIVE-MONITOR PARITY
-------------------
We intentionally reuse the SAME `classify_event_to_signals` the live monitor
will call after the refactor. The only difference is the strategy filter so
"geo-defense" backtest only counts defense fires, not collateral energy/gold
matches on the same headline.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.abspath(os.path.join(HERE, "..", "shared"))
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from geo_classifier import (
    classify_event_to_signals as _classify,
    STRATEGY_DEFENSE, STRATEGY_ENERGY, STRATEGY_GOLD, STRATEGY_XOM,
)


def _filter_to_strategies(signals, allowed):
    """Keep only signals whose .strategy is in `allowed` set."""
    return [s for s in signals if s.strategy in allowed]


def geo_defense_event_strategy(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result=None,
    priority=None,
    score=None,
):
    """Defense bucket only — RTX, LMT primary."""
    signals = _classify(
        headline=headline, summary=summary, source_type=source_type,
        detected_at_iso=detected_at_iso,
        event_scoring_result=event_scoring_result,
        priority=priority, score=score,
    )
    return _filter_to_strategies(signals, {STRATEGY_DEFENSE})


def geo_energy_event_strategy(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result=None,
    priority=None,
    score=None,
):
    """Energy bucket only — XOM, CVX primary (geo-xom and geo-energy strategies)."""
    signals = _classify(
        headline=headline, summary=summary, source_type=source_type,
        detected_at_iso=detected_at_iso,
        event_scoring_result=event_scoring_result,
        priority=priority, score=score,
    )
    return _filter_to_strategies(signals, {STRATEGY_ENERGY, STRATEGY_XOM})


def geo_gold_event_strategy(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result=None,
    priority=None,
    score=None,
):
    """Gold safe-haven bucket only — GLD primary."""
    signals = _classify(
        headline=headline, summary=summary, source_type=source_type,
        detected_at_iso=detected_at_iso,
        event_scoring_result=event_scoring_result,
        priority=priority, score=score,
    )
    return _filter_to_strategies(signals, {STRATEGY_GOLD})


def geo_all_event_strategy(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result=None,
    priority=None,
    score=None,
):
    """All geo buckets in one pass — match the live monitor's broad fire pattern."""
    return _classify(
        headline=headline, summary=summary, source_type=source_type,
        detected_at_iso=detected_at_iso,
        event_scoring_result=event_scoring_result,
        priority=priority, score=score,
    )


# Convenience map for the CLI.
EVENT_STRATEGIES = {
    "geo-defense": geo_defense_event_strategy,
    "geo-energy":  geo_energy_event_strategy,
    "geo-gold":    geo_gold_event_strategy,
    "geo-all":     geo_all_event_strategy,
}


__all__ = [
    "geo_defense_event_strategy",
    "geo_energy_event_strategy",
    "geo_gold_event_strategy",
    "geo_all_event_strategy",
    "EVENT_STRATEGIES",
]

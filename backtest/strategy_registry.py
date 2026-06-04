"""v3.15.0 (2026-06-04) — StrategyBacktestHarness / StrategyRegistry.

Closes audit-board feedback FB-005 (backtest all strategies).

WHY
---
Trader feedback: every strategy should be backtestable. The system has
`backtest/run.py` with 3 registered strategies (momentum-long, momentum-long-
loose, overbought-short) but the live system has 12+ strategies in
state.json. The non-registered strategies cannot be replayed.

This module formalizes a `StrategyRegistry` that lists EVERY strategy
known to the system and records its backtest readiness:
  - HAS_SIGNAL  — pure signal function exists, can be backtested today
  - INTERFACE   — interface declared, function stub returns None (placeholder)
  - EVENT_DRIVEN — requires event-stream replay (not walk-forward bars)
  - NOT_APPLICABLE — admin / synthetic strategies that don't trade signals

This is an HONEST registry — it documents the gap rather than pretending
all strategies are backtested. The audit-board STRAT-003 explicitly
requires backtest validation before EDGE_GATE_ENABLED=true; this is the
roadmap for closing that.

CONTRACT
--------
Every registered strategy must declare its readiness. A strategy that
"trades" but cannot be backtested CANNOT have EDGE_GATE_ENABLED=true.

NEVER
-----
- Auto-enable strategy without backtest.
- Pretend an event-driven strategy passed a walk-forward test.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, Optional

# ─── Readiness levels ─────────────────────────────────────────────────────────

HAS_SIGNAL        = "HAS_SIGNAL"          # ready for walk-forward backtest
INTERFACE         = "INTERFACE"           # registered but no backtest function
EVENT_DRIVEN      = "EVENT_DRIVEN"        # needs event replay, not bars
MVP_IN_PROGRESS   = "MVP_IN_PROGRESS"     # harness exists, n < 50; advisory only
NOT_APPLICABLE    = "NOT_APPLICABLE"      # admin / no actual trading signal


@dataclass(frozen=True)
class StrategyRegistration:
    name:                  str
    readiness:             str
    signal_fn_name:        str | None
    description:           str
    backtest_data_needed:  str
    notes:                 str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Registry ─────────────────────────────────────────────────────────────────

# Curated list of every strategy known to the system. Update when a new
# strategy ships.
REGISTRY: dict = {
    "momentum-long": StrategyRegistration(
        name="momentum-long",
        readiness=HAS_SIGNAL,
        signal_fn_name="momentum_long_signal_at",
        description="Strict breakout + RSI + volume long entry.",
        backtest_data_needed="daily_bars",
        notes="Live in price-monitor. Backtest verified via momentum-long.",
    ),
    "momentum-long-loose": StrategyRegistration(
        name="momentum-long-loose",
        readiness=HAS_SIGNAL,
        signal_fn_name="momentum_long_loose_signal_at",
        description="Loose variant: wider RSI / vol.",
        backtest_data_needed="daily_bars",
        notes="Research/backtest only — NOT live.",
    ),
    "overbought-short": StrategyRegistration(
        name="overbought-short",
        readiness=HAS_SIGNAL,
        signal_fn_name="overbought_short_signal_at",
        description="RSI > 72 + weakening signals → short.",
        backtest_data_needed="daily_bars",
        notes="Disabled live (2026-05-08 backtest showed -$2,065 11% WR).",
    ),

    # ── Event-driven (Phase 1 MVP harness landed v3.16.0; n < 50 threshold)
    "geo-defense": StrategyRegistration(
        name="geo-defense",
        readiness=MVP_IN_PROGRESS,
        signal_fn_name="geo_defense_event_strategy",
        description="Geopolitical defense escalation → BUY ITA/LMT/RTX.",
        backtest_data_needed="historical_news_events_with_tickers",
        notes=("v3.16.0 (2026-06-04): event-driven backtest harness shipped "
                "via backtest.event_data (GDELT 2.0) + backtest.event_replay. "
                "Results ADVISORY ONLY until n>=50 trades accumulated. "
                "Live wired in geo-monitor."),
    ),
    "geo-energy": StrategyRegistration(
        name="geo-energy",
        readiness=MVP_IN_PROGRESS,
        signal_fn_name="geo_energy_event_strategy",
        description="Energy supply shock → BUY XLE/XOM/CVX.",
        backtest_data_needed="historical_energy_news",
        notes=("v3.16.0 (2026-06-04): event-driven harness shipped, advisory "
                "only until n>=50."),
    ),
    "geo-gold": StrategyRegistration(
        name="geo-gold",
        readiness=MVP_IN_PROGRESS,
        signal_fn_name="geo_gold_event_strategy",
        description="Geopolitical risk → BUY GLD.",
        backtest_data_needed="historical_news_risk_index",
        notes=("v3.16.0 (2026-06-04): event-driven harness shipped, advisory "
                "only until n>=50."),
    ),
    "geo-xom": StrategyRegistration(
        name="geo-xom",
        readiness=EVENT_DRIVEN,
        signal_fn_name=None,
        description="Defunct (deprecated routine path) — disabled in state.json.",
        backtest_data_needed="n/a",
        notes="Backlog: refactor to direct execution. Shares classifier with geo-energy.",
    ),

    # ── Crypto (v3.16 — hourly bar harness landed) ─────────────────────────
    "crypto-momentum": StrategyRegistration(
        name="crypto-momentum",
        readiness=HAS_SIGNAL,
        signal_fn_name="crypto_momentum_signal_at",
        description="11-coin predator: breakout + RSI band + volume + 24h move bracket.",
        backtest_data_needed="hourly_crypto_bars",
        notes=("Live in crypto-monitor. v3.16 (2026-06-04): pure signal "
                "fn + hourly Alpaca v1beta3 fetcher shipped; backtest-ready. "
                "Use: python -m backtest.run --strategy crypto-momentum "
                "--tickers BTC/USD ETH/USD --hours 4320 --mode both."),
    ),
    "crypto-oversold-bounce": StrategyRegistration(
        name="crypto-oversold-bounce",
        readiness=HAS_SIGNAL,
        signal_fn_name="crypto_oversold_bounce_signal_at",
        description="Deep oversold mean-reversion (RSI ≤30 + 3-bar stabilization).",
        backtest_data_needed="hourly_crypto_bars",
        notes=("Live in crypto-monitor. v3.16 (2026-06-04): pure signal "
                "fn + hourly Alpaca v1beta3 fetcher shipped; backtest-ready. "
                "Closes STRAT-002 observation question 2026-06-16. Use: "
                "python -m backtest.run --strategy crypto-oversold-bounce "
                "--tickers BTC/USD ETH/USD --hours 4320 --mode both "
                "--explain-zero-fires."),
    ),
    "crypto-breakdown": StrategyRegistration(
        name="crypto-breakdown",
        readiness=NOT_APPLICABLE,
        signal_fn_name=None,
        description="Short-only crypto breakdown.",
        backtest_data_needed="n/a",
        notes="Structurally disabled (Alpaca paper crypto LONG-only).",
    ),

    # ── Options ────────────────────────────────────────────────────────────
    "options-momentum": StrategyRegistration(
        name="options-momentum",
        readiness=INTERFACE,
        signal_fn_name=None,
        description="Options momentum (CALL on RSI 45-65, PUT on RSI > 72).",
        backtest_data_needed="historical_option_chain",
        notes=("Options backtest requires historical chain (paid). Live wired "
                "in options-monitor with confidence gate (v3.14.0). Backtest "
                "not feasible without paid data — operator decision required."),
    ),

    # ── Allocator level (not bar-driven) ───────────────────────────────────
    "allocator-rebalance": StrategyRegistration(
        name="allocator-rebalance",
        readiness=NOT_APPLICABLE,
        signal_fn_name=None,
        description="Daily portfolio rebalance via composite scoring.",
        backtest_data_needed="multi_asset_daily_bars_with_regime",
        notes="Score-based rebalance. Backtest = portfolio simulation, not signal replay.",
    ),
    "alloc-exit": StrategyRegistration(
        name="alloc-exit",
        readiness=NOT_APPLICABLE,
        signal_fn_name=None,
        description="Allocator-emitted exit (admin tag, not a signal strategy).",
        backtest_data_needed="n/a",
        notes="Administrative.",
    ),
    "alloc-reduce": StrategyRegistration(
        name="alloc-reduce",
        readiness=NOT_APPLICABLE,
        signal_fn_name=None,
        description="Allocator-emitted reduction (admin tag).",
        backtest_data_needed="n/a",
        notes="Administrative.",
    ),
}


# ─── Public API ───────────────────────────────────────────────────────────────

def get(name: str) -> StrategyRegistration | None:
    return REGISTRY.get(name)


def list_all() -> list[StrategyRegistration]:
    return list(REGISTRY.values())


def list_by_readiness(readiness: str) -> list[StrategyRegistration]:
    return [r for r in REGISTRY.values() if r.readiness == readiness]


def is_backtest_ready(name: str) -> bool:
    """True only when a strategy meets the statistical-power threshold for
    EDGE_GATE flip.

    MVP_IN_PROGRESS deliberately returns False — the harness exists but n<50
    so results are advisory only. Caller must wait until n>=50 (backtest)
    AND n>=20 (live) per audit-board STRAT-003.
    """
    r = REGISTRY.get(name)
    return bool(r and r.readiness == HAS_SIGNAL)


def is_known(name: str) -> bool:
    return name in REGISTRY


def coverage_report() -> dict:
    """Honest snapshot of backtest coverage."""
    counts = {HAS_SIGNAL: 0, INTERFACE: 0, EVENT_DRIVEN: 0,
              MVP_IN_PROGRESS: 0, NOT_APPLICABLE: 0}
    for r in REGISTRY.values():
        counts[r.readiness] = counts.get(r.readiness, 0) + 1
    total_tradeable = (counts[HAS_SIGNAL] + counts[INTERFACE]
                       + counts[EVENT_DRIVEN] + counts[MVP_IN_PROGRESS])
    backtest_ready = counts[HAS_SIGNAL]
    return {
        "total_registered":   len(REGISTRY),
        "by_readiness":       counts,
        "backtest_ready_pct": (backtest_ready / total_tradeable * 100.0)
                               if total_tradeable else 0.0,
        "tradeable_uncovered": [r.name for r in REGISTRY.values()
                                  if r.readiness in (INTERFACE, EVENT_DRIVEN,
                                                      MVP_IN_PROGRESS)],
    }


__all__ = [
    "HAS_SIGNAL", "INTERFACE", "EVENT_DRIVEN", "MVP_IN_PROGRESS",
    "NOT_APPLICABLE",
    "StrategyRegistration", "REGISTRY",
    "get", "list_all", "list_by_readiness",
    "is_backtest_ready", "is_known", "coverage_report",
]

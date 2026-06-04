"""v3.15.0 (2026-06-04) — MarketUniverseConfig / UniverseSelector (FB-010).

WHY
---
Trader feedback: US markets are saturated with algos; microcaps or exotic
markets (e.g. Polish GPW) might offer edge. The system currently has only
a US universe (`config/watchlists.json`). This module adds a formal
universe abstraction so the question "which universe are we trading?" has
an explicit answer.

CONTRACT
--------
Configuration-driven. Universes are listed in `config/market_universes.json`
(created alongside this module). Each universe carries:
  - data availability assumption
  - liquidity constraints
  - cost/spread/slippage assumptions
  - risk limits override

The selector reads the operator-configured active universe from
`runtime_config.py::active_universe()`. Default is `US_LARGE` matching the
existing setup.

WHY NOT JUST FLIP TO PL/microcap?
----------------------------------
- Alpaca paper account is US-only; PL requires a PL broker (none free).
- Microcaps have illiquidity + manipulation risk that current system
  has no defense for (would need wider spread tolerance + smaller size).
- Polish broker integration is out-of-scope for paper-only experiment.

So we ship the abstraction + config + selector + tests. The operator can
DEFINE a universe but cannot just switch and expect it to work — switching
universes intentionally fails LOUDLY in the selector if required data/broker
is not available.

NEVER
-----
- Auto-migrate to a different universe.
- Assume strategies transfer across universes.
- Suggest microcaps are "safer".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any

# ─── Universe identifiers ─────────────────────────────────────────────────────

UNIV_US_LARGE       = "US_LARGE"
UNIV_US_MICROCAP    = "US_MICROCAP"
UNIV_PL_GPW         = "PL_GPW"
UNIV_CRYPTO         = "CRYPTO"
UNIV_CUSTOM         = "CUSTOM"

VALID_UNIVERSES = (UNIV_US_LARGE, UNIV_US_MICROCAP, UNIV_PL_GPW,
                    UNIV_CRYPTO, UNIV_CUSTOM)


# Default config path (relative to repo)
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "market_universes.json",
)


@dataclass(frozen=True)
class UniverseSpec:
    """Frozen spec for a market universe. Read from config JSON."""
    id:                       str
    description:              str
    enabled:                  bool
    data_source:              str    # which data source is required
    free_data_available:      bool   # paper-only constraint
    broker_supported:         bool   # paper-only constraint
    typical_spread_bps:       float
    typical_slippage_bps:     float
    min_liquidity_usd_daily:  float
    risk_limit_multipliers:   dict   # override factors (size, sl, tp)
    notes:                    str

    def to_dict(self) -> dict:
        return asdict(self)

    def is_paper_ready(self) -> bool:
        """Paper trading prerequisites: free data + supported broker."""
        return self.enabled and self.free_data_available and self.broker_supported


# ─── Default universes (shipped as fallback when config missing) ──────────────

DEFAULT_UNIVERSES: dict = {
    UNIV_US_LARGE: UniverseSpec(
        id=UNIV_US_LARGE,
        description="US large-cap equities + popular ETFs",
        enabled=True,
        data_source="alpaca_iex_free",
        free_data_available=True,
        broker_supported=True,
        typical_spread_bps=2.0,
        typical_slippage_bps=5.0,
        min_liquidity_usd_daily=10_000_000,
        risk_limit_multipliers={"size": 1.0, "sl": 1.0, "tp": 1.0},
        notes="Default. Matches `config/watchlists.json` buckets.",
    ),
    UNIV_US_MICROCAP: UniverseSpec(
        id=UNIV_US_MICROCAP,
        description="US microcap equities (< $300M)",
        enabled=False,
        data_source="alpaca_iex_free",
        free_data_available=True,
        broker_supported=True,
        typical_spread_bps=50.0,
        typical_slippage_bps=80.0,
        min_liquidity_usd_daily=100_000,
        risk_limit_multipliers={"size": 0.25, "sl": 1.5, "tp": 1.5},
        notes=(
            "DISABLED by default. Illiquidity + manipulation risk. Requires "
            "explicit operator opt-in + LiquiditySweepGuard active + "
            "smaller per-position size."
        ),
    ),
    UNIV_PL_GPW: UniverseSpec(
        id=UNIV_PL_GPW,
        description="Polish GPW (Warsaw Stock Exchange)",
        enabled=False,
        data_source="gpw_open_data_free",
        free_data_available=True,         # GPW publishes daily snapshot
        broker_supported=False,           # No free Polish paper broker
        typical_spread_bps=20.0,
        typical_slippage_bps=30.0,
        min_liquidity_usd_daily=500_000,
        risk_limit_multipliers={"size": 0.5, "sl": 1.2, "tp": 1.2},
        notes=(
            "DISABLED — no free Polish paper-trading broker integrated. "
            "Operator would need to wire a PL broker SDK (not free) "
            "before this can run paper."
        ),
    ),
    UNIV_CRYPTO: UniverseSpec(
        id=UNIV_CRYPTO,
        description="24/7 crypto via Alpaca",
        enabled=True,
        data_source="alpaca_crypto_free",
        free_data_available=True,
        broker_supported=True,
        typical_spread_bps=10.0,
        typical_slippage_bps=15.0,
        min_liquidity_usd_daily=50_000_000,
        risk_limit_multipliers={"size": 0.5, "sl": 1.0, "tp": 1.0},
        notes="Long-only on Alpaca paper. See `crypto-monitor`.",
    ),
    UNIV_CUSTOM: UniverseSpec(
        id=UNIV_CUSTOM,
        description="Operator-defined custom universe",
        enabled=False,
        data_source="custom",
        free_data_available=False,
        broker_supported=False,
        typical_spread_bps=0.0,
        typical_slippage_bps=0.0,
        min_liquidity_usd_daily=0.0,
        risk_limit_multipliers={},
        notes="Placeholder.",
    ),
}


# ─── Public API ───────────────────────────────────────────────────────────────

def _load_config(path: str | None = None) -> dict:
    """Load market_universes.json or return DEFAULT_UNIVERSES."""
    p = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(p):
        return {k: v.to_dict() for k, v in DEFAULT_UNIVERSES.items()}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # Merge with defaults so missing fields fall back
        merged = {k: v.to_dict() for k, v in DEFAULT_UNIVERSES.items()}
        for k, v in data.items():
            if isinstance(v, dict):
                merged.setdefault(k, {}).update(v)
        return merged
    except Exception:
        return {k: v.to_dict() for k, v in DEFAULT_UNIVERSES.items()}


def get_universe(universe_id: str, *,
                   config_path: str | None = None) -> UniverseSpec | None:
    """Return UniverseSpec for the given id, or None if unknown."""
    if universe_id not in VALID_UNIVERSES:
        return None
    cfg = _load_config(config_path).get(universe_id)
    if not cfg:
        return DEFAULT_UNIVERSES.get(universe_id)
    return UniverseSpec(
        id=cfg.get("id", universe_id),
        description=cfg.get("description", ""),
        enabled=bool(cfg.get("enabled", False)),
        data_source=cfg.get("data_source", ""),
        free_data_available=bool(cfg.get("free_data_available", False)),
        broker_supported=bool(cfg.get("broker_supported", False)),
        typical_spread_bps=float(cfg.get("typical_spread_bps", 0.0)),
        typical_slippage_bps=float(cfg.get("typical_slippage_bps", 0.0)),
        min_liquidity_usd_daily=float(cfg.get("min_liquidity_usd_daily", 0.0)),
        risk_limit_multipliers=cfg.get("risk_limit_multipliers", {}) or {},
        notes=cfg.get("notes", ""),
    )


def list_enabled(config_path: str | None = None) -> list[UniverseSpec]:
    cfg = _load_config(config_path)
    out = []
    for u_id in VALID_UNIVERSES:
        spec = get_universe(u_id, config_path=config_path)
        if spec and spec.enabled:
            out.append(spec)
    return out


def is_paper_ready(universe_id: str,
                    config_path: str | None = None) -> tuple[bool, str]:
    """(ready, reason)."""
    spec = get_universe(universe_id, config_path=config_path)
    if spec is None:
        return False, f"unknown_universe:{universe_id}"
    if not spec.enabled:
        return False, "universe_disabled_in_config"
    if not spec.free_data_available:
        return False, "no_free_data_source_available"
    if not spec.broker_supported:
        return False, "no_supported_paper_broker"
    return True, "paper_ready"


def can_switch(from_universe: str, to_universe: str,
                config_path: str | None = None) -> tuple[bool, str]:
    """Conservative switch policy. Cross-universe migration is DANGEROUS.

    System never auto-switches. Operator can explicitly switch IF
    `to_universe.is_paper_ready()` AND a DIFFERENT strategy set is
    available for that universe.
    """
    if from_universe == to_universe:
        return True, "no_op"
    ok, reason = is_paper_ready(to_universe, config_path=config_path)
    if not ok:
        return False, f"target_not_ready: {reason}"
    return True, "operator_decision_required"


__all__ = [
    "UNIV_US_LARGE", "UNIV_US_MICROCAP", "UNIV_PL_GPW",
    "UNIV_CRYPTO", "UNIV_CUSTOM",
    "VALID_UNIVERSES",
    "DEFAULT_UNIVERSES", "DEFAULT_CONFIG_PATH",
    "UniverseSpec",
    "get_universe", "list_enabled", "is_paper_ready", "can_switch",
]

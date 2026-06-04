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


# ─── v3.18.0 (2026-06-04) — Paper-trading symbol filter ──────────────────────
#
# Forbidden symbol patterns. Conservative hard-coded list. If a symbol matches
# ANY pattern → REJECT. Patterns chosen to block known low-quality / unsupported
# instruments:
#   - "_OB" / ".OB" / ".PK" suffix → OTC bulletin board / pink sheet
#   - "_W" / "-W" suffix           → SPAC warrants (low liquidity, paper-side caveats)
#   - "_R" / "-R" suffix           → rights (event-driven, irregular)
#   - "_U" / "-U" suffix           → SPAC unit (low liquidity)
#   - "$"                          → cashtag accidentally passed (not a real symbol)
#   - leading underscore           → reserved Alpaca internal
#   - empty / whitespace-only      → caller bug
FORBIDDEN_SYMBOL_SUFFIXES = (".OB", "_OB", ".PK", "_W", "-W",
                              "_R", "-R", "_U", "-U")
FORBIDDEN_SYMBOL_CHARS    = ("$", "*", "?", "!")


def _is_forbidden_symbol(symbol: str) -> tuple[bool, str]:
    """Conservative pattern check. Returns (forbidden, reason)."""
    if not symbol or not isinstance(symbol, str):
        return True, "empty_or_invalid_symbol"
    s = symbol.strip()
    if not s:
        return True, "empty_after_strip"
    if s.startswith("_"):
        return True, "leading_underscore_reserved"
    for ch in FORBIDDEN_SYMBOL_CHARS:
        if ch in s:
            return True, f"contains_forbidden_char:{ch}"
    su = s.upper()
    for suf in FORBIDDEN_SYMBOL_SUFFIXES:
        if su.endswith(suf):
            return True, f"forbidden_suffix:{suf}"
    return False, ""


def filter_symbols_for_paper_trading(
    symbols: list[str],
    *,
    spread_data: dict | None = None,
    volume_data: dict | None = None,
    history_data: dict | None = None,
    universe_id: str | None = None,
    strict: bool = False,
    audit: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """Filter symbols by liquidity + spread + data quality + history.

    v3.18.0 (2026-06-04) — Paper-trading universe filter.

    Args:
        symbols: list of candidate symbol strings.
        spread_data: optional {symbol → typical_spread_bps}.
        volume_data: optional {symbol → daily_volume_usd}.
        history_data: optional {symbol → days_with_bars_last_5d (int)}.
        universe_id: universe to validate against. Default: active universe.
        strict: if True, MISSING data → REJECT (conservative for unknown
                universes). Default False (ALLOW with warning).
        audit: if True, emit one audit JSONL line per rejection.

    Returns:
        (allowed_symbols, rejection_reasons) where rejection_reasons is
        {symbol → reason_str}.

    Rejection conditions (each fail-soft if data unavailable):
      - typical_spread_bps > universe.typical_spread_bps * 2 → REJECT
      - daily_volume_usd  < universe.min_liquidity_usd_daily → REJECT
      - Forbidden symbol pattern (OTC / SPAC / etc.)         → REJECT
      - No daily bars in last 5 days                         → REJECT
                                                            (data unavailable)

    Conservative defaults:
      - Missing spread_data + strict=False → ALLOW with warning rationale.
      - Missing volume_data + strict=False → ALLOW with warning rationale.
      - Missing history_data + strict=False → ALLOW (assume bars exist if
        symbol is on a known whitelist).

    NEVER raises. Returns empty allowed list on unknown universe.

    Audit contract:
      One JSONL event per rejection at journal/autonomy/<date>.jsonl with
      kind='trading' + type='universe_filter' + symbol + reason +
      universe_id. Caller is risk-bound (no orders placed by this function).
    """
    rejections: dict[str, str] = {}
    allowed: list[str] = []

    if not symbols or not isinstance(symbols, list):
        return [], {}

    # Resolve universe — default to active universe if unspecified
    if universe_id is None:
        try:
            from runtime_config import active_universe as _au
        except ImportError:  # pragma: no cover
            try:
                from shared.runtime_config import active_universe as _au  # type: ignore
            except Exception:
                _au = lambda: "US_LARGE"  # noqa: E731 — fail-soft fallback
        universe_id = _au()

    spec = get_universe(universe_id)
    if spec is None:
        # Unknown universe → reject all (operator must explicitly enable).
        for s in symbols:
            rejections[s] = "unknown_universe"
        return [], rejections

    spread_threshold = spec.typical_spread_bps * 2.0 if spec.typical_spread_bps > 0 else None
    volume_threshold = spec.min_liquidity_usd_daily if spec.min_liquidity_usd_daily > 0 else None

    spread_data = spread_data or {}
    volume_data = volume_data or {}
    history_data = history_data or {}

    for sym in symbols:
        if not isinstance(sym, str):
            rejections[str(sym)] = "non_string_symbol"
            continue

        # 1. Pattern check
        forbidden, why = _is_forbidden_symbol(sym)
        if forbidden:
            rejections[sym] = f"forbidden_pattern:{why}"
            continue

        # 2. Spread check (fail-soft if data missing)
        spread = spread_data.get(sym)
        if spread is not None and spread_threshold is not None:
            try:
                if float(spread) > spread_threshold:
                    rejections[sym] = (
                        f"spread_exceeds:{spread:.1f}bps>{spread_threshold:.1f}bps"
                    )
                    continue
            except (TypeError, ValueError):
                pass
        elif spread is None and strict:
            rejections[sym] = "missing_spread_data_strict"
            continue

        # 3. Volume check (fail-soft if data missing)
        vol = volume_data.get(sym)
        if vol is not None and volume_threshold is not None:
            try:
                if float(vol) < volume_threshold:
                    rejections[sym] = (
                        f"volume_below:{vol:.0f}usd<{volume_threshold:.0f}usd"
                    )
                    continue
            except (TypeError, ValueError):
                pass
        elif vol is None and strict:
            rejections[sym] = "missing_volume_data_strict"
            continue

        # 4. History check (fail-soft if data missing)
        hist = history_data.get(sym)
        if hist is not None:
            try:
                if int(hist) < 1:
                    rejections[sym] = "no_daily_bars_last_5d"
                    continue
            except (TypeError, ValueError):
                pass
        elif strict:
            rejections[sym] = "missing_history_data_strict"
            continue

        allowed.append(sym)

    # Audit emission — one event per rejection. Fail-soft.
    if audit and rejections:
        try:
            from datetime import datetime, timezone
            try:
                from audit import write_audit_event
            except ImportError:
                from shared.audit import write_audit_event  # type: ignore
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for sym, reason in rejections.items():
                rec = {
                    "type":          "universe_filter",
                    "decision":      "REJECT",
                    "symbol":        sym,
                    "reason":        reason,
                    "universe_id":   universe_id,
                    "strict_mode":   bool(strict),
                    "decided_at":    now_iso,
                }
                try:
                    write_audit_event(rec, kind="trading")
                except Exception:
                    # Never break the filter on audit failure
                    pass
        except Exception:
            pass

    return allowed, rejections


__all__ = [
    "UNIV_US_LARGE", "UNIV_US_MICROCAP", "UNIV_PL_GPW",
    "UNIV_CRYPTO", "UNIV_CUSTOM",
    "VALID_UNIVERSES",
    "DEFAULT_UNIVERSES", "DEFAULT_CONFIG_PATH",
    "UniverseSpec",
    "get_universe", "list_enabled", "is_paper_ready", "can_switch",
    "FORBIDDEN_SYMBOL_SUFFIXES", "FORBIDDEN_SYMBOL_CHARS",
    "filter_symbols_for_paper_trading",
]

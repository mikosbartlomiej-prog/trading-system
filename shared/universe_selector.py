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


# ─── v3.19.0 (2026-06-04) — Universe Selector v2 (Ranking) ───────────────────
#
# WHY
# ---
# Filter (v3.18.0) tells us which symbols PASS minimum spread/liquidity gates.
# Ranking (v3.19.0) tells us which symbols deserve attention FIRST.
#
# CONTRACT
# --------
# rank_symbols(...) is a PURE function:
#   - reads only the dicts passed as kwargs (no network, no broker calls).
#   - returns a deterministic list sorted by score (descending).
#   - NEVER auto-trades. NEVER changes runtime risk limits.
#   - Emits one audit JSONL line per ranking decision (kind='trading',
#     type='universe_ranking', source='evidence_analysis').
#
# STATUS ENUM
# -----------
#   TRADE_ELIGIBLE — passes all gates AND has positive paper-trade history
#                    (n_closed >= 5).
#   OBSERVE_ONLY   — passes all data gates but no/insufficient evidence.
#   REJECTED       — fails forbidden-pattern or spread/liquidity hard gate.
#   NEEDS_DATA     — missing volume_data AND history_data.
#
# SCORE COMPONENTS (each clamped to [0.0, 1.0])
# ----------------------------------------------
#   liquidity_score          — log-scaled vs universe baseline.
#   spread_score             — inverted (lower spread = higher score).
#   volatility_score         — moderate volatility (1-3% daily) scored best.
#   data_quality_score       — bar-freshness proxy from history_data.
#   paper_performance_score  — sample-size weighted PF; missing → 0.5 (neutral).
#   strategy_compat_score    — number of strategies that can use this symbol.
#   calibration_score        — confidence calibration quality for symbol.
#   regime_fit_score         — symbol's bucket fit with current regime.
#   drawdown_history_score   — lower historical max_dd = higher score.
#   recent_anomalies_score   — fewer flagged anomalies = higher score.
#
# Component weights (must sum to 1.0):
_RANKING_WEIGHTS = {
    "liquidity_score":         0.16,
    "spread_score":            0.12,
    "volatility_score":        0.10,
    "data_quality_score":      0.10,
    "paper_performance_score": 0.14,
    "strategy_compat_score":   0.08,
    "calibration_score":       0.08,
    "regime_fit_score":        0.10,
    "drawdown_history_score":  0.08,
    "recent_anomalies_score":  0.04,
}


def _clamp01(x: object) -> float:
    """Clamp arbitrary input to [0.0, 1.0] interval. Fail-soft → 0.5."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    if v != v:  # NaN
        return 0.5
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _score_liquidity(vol: float | None, baseline: float) -> float:
    """Log-scaled liquidity vs universe baseline. Missing → 0.5."""
    if vol is None or baseline <= 0:
        return 0.5
    try:
        v = float(vol)
        if v <= 0:
            return 0.0
        ratio = v / baseline
        # log-scale: 1× → 0.5, 10× → ~0.83, 100× → ~1.0, 0.1× → ~0.17
        import math
        score = 0.5 + 0.25 * math.log10(max(ratio, 1e-6))
        return _clamp01(score)
    except Exception:
        return 0.5


def _score_spread(spread_bps: float | None, baseline_bps: float) -> float:
    """Inverted spread vs baseline. Missing → 0.5. Lower spread = higher score."""
    if spread_bps is None or baseline_bps <= 0:
        return 0.5
    try:
        s = float(spread_bps)
        if s <= 0:
            return 1.0
        ratio = s / baseline_bps
        # Better than baseline → >0.5, worse → <0.5.
        # Hard floor: 4× baseline = 0.0
        if ratio >= 4.0:
            return 0.0
        return _clamp01(1.0 - (ratio / 4.0))
    except Exception:
        return 0.5


def _score_volatility(daily_vol_pct: float | None) -> float:
    """Volatility sweet spot: 1.0%-3.0% daily. Outside that → penalised."""
    if daily_vol_pct is None:
        return 0.5
    try:
        v = float(daily_vol_pct)
        if v < 0.5 or v > 8.0:
            return 0.2
        if 1.0 <= v <= 3.0:
            return 1.0
        if v < 1.0:
            return 0.5 + (v - 0.5) * 1.0  # 0.5..1.0 in [0.5, 1.0]
        # 3.0 < v < 8.0 → linear decay 1.0 → 0.2
        return _clamp01(1.0 - (v - 3.0) / 5.0 * 0.8)
    except Exception:
        return 0.5


def _score_data_quality(days_with_bars: int | None) -> float:
    """Bar freshness: 5/5 last week → 1.0, fewer → linear."""
    if days_with_bars is None:
        return 0.5
    try:
        d = int(days_with_bars)
        if d <= 0:
            return 0.0
        return _clamp01(d / 5.0)
    except Exception:
        return 0.5


def _score_paper_performance(perf: dict | None) -> tuple[float, dict]:
    """Sample-size-weighted profit factor mapped to [0, 1].

    Missing or n_closed < 5 → neutral 0.5 with low_evidence flag.
    """
    info: dict = {"n_closed": 0, "pf": None}
    if not isinstance(perf, dict):
        return 0.5, info
    n = perf.get("n_closed") or 0
    try:
        n_closed = int(n)
    except (TypeError, ValueError):
        n_closed = 0
    info["n_closed"] = n_closed
    if n_closed < 5:
        info["low_evidence"] = True
        return 0.5, info
    pf = perf.get("profit_factor")
    try:
        pf_f = float(pf) if pf is not None else None
    except (TypeError, ValueError):
        pf_f = None
    info["pf"] = pf_f
    if pf_f is None:
        return 0.5, info
    if pf_f <= 0.5:
        score = 0.0
    elif pf_f >= 2.0:
        score = 1.0
    else:
        # Linear 0.5..2.0 → 0..1
        score = _clamp01((pf_f - 0.5) / 1.5)
    # Sample-size confidence: n >= 30 → full credit, less → blend toward neutral
    if n_closed < 30:
        weight = n_closed / 30.0
        score = 0.5 + (score - 0.5) * weight
    return _clamp01(score), info


def _score_strategy_compat(n_strategies: int | None) -> float:
    """Number of strategies that can use this symbol."""
    if n_strategies is None:
        return 0.5
    try:
        n = int(n_strategies)
    except (TypeError, ValueError):
        return 0.5
    if n <= 0:
        return 0.0
    # 1 strategy → 0.5, 3 → 0.85, 5+ → 1.0
    return _clamp01(0.5 + 0.15 * n)


def _score_calibration(cal: dict | None) -> float:
    """Calibration quality. Missing → 0.5."""
    if not isinstance(cal, dict):
        return 0.5
    err = cal.get("calibration_error")
    try:
        e = float(err) if err is not None else None
    except (TypeError, ValueError):
        e = None
    if e is None:
        return 0.5
    # error in [0, 1]; lower = better
    return _clamp01(1.0 - e)


def _score_regime_fit(fit: dict | None) -> float:
    """Regime fit. Missing → 0.5."""
    if not isinstance(fit, dict):
        return 0.5
    v = fit.get("fit_score")
    return _clamp01(v if v is not None else 0.5)


def _score_drawdown_history(dd: float | None) -> float:
    """Lower historical max_dd = higher score. dd in [0, 1]."""
    if dd is None:
        return 0.5
    try:
        d = float(dd)
    except (TypeError, ValueError):
        return 0.5
    if d <= 0.0:
        return 1.0
    if d >= 0.5:
        return 0.0
    return _clamp01(1.0 - d * 2.0)


def _score_recent_anomalies(n_anomalies: int | None) -> float:
    """Fewer anomalies (flagged by incident detector) = higher score."""
    if n_anomalies is None:
        return 0.5
    try:
        n = int(n_anomalies)
    except (TypeError, ValueError):
        return 0.5
    if n <= 0:
        return 1.0
    if n >= 5:
        return 0.0
    return _clamp01(1.0 - n / 5.0)


def _composite_score(components: dict) -> float:
    """Weighted sum of components. Weights from _RANKING_WEIGHTS."""
    total = 0.0
    weight_sum = 0.0
    for k, w in _RANKING_WEIGHTS.items():
        v = components.get(k)
        if v is None:
            continue
        total += float(v) * w
        weight_sum += w
    if weight_sum <= 0:
        return 0.0
    # Normalize in case some components are missing.
    return _clamp01(total / weight_sum)


def _emit_ranking_audit(records: list[dict], universe_id: str | None) -> None:
    """One audit event summarising the ranking decision. Fail-soft."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        now_iso = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec = {
            "type":        "universe_ranking",
            "source":      "evidence_analysis",
            "decision":    "ANALYSED",
            "universe_id": universe_id or "",
            "n_ranked":    len(records),
            "n_eligible":  sum(1 for r in records if r.get("status") == "TRADE_ELIGIBLE"),
            "n_observe":   sum(1 for r in records if r.get("status") == "OBSERVE_ONLY"),
            "n_rejected":  sum(1 for r in records if r.get("status") == "REJECTED"),
            "n_needs_data": sum(1 for r in records if r.get("status") == "NEEDS_DATA"),
            "decided_at":  now_iso,
            "top_5":       [
                {"symbol": r.get("symbol"), "score": r.get("score"),
                 "status": r.get("status")}
                for r in records[:5]
            ],
        }
        try:
            write_audit_event(rec, kind="trading")
        except Exception:
            pass
    except Exception:
        pass


def rank_symbols(
    symbols: list[str],
    *,
    spread_data: dict | None = None,
    volume_data: dict | None = None,
    paper_performance: dict | None = None,
    strategy_compat: dict | None = None,
    confidence_calibration: dict | None = None,
    regime_fit: dict | None = None,
    drawdown_history: dict | None = None,
    recent_anomalies: dict | None = None,
    universe_id: str | None = None,
    audit: bool = True,
) -> list[dict]:
    """Rank symbols by quality score for paper trading attention.

    v3.19.0 (2026-06-04) — Universe Selector v2 ranking layer.

    Args:
        symbols:                list of candidate symbols.
        spread_data:            {symbol → typical_spread_bps}.
        volume_data:            {symbol → daily_volume_usd}.
        paper_performance:      {symbol → {n_closed, profit_factor, ...}}.
        strategy_compat:        {symbol → n_strategies_compatible}.
        confidence_calibration: {symbol → {calibration_error, ...}}.
        regime_fit:             {symbol → {fit_score: float}}.
        drawdown_history:       {symbol → max_drawdown_pct in [0, 1]}.
        recent_anomalies:       {symbol → n_anomalies_last_30d}.
        universe_id:            universe to validate against. Default: active.
        audit:                  emit one audit summary JSONL line.

    Returns:
        list of dicts sorted by score (desc), shape:
            {
              "rank":       int,
              "symbol":     str,
              "score":      float in [0,1],
              "status":     "TRADE_ELIGIBLE" | "OBSERVE_ONLY" | "REJECTED" | "NEEDS_DATA",
              "reason":     str | None,  # filled when REJECTED / NEEDS_DATA
              "components": dict,        # per-component scores
            }

    NEVER auto-trades. NEVER raises real money. PURE function: same inputs →
    same outputs.

    Conservative defaults:
      - Missing data → component score 0.5 (neutral), never blocks ranking.
      - Empty input → empty list.
      - Unknown universe → all symbols rejected.
    """
    out: list[dict] = []
    if not isinstance(symbols, list) or not symbols:
        return out

    # Resolve universe (fail-soft)
    if universe_id is None:
        try:
            from runtime_config import active_universe as _au
        except ImportError:  # pragma: no cover
            try:
                from shared.runtime_config import active_universe as _au  # type: ignore
            except Exception:
                _au = lambda: "US_LARGE"  # noqa: E731
        universe_id = _au()
    spec = get_universe(universe_id)
    if spec is None:
        # Unknown universe → all rejected.
        for s in symbols:
            out.append({
                "rank":       0,
                "symbol":     s if isinstance(s, str) else str(s),
                "score":      0.0,
                "status":     "REJECTED",
                "reason":     "unknown_universe",
                "components": {},
            })
        if audit:
            _emit_ranking_audit(out, universe_id)
        return out

    spread_baseline_bps = spec.typical_spread_bps if spec.typical_spread_bps > 0 else 10.0
    volume_baseline = spec.min_liquidity_usd_daily if spec.min_liquidity_usd_daily > 0 else 1_000_000.0

    spread_data = spread_data or {}
    volume_data = volume_data or {}
    paper_performance = paper_performance or {}
    strategy_compat = strategy_compat or {}
    confidence_calibration = confidence_calibration or {}
    regime_fit = regime_fit or {}
    drawdown_history = drawdown_history or {}
    recent_anomalies = recent_anomalies or {}

    # Step 1: pre-filter via forbidden-pattern + hard spread/liquidity gates.
    # We reuse filter_symbols_for_paper_trading semantics (but here we only
    # gather the rejections, since ranking includes all symbols by design).
    rejected_reasons: dict[str, str] = {}
    candidates: list[str] = []
    for sym in symbols:
        if not isinstance(sym, str):
            rejected_reasons[str(sym)] = "non_string_symbol"
            continue
        forbidden, why = _is_forbidden_symbol(sym)
        if forbidden:
            rejected_reasons[sym] = f"forbidden_pattern:{why}"
            continue
        # Hard spread fail
        s = spread_data.get(sym)
        if s is not None and spec.typical_spread_bps > 0:
            try:
                if float(s) > spec.typical_spread_bps * 2.0:
                    rejected_reasons[sym] = (
                        f"spread_exceeds:{float(s):.1f}bps>"
                        f"{spec.typical_spread_bps*2.0:.1f}bps"
                    )
                    continue
            except (TypeError, ValueError):
                pass
        # Hard liquidity fail
        v = volume_data.get(sym)
        if v is not None and spec.min_liquidity_usd_daily > 0:
            try:
                if float(v) < spec.min_liquidity_usd_daily:
                    rejected_reasons[sym] = (
                        f"volume_below:{float(v):.0f}usd<"
                        f"{spec.min_liquidity_usd_daily:.0f}usd"
                    )
                    continue
            except (TypeError, ValueError):
                pass
        candidates.append(sym)

    # Step 2: score candidates. Determine NEEDS_DATA status: when caller passed
    # no volume_data AND no_history information for a symbol, we still rank but
    # mark as NEEDS_DATA (status precedence over TRADE_ELIGIBLE/OBSERVE_ONLY).
    scored: list[dict] = []
    for sym in candidates:
        vol = volume_data.get(sym)
        spr = spread_data.get(sym)
        perf = paper_performance.get(sym)
        compat = strategy_compat.get(sym)
        cal = confidence_calibration.get(sym)
        fit = regime_fit.get(sym)
        dd = drawdown_history.get(sym)
        anoms = recent_anomalies.get(sym)

        # Volatility proxy: derive from perf if present, else None.
        daily_vol_pct = None
        if isinstance(perf, dict):
            daily_vol_pct = perf.get("daily_vol_pct")

        # Days_with_bars proxy: derive from perf if present, else None.
        days_with_bars = None
        if isinstance(perf, dict):
            days_with_bars = perf.get("days_with_bars_last_5d")

        perf_score, perf_info = _score_paper_performance(perf)
        components = {
            "liquidity_score":         _score_liquidity(vol, volume_baseline),
            "spread_score":            _score_spread(spr, spread_baseline_bps),
            "volatility_score":        _score_volatility(daily_vol_pct),
            "data_quality_score":      _score_data_quality(days_with_bars),
            "paper_performance_score": perf_score,
            "strategy_compat_score":   _score_strategy_compat(compat),
            "calibration_score":       _score_calibration(cal),
            "regime_fit_score":        _score_regime_fit(fit),
            "drawdown_history_score":  _score_drawdown_history(dd),
            "recent_anomalies_score":  _score_recent_anomalies(anoms),
        }
        score = _composite_score(components)

        # Determine status:
        #   NEEDS_DATA precedes everything else when we genuinely have nothing.
        #   TRADE_ELIGIBLE requires positive paper history (n_closed >= 5).
        if vol is None and days_with_bars is None and perf is None:
            status = "NEEDS_DATA"
            reason: str | None = "no_volume_or_history_or_perf"
        else:
            n_closed = perf_info.get("n_closed", 0)
            if n_closed >= 5:
                status = "TRADE_ELIGIBLE"
                reason = None
            else:
                status = "OBSERVE_ONLY"
                reason = "insufficient_paper_history"

        scored.append({
            "symbol":     sym,
            "score":      round(score, 6),
            "status":     status,
            "reason":     reason,
            "components": {k: round(float(v), 6) for k, v in components.items()},
        })

    # Append the hard-rejected ones at the end with score 0.0
    for sym, why in rejected_reasons.items():
        scored.append({
            "symbol":     sym,
            "score":      0.0,
            "status":     "REJECTED",
            "reason":     why,
            "components": {},
        })

    # Step 3: sort deterministically by (-score, status_order, symbol)
    _STATUS_ORDER = {
        "TRADE_ELIGIBLE": 0, "OBSERVE_ONLY": 1, "NEEDS_DATA": 2, "REJECTED": 3,
    }

    def _sort_key(r: dict) -> tuple:
        return (
            -float(r.get("score") or 0.0),
            _STATUS_ORDER.get(r.get("status") or "REJECTED", 9),
            str(r.get("symbol") or ""),
        )

    scored.sort(key=_sort_key)

    # Step 4: assign ranks
    for i, r in enumerate(scored, start=1):
        r["rank"] = i
        out.append(r)

    if audit:
        _emit_ranking_audit(out, universe_id)

    return out


# ─── Report writer ───────────────────────────────────────────────────────────

def _format_ranking_markdown(ranking: list[dict], *,
                              universe_id: str | None = None) -> str:
    """Render the ranking as a markdown table. Paper-analysis only."""
    from datetime import datetime as _dt, timezone as _tz
    now_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# Universe Ranking (paper trading)")
    lines.append("")
    lines.append(
        "*Paper analysis only. Ranking informs operator attention; it does "
        "NOT auto-trade. Risk engine retains FINAL SAY on every order.*"
    )
    lines.append("")
    lines.append(f"Universe: `{universe_id or 'US_LARGE'}` — generated {now_iso}.")
    lines.append("")
    lines.append("| Rank | Symbol | Status | Score | Liq | Spread | Vol | Data | Paper | Strat | Cal | Regime | DD | Anom | Reason |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in ranking:
        c = r.get("components") or {}
        def _c(k: str) -> str:
            v = c.get(k)
            if v is None:
                return "–"
            try:
                return f"{float(v):.2f}"
            except (TypeError, ValueError):
                return "–"
        lines.append(
            f"| {r.get('rank', '–')} | {r.get('symbol', '?')} | "
            f"{r.get('status', '?')} | "
            f"{float(r.get('score') or 0.0):.3f} | "
            f"{_c('liquidity_score')} | "
            f"{_c('spread_score')} | "
            f"{_c('volatility_score')} | "
            f"{_c('data_quality_score')} | "
            f"{_c('paper_performance_score')} | "
            f"{_c('strategy_compat_score')} | "
            f"{_c('calibration_score')} | "
            f"{_c('regime_fit_score')} | "
            f"{_c('drawdown_history_score')} | "
            f"{_c('recent_anomalies_score')} | "
            f"{r.get('reason') or ''} |"
        )
    lines.append("")
    lines.append(
        "Status legend: TRADE_ELIGIBLE (passes gates + has paper evidence) · "
        "OBSERVE_ONLY (passes gates, evidence too thin) · "
        "NEEDS_DATA (no volume/history available) · "
        "REJECTED (forbidden pattern or spread/liquidity hard gate).")
    lines.append("")
    lines.append(
        "> This report cannot raise risk limits, position sizes, or trigger "
        "trades. It is informational and audit-traceable.")
    return "\n".join(lines) + "\n"


def write_universe_report(
    ranking: list[dict],
    *,
    out_md_path: str | None = None,
    out_json_path: str | None = None,
    universe_id: str | None = None,
) -> tuple[str, str]:
    """Write docs/universe_ranking_LATEST.{md,json}.

    Returns (md_path, json_path) — the paths actually written. Empty
    string if the corresponding output was skipped.
    """
    import json as _json
    from pathlib import Path as _Path

    md_target = out_md_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "universe_ranking_LATEST.md",
    )
    json_target = out_json_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "universe_ranking_LATEST.json",
    )

    md_written = ""
    json_written = ""

    md_body = _format_ranking_markdown(ranking, universe_id=universe_id)
    try:
        p = _Path(md_target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md_body, encoding="utf-8")
        md_written = str(p)
    except Exception:
        pass

    try:
        p = _Path(json_target)
        p.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt, timezone as _tz
        payload = {
            "universe_id":  universe_id,
            "generated_at": _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n":            len(ranking),
            "ranking":      ranking,
        }
        p.write_text(_json.dumps(payload, indent=2, sort_keys=True),
                      encoding="utf-8")
        json_written = str(p)
    except Exception:
        pass

    return md_written, json_written


__all__ = [
    "UNIV_US_LARGE", "UNIV_US_MICROCAP", "UNIV_PL_GPW",
    "UNIV_CRYPTO", "UNIV_CUSTOM",
    "VALID_UNIVERSES",
    "DEFAULT_UNIVERSES", "DEFAULT_CONFIG_PATH",
    "UniverseSpec",
    "get_universe", "list_enabled", "is_paper_ready", "can_switch",
    "FORBIDDEN_SYMBOL_SUFFIXES", "FORBIDDEN_SYMBOL_CHARS",
    "filter_symbols_for_paper_trading",
    # v3.19.0 — ranking
    "rank_symbols", "write_universe_report",
]

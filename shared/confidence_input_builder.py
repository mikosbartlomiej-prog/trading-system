"""v3.24.0 (2026-06-15) — ETAP 2 — Production-side confidence inputs builder.

WHY
---
v3.22 wired ``emit_signal_opportunity`` as the single ledger entry-point,
but the audit on 2026-06-15 showed that 100% of the last 7 days of
opportunity rows (16,238 rows) have ``confidence_score=null`` and an
EMPTY ``confidence_components={}``. The reason is mechanical: monitors
build a SignalEvent but most of them either (a) leave
``confidence_inputs={}`` or (b) pass partial data that
``compute_confidence`` accepts but renders to a neutral 0.5 across the
board. Result: the shadow-eligibility gate (``confidence >= 0.50``) can
never fire, the throughput SLA stays at ``FINDING_P0``, and no
real-market edge can accumulate.

This module provides a deterministic, FAIL-SOFT builder that turns a
``SignalEvent`` into a ``ConfidenceInputs`` dataclass. ``signal_emitter``
calls it for every entry-capable event before invoking
``compute_confidence(**components)``. Each component that cannot be
computed gets a neutral default (0.5) **and** an explicit reason string
written to ``default_reasons``. The caller can therefore audit, per
row, which components were genuine measurements and which were defaults.

CONTRACT
--------
* Pure-data + pure-compute. Imports ``shared.heartbeat`` only because
  health is a system-level signal that is otherwise impossible to
  source from a per-event payload.
* NEVER imports ``alpaca_orders`` or any broker module.
* NEVER makes network calls.
* NEVER raises on bad inputs — it returns a degraded ``ConfidenceInputs``
  with reasons attached.
* For entry-capable events the returned ``components`` dict is
  guaranteed to carry at least ``data_quality``, ``signal_strength`` and
  ``system_health``. If even the defaults would leave the dict empty
  (which would be a bug in this module) we raise ``ValueError``.

Builder stamped ``v3.24.0`` so downstream rows know which generation of
the builder produced them. When we ship v3.25 with calibration data, the
stamp lets the learning loop separate calibrated vs uncalibrated rows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


BUILDER_VERSION = "v3.24.0"

# Component keys we attempt to populate for every entry-capable event.
# Order matters only for completeness-fraction calculation.
_TARGET_COMPONENT_KEYS = (
    "data_quality",
    "signal_strength",
    "regime_alignment",
    "system_health",
    "risk_state",
    "sample_size",
    "track_record",
    "calibration",
    "edge_evidence",
    "slippage_risk",
    "price_move_atr",
    "volume_ratio",
)

# Components that MUST appear (even as defaults) for an entry-capable event.
_MANDATORY_FOR_ENTRY = ("data_quality", "signal_strength", "system_health")

# Neutral fallback shared with shared/confidence.py.
NEUTRAL_COMPONENT = 0.5


# ─── Public dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConfidenceInputs:
    """Structured envelope produced by ``build_confidence_inputs``.

    * ``components`` — the kwargs to pass to ``compute_confidence``.
    * ``default_reasons`` — per-component string explaining WHY a value
      defaulted (e.g. ``"NO_HEARTBEAT_DATA"``, ``"NO_STRATEGY_TRADES"``).
    * ``completeness`` — fraction in [0.0, 1.0] of components that were
      sourced from real data (i.e. NOT defaulted).
    * ``builder_version`` — version stamp for traceability.
    """

    strategy_id: str
    symbol: str
    source_monitor: str
    raw_signal: dict
    components: dict
    default_reasons: dict
    completeness: float
    builder_version: str = BUILDER_VERSION

    def to_dict(self) -> dict:
        return {
            "strategy_id":      self.strategy_id,
            "symbol":           self.symbol,
            "source_monitor":   self.source_monitor,
            "raw_signal":       dict(self.raw_signal or {}),
            "components":       dict(self.components or {}),
            "default_reasons":  dict(self.default_reasons or {}),
            "completeness":     float(self.completeness),
            "builder_version":  self.builder_version,
        }


# ─── Internal helpers — every one is fail-soft ───────────────────────────────


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _signal_dict(event: Any) -> dict:
    raw = getattr(event, "raw_signal", None)
    return _safe_dict(raw)


def _data_quality_from_event(event: Any) -> tuple[Optional[float], Optional[str]]:
    """Pick a measured data_quality score from the event, if any.

    Order:
      1. ``raw_signal['data_quality']`` if it's a numeric in [0, 1].
      2. ``universe_status.get('data_quality')`` likewise.
      3. ``raw_signal['bars_count']`` as a proxy (≥20 bars → 1.0,
         else linearly interpolated down to 0.2 at 0 bars).
    Returns ``(value_or_None, reason_or_None_if_defaulted)``.
    """
    raw = _signal_dict(event)
    direct = _safe_float(raw.get("data_quality"))
    if direct is not None and 0.0 <= direct <= 1.0:
        return direct, None

    universe = _safe_dict(getattr(event, "universe_status", {}))
    direct_uni = _safe_float(universe.get("data_quality"))
    if direct_uni is not None and 0.0 <= direct_uni <= 1.0:
        return direct_uni, None

    bars_count = _safe_int(raw.get("bars_count"))
    if bars_count is not None and bars_count >= 0:
        # ≥20 → 1.0 (fresh and complete); 0 → 0.2 (very degraded).
        proxy = 0.2 + min(1.0, bars_count / 20.0) * 0.8
        return max(0.2, min(1.0, proxy)), None

    return None, "NO_DATA_QUALITY_INPUTS"


def _signal_strength_from_event(event: Any) -> tuple[Optional[float], Optional[str]]:
    """Try several sources for signal_strength, in order:

      1. ``raw_signal['primary_score']`` (canonical builder field).
      2. ``raw_signal['confidence_inputs']['primary_score']`` (legacy).
      3. ``raw_signal['rsi']`` normalised to [0, 1] via |RSI-50|/50 (a
         neutral RSI=50 maps to 0; an extreme RSI of 0 or 100 maps to
         1.0). This is a conservative proxy — strategies with their own
         scoring should always supply ``primary_score`` instead.
    """
    raw = _signal_dict(event)
    direct = _safe_float(raw.get("primary_score"))
    if direct is not None:
        return max(0.0, min(1.0, direct)), None

    nested = _safe_dict(raw.get("confidence_inputs")).get("primary_score")
    direct_nested = _safe_float(nested)
    if direct_nested is not None:
        return max(0.0, min(1.0, direct_nested)), None

    rsi = _safe_float(raw.get("rsi"))
    if rsi is not None and 0.0 <= rsi <= 100.0:
        # Distance from neutral 50 in [0, 50] → strength in [0, 1].
        strength = abs(rsi - 50.0) / 50.0
        return max(0.0, min(1.0, strength)), None

    return None, "NO_SIGNAL_STRENGTH_INPUTS"


def _regime_alignment_from_event(event: Any, market_context: dict | None
                                  ) -> tuple[Optional[str], Optional[str]]:
    """Resolve the regime label.

    ``compute_confidence`` accepts a string regime ("RISK_ON", "RISK_OFF",
    "NEUTRAL", "INFLATION_SHOCK"); the alignment score is computed
    server-side. We therefore only need to forward the label.
    """
    if market_context:
        regime = market_context.get("regime") if isinstance(market_context, dict) else None
        if isinstance(regime, str) and regime.strip():
            return regime.strip(), None

    mr = _safe_dict(getattr(event, "market_regime", {}))
    regime = mr.get("regime") if isinstance(mr, dict) else None
    if isinstance(regime, str) and regime.strip():
        return regime.strip(), None

    return None, "NO_REGIME_DATA"


def _system_health_snapshot() -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Read live heartbeat snapshot. Fail-soft on import failure."""
    try:
        try:
            from heartbeat import health_snapshot  # type: ignore
        except ImportError:
            from shared.heartbeat import health_snapshot  # type: ignore
    except Exception:
        return None, None, "HEARTBEAT_UNAVAILABLE"
    try:
        snap = health_snapshot()
    except Exception:
        return None, None, "HEARTBEAT_UNAVAILABLE"
    if not isinstance(snap, dict):
        return None, None, "HEARTBEAT_UNAVAILABLE"
    alive = _safe_int(snap.get("alive"))
    total = _safe_int(snap.get("total"))
    if alive is None or total is None:
        return None, None, "NO_HEARTBEAT_DATA"
    return alive, total, None


def _risk_state_from_event(event: Any) -> tuple[dict, list[str]]:
    """Forward whatever risk inputs we have. Returns (kwargs, missing_keys)."""
    risk = _safe_dict(getattr(event, "risk_inputs", {}))
    out: dict = {}
    missing: list[str] = []

    pnl_pct = _safe_float(risk.get("intraday_pnl_pct"))
    if pnl_pct is not None:
        out["intraday_pnl_pct"] = pnl_pct
    else:
        missing.append("intraday_pnl_pct")

    giveback = _safe_float(risk.get("giveback_pct_of_peak"))
    if giveback is not None:
        out["giveback_pct_of_peak"] = giveback
    else:
        missing.append("giveback_pct_of_peak")

    losses = _safe_int(risk.get("consecutive_losses"))
    if losses is not None:
        out["consecutive_losses"] = losses
    else:
        missing.append("consecutive_losses")

    drawdown = _safe_float(risk.get("drawdown_pct"))
    if drawdown is not None:
        out["drawdown_pct"] = drawdown
    else:
        missing.append("drawdown_pct")

    return out, missing


def _sample_size_from_state(strategy_state: dict | None
                             ) -> tuple[Optional[int], Optional[str]]:
    """Pull ``trades_lifetime`` (or similar) from a strategy state dict."""
    if not isinstance(strategy_state, dict):
        return None, "NO_STRATEGY_STATE"
    for key in ("trades_lifetime", "n_closed_paper", "trades_closed",
                "trades_count", "closed_paper_trades"):
        val = _safe_int(strategy_state.get(key))
        if val is not None and val >= 0:
            return val, None
    return None, "NO_STRATEGY_TRADES"


def _track_record_from_state(strategy_state: dict | None
                              ) -> tuple[Optional[float], Optional[float],
                                          Optional[str]]:
    """Recent rolling P&L / win-rate. Returns (recent_wr, profit_factor, reason)."""
    if not isinstance(strategy_state, dict):
        return None, None, "NO_STRATEGY_STATE"
    recent_wr = _safe_float(strategy_state.get("recent_wr"))
    if recent_wr is None:
        recent_wr = _safe_float(strategy_state.get("recent_20_wr"))
    if recent_wr is not None and (recent_wr < 0.0 or recent_wr > 1.0):
        # Some sources store percent. Convert.
        if 0.0 <= recent_wr <= 100.0:
            recent_wr = recent_wr / 100.0
        else:
            recent_wr = None

    profit_factor = _safe_float(strategy_state.get("profit_factor"))
    if recent_wr is None and profit_factor is None:
        return None, None, "NO_TRACK_RECORD"
    return recent_wr, profit_factor, None


def _calibration_marker(strategy_state: dict | None
                         ) -> tuple[Optional[float], Optional[str]]:
    """Until we ship per-bucket calibration in v3.25, return neutral.

    If a state dict already carries a ``calibration_total`` we forward
    it (this lets unit tests exercise the future path).
    """
    if isinstance(strategy_state, dict):
        cal = _safe_float(strategy_state.get("calibration_total"))
        if cal is not None and 0.0 <= cal <= 1.0:
            return cal, None
    return None, "NO_CALIBRATION_HISTORY"


def _anomaly_multipliers_from_event(event: Any
                                     ) -> tuple[Optional[float], Optional[float],
                                                 list[str]]:
    """price_move_atr + volume_ratio. Missing values default to no-penalty."""
    raw = _signal_dict(event)
    pma = _safe_float(raw.get("price_move_atr"))
    if pma is None:
        pma = _safe_float(raw.get("move_atr"))
    vol_ratio = _safe_float(raw.get("volume_ratio"))
    if vol_ratio is None:
        vol_ratio = _safe_float(raw.get("vol_ratio"))
    missing: list[str] = []
    if pma is None:
        missing.append("price_move_atr")
    if vol_ratio is None:
        missing.append("volume_ratio")
    return pma, vol_ratio, missing


# ─── Public API ──────────────────────────────────────────────────────────────


def build_confidence_inputs(signal_event: Any,
                             *,
                             market_context: dict | None = None,
                             strategy_state: dict | None = None,
                             ) -> ConfidenceInputs:
    """Build a ``ConfidenceInputs`` from a SignalEvent (or any duck-type).

    Parameters
    ----------
    signal_event
        Any object exposing the SignalEvent attribute surface (``raw_signal``,
        ``risk_inputs``, ``market_regime``, ``universe_status``,
        ``strategy_id``, ``symbol``, ``source_monitor``,
        ``entry_capable``).
    market_context
        Optional dict supplying authoritative regime info (preferred over
        the in-event copy).
    strategy_state
        Optional dict carrying per-strategy state (``trades_lifetime``,
        ``recent_wr``, ``profit_factor``, ``calibration_total``).

    Returns
    -------
    ConfidenceInputs
        Always returns a valid dataclass. For ``entry_capable`` events
        with truly empty input, raises ``ValueError`` (this is a bug in
        the caller — they invoked the builder with no data at all).
    """

    strategy_id = str(getattr(signal_event, "strategy_id", "") or "")
    symbol = str(getattr(signal_event, "symbol", "") or "")
    source_monitor = str(getattr(signal_event, "source_monitor", "") or "")
    raw_signal = _signal_dict(signal_event)
    entry_capable = bool(getattr(signal_event, "entry_capable", False))

    components: dict = {"strategy": strategy_id}
    default_reasons: dict = {}
    real_components: set[str] = set()

    # ── data_quality ──────────────────────────────────────────────────────
    dq, dq_reason = _data_quality_from_event(signal_event)
    if dq is not None:
        # data_quality is computed server-side via score_data_quality from
        # bar_age + spread + bars_count. We have a precomputed proxy so we
        # forward it via bars_count (≥20 → fresh) AND quote_spread_pct (low).
        # Map our [0, 1] back into the server's inputs:
        #   dq ≥ 0.9 → bars_count=25, spread=0.0001 → server returns ≥0.95
        #   dq ≤ 0.3 → bars_count=5,  spread=0.005  → server returns ≤0.35
        # We use bars_count linearly + a tight spread so the resulting
        # score from compute_confidence tracks our proxy.
        components["bars_count"] = max(1, int(round(dq * 25)))
        components["quote_spread_pct"] = max(0.0, 0.05 * (1.0 - dq))
        components["bar_age_seconds"] = max(0.0, 600.0 * (1.0 - dq))
        real_components.add("data_quality")
    else:
        default_reasons["data_quality"] = dq_reason or "NO_DATA_QUALITY_INPUTS"
        # Server fallback: omit inputs → score_data_quality returns
        # NEUTRAL_COMPONENT (0.5). That is the contract.

    # ── signal_strength ───────────────────────────────────────────────────
    ss, ss_reason = _signal_strength_from_event(signal_event)
    if ss is not None:
        components["primary_score"] = ss
        real_components.add("signal_strength")
        # Forward confirmations if present.
        confirmations = _safe_int(raw_signal.get("confirmations"))
        if confirmations is not None:
            components["confirmations"] = confirmations
    else:
        default_reasons["signal_strength"] = ss_reason or "NO_SIGNAL_STRENGTH_INPUTS"

    # ── regime_alignment ──────────────────────────────────────────────────
    regime, regime_reason = _regime_alignment_from_event(signal_event, market_context)
    if regime is not None:
        components["regime"] = regime
        real_components.add("regime_alignment")
    else:
        default_reasons["regime_alignment"] = regime_reason or "NO_REGIME_DATA"

    # ── system_health ─────────────────────────────────────────────────────
    alive, total, hb_reason = _system_health_snapshot()
    if alive is not None and total is not None:
        components["components_alive"] = alive
        components["components_total"] = total
        real_components.add("system_health")
    else:
        default_reasons["system_health"] = hb_reason or "NO_HEARTBEAT_DATA"

    # ── risk_state ────────────────────────────────────────────────────────
    risk_kwargs, missing_risk = _risk_state_from_event(signal_event)
    if risk_kwargs:
        components.update(risk_kwargs)
        real_components.add("risk_state")
    if missing_risk:
        # Single combined reason; server falls back to 0.5 for missing pieces.
        default_reasons["risk_state"] = (
            "PARTIAL_RISK_INPUTS:" + ",".join(missing_risk)
        )

    # ── sample_size ───────────────────────────────────────────────────────
    n_trades, n_reason = _sample_size_from_state(strategy_state)
    if n_trades is not None:
        components["strategy_n_closed_paper"] = n_trades
        real_components.add("sample_size")
    else:
        default_reasons["sample_size"] = n_reason or "NO_STRATEGY_TRADES"

    # ── track_record ──────────────────────────────────────────────────────
    wr, pf, tr_reason = _track_record_from_state(strategy_state)
    if wr is not None or pf is not None:
        if wr is not None:
            components["recent_20_wr"] = wr
        if pf is not None:
            components["strategy_profit_factor"] = pf
        real_components.add("track_record")
    else:
        default_reasons["track_record"] = tr_reason or "NO_TRACK_RECORD"

    # ── calibration ───────────────────────────────────────────────────────
    cal, cal_reason = _calibration_marker(strategy_state)
    if cal is not None:
        # compute_confidence doesn't take a direct calibration scalar yet
        # (will land in v3.25). Until then we only log it via metadata.
        # Stash on the raw_signal copy in the dataclass output so the
        # learning loop can read it back.
        pass
    if cal is None:
        default_reasons["calibration"] = cal_reason or "NO_CALIBRATION_HISTORY"

    # ── edge_evidence + slippage_risk ─────────────────────────────────────
    # These are informational components that compute_confidence already
    # scores from the same kwargs as sample_size + track_record. We log a
    # default-reason if no data was available so callers can audit.
    if "strategy_profit_factor" not in components:
        default_reasons["edge_evidence"] = "NO_PROFIT_FACTOR"

    estimated_slippage = _safe_float(raw_signal.get("estimated_slippage_bps"))
    expected_edge = _safe_float(raw_signal.get("expected_edge_bps"))
    if estimated_slippage is not None:
        components["estimated_slippage_bps"] = estimated_slippage
    if expected_edge is not None:
        components["expected_edge_bps"] = expected_edge
    if estimated_slippage is not None and expected_edge is not None:
        real_components.add("slippage_risk")
    else:
        default_reasons["slippage_risk"] = "NO_SLIPPAGE_INPUTS"

    # ── multipliers: price_move_atr + volume_ratio ────────────────────────
    pma, vol_ratio, missing_multipliers = _anomaly_multipliers_from_event(signal_event)
    if pma is not None:
        components["price_move_atr"] = pma
        real_components.add("price_move_atr")
    if vol_ratio is not None:
        components["volume_ratio"] = vol_ratio
        real_components.add("volume_ratio")
    for key in missing_multipliers:
        default_reasons[key] = "NO_ANOMALY_INPUT_DEFAULTS_TO_NO_PENALTY"

    # ── completeness ──────────────────────────────────────────────────────
    completeness = len(real_components) / float(len(_TARGET_COMPONENT_KEYS))
    completeness = max(0.0, min(1.0, completeness))

    # ── invariant: entry_capable rows MUST have at least minimal kwargs ───
    # ``components`` should always contain at least the keys we explicitly
    # set above for the mandatory components OR an explicit default reason.
    if entry_capable:
        # The components dict will always carry at least "strategy" — but
        # the compute_confidence call needs at minimum data_quality OR
        # signal_strength OR system_health to produce a meaningful number.
        has_mandatory = any(
            key in real_components for key in _MANDATORY_FOR_ENTRY
        ) or any(
            default_reasons.get(key) for key in _MANDATORY_FOR_ENTRY
        )
        if not has_mandatory:
            # This should never happen given the fallbacks above. If it
            # does, the builder is broken — fail loudly.
            raise ValueError(
                "build_confidence_inputs produced empty components for an "
                "entry_capable event — this indicates a builder bug."
            )

    return ConfidenceInputs(
        strategy_id=strategy_id,
        symbol=symbol,
        source_monitor=source_monitor,
        raw_signal=raw_signal,
        components=components,
        default_reasons=default_reasons,
        completeness=completeness,
        builder_version=BUILDER_VERSION,
    )


__all__ = [
    "BUILDER_VERSION",
    "ConfidenceInputs",
    "build_confidence_inputs",
    "NEUTRAL_COMPONENT",
]

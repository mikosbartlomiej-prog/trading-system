"""v3.21.0 (2026-06-04) — ETAP 7 — Fill Model Calibration.

WHY
---
Audit-board theme STRAT-003 explicitly called out the "shadow-vs-broker"
gap: the system reasons about fills using a 5 bps slippage + 1 bps half
spread assumption (see ``shared/evidence_production``) but does not
verify those numbers against actual broker paper fills. Without
calibration the WR / PF / expectancy bounds reported by
``shared/evidence_lower_bounds`` can drift away from execution reality
without anyone noticing.

This module is the *read-only* calibration layer that compares the
shadow fill model against broker paper actuals when both signals exist.
It NEVER mutates the runtime, NEVER raises sizing limits, NEVER lowers
confidence thresholds, NEVER flips ``EDGE_GATE_ENABLED``, NEVER calls
a paid API, NEVER touches the live broker.

If the broker-paper sample is small (< 20 paired observations) the
report status is ``INSUFFICIENT_BROKER_PAPER_DATA`` and we explicitly
skip any model adjustment. The behaviour is governed by Multi-Agent
Audit Board and is non-auto-apply by design.

CONTRACT
--------
- ``compare_shadow_vs_broker(pairs)`` returns the per-observation deltas.
- ``build_calibration_report(window_days)`` returns the aggregate report
  dict (deterministic, paper-only).
- ``HIGH_SLIPPAGE_WARN_BPS`` triggers a WARN — the warning is surfaced
  via the operator action queue / audit log; it does NOT change runtime.
- ``MIN_PAIRED_OBSERVATIONS`` is the threshold below which calibration
  is skipped (``INSUFFICIENT_BROKER_PAPER_DATA``).
- Pure stdlib. Free-tier safe. Offline.

STATUS LADDER
-------------
- ``INSUFFICIENT_BROKER_PAPER_DATA`` — paired n < 20.
- ``WITHIN_TOLERANCE``               — observed slippage <= shadow + 5 bps.
- ``MODEL_UNDERESTIMATES``           — observed - shadow > 5 bps but < 15 bps.
- ``MODEL_DRIFT_HIGH``               — observed - shadow >= 15 bps (warn).
- ``MODEL_OVERESTIMATES``            — shadow > observed by >= 5 bps.

NEVER MUTATES RUNTIME. EVIDENCE BUDGET (ETAP 9) caps the report size.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

# ─── Statuses (closed enum) ───────────────────────────────────────────────────

INSUFFICIENT_BROKER_PAPER_DATA = "INSUFFICIENT_BROKER_PAPER_DATA"
WITHIN_TOLERANCE               = "WITHIN_TOLERANCE"
MODEL_UNDERESTIMATES           = "MODEL_UNDERESTIMATES"
MODEL_DRIFT_HIGH               = "MODEL_DRIFT_HIGH"
MODEL_OVERESTIMATES            = "MODEL_OVERESTIMATES"

CALIBRATION_STATUSES: frozenset[str] = frozenset({
    INSUFFICIENT_BROKER_PAPER_DATA,
    WITHIN_TOLERANCE,
    MODEL_UNDERESTIMATES,
    MODEL_DRIFT_HIGH,
    MODEL_OVERESTIMATES,
})


# ─── Thresholds (deterministic constants) ─────────────────────────────────────

# Minimum paired (shadow, broker_paper) observations before we calibrate.
MIN_PAIRED_OBSERVATIONS:    int = 20

# Tolerance band for "shadow ≈ broker": ±5 bps centred on 0.
TOLERANCE_BPS:              float = 5.0

# Warn when observed slippage drifts above shadow by this many bps.
HIGH_SLIPPAGE_WARN_BPS:     float = 15.0

# Cap any extreme outlier so the aggregate isn't dominated by a fat tail.
MAX_PER_OBSERVATION_BPS:    float = 200.0

# Adverse-selection lookback (seconds) - retained for record only; this
# module does not fetch additional data, the caller passes it pre-computed.
ADVERSE_SELECTION_LOOKBACK_S: int = 60


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        if v == float("inf") or v == float("-inf"):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bps_diff(price_actual: float, price_reference: float) -> float:
    """Return signed bps delta of ``actual`` vs ``reference``."""
    ref = _safe_float(price_reference, 0.0)
    if ref <= 0:
        return 0.0
    return ((_safe_float(price_actual) - ref) / ref) * 10000.0


def _clamp_bps(bps: float) -> float:
    return max(-MAX_PER_OBSERVATION_BPS,
               min(MAX_PER_OBSERVATION_BPS, _safe_float(bps)))


# ─── Per-observation comparison ───────────────────────────────────────────────


def compare_shadow_vs_broker(pairs: Iterable[Mapping[str, Any]]
                              ) -> list[dict]:
    """Return per-observation deltas for each shadow/broker fill pair.

    Each input pair MUST carry:
      - ``shadow_fill_price``
      - ``broker_paper_fill_price``
      - ``reference_price`` (mid at signal generation)
      - ``expected_slippage_bps`` (from the shadow model)
      - ``observed_spread_bps`` (broker-reported, if available)
      - ``spread_assumption_bps`` (from the shadow model)
      - ``fill_delay_seconds`` (broker latency)
      - ``adverse_selection_after_fill_bps`` (pre-computed)
      - ``symbol`` / ``strategy`` for diagnostics

    Output schema (stable):
      shadow_vs_broker_bps, slippage_delta_bps, spread_delta_bps,
      fill_delay_seconds, adverse_selection_after_fill_bps, symbol,
      strategy.

    Pure function. No side effects. No network.
    """
    out: list[dict] = []
    for raw in pairs:
        if not isinstance(raw, Mapping):
            continue
        ref = _safe_float(raw.get("reference_price"))
        if ref <= 0:
            continue
        sh = _safe_float(raw.get("shadow_fill_price"))
        br = _safe_float(raw.get("broker_paper_fill_price"))
        # If either side is missing this is not a paired observation.
        if sh <= 0 or br <= 0:
            continue
        out.append({
            "symbol":   str(raw.get("symbol") or "?"),
            "strategy": str(raw.get("strategy") or "unknown"),
            "shadow_vs_broker_bps": _clamp_bps(_bps_diff(br, sh)),
            "slippage_delta_bps":   _clamp_bps(
                _safe_float(raw.get("actual_paper_slippage_bps"))
                - _safe_float(raw.get("expected_slippage_bps"))
            ),
            "spread_delta_bps":     _clamp_bps(
                _safe_float(raw.get("observed_spread_bps"))
                - _safe_float(raw.get("spread_assumption_bps"))
            ),
            "fill_delay_seconds":   _safe_float(raw.get("fill_delay_seconds")),
            "adverse_selection_after_fill_bps": _clamp_bps(
                _safe_float(raw.get("adverse_selection_after_fill_bps"))
            ),
        })
    return out


# ─── Aggregation ──────────────────────────────────────────────────────────────


def _classify(mean_slippage_delta_bps: float, n: int) -> str:
    if n < MIN_PAIRED_OBSERVATIONS:
        return INSUFFICIENT_BROKER_PAPER_DATA
    d = _safe_float(mean_slippage_delta_bps)
    if d >= HIGH_SLIPPAGE_WARN_BPS:
        return MODEL_DRIFT_HIGH
    if d > TOLERANCE_BPS:
        return MODEL_UNDERESTIMATES
    if d < -TOLERANCE_BPS:
        return MODEL_OVERESTIMATES
    return WITHIN_TOLERANCE


def _safe_mean(xs: list[float]) -> float:
    if not xs:
        return 0.0
    try:
        return statistics.fmean(xs)
    except Exception:
        return sum(xs) / max(1, len(xs))


def _safe_stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    try:
        return statistics.pstdev(xs)
    except Exception:
        m = _safe_mean(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _aggregate(deltas: list[dict]) -> dict:
    n = len(deltas)
    if n == 0:
        return {
            "n_paired": 0,
            "status":   INSUFFICIENT_BROKER_PAPER_DATA,
            "warning":  False,
        }

    shadow_vs_broker = [_safe_float(d["shadow_vs_broker_bps"]) for d in deltas]
    slippage_delta   = [_safe_float(d["slippage_delta_bps"]) for d in deltas]
    spread_delta     = [_safe_float(d["spread_delta_bps"]) for d in deltas]
    fill_delay       = [_safe_float(d["fill_delay_seconds"]) for d in deltas]
    adverse          = [_safe_float(d["adverse_selection_after_fill_bps"])
                        for d in deltas]

    mean_slip = _safe_mean(slippage_delta)
    status = _classify(mean_slip, n)
    return {
        "n_paired":                       n,
        "status":                         status,
        "warning":                        status == MODEL_DRIFT_HIGH,
        "mean_shadow_vs_broker_bps":      _safe_mean(shadow_vs_broker),
        "stdev_shadow_vs_broker_bps":     _safe_stdev(shadow_vs_broker),
        "mean_slippage_delta_bps":        mean_slip,
        "stdev_slippage_delta_bps":       _safe_stdev(slippage_delta),
        "mean_spread_delta_bps":          _safe_mean(spread_delta),
        "mean_fill_delay_seconds":        _safe_mean(fill_delay),
        "mean_adverse_selection_bps":     _safe_mean(adverse),
        "high_slippage_warn_threshold_bps": HIGH_SLIPPAGE_WARN_BPS,
        "tolerance_bps":                  TOLERANCE_BPS,
    }


# ─── Per-execution-quality breakdown ──────────────────────────────────────────


def execution_quality_by_key(deltas: list[dict],
                             *, key: str = "symbol") -> dict[str, dict]:
    """Group deltas by ``symbol`` or ``strategy`` and aggregate.

    Returns a stable dict whose values are themselves aggregate dicts
    of the same shape as ``_aggregate``.
    """
    groups: dict[str, list[dict]] = {}
    for d in deltas:
        k = str(d.get(key, "?"))
        groups.setdefault(k, []).append(d)
    return {k: _aggregate(v) for k, v in groups.items()}


# ─── Top-level report ────────────────────────────────────────────────────────


def build_calibration_report(pairs: Iterable[Mapping[str, Any]] | None = None,
                              *,
                              window_days: int = 90,
                              symbol_filter: str | None = None,
                              ) -> dict:
    """Build the full calibration report dict.

    NEVER mutates runtime parameters. NEVER touches the broker.

    Args:
        pairs: explicit (shadow, broker_paper) observations. When None,
            the function does not fetch from disk — callers should pass
            the paired ledger explicitly. The CLI wrapper
            ``scripts/fill_model_calibration_report.py`` is responsible
            for assembling pairs from the paper ledger.
        window_days: documented for the consumer; this function does NOT
            filter by date itself.
        symbol_filter: optional substring filter on the symbol field.

    Returns a dict suitable for JSON serialisation. Always carries
    ``status``, ``mutates_runtime: false`` and ``produced_at`` so the
    auditor can confirm we did not silently calibrate runtime.
    """
    raw = list(pairs or [])
    if symbol_filter:
        sf = str(symbol_filter)
        raw = [r for r in raw
               if sf in str(r.get("symbol") if isinstance(r, Mapping) else "")]
    deltas = compare_shadow_vs_broker(raw)
    agg = _aggregate(deltas)
    by_symbol = execution_quality_by_key(deltas, key="symbol")
    by_strategy = execution_quality_by_key(deltas, key="strategy")
    report = {
        "produced_at":         _utc_now_iso(),
        "window_days":         int(window_days),
        "mutates_runtime":     False,
        "non_auto_apply":      True,
        "evidence_source":     "PAPER",
        "execution_source":    "SHADOW_AND_BROKER_PAPER",
        "min_paired_required": MIN_PAIRED_OBSERVATIONS,
        "aggregate":           agg,
        "by_symbol":           by_symbol,
        "by_strategy":         by_strategy,
        "n_pairs_in":          len(raw),
        "n_pairs_valid":       len(deltas),
    }
    return report


# ─── Markdown rendering ──────────────────────────────────────────────────────


def render_report_markdown(report: dict) -> str:
    """Deterministic markdown rendering of ``build_calibration_report``.

    Stable schema — consumers can diff it.
    """
    if not isinstance(report, dict):
        return "# Fill model calibration — invalid report\n"

    agg = report.get("aggregate", {}) or {}
    lines: list[str] = []
    lines.append("# Fill model calibration — latest")
    lines.append("")
    lines.append(f"- produced_at: `{report.get('produced_at', '?')}`")
    lines.append(f"- window_days: {report.get('window_days', '?')}")
    lines.append(f"- status: **{agg.get('status', '?')}**")
    lines.append(
        f"- mutates_runtime: {bool(report.get('mutates_runtime', False))}"
    )
    lines.append(
        f"- non_auto_apply: {bool(report.get('non_auto_apply', True))}"
    )
    lines.append("")
    n_paired = int(_safe_float(agg.get("n_paired", 0)))
    if n_paired < MIN_PAIRED_OBSERVATIONS:
        lines.append(
            f"> **n_paired = {n_paired} < {MIN_PAIRED_OBSERVATIONS}** — "
            f"calibration is review-gated; no shadow model adjustment "
            f"performed. Governed by Multi-Agent Audit Board."
        )
        lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    for k, v in agg.items():
        if isinstance(v, float):
            lines.append(f"| {k} | {v:.4f} |")
        else:
            lines.append(f"| {k} | {v} |")
    lines.append("")
    by_symbol = report.get("by_symbol", {}) or {}
    if by_symbol:
        lines.append("## By symbol")
        lines.append("")
        lines.append("| Symbol | n | status | mean_slippage_delta_bps |")
        lines.append("|---|---:|:---:|---:|")
        for sym in sorted(by_symbol):
            row = by_symbol[sym]
            lines.append(
                f"| {sym} "
                f"| {int(_safe_float(row.get('n_paired', 0)))} "
                f"| {row.get('status', '?')} "
                f"| {_safe_float(row.get('mean_slippage_delta_bps', 0)):.4f} |"
            )
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "INSUFFICIENT_BROKER_PAPER_DATA",
    "WITHIN_TOLERANCE",
    "MODEL_UNDERESTIMATES",
    "MODEL_DRIFT_HIGH",
    "MODEL_OVERESTIMATES",
    "CALIBRATION_STATUSES",
    "MIN_PAIRED_OBSERVATIONS",
    "HIGH_SLIPPAGE_WARN_BPS",
    "TOLERANCE_BPS",
    "ADVERSE_SELECTION_LOOKBACK_S",
    "compare_shadow_vs_broker",
    "execution_quality_by_key",
    "build_calibration_report",
    "render_report_markdown",
]

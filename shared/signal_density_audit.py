"""v3.21.0 (2026-06-04) — ETAP 4 — Strategy Signal Density Audit.

WHY
---
Audit board 2026-06-04 follow-up reaffirmed STRAT-001 / STRAT-002 /
STRAT-003: a strategy that is technically ``enabled = true`` but
generates zero / sparse / overly-noisy signals is a hidden liability.
It blocks paper evidence accumulation, gives the LLM Senior PM a fake
data point ("strategy X is on the roster") and silently shifts
allocation budget away from honest performers.

This module is the READ-ONLY classifier that scans the opportunity
ledger + paper experiments + shadow ledger and labels each strategy
with a density-quality status. Downstream callers (Strategy Quality
Gate, audit board) decide what to DO with the label — this module
NEVER mutates state, runtime, risk thresholds, or strategy enablement.

CONTRACT (do-not-cross lines)
-----------------------------
* READ-ONLY. No trades, no broker calls, no state mutations, no
  promotion of variants, no flipping of ``EDGE_GATE_ENABLED``, no
  auto-disabling of strategies.
* Evidence sources stay SEPARATE. Shadow / counterfactual / paper
  ledgers are aggregated into independent counters via
  ``shared.evidence_throughput`` and never collapsed.
* Audit emit per status assignment: ``V321_SIGNAL_DENSITY_AUDIT``.
* Fail-soft. Missing files / malformed records never raise.
* No paid APIs / SDKs / network. Pure stdlib + repo helpers.

PUBLIC API
----------
``run_density_audit(now=None, *, days_window=14, dirs=None,
                    emit_audit=True)``
    Returns ``DensityAuditReport`` with per-strategy ``DensityRecord``.

``classify_density_status(record, *, throughput=None)``
    Returns one of ``DENSITY_STATUSES`` for a single record.

STATUSES (closed enum)
----------------------
- ``DEAD_STRATEGY`` — 0 raw signals over the window.
- ``TOO_SPARSE``    — < 5 signals AND no shadow / broker fills.
- ``NOISY_STRATEGY`` — high signal count but very low average confidence
  AND mostly observe-only / rejected.
- ``HIGH_REJECTION_BUT_PROMISING`` — high rejection rate but average
  confidence on the accepted minority is solid.
- ``NEEDS_VARIANT_DISCOVERY`` — one-symbol or one-regime dependence.
- ``NEEDS_UNIVERSE_EXPANSION`` — single-symbol concentration with
  healthy density.
- ``HEALTHY_DENSITY`` — none of the above triggered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from evidence_throughput import (
        DEFAULT_WINDOW_DAYS,
        StrategyThroughput,
        ThroughputReport,
        compute_throughput,
    )
except ImportError:  # pragma: no cover
    from shared.evidence_throughput import (  # type: ignore
        DEFAULT_WINDOW_DAYS,
        StrategyThroughput,
        ThroughputReport,
        compute_throughput,
    )


# ─── Status enum (closed) ─────────────────────────────────────────────────────

DEAD_STRATEGY                 = "DEAD_STRATEGY"
TOO_SPARSE                    = "TOO_SPARSE"
NOISY_STRATEGY                = "NOISY_STRATEGY"
HEALTHY_DENSITY               = "HEALTHY_DENSITY"
HIGH_REJECTION_BUT_PROMISING  = "HIGH_REJECTION_BUT_PROMISING"
NEEDS_VARIANT_DISCOVERY       = "NEEDS_VARIANT_DISCOVERY"
NEEDS_UNIVERSE_EXPANSION      = "NEEDS_UNIVERSE_EXPANSION"

DENSITY_STATUSES: frozenset[str] = frozenset({
    DEAD_STRATEGY,
    TOO_SPARSE,
    NOISY_STRATEGY,
    HEALTHY_DENSITY,
    HIGH_REJECTION_BUT_PROMISING,
    NEEDS_VARIANT_DISCOVERY,
    NEEDS_UNIVERSE_EXPANSION,
})


# ─── Thresholds (exported for tests + audit board review) ────────────────────

MIN_SIGNALS_NOT_DEAD            = 1       # ≥ 1 raw signal => not DEAD
SPARSE_MAX_SIGNALS              = 5       # < 5 raw signals
SPARSE_REQUIRES_NO_FILLS        = True    # ... AND zero shadow/broker fills
NOISY_MIN_SIGNAL_VOLUME         = 20      # ≥ 20 signals AND low quality
NOISY_MAX_AVG_CONFIDENCE        = 0.45    # average confidence below ALERT band
NOISY_MIN_LOW_CONFIDENCE_RATIO  = 0.60    # ≥ 60% scored under 0.50
HIGH_REJECTION_MIN_RATIO        = 0.70    # ≥ 70% rejected
HIGH_REJECTION_PROMISING_MIN_CONF = 0.65  # accepted minority high confidence
SINGLE_SYMBOL_THRESHOLD         = 1
SINGLE_REGIME_THRESHOLD         = 1
UNIVERSE_EXPAND_MIN_SIGNALS     = 15      # healthy density but 1-symbol pin


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        if v in (float("inf"), float("-inf")):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_str(x: Any, default: str = "") -> str:
    try:
        return str(x) if x is not None else default
    except Exception:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Audit emission ──────────────────────────────────────────────────────────


def _emit_density_audit(strategy: str,
                        status: str,
                        payload_extra: dict,
                        ) -> None:
    """Append one ``V321_SIGNAL_DENSITY_AUDIT`` event to the audit log.

    Best-effort. Never raises (audit write must not break the call
    path — fail-soft contract).
    """
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
    except Exception:
        return
    try:
        record = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "decision":   "V321_SIGNAL_DENSITY_AUDIT",
            "event_type": "V321_SIGNAL_DENSITY_AUDIT",
            "actor":      "signal_density_audit",
            "strategy":   strategy,
            "status":     status,
            "payload":    payload_extra,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        return


# ─── Per-strategy density record ─────────────────────────────────────────────


@dataclass
class DensityRecord:
    """Per-strategy snapshot used for density classification.

    The fields mirror the subset of ``StrategyThroughput`` we need for
    the rule ladder, plus a few derived quality indicators.
    """

    strategy: str
    raw_signal_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    observe_only_count: int = 0
    shadow_paper_fills: int = 0
    broker_paper_fills: int = 0
    symbol_coverage: int = 0
    regime_coverage: int = 0
    confidence_buckets: dict[str, int] = field(default_factory=dict)
    avg_confidence_score: float = 0.0
    low_confidence_ratio: float = 0.0
    accepted_avg_confidence_score: float = 0.0
    rejection_ratio: float = 0.0
    status: str = HEALTHY_DENSITY

    def to_dict(self) -> dict:
        return {
            "strategy":                        self.strategy,
            "raw_signal_count":                self.raw_signal_count,
            "accepted_count":                  self.accepted_count,
            "rejected_count":                  self.rejected_count,
            "observe_only_count":              self.observe_only_count,
            "shadow_paper_fills":              self.shadow_paper_fills,
            "broker_paper_fills":              self.broker_paper_fills,
            "symbol_coverage":                 self.symbol_coverage,
            "regime_coverage":                 self.regime_coverage,
            "confidence_buckets":              dict(self.confidence_buckets),
            "avg_confidence_score":            self.avg_confidence_score,
            "low_confidence_ratio":            self.low_confidence_ratio,
            "accepted_avg_confidence_score":   self.accepted_avg_confidence_score,
            "rejection_ratio":                 self.rejection_ratio,
            "status":                          self.status,
        }


# ─── Confidence helpers (operate on the bucketed dict) ───────────────────────


def _bucket_avg(buckets: Mapping[str, int]) -> float:
    """Return the volume-weighted midpoint average of bucketed confidence.

    Buckets follow the ``<0.50`` / ``0.50-0.65`` / ``0.65-0.80`` /
    ``0.80-0.95`` / ``>=0.95`` schema from ``evidence_throughput``.
    """
    midpoints = {
        "<0.50":      0.25,
        "0.50-0.65":  0.575,
        "0.65-0.80":  0.725,
        "0.80-0.95":  0.875,
        ">=0.95":     0.975,
    }
    total = 0
    weighted = 0.0
    for label, count in (buckets or {}).items():
        c = int(count) if isinstance(count, (int, float)) else 0
        if c <= 0:
            continue
        mid = midpoints.get(label, 0.5)
        total += c
        weighted += c * mid
    if total <= 0:
        return 0.0
    return round(weighted / total, 6)


def _low_confidence_ratio(buckets: Mapping[str, int]) -> float:
    total = sum(int(v) for v in (buckets or {}).values()
                if isinstance(v, (int, float)) and v > 0)
    if total <= 0:
        return 0.0
    low = int((buckets or {}).get("<0.50", 0))
    return round(low / total, 6)


# ─── Record construction ─────────────────────────────────────────────────────


def _build_record(throughput: StrategyThroughput) -> DensityRecord:
    raw = int(throughput.raw_signals_count)
    accepted = int(throughput.accepted_count)
    rejected = int(throughput.rejected_count)
    observe = int(throughput.observe_only_count)
    rec = DensityRecord(
        strategy=_safe_str(throughput.strategy) or "unknown",
        raw_signal_count=raw,
        accepted_count=accepted,
        rejected_count=rejected,
        observe_only_count=observe,
        shadow_paper_fills=int(throughput.shadow_paper_fills),
        broker_paper_fills=int(throughput.broker_paper_fills),
        symbol_coverage=int(throughput.symbol_coverage),
        regime_coverage=int(throughput.regime_coverage),
        confidence_buckets=dict(throughput.confidence_buckets),
    )

    rec.avg_confidence_score = _bucket_avg(throughput.confidence_buckets)
    rec.low_confidence_ratio = _low_confidence_ratio(
        throughput.confidence_buckets)
    rec.rejection_ratio = (
        round(rejected / raw, 6) if raw > 0 else 0.0
    )

    # Approximate accepted_avg_confidence_score by assuming accepted
    # signals skew to the upper buckets when their share matches the
    # ALLOW band; this is a deterministic best-effort proxy because the
    # opportunity ledger does not split confidence buckets by decision.
    if accepted > 0 and raw > 0:
        # Upper-band volume (>=0.65) acts as proxy for accepted quality.
        upper_total = sum(
            int(v) for k, v in (throughput.confidence_buckets or {}).items()
            if k in ("0.65-0.80", "0.80-0.95", ">=0.95")
            and isinstance(v, (int, float)) and v > 0
        )
        if upper_total > 0:
            num = (
                0.725 * int(throughput.confidence_buckets.get(
                    "0.65-0.80", 0))
                + 0.875 * int(throughput.confidence_buckets.get(
                    "0.80-0.95", 0))
                + 0.975 * int(throughput.confidence_buckets.get(
                    ">=0.95", 0))
            )
            rec.accepted_avg_confidence_score = round(num / upper_total, 6)
        else:
            rec.accepted_avg_confidence_score = rec.avg_confidence_score
    return rec


# ─── Status classifier ───────────────────────────────────────────────────────


def classify_density_status(record: DensityRecord) -> str:
    """Map a :class:`DensityRecord` to a status. Pure function.

    Order matters — first rule wins.
    """
    raw = record.raw_signal_count
    fills = record.shadow_paper_fills + record.broker_paper_fills

    # 1. Fully dead.
    if raw < MIN_SIGNALS_NOT_DEAD and fills == 0:
        return DEAD_STRATEGY

    # 2. Too-sparse — small raw count AND no shadow/broker evidence yet.
    if raw < SPARSE_MAX_SIGNALS and (
            not SPARSE_REQUIRES_NO_FILLS or fills == 0):
        return TOO_SPARSE

    # 3. High rejection but accepted minority is high-confidence — the
    #    risk gate is correctly screening noise, but there is real
    #    edge in the accepted slice. Checked BEFORE noisy so a strategy
    #    whose risk gate is doing its job correctly is not mislabelled.
    if (record.rejection_ratio >= HIGH_REJECTION_MIN_RATIO
            and record.accepted_avg_confidence_score
                >= HIGH_REJECTION_PROMISING_MIN_CONF
            and record.accepted_count > 0):
        return HIGH_REJECTION_BUT_PROMISING

    # 4. Noisy — heavy signal volume but very low avg confidence and
    #    almost no quality-band signals (i.e. the strategy is firing
    #    lots of low-conviction noise that the gate is NOT correctly
    #    rescuing into a high-quality accepted slice).
    if (raw >= NOISY_MIN_SIGNAL_VOLUME
            and record.avg_confidence_score <= NOISY_MAX_AVG_CONFIDENCE
            and record.low_confidence_ratio
                >= NOISY_MIN_LOW_CONFIDENCE_RATIO):
        return NOISY_STRATEGY

    # 5. One-symbol OR one-regime dependence with low fill volume.
    one_symbol = record.symbol_coverage <= SINGLE_SYMBOL_THRESHOLD
    one_regime = record.regime_coverage <= SINGLE_REGIME_THRESHOLD
    if (one_symbol or one_regime) and raw < UNIVERSE_EXPAND_MIN_SIGNALS:
        return NEEDS_VARIANT_DISCOVERY

    # 6. Healthy density but symbol concentration — promote a wider
    #    universe so we don't end up with a single-name dependency.
    if (one_symbol
            and raw >= UNIVERSE_EXPAND_MIN_SIGNALS
            and record.avg_confidence_score >= 0.50):
        return NEEDS_UNIVERSE_EXPANSION

    # 7. Default: healthy density.
    return HEALTHY_DENSITY


# ─── Report ──────────────────────────────────────────────────────────────────


@dataclass
class DensityAuditReport:
    """Output of :func:`run_density_audit`."""

    generated_at: datetime
    window_days: int
    records: dict[str, DensityRecord] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "window_days":  self.window_days,
            "n_strategies": len(self.records),
            "records":      {k: v.to_dict()
                             for k, v in self.records.items()},
        }


# ─── Public API ──────────────────────────────────────────────────────────────


def run_density_audit(now: datetime | None = None,
                      *,
                      days_window: int = DEFAULT_WINDOW_DAYS,
                      dirs: Mapping[str, Path | str] | None = None,
                      throughput_report: ThroughputReport | None = None,
                      emit_audit: bool = True,
                      ) -> DensityAuditReport:
    """Run the density audit, emitting one audit line per strategy.

    Parameters
    ----------
    now : datetime, optional
        End of the aggregation window. Default: ``datetime.now(UTC)``.
    days_window : int
        Days back from ``now`` to aggregate.
    dirs : mapping, optional
        Override the four input directories used by the underlying
        throughput aggregation. Useful for tests.
    throughput_report : ThroughputReport, optional
        Pre-computed throughput report (avoids re-reading the ledgers
        when callers already have one).
    emit_audit : bool
        When True (default), each status assignment is appended to the
        audit log as ``V321_SIGNAL_DENSITY_AUDIT``.

    Returns
    -------
    DensityAuditReport
    """
    if now is None:
        now = _utc_now()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = max(1, int(days_window))

    if throughput_report is None:
        throughput_report = compute_throughput(
            now=now, days_window=days, dirs=dirs)

    report = DensityAuditReport(generated_at=now, window_days=days)

    for strategy, agg in throughput_report.strategies.items():
        rec = _build_record(agg)
        rec.status = classify_density_status(rec)
        report.records[strategy] = rec
        if emit_audit:
            _emit_density_audit(
                strategy=strategy,
                status=rec.status,
                payload_extra={
                    "raw_signal_count":              rec.raw_signal_count,
                    "accepted_count":                rec.accepted_count,
                    "rejected_count":                rec.rejected_count,
                    "shadow_paper_fills":            rec.shadow_paper_fills,
                    "broker_paper_fills":            rec.broker_paper_fills,
                    "symbol_coverage":               rec.symbol_coverage,
                    "regime_coverage":               rec.regime_coverage,
                    "avg_confidence_score":          rec.avg_confidence_score,
                    "rejection_ratio":               rec.rejection_ratio,
                    "low_confidence_ratio":          rec.low_confidence_ratio,
                    "accepted_avg_confidence_score":
                        rec.accepted_avg_confidence_score,
                },
            )
    return report


__all__ = [
    # statuses
    "DEAD_STRATEGY",
    "TOO_SPARSE",
    "NOISY_STRATEGY",
    "HEALTHY_DENSITY",
    "HIGH_REJECTION_BUT_PROMISING",
    "NEEDS_VARIANT_DISCOVERY",
    "NEEDS_UNIVERSE_EXPANSION",
    "DENSITY_STATUSES",
    # thresholds
    "MIN_SIGNALS_NOT_DEAD",
    "SPARSE_MAX_SIGNALS",
    "NOISY_MIN_SIGNAL_VOLUME",
    "NOISY_MAX_AVG_CONFIDENCE",
    "NOISY_MIN_LOW_CONFIDENCE_RATIO",
    "HIGH_REJECTION_MIN_RATIO",
    "HIGH_REJECTION_PROMISING_MIN_CONF",
    "SINGLE_SYMBOL_THRESHOLD",
    "SINGLE_REGIME_THRESHOLD",
    "UNIVERSE_EXPAND_MIN_SIGNALS",
    # dataclasses + API
    "DensityRecord",
    "DensityAuditReport",
    "classify_density_status",
    "run_density_audit",
]

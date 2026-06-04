"""v3.21.0 (2026-06-04) — ETAP 1 — Evidence Throughput Monitor.

WHY
---
Audit board 2026-06-02 + 2026-06-04 reaffirmed that the system has the
plumbing for paper evidence (ETAP 4/5 v3.19, ETAP 1-9 v3.20) but does
not yet measure WHETHER evidence is actually flowing fast enough per
strategy. Strategy Quality Gate needs ``n ≥ 50`` closed paper trades
before it can promote anything to ``ENABLED``. Without measuring the
*rate* at which signals are being recorded — across all four evidence
sources (opportunity ledger, shadow ledger, paper experiments,
counterfactual outcomes) — we cannot tell whether a strategy is on
track to reach ``n=50`` in the operator's expected timeframe, or stuck
in a no-signal regime that needs intervention.

CONTRACT (do-not-cross lines)
-----------------------------
* READ-ONLY. This module never places trades, never mutates strategy
  state, never changes a risk threshold, never flips
  ``EDGE_GATE_ENABLED``, and never auto-disables a strategy. It only
  aggregates files that other modules have already written.
* No mixing of evidence sources. SHADOW / COUNTERFACTUAL / BACKTEST /
  REPLAY counts are reported separately from BROKER_PAPER counts.
  Downstream consumers (Strategy Quality Gate) keep treating those as
  triage-only; the throughput counters preserve that separation.
* Fail-soft. Missing or malformed files NEVER raise. We return a
  ``StrategyThroughput`` with status ``NO_EVIDENCE_FLOW`` for that
  strategy and continue.
* Free operation. Pure stdlib. No paid APIs. No network. No new SDKs.
* Audit emit per ``classify_status`` call is INTENTIONALLY NOT done in
  this read-only module — it is left to ``signal_density_audit`` so
  the same status is not emitted twice (throughput + density both run
  the same daily job). Throughput is the underlying numeric layer.

PUBLIC API
----------
``compute_throughput(now=None, *, days_window=14, dirs=None)``
    Returns ``ThroughputReport`` aggregating all ledgers in the window.

``StrategyThroughput.classify_status(...)``
    Returns one of ``THROUGHPUT_STATUSES``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Status enum (closed) ─────────────────────────────────────────────────────

# Statuses governed by Strategy Quality Gate review; this module only
# reports them — it never acts on them.
NO_EVIDENCE_FLOW              = "NO_EVIDENCE_FLOW"
TOO_SLOW_TO_REACH_N50         = "TOO_SLOW_TO_REACH_N50"
HEALTHY_SHADOW_FLOW           = "HEALTHY_SHADOW_FLOW"
HEALTHY_BROKER_PAPER_FLOW     = "HEALTHY_BROKER_PAPER_FLOW"
NEEDS_MORE_SYMBOLS            = "NEEDS_MORE_SYMBOLS"
NEEDS_MORE_SIGNAL_DENSITY     = "NEEDS_MORE_SIGNAL_DENSITY"
NEEDS_MORE_REGIME_COVERAGE    = "NEEDS_MORE_REGIME_COVERAGE"

THROUGHPUT_STATUSES: frozenset[str] = frozenset({
    NO_EVIDENCE_FLOW,
    TOO_SLOW_TO_REACH_N50,
    HEALTHY_SHADOW_FLOW,
    HEALTHY_BROKER_PAPER_FLOW,
    NEEDS_MORE_SYMBOLS,
    NEEDS_MORE_SIGNAL_DENSITY,
    NEEDS_MORE_REGIME_COVERAGE,
})


# ─── Thresholds (exported for tests + audit board review) ────────────────────

DEFAULT_WINDOW_DAYS                   = 14
MIN_GROWTH_PER_DAY_FOR_HEALTHY        = 1.0    # ≥ 1 sample/day on average
MIN_GROWTH_PER_DAY_FOR_HEALTHY_BROKER = 0.5    # broker_paper grows ≈ 1 / 2d
TARGET_SAMPLE_SIZE                    = 50     # Strategy Quality Gate n=50
MAX_DAYS_TO_N50                       = 120    # 4 months max — else TOO_SLOW
MIN_SYMBOLS_FOR_DIVERSE               = 2
MIN_REGIMES_FOR_DIVERSE               = 2
STALE_STRATEGY_DAYS                   = 7
CONFIDENCE_BUCKET_MIN_SAMPLES         = 10
DEFAULT_CONFIDENCE_BUCKET_EDGES       = (0.50, 0.65, 0.80, 0.95)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        s = ts.rstrip("Z")
        # Drop microseconds beyond 6 digits if any.
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _confidence_bucket(score: float,
                       edges: Sequence[float] = DEFAULT_CONFIDENCE_BUCKET_EDGES
                       ) -> str:
    """Map a confidence score (0..1) to a coarse bucket label.

    Buckets:
      ``<0.50`` (BLOCK band)
      ``0.50-0.65``, ``0.65-0.80``, ``0.80-0.95``, ``>=0.95``.
    """
    s = _safe_float(score)
    if s < edges[0]:
        return f"<{edges[0]:.2f}"
    for i in range(len(edges) - 1):
        if s < edges[i + 1]:
            return f"{edges[i]:.2f}-{edges[i + 1]:.2f}"
    return f">={edges[-1]:.2f}"


# ─── Directory resolution (overridable for tests) ────────────────────────────


def _opportunity_dir() -> Path:
    return Path(os.environ.get("OPPORTUNITY_LEDGER_DIR")
                or _REPO_ROOT / "learning-loop" / "opportunity_ledger")


def _shadow_dir() -> Path:
    return Path(os.environ.get("SHADOW_LEDGER_DIR")
                or _REPO_ROOT / "learning-loop" / "shadow_ledger")


def _paper_dir() -> Path:
    return Path(os.environ.get("PAPER_EXPERIMENT_DIR")
                or _REPO_ROOT / "learning-loop" / "paper_experiments")


def _counterfactual_audit_dir() -> Path:
    # Counterfactual outcomes are written by ``shared.counterfactual_outcomes``
    # via ``shared.audit.write_audit_event`` to journal/autonomy/<date>.jsonl
    # with ``decision == "V320_COUNTERFACTUAL_COMPUTED"``. We re-scan that
    # JSONL stream here. Overridable via env for tests.
    return Path(os.environ.get("AUDIT_TRADING_DIR")
                or _REPO_ROOT / "journal" / "autonomy")


def _resolve_dirs(dirs: Mapping[str, Path | str] | None
                  ) -> dict[str, Path]:
    """Resolve effective input directories. Test-friendly override hook."""
    eff = {
        "opportunity":    _opportunity_dir(),
        "shadow":         _shadow_dir(),
        "paper":          _paper_dir(),
        "counterfactual": _counterfactual_audit_dir(),
    }
    if dirs:
        for k, v in dirs.items():
            if k in eff and v is not None:
                eff[k] = Path(v)
    return eff


# ─── JSONL reader (fail-soft) ────────────────────────────────────────────────


def _read_jsonl_in_window(directory: Path,
                          start: datetime,
                          end: datetime,
                          ) -> list[dict]:
    """Read all JSONL records in [start, end] from ``directory``.

    ``directory`` is expected to follow the ``<date>.jsonl`` naming
    convention used by all v3.19/v3.20 evidence modules. Files that
    fall outside the window are skipped without parsing. Files that
    are malformed are silently dropped (we never raise).
    """
    out: list[dict] = []
    if not directory.exists() or not directory.is_dir():
        return out
    cur = start.date()
    end_d = end.date()
    while cur <= end_d:
        path = directory / f"{cur.isoformat()}.jsonl"
        cur = cur + timedelta(days=1)
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return out


# ─── Per-strategy aggregator state ───────────────────────────────────────────


@dataclass
class StrategyThroughput:
    """Per-strategy throughput aggregate.

    Counts are kept SEPARATE per evidence source. Downstream callers
    must not collapse SHADOW / COUNTERFACTUAL / BROKER_PAPER into one
    bucket — that mixing is explicitly forbidden by the v3.20 contract.
    """

    strategy: str
    raw_signals_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    observe_only_count: int = 0
    shadow_paper_fills: int = 0
    broker_paper_fills: int = 0
    counterfactual_outcomes: int = 0
    unknown_outcomes: int = 0
    symbols: set[str] = field(default_factory=set)
    regimes: set[str] = field(default_factory=set)
    confidence_buckets: dict[str, int] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    days_with_signal: set[str] = field(default_factory=set)

    # Derived (filled in by ``finalize``).
    strategy_sample_growth_rate: float = 0.0          # samples/day
    broker_growth_rate: float = 0.0                    # broker_paper / day
    shadow_growth_rate: float = 0.0                    # shadow_paper / day
    estimated_days_to_n50: float | None = None
    confidence_bucket_coverage: float = 0.0            # 0..1
    regime_coverage: int = 0
    symbol_coverage: int = 0
    stale_strategy_flag: bool = False
    under_sampled_regime_flag: bool = False
    status: str = NO_EVIDENCE_FLOW

    # ─── Mutators (used by compute_throughput) ────────────────────────

    def _bump_confidence(self, score: Any) -> None:
        s = _safe_float(score, default=-1.0)
        if s < 0:
            return
        bucket = _confidence_bucket(s)
        self.confidence_buckets[bucket] = (
            self.confidence_buckets.get(bucket, 0) + 1)

    def _bump_symbol(self, symbol: Any) -> None:
        s = _safe_str(symbol).strip()
        if s and s != "?":
            self.symbols.add(s)

    def _bump_regime(self, regime: Any) -> None:
        s = _safe_str(regime).strip()
        if s and s.lower() not in ("", "none", "null", "?"):
            self.regimes.add(s)

    def _record_timestamp(self, ts: datetime | None) -> None:
        if ts is None:
            return
        if self.first_seen is None or ts < self.first_seen:
            self.first_seen = ts
        if self.last_seen is None or ts > self.last_seen:
            self.last_seen = ts
        self.days_with_signal.add(ts.date().isoformat())

    # ─── Finalization ─────────────────────────────────────────────────

    def finalize(self,
                 *,
                 now: datetime,
                 window_days: int,
                 target_n: int = TARGET_SAMPLE_SIZE) -> None:
        """Compute derived metrics + classify status. No I/O."""
        window_days = max(1, int(window_days))

        # Total "samples" that count toward n=50 = BROKER_PAPER fills only.
        # We do NOT count shadow / counterfactual / accepted signals here —
        # the constraint is to never mix evidence sources.
        broker_samples = self.broker_paper_fills
        total_samples_seen = (
            self.broker_paper_fills
            + self.shadow_paper_fills
            + self.counterfactual_outcomes
        )

        # Growth rates per day (over the configured window).
        self.strategy_sample_growth_rate = round(
            total_samples_seen / window_days, 6)
        self.broker_growth_rate = round(
            broker_samples / window_days, 6)
        self.shadow_growth_rate = round(
            self.shadow_paper_fills / window_days, 6)

        # Days-to-N50 extrapolation (uses BROKER_PAPER fills only — the
        # only evidence source the Strategy Quality Gate counts).
        if broker_samples >= target_n:
            self.estimated_days_to_n50 = 0.0
        elif self.broker_growth_rate > 0:
            remaining = max(0, target_n - broker_samples)
            self.estimated_days_to_n50 = round(
                remaining / self.broker_growth_rate, 2)
        else:
            self.estimated_days_to_n50 = None

        # Coverage metrics.
        self.symbol_coverage = len(self.symbols)
        self.regime_coverage = len(self.regimes)

        # Confidence bucket coverage: % of buckets with ≥ 10 samples.
        all_buckets = self._possible_confidence_buckets()
        if all_buckets:
            covered = sum(
                1 for b in all_buckets
                if self.confidence_buckets.get(b, 0)
                   >= CONFIDENCE_BUCKET_MIN_SAMPLES
            )
            self.confidence_bucket_coverage = round(
                covered / len(all_buckets), 6)

        # Staleness flag.
        if self.last_seen is None:
            self.stale_strategy_flag = True
        else:
            age_days = (now - self.last_seen).total_seconds() / 86400.0
            self.stale_strategy_flag = age_days >= STALE_STRATEGY_DAYS

        # Under-sampled regime flag.
        self.under_sampled_regime_flag = (
            self.regime_coverage < MIN_REGIMES_FOR_DIVERSE
        )

        self.status = self.classify_status()

    # ─── Status classifier ────────────────────────────────────────────

    def classify_status(self) -> str:
        """Map this strategy's derived metrics to a throughput status.

        Spec order:
          1. NO_EVIDENCE_FLOW       — no signals at all (or fully stale).
          2. NEEDS_MORE_REGIME_COVERAGE — only one regime observed.
          3. NEEDS_MORE_SYMBOLS     — only one symbol observed.
          4. HEALTHY_BROKER_PAPER_FLOW — broker_paper growth ≥ threshold.
          5. HEALTHY_SHADOW_FLOW    — shadow growth ≥ threshold.
          6. TOO_SLOW_TO_REACH_N50  — extrapolation > MAX_DAYS_TO_N50.
          7. NEEDS_MORE_SIGNAL_DENSITY — fallback for low-but-existing flow.
        """
        if (self.raw_signals_count == 0
                and self.shadow_paper_fills == 0
                and self.broker_paper_fills == 0
                and self.counterfactual_outcomes == 0):
            return NO_EVIDENCE_FLOW
        if self.stale_strategy_flag and self.raw_signals_count == 0:
            return NO_EVIDENCE_FLOW

        if (self.broker_paper_fills + self.shadow_paper_fills) > 0:
            if self.regime_coverage < MIN_REGIMES_FOR_DIVERSE:
                return NEEDS_MORE_REGIME_COVERAGE
            if self.symbol_coverage < MIN_SYMBOLS_FOR_DIVERSE:
                return NEEDS_MORE_SYMBOLS
        else:
            # Only counterfactual / raw signals — coverage gates fire too.
            if self.symbol_coverage < MIN_SYMBOLS_FOR_DIVERSE:
                return NEEDS_MORE_SYMBOLS
            if self.regime_coverage < MIN_REGIMES_FOR_DIVERSE:
                return NEEDS_MORE_REGIME_COVERAGE

        if self.broker_growth_rate >= MIN_GROWTH_PER_DAY_FOR_HEALTHY_BROKER:
            return HEALTHY_BROKER_PAPER_FLOW
        if self.shadow_growth_rate >= MIN_GROWTH_PER_DAY_FOR_HEALTHY:
            return HEALTHY_SHADOW_FLOW

        if (self.estimated_days_to_n50 is not None
                and self.estimated_days_to_n50 > MAX_DAYS_TO_N50):
            return TOO_SLOW_TO_REACH_N50
        if self.estimated_days_to_n50 is None and self.broker_growth_rate == 0:
            return TOO_SLOW_TO_REACH_N50

        return NEEDS_MORE_SIGNAL_DENSITY

    # ─── Misc helpers ─────────────────────────────────────────────────

    def _possible_confidence_buckets(self) -> list[str]:
        edges = DEFAULT_CONFIDENCE_BUCKET_EDGES
        buckets = [f"<{edges[0]:.2f}"]
        for i in range(len(edges) - 1):
            buckets.append(f"{edges[i]:.2f}-{edges[i + 1]:.2f}")
        buckets.append(f">={edges[-1]:.2f}")
        return buckets

    def to_dict(self) -> dict:
        return {
            "strategy":                            self.strategy,
            "raw_signals_count":                   self.raw_signals_count,
            "accepted_count":                      self.accepted_count,
            "rejected_count":                      self.rejected_count,
            "observe_only_count":                  self.observe_only_count,
            "shadow_paper_fills":                  self.shadow_paper_fills,
            "broker_paper_fills":                  self.broker_paper_fills,
            "counterfactual_outcomes":             self.counterfactual_outcomes,
            "unknown_outcomes":                    self.unknown_outcomes,
            "strategy_sample_growth_rate":         self.strategy_sample_growth_rate,
            "broker_growth_rate":                  self.broker_growth_rate,
            "shadow_growth_rate":                  self.shadow_growth_rate,
            "estimated_days_to_n50":               self.estimated_days_to_n50,
            "confidence_bucket_coverage":          self.confidence_bucket_coverage,
            "regime_coverage":                     self.regime_coverage,
            "symbol_coverage":                     self.symbol_coverage,
            "stale_strategy_flag":                 self.stale_strategy_flag,
            "under_sampled_regime_flag":           self.under_sampled_regime_flag,
            "symbols":                             sorted(self.symbols),
            "regimes":                             sorted(self.regimes),
            "confidence_buckets":                  dict(self.confidence_buckets),
            "first_seen":                          (self.first_seen.isoformat()
                                                    if self.first_seen else None),
            "last_seen":                           (self.last_seen.isoformat()
                                                    if self.last_seen else None),
            "days_with_signal":                    len(self.days_with_signal),
            "status":                              self.status,
        }


# ─── Top-level report ────────────────────────────────────────────────────────


@dataclass
class ThroughputReport:
    """Aggregated throughput across all strategies in the window."""

    window_start: datetime
    window_end:   datetime
    window_days:  int
    strategies:   dict[str, StrategyThroughput] = field(default_factory=dict)
    raw_signal_total:  int = 0
    shadow_total:      int = 0
    broker_total:      int = 0
    counterfactual_total: int = 0
    unknown_total:     int = 0

    def to_dict(self) -> dict:
        return {
            "window_start":         self.window_start.isoformat(),
            "window_end":           self.window_end.isoformat(),
            "window_days":          self.window_days,
            "strategy_count":       len(self.strategies),
            "raw_signal_total":     self.raw_signal_total,
            "shadow_total":         self.shadow_total,
            "broker_total":         self.broker_total,
            "counterfactual_total": self.counterfactual_total,
            "unknown_total":        self.unknown_total,
            "strategies":           {k: v.to_dict()
                                     for k, v in self.strategies.items()},
        }


# ─── Per-record consumers ────────────────────────────────────────────────────


def _consume_opportunity(rec: dict,
                         agg_map: dict[str, StrategyThroughput],
                         ) -> None:
    strategy = _safe_str(rec.get("strategy")) or "unknown"
    agg = agg_map.get(strategy)
    if agg is None:
        agg = StrategyThroughput(strategy=strategy)
        agg_map[strategy] = agg
    agg.raw_signals_count += 1
    decision = _safe_str(rec.get("risk_decision")).upper()
    if decision in ("ALLOW", "APPROVE", "APPROVE_ENTRY"):
        agg.accepted_count += 1
    elif decision in ("ALERT_ONLY", "DOWNSIZE", "OBSERVE", "OBSERVE_ONLY"):
        agg.observe_only_count += 1
    elif decision in ("BLOCK", "REJECT", "REJECT_ENTRY", "DEFER"):
        agg.rejected_count += 1
    else:
        # Unknown decision still counts as raw signal — don't double-count.
        pass
    agg._bump_symbol(rec.get("symbol"))
    agg._bump_regime(rec.get("market_regime"))
    agg._bump_confidence(rec.get("confidence_score"))
    agg._record_timestamp(_parse_iso(rec.get("timestamp")))


def _consume_shadow(rec: dict,
                    agg_map: dict[str, StrategyThroughput],
                    ) -> None:
    # Shadow ledger records may use ``execution_source == SHADOW_SIM``
    # but always carry strategy + symbol + timestamp.
    strategy = _safe_str(rec.get("strategy")) or "unknown"
    agg = agg_map.get(strategy)
    if agg is None:
        agg = StrategyThroughput(strategy=strategy)
        agg_map[strategy] = agg
    agg.shadow_paper_fills += 1
    agg._bump_symbol(rec.get("symbol"))
    agg._bump_regime(rec.get("market_regime") or rec.get("regime"))
    agg._bump_confidence(rec.get("confidence_score"))
    agg._record_timestamp(_parse_iso(rec.get("ts")
                                     or rec.get("timestamp")))


def _consume_paper(rec: dict,
                   agg_map: dict[str, StrategyThroughput],
                   ) -> None:
    src = _safe_str(rec.get("evidence_source")
                    or rec.get("source")).upper()
    # Only count records actually tagged PAPER. BACKTEST / REPLAY /
    # COUNTERFACTUAL records that may live in the same tree are NEVER
    # mixed into the broker total.
    if src and src not in ("PAPER", "BROKER_PAPER", "PAPER_BROKER"):
        return
    strategy = _safe_str(rec.get("strategy")) or "unknown"
    agg = agg_map.get(strategy)
    if agg is None:
        agg = StrategyThroughput(strategy=strategy)
        agg_map[strategy] = agg
    agg.broker_paper_fills += 1
    agg._bump_symbol(rec.get("symbol"))
    agg._bump_regime(rec.get("regime") or rec.get("market_regime"))
    agg._bump_confidence(rec.get("confidence_score"))
    agg._record_timestamp(_parse_iso(rec.get("closed_at")
                                     or rec.get("opened_at")
                                     or rec.get("ts")))


def _consume_counterfactual(rec: dict,
                            agg_map: dict[str, StrategyThroughput],
                            ) -> None:
    # The counterfactual engine writes audit lines via
    # ``write_audit_event`` to journal/autonomy/<date>.jsonl. We filter
    # on the canonical decision tag emitted by ETAP 3.
    decision = _safe_str(rec.get("decision")
                         or rec.get("event_type")).upper()
    if decision != "V320_COUNTERFACTUAL_COMPUTED":
        return
    payload = rec.get("payload") or rec
    strategy = _safe_str(payload.get("strategy")) or "unknown"
    agg = agg_map.get(strategy)
    if agg is None:
        agg = StrategyThroughput(strategy=strategy)
        agg_map[strategy] = agg
    outcome = _safe_str(payload.get("outcome")).upper()
    if outcome == "UNKNOWN":
        agg.unknown_outcomes += 1
    else:
        agg.counterfactual_outcomes += 1
    agg._bump_symbol(payload.get("symbol"))
    agg._record_timestamp(_parse_iso(payload.get("ts")
                                     or rec.get("ts")))


# ─── Top-level API ───────────────────────────────────────────────────────────


def compute_throughput(now: datetime | None = None,
                       *,
                       days_window: int = DEFAULT_WINDOW_DAYS,
                       dirs: Mapping[str, Path | str] | None = None,
                       ) -> ThroughputReport:
    """Build a ``ThroughputReport`` over the ``days_window`` ending at ``now``.

    Parameters
    ----------
    now : datetime, optional
        End of the aggregation window. Defaults to ``datetime.now(UTC)``.
        Must be timezone-aware; naive datetimes are coerced to UTC.
    days_window : int
        Number of days back from ``now`` to scan. Must be ≥ 1.
    dirs : mapping, optional
        Test-friendly override of the four input directories
        (``opportunity`` / ``shadow`` / ``paper`` / ``counterfactual``).

    Returns
    -------
    ThroughputReport
        Aggregated per-strategy throughput. Never raises; missing
        files yield zero counts.
    """
    if now is None:
        now = _utc_now()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = max(1, int(days_window))
    start = now - timedelta(days=days)

    eff = _resolve_dirs(dirs)
    report = ThroughputReport(
        window_start=start, window_end=now, window_days=days)

    agg_map: dict[str, StrategyThroughput] = {}

    # 1. Opportunity ledger — raw signals (accepted + rejected + observe).
    for rec in _read_jsonl_in_window(eff["opportunity"], start, now):
        _consume_opportunity(rec, agg_map)
        report.raw_signal_total += 1

    # 2. Shadow paper ledger.
    for rec in _read_jsonl_in_window(eff["shadow"], start, now):
        _consume_shadow(rec, agg_map)
        report.shadow_total += 1

    # 3. Paper experiments (BROKER_PAPER source only).
    for rec in _read_jsonl_in_window(eff["paper"], start, now):
        before = sum(a.broker_paper_fills for a in agg_map.values())
        _consume_paper(rec, agg_map)
        after = sum(a.broker_paper_fills for a in agg_map.values())
        report.broker_total += (after - before)

    # 4. Counterfactual outcomes — read from the audit JSONL stream.
    for rec in _read_jsonl_in_window(eff["counterfactual"], start, now):
        before_cf = sum(a.counterfactual_outcomes for a in agg_map.values())
        before_un = sum(a.unknown_outcomes for a in agg_map.values())
        _consume_counterfactual(rec, agg_map)
        after_cf = sum(a.counterfactual_outcomes for a in agg_map.values())
        after_un = sum(a.unknown_outcomes for a in agg_map.values())
        report.counterfactual_total += (after_cf - before_cf)
        report.unknown_total += (after_un - before_un)

    # Finalize every strategy.
    for agg in agg_map.values():
        agg.finalize(now=now, window_days=days)

    report.strategies = agg_map
    return report


# ─── Convenience: get one strategy ───────────────────────────────────────────


def strategy_throughput(strategy: str,
                        *,
                        now: datetime | None = None,
                        days_window: int = DEFAULT_WINDOW_DAYS,
                        dirs: Mapping[str, Path | str] | None = None,
                        ) -> StrategyThroughput | None:
    """Return the ``StrategyThroughput`` for ``strategy``, or None if absent."""
    rep = compute_throughput(now=now, days_window=days_window, dirs=dirs)
    return rep.strategies.get(strategy)


__all__ = [
    # statuses
    "NO_EVIDENCE_FLOW",
    "TOO_SLOW_TO_REACH_N50",
    "HEALTHY_SHADOW_FLOW",
    "HEALTHY_BROKER_PAPER_FLOW",
    "NEEDS_MORE_SYMBOLS",
    "NEEDS_MORE_SIGNAL_DENSITY",
    "NEEDS_MORE_REGIME_COVERAGE",
    "THROUGHPUT_STATUSES",
    # thresholds
    "DEFAULT_WINDOW_DAYS",
    "MIN_GROWTH_PER_DAY_FOR_HEALTHY",
    "MIN_GROWTH_PER_DAY_FOR_HEALTHY_BROKER",
    "TARGET_SAMPLE_SIZE",
    "MAX_DAYS_TO_N50",
    "MIN_SYMBOLS_FOR_DIVERSE",
    "MIN_REGIMES_FOR_DIVERSE",
    "STALE_STRATEGY_DAYS",
    "CONFIDENCE_BUCKET_MIN_SAMPLES",
    # dataclasses
    "StrategyThroughput",
    "ThroughputReport",
    # API
    "compute_throughput",
    "strategy_throughput",
]

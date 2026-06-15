"""v3.24 (2026-06-15) — Near-miss tracker (ETAP 10).

WHY
---
A strict gate that NEVER fires is indistinguishable from a broken
strategy: in both cases the operator sees zero shadow-eligible rows.
This module captures evidence that, while the gate did not fire, the
underlying metric came WITHIN some distance of triggering. A
"near miss" — never a trade, never a shadow fill, never an outcome.

Rows look like::

    NearMiss(
        strategy_id="crypto-momentum",
        symbol="BTC/USD",
        metric_name="rsi",
        current_value=49.8,
        threshold=50.0,
        distance_to_trigger=-0.2,
        timestamp_iso="2026-06-15T12:00:00+00:00",
        is_paper_trade=False,
        is_signal=False,
    )

The aggregate report flags strategies whose 95th-percentile distance
is FAR from the threshold ("threshold may be too strict — operator
review"). The flag is purely advisory; this module NEVER auto-adjusts
a threshold.

HARD SAFETY INVARIANTS (test-asserted)
--------------------------------------
- NEVER imports ``shared.alpaca_orders``.
- NEVER makes network calls.
- ``is_paper_trade`` is hard-coded to ``False`` on every record.
- ``is_signal`` is hard-coded to ``False`` on every record.
- NEVER auto-adjusts a strategy threshold; it can only flag.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Defensive invariants — used by the static test.
NEVER_SUBMITS_ORDERS         = True
NEVER_IMPORTS_ALPACA_ORDERS  = True
NEVER_COUNTS_AS_TRADE        = True
NEVER_COUNTS_AS_SIGNAL       = True
NEVER_AUTO_ADJUSTS_THRESHOLD = True

# Module-level version stamp so consumers can pin behaviour.
NEAR_MISS_VERSION = "v3.24.0"


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Data class ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NearMiss:
    strategy_id: str
    symbol: str
    metric_name: str
    current_value: float
    threshold: float
    distance_to_trigger: float
    timestamp_iso: str
    is_paper_trade: bool = False   # invariant: always False
    is_signal: bool = False        # invariant: always False

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Storage helpers ──────────────────────────────────────────────────────────


def _default_dir() -> Path:
    base = (
        os.environ.get("NEAR_MISS_DIR")
        or _REPO_ROOT / "learning-loop" / "near_miss"
    )
    return Path(base)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_float(x: Any, default: float | None = None) -> float | None:
    if x is None:
        return default
    try:
        v = float(x)
        if v != v:    # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


# ─── Public API ───────────────────────────────────────────────────────────────


def record_near_miss(
    strategy_id: str,
    symbol: str,
    metric_name: str,
    current_value: float | int,
    threshold: float | int,
    *,
    path: str | Path | None = None,
    timestamp_iso: str | None = None,
) -> dict:
    """Append a single NearMiss record to the daily JSONL.

    Never raises on filesystem errors — callers are entry-monitors and
    must not be blocked by audit-write failures. Returns the dict that
    was written (or would have been written) for traceability.

    ``current_value`` and ``threshold`` are coerced to float; NaN or
    non-numeric values short-circuit to a no-op record (still
    persisted with default values for traceability).
    """
    cv = _safe_float(current_value, default=0.0) or 0.0
    th = _safe_float(threshold, default=0.0) or 0.0
    dist = cv - th
    ts = timestamp_iso or _utc_now_iso()

    record = NearMiss(
        strategy_id=str(strategy_id or "unknown"),
        symbol=str(symbol or "unknown"),
        metric_name=str(metric_name or "unknown"),
        current_value=float(cv),
        threshold=float(th),
        distance_to_trigger=float(dist),
        timestamp_iso=str(ts),
        is_paper_trade=False,   # HARD invariant
        is_signal=False,        # HARD invariant
    )

    target_dir: Path
    target_file: Path
    if path is None:
        target_dir = _default_dir()
        target_file = target_dir / f"{_utc_today_iso()}.jsonl"
    else:
        target_file = Path(path)
        target_dir = target_file.parent

    payload = record.to_dict()
    try:
        _ensure_dir(target_dir)
        with target_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception:
        # never raise — fail-soft per HARD safety
        pass

    return payload


# ─── Aggregation ──────────────────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float | None:
    """Pure-Python percentile helper (linear interp). Never uses
    third-party libs to keep zero runtime deps."""
    if not values:
        return None
    sv = sorted(values)
    if len(sv) == 1:
        return sv[0]
    k = (len(sv) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sv) - 1)
    if f == c:
        return sv[int(k)]
    d0 = sv[f] * (c - k)
    d1 = sv[c] * (k - f)
    return d0 + d1


def evaluate_threshold_realism(
    rows: Iterable[dict],
    *,
    flag_distance_ratio: float = 0.40,
    min_sample: int = 10,
) -> dict[str, Any]:
    """Aggregate near-miss rows per (strategy, metric).

    Reports the 95th-percentile of |distance_to_trigger|. If that
    percentile is FAR from zero in relative terms (default ratio
    >= 40% of |threshold|), flag the (strategy, metric) pair as
    "threshold may be too strict — operator review". The flag is
    ADVISORY only; this function NEVER adjusts a threshold.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("strategy_id") or "unknown"
        metric = row.get("metric_name") or "unknown"
        buckets.setdefault((sid, metric), []).append(row)

    by_pair: list[dict] = []
    flagged: list[dict] = []
    for (sid, metric), pair_rows in sorted(buckets.items()):
        dists = []
        thresholds = []
        for r in pair_rows:
            d = _safe_float(r.get("distance_to_trigger"))
            if d is None:
                continue
            dists.append(abs(d))
            t = _safe_float(r.get("threshold"))
            if t is not None:
                thresholds.append(abs(t))
        if not dists:
            continue
        median_thr = sorted(thresholds)[len(thresholds) // 2] if thresholds else 0.0
        p95 = _percentile(dists, 95) or 0.0
        ratio = (p95 / median_thr) if median_thr > 0 else 0.0
        info = {
            "strategy_id":        sid,
            "metric_name":        metric,
            "sample_size":        len(pair_rows),
            "p95_abs_distance":   round(float(p95), 6),
            "median_threshold":   round(float(median_thr), 6),
            "abs_distance_ratio": round(float(ratio), 4),
            "advisory_flag":      False,
            "advisory_reason":    None,
        }
        if len(pair_rows) >= min_sample and ratio >= flag_distance_ratio:
            info["advisory_flag"]   = True
            info["advisory_reason"] = (
                f"95th-percentile distance ({p95:.4f}) is "
                f"{ratio * 100:.1f}% of |threshold| "
                f"({median_thr:.4f}) — threshold may be too strict; "
                f"operator review")
            flagged.append(info)
        by_pair.append(info)

    return {
        "version":          NEAR_MISS_VERSION,
        "generated_at_iso": _utc_now_iso(),
        "pairs":            by_pair,
        "flagged":          flagged,
        "params": {
            "flag_distance_ratio": flag_distance_ratio,
            "min_sample":          min_sample,
        },
    }


# ─── Loader helper for downstream reporter ────────────────────────────────────


def load_recent_rows(
    *,
    days: int = 7,
    base_dir: str | Path | None = None,
    as_of: datetime | None = None,
) -> list[dict]:
    """Load the last ``days`` daily JSONL files of near-miss records.

    Defaults to the standard ``learning-loop/near_miss/`` location.
    Returns an empty list if no files exist.
    """
    if base_dir is None:
        base = _default_dir()
    else:
        base = Path(base_dir)
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    out: list[dict] = []
    for delta in range(days):
        d = (as_of - timedelta(days=delta)).date()
        f = base / f"{d.isoformat()}.jsonl"
        if not f.exists():
            continue
        try:
            with f.open(encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue
    return out


# ─── v3.26 (Agent 3A ETAP 3) — helper invoked by signal_emitter ──────────────
#
# Default strategy threshold map. Each entry is:
#   (metric_name, threshold, direction)
# direction == "above" -> trigger when metric > threshold;
#              "below" -> trigger when metric < threshold.
# These values mirror backtest/strategies.py constants. Source of truth
# stays in strategies.py; this map is a convenience cache for emitter-
# side near-miss detection.
DEFAULT_STRATEGY_THRESHOLD_MAP: dict[str, tuple[str, float, str]] = {
    "crypto-oversold-bounce": ("rsi",         30.0, "below"),
    "crypto-momentum":        ("rsi",         60.0, "above"),
    "momentum-long":          ("breakout_pct", 0.02, "above"),
    "momentum-long-loose":    ("breakout_pct", 0.02, "above"),
    "overbought-short":       ("rsi",         72.0, "above"),
}

# Default near-miss capture window: |distance / threshold| <= 0.15.
NEAR_MISS_WINDOW_RATIO_DEFAULT = 0.15


def _within_near_miss_window(
    current: float,
    threshold: float,
    direction: str,
    *,
    window_ratio: float,
) -> bool:
    """Return True if the metric is within the near-miss window but did
    NOT actually trigger.

    "Direction" semantics:
      "above" — trigger fires when current > threshold.
                NEAR-miss: current < threshold AND distance within ratio.
      "below" — trigger fires when current < threshold.
                NEAR-miss: current > threshold AND distance within ratio.
    """
    if threshold == 0.0:
        return False
    dist_pct = abs(current - threshold) / abs(threshold)
    if dist_pct > window_ratio:
        return False
    if direction == "above":
        # Already triggered → not a miss.
        return current < threshold
    if direction == "below":
        return current > threshold
    return False


def _extract_metric(raw_signal: Any, metric_name: str) -> float | None:
    """Pull a metric value out of the raw_signal dict, safely."""
    if not isinstance(raw_signal, dict):
        return None
    val = raw_signal.get(metric_name)
    return _safe_float(val)


def maybe_record_near_miss_from_signal_event(
    signal_event: Any,
    *,
    strategy_threshold_map: dict[str, tuple[str, float, str]] | None = None,
    window_ratio: float = NEAR_MISS_WINDOW_RATIO_DEFAULT,
    path: str | Path | None = None,
) -> dict | None:
    """If the signal_event's raw_signal carries an evaluation metric
    within ``window_ratio`` of a known strategy threshold, record a
    NearMiss. Return the persisted row, or None if no near-miss.

    HARD invariants:
      - NEVER counts as a signal, paper trade, shadow fill, or outcome.
      - NEVER raises on a malformed event — fail-soft per spec.
      - NEVER auto-adjusts a threshold; pure observation.

    Parameters
    ----------
    signal_event :
        Any object whose attributes include ``strategy_id``, ``symbol``,
        ``raw_signal`` (dict), and ``timestamp_iso``. Most commonly a
        ``shared.signal_event.SignalEvent``.
    strategy_threshold_map :
        Override the default map; helpful for tests.
    window_ratio :
        Distance bound expressed as a fraction of |threshold|.
    """
    try:
        strategy_id = getattr(signal_event, "strategy_id", "") or ""
        symbol = getattr(signal_event, "symbol", "") or ""
        raw_signal = getattr(signal_event, "raw_signal", None) or {}
        ts = getattr(signal_event, "timestamp_iso", None)
    except Exception:
        return None

    if not isinstance(strategy_id, str) or not strategy_id.strip():
        return None

    table = strategy_threshold_map or DEFAULT_STRATEGY_THRESHOLD_MAP
    if strategy_id not in table:
        return None

    metric_name, threshold, direction = table[strategy_id]
    current = _extract_metric(raw_signal, metric_name)
    if current is None:
        return None

    if not _within_near_miss_window(current, threshold, direction,
                                    window_ratio=window_ratio):
        return None

    return record_near_miss(
        strategy_id=strategy_id,
        symbol=symbol or "unknown",
        metric_name=metric_name,
        current_value=float(current),
        threshold=float(threshold),
        timestamp_iso=ts,
        path=path,
    )


__all__ = [
    "NEAR_MISS_VERSION",
    "NearMiss",
    "record_near_miss",
    "evaluate_threshold_realism",
    "load_recent_rows",
    "maybe_record_near_miss_from_signal_event",
    "DEFAULT_STRATEGY_THRESHOLD_MAP",
    "NEAR_MISS_WINDOW_RATIO_DEFAULT",
    "NEVER_SUBMITS_ORDERS",
    "NEVER_IMPORTS_ALPACA_ORDERS",
    "NEVER_COUNTS_AS_TRADE",
    "NEVER_COUNTS_AS_SIGNAL",
    "NEVER_AUTO_ADJUSTS_THRESHOLD",
]

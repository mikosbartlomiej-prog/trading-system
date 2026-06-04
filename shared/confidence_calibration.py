"""v3.19.0 (2026-06-04) — ETAP 4 — Confidence Calibration.

Builds on v3.18.0 `shared/confidence.py` (12 scoring functions producing
the 0..1 confidence number that the risk engine consumes).

WHY
---
The confidence score is only useful if it is *calibrated* — meaning
trades with higher confidence actually win more often (or earn more)
than trades with lower confidence. If the high bucket has the same WR
as the mid bucket, the score is overstating signal and the gate
threshold is meaningless.

This module reads the **paper ledger only** (per v3.19.0 ETAP 3,
backtest and replay records do NOT contribute) and reports:

- Per-bucket WR / expectancy / profit factor / max drawdown
- Whether the bucket sequence is monotonic
- Specific buckets that **overstate** (high conf → poor outcome)
- Specific buckets that **underuse** (low conf → good outcome)
- Drift vs a previously-saved calibration

The output is a deterministic dict + a local Markdown report. The
module DOES NOT mutate any thresholds. The Strategy Quality Gate reads
the calibration as one of its inputs; an operator decides whether to
adjust the confidence threshold.

CONTRACT
--------
- compute_calibration_metrics(ledger, *, source="PAPER") → dict bucket→stats
- is_calibrated(calibration, *, min_n_per_bucket=10) → (bool, rationale)
- calibration_drift(prev, curr) → float
- detect_overstatement(calibration) → list[bucket]
- detect_underuse(calibration) → list[bucket]
- generate_calibration_report(...) → (markdown_path, json_path)

Pure functions. No external API calls. Fail-soft on missing data.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Buckets ──────────────────────────────────────────────────────────────────

# (lower_inclusive, upper_exclusive_or_inclusive_for_last, name)
CONFIDENCE_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.40, "very_low"),
    (0.40, 0.50, "low"),
    (0.50, 0.65, "mid"),
    (0.65, 0.75, "high"),
    (0.75, 0.85, "very_high"),
    (0.85, 1.00, "extreme"),
)

# Ordering for monotonicity checks (low → extreme). Lower confidence
# buckets come first.
_BUCKET_ORDER: tuple[str, ...] = tuple(b[2] for b in CONFIDENCE_BUCKETS)
_BUCKET_INDEX: dict[str, int] = {n: i for i, n in enumerate(_BUCKET_ORDER)}


# ─── Safe helpers ─────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


# ─── bucket_for ───────────────────────────────────────────────────────────────


def bucket_for(confidence: Any) -> str:
    """Map a confidence in [0..1] to bucket name.

    Edge handling:
      - NaN / non-numeric → "very_low" (defensive: refuse to elevate).
      - Negative → "very_low".
      - ≥ 1.0 → "extreme" (the last bucket is inclusive of its upper bound).
      - Boundary 0.40 → "low" (lower-inclusive convention everywhere).
    """
    v = _safe_float(confidence, default=-1.0)
    if v < 0.0 or v != v:  # NaN catch belt-and-braces
        return "very_low"
    if v >= 1.0:
        return "extreme"
    for lo, hi, name in CONFIDENCE_BUCKETS:
        if lo <= v < hi:
            return name
    # Shouldn't reach here for v in [0,1) but stay defensive.
    return "very_low"


# ─── compute_calibration_metrics ─────────────────────────────────────────────


def _empty_bucket_stats() -> dict[str, Any]:
    return {
        "n": 0,
        "win_rate": 0.0,
        "expectancy": 0.0,
        "profit_factor": 0.0,
        "avg_drawdown_after_entry": 0.0,
        "false_positive_rate": 0.0,
    }


def _aggregate_bucket(records: list[dict]) -> dict[str, Any]:
    """Compute per-bucket stats from the records assigned to that bucket."""
    if not records:
        return _empty_bucket_stats()

    nets = [_safe_float(r.get("net_pnl"), 0.0) for r in records]
    n = len(nets)
    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p < 0]
    win_rate = len(wins) / n if n else 0.0

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss

    gross_wins = sum(wins)
    gross_losses = -sum(losses)
    if gross_losses > 0:
        pf = gross_wins / gross_losses
    elif gross_wins > 0:
        pf = 999.0
    else:
        pf = 0.0

    # avg drawdown after entry — best-effort: if records carry an
    # explicit per-trade drawdown number we use it, otherwise the
    # average of the per-trade absolute losses normalised by the entry
    # size as a proxy.
    dds: list[float] = []
    for r in records:
        v = r.get("max_drawdown_after_entry")
        if v is None:
            # Proxy: |net_pnl| / (entry * qty) when net_pnl < 0
            entry = _safe_float(r.get("entry"), 0.0)
            qty = _safe_float(r.get("qty"), 0.0)
            net = _safe_float(r.get("net_pnl"), 0.0)
            cost_basis = abs(entry * qty)
            if net < 0 and cost_basis > 0:
                dds.append(abs(net) / cost_basis)
        else:
            dds.append(abs(_safe_float(v, 0.0)))
    avg_dd = (sum(dds) / len(dds)) if dds else 0.0

    # false_positive_rate — interpreted as the fraction of trades that
    # both fired (i.e. record exists) AND lost money. For a "signal
    # bucket" this is exactly 1 - win_rate.
    fpr = (len([p for p in nets if p <= 0]) / n) if n else 0.0

    return {
        "n":                         n,
        "win_rate":                  round(win_rate, 6),
        "expectancy":                round(expectancy, 6),
        "profit_factor":             round(pf, 6),
        "avg_drawdown_after_entry":  round(avg_dd, 6),
        "false_positive_rate":       round(fpr, 6),
    }


def compute_calibration_metrics(ledger_entries: Iterable[dict],
                                  *, source: str = "PAPER") -> dict[str, Any]:
    """For each bucket compute: n, win_rate, expectancy, profit_factor,
    avg_drawdown_after_entry, false_positive_rate.

    Parameters
    ----------
    ledger_entries
        Iterable of trade dicts. Each dict is expected to carry at
        least ``confidence_at_entry`` (float) and ``net_pnl`` (float).
        Records missing ``confidence_at_entry`` are dropped.
    source
        Source label kept on the returned dict for traceability (this
        function does not filter on it — callers should pre-filter).

    Returns
    -------
    dict
        ``{"source": "PAPER", "buckets": {name → stats}}``. Buckets
        with n < 5 still appear but are flagged sparse — the
        monotonicity check excludes them by default.
    """
    by_bucket: dict[str, list[dict]] = {n: [] for n in _BUCKET_ORDER}
    for r in ledger_entries or []:
        if not isinstance(r, dict):
            continue
        conf = r.get("confidence_at_entry")
        if conf is None:
            continue
        b = bucket_for(conf)
        by_bucket.setdefault(b, []).append(r)

    out: dict[str, Any] = {
        "source":   str(source).upper(),
        "buckets":  {},
        "n_total":  sum(len(v) for v in by_bucket.values()),
    }
    for name in _BUCKET_ORDER:
        stats = _aggregate_bucket(by_bucket.get(name, []))
        stats["sparse"] = stats["n"] < 5
        out["buckets"][name] = stats
    return out


# ─── is_calibrated ────────────────────────────────────────────────────────────


def is_calibrated(calibration: dict[str, Any],
                  *, min_n_per_bucket: int = 10) -> tuple[bool, str]:
    """Monotonicity check.

    Higher buckets should have at least the WR (and expectancy) of any
    lower bucket. A high bucket should not have a higher false-positive
    rate than a low bucket. Buckets with n < min_n_per_bucket are
    ignored — without enough samples we cannot judge.

    Returns
    -------
    (is_calibrated, rationale)
        is_calibrated=True only when ALL pairwise comparisons hold.
        Rationale is a short human-readable explanation.
    """
    if not isinstance(calibration, dict):
        return (False, "calibration not a dict")
    buckets = calibration.get("buckets") or {}
    # Iterate in canonical order from lowest to highest.
    eligible: list[tuple[str, dict]] = []
    for name in _BUCKET_ORDER:
        stats = buckets.get(name) or {}
        if _safe_int(stats.get("n")) >= int(min_n_per_bucket):
            eligible.append((name, stats))

    if len(eligible) < 2:
        return (False, "insufficient samples — need ≥2 buckets with "
                       f"n ≥ {min_n_per_bucket}")

    # WR monotonicity: for every pair (lo, hi) with hi > lo, WR_hi >= WR_lo.
    for i, (lo_name, lo_stats) in enumerate(eligible):
        for hi_name, hi_stats in eligible[i + 1:]:
            wr_lo = _safe_float(lo_stats.get("win_rate"))
            wr_hi = _safe_float(hi_stats.get("win_rate"))
            ex_lo = _safe_float(lo_stats.get("expectancy"))
            ex_hi = _safe_float(hi_stats.get("expectancy"))
            fp_lo = _safe_float(lo_stats.get("false_positive_rate"))
            fp_hi = _safe_float(hi_stats.get("false_positive_rate"))

            if wr_hi < wr_lo:
                return (False,
                        f"bucket {hi_name} WR {wr_hi:.0%} < "
                        f"bucket {lo_name} WR {wr_lo:.0%}")
            if ex_hi < ex_lo:
                return (False,
                        f"bucket {hi_name} expectancy {ex_hi:+.4f} < "
                        f"bucket {lo_name} expectancy {ex_lo:+.4f}")
            if fp_hi > fp_lo:
                return (False,
                        f"bucket {hi_name} false-positive rate "
                        f"{fp_hi:.0%} > bucket {lo_name} {fp_lo:.0%}")

    return (True, f"monotonic across {len(eligible)} eligible buckets")


# ─── calibration_drift ───────────────────────────────────────────────────────


# Weights for the drift metric. Higher buckets get more weight because
# their behaviour drives the risk-engine threshold.
_DRIFT_WEIGHTS: dict[str, float] = {
    "very_low":   0.50,
    "low":        0.75,
    "mid":        1.00,
    "high":       1.25,
    "very_high":  1.50,
    "extreme":    1.75,
}


def calibration_drift(prev_calibration: dict[str, Any] | None,
                       curr_calibration: dict[str, Any] | None) -> float:
    """Score drift between two calibration snapshots.

    Drift = Σ_bucket weight_bucket · |curr.WR − prev.WR|. Buckets that
    are missing in either snapshot contribute 0. A drift of 0 means
    identical (or trivially close) calibrations.
    """
    if not isinstance(prev_calibration, dict) or \
       not isinstance(curr_calibration, dict):
        return 0.0
    prev_buckets = prev_calibration.get("buckets") or {}
    curr_buckets = curr_calibration.get("buckets") or {}
    total = 0.0
    for name in _BUCKET_ORDER:
        prev = prev_buckets.get(name) or {}
        curr = curr_buckets.get(name) or {}
        if not prev or not curr:
            continue
        prev_wr = _safe_float(prev.get("win_rate"))
        curr_wr = _safe_float(curr.get("win_rate"))
        w = _DRIFT_WEIGHTS.get(name, 1.0)
        total += w * abs(curr_wr - prev_wr)
    return round(total, 6)


# ─── detect_overstatement / detect_underuse ──────────────────────────────────


def detect_overstatement(calibration: dict[str, Any]) -> list[str]:
    """Find buckets where high confidence has POOR outcome.

    A "high" bucket overstates when its WR is below 0.50 OR its
    expectancy is non-positive while a lower bucket beats it. Returns
    the bucket names that overstate (canonical order).
    """
    if not isinstance(calibration, dict):
        return []
    buckets = calibration.get("buckets") or {}
    out: list[str] = []
    high_set = ("high", "very_high", "extreme")
    for name in high_set:
        stats = buckets.get(name) or {}
        if _safe_int(stats.get("n")) < 5:
            continue
        wr = _safe_float(stats.get("win_rate"))
        ex = _safe_float(stats.get("expectancy"))
        bad_absolute = wr < 0.50 or ex <= 0.0
        # Also overstates if a lower bucket actually beats it on WR.
        beat_by_lower = False
        for lo_name in ("very_low", "low", "mid"):
            lo_stats = buckets.get(lo_name) or {}
            if _safe_int(lo_stats.get("n")) < 5:
                continue
            if _safe_float(lo_stats.get("win_rate")) > wr:
                beat_by_lower = True
                break
        if bad_absolute or beat_by_lower:
            out.append(name)
    return out


def detect_underuse(calibration: dict[str, Any]) -> list[str]:
    """Find buckets where LOW confidence has GOOD outcome.

    A "low" bucket is underused when its WR ≥ 0.55 AND expectancy > 0.
    That means the scoring function should have rated the underlying
    trades higher.
    """
    if not isinstance(calibration, dict):
        return []
    buckets = calibration.get("buckets") or {}
    out: list[str] = []
    low_set = ("very_low", "low", "mid")
    for name in low_set:
        stats = buckets.get(name) or {}
        if _safe_int(stats.get("n")) < 5:
            continue
        wr = _safe_float(stats.get("win_rate"))
        ex = _safe_float(stats.get("expectancy"))
        if wr >= 0.55 and ex > 0.0:
            out.append(name)
    return out


# ─── Audit emission ──────────────────────────────────────────────────────────


def _emit_audit(payload: dict[str, Any]) -> None:
    """Emit a JSONL audit line under journal/autonomy/<date>.jsonl.

    Custom ``kind`` ("confidence_calibration") — does NOT use
    ``shared.audit.write_audit_event`` because that helper validates
    against ``DECISION_TYPES`` which is too narrow for calibration
    findings. Fail-soft: any error is swallowed.
    """
    try:
        base = Path(
            os.environ.get("AUDIT_TRADING_DIR")
            or _REPO_ROOT / "journal" / "autonomy"
        )
        base.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).date().isoformat()
        path = base / f"{today}.jsonl"
        line = json.dumps({
            "kind":       "confidence_calibration",
            "timestamp":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor":      "confidence-calibration",
            **payload,
        }, sort_keys=True, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return


# ─── Report generator ────────────────────────────────────────────────────────


def _read_paper_ledger(window_days: int) -> list[dict]:
    """Pull paper-only records via shared.paper_experiment.

    Fail-soft: returns an empty list if the module isn't loadable.
    """
    try:
        from paper_experiment import load_paper_ledger  # type: ignore
    except ImportError:
        try:
            from shared.paper_experiment import load_paper_ledger  # type: ignore
        except ImportError:
            return []
    try:
        return load_paper_ledger(int(window_days))
    except Exception:
        return []


def _render_markdown(calibration: dict[str, Any],
                      calibrated: bool,
                      rationale: str,
                      over: list[str],
                      under: list[str],
                      window_days: int) -> str:
    lines: list[str] = []
    lines.append("# Confidence Calibration Report")
    lines.append("")
    lines.append(
        "*Paper trading only. Buckets are based on the confidence score "
        "attached to each trade at entry. Backtest and replay records "
        "are excluded.*"
    )
    lines.append("")
    lines.append(
        f"Window: last {window_days} days. "
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}."
    )
    lines.append("")
    lines.append(f"Calibrated (monotonic): **{'YES' if calibrated else 'NO'}** — "
                 f"{rationale}")
    lines.append("")
    lines.append("| Bucket | n | WR | Expectancy | PF | "
                 "avgDDpost | FP rate | Notes |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    buckets = calibration.get("buckets") or {}
    for name in _BUCKET_ORDER:
        stats = buckets.get(name) or _empty_bucket_stats()
        notes_parts: list[str] = []
        if stats.get("sparse"):
            notes_parts.append("sparse")
        if name in over:
            notes_parts.append("overstates")
        if name in under:
            notes_parts.append("underused")
        notes = ", ".join(notes_parts) or "—"
        lines.append(
            f"| {name} | {stats.get('n', 0)} | "
            f"{stats.get('win_rate', 0.0)*100:.1f}% | "
            f"{stats.get('expectancy', 0.0):+.4f} | "
            f"{stats.get('profit_factor', 0.0):.2f} | "
            f"{stats.get('avg_drawdown_after_entry', 0.0)*100:.1f}% | "
            f"{stats.get('false_positive_rate', 0.0)*100:.1f}% | "
            f"{notes} |"
        )
    lines.append("")
    if over:
        lines.append("**Overstating buckets:** " + ", ".join(over))
    if under:
        lines.append("**Underused buckets:** " + ", ".join(under))
    if not over and not under:
        lines.append("No overstatement or underuse detected.")
    lines.append("")
    lines.append("> Uncalibrated buckets DO NOT auto-raise the risk-engine "
                 "threshold. An operator reviews this report and adjusts "
                 "deliberately. The Strategy Quality Gate consumes this as "
                 "context.")
    return "\n".join(lines) + "\n"


def generate_calibration_report(out_md_path: str | None = None,
                                  out_json_path: str | None = None,
                                  *,
                                  window_days: int = 180,
                                  min_n_per_bucket: int = 10
                                  ) -> tuple[str, str]:
    """Read paper ledger, compute calibration, write reports.

    Returns
    -------
    (markdown_path, json_path)
        Absolute paths of the written reports (or empty strings when
        the caller passed None and no default was constructed).
    """
    records = _read_paper_ledger(window_days)
    calibration = compute_calibration_metrics(records, source="PAPER")
    calibrated, rationale = is_calibrated(calibration,
                                            min_n_per_bucket=min_n_per_bucket)
    over = detect_overstatement(calibration)
    under = detect_underuse(calibration)

    # Always emit an audit line. Fail-soft inside _emit_audit.
    _emit_audit({
        "window_days":          int(window_days),
        "calibrated":           bool(calibrated),
        "rationale":            rationale,
        "overstating_buckets":  over,
        "underused_buckets":    under,
        "n_total":              calibration.get("n_total", 0),
    })

    md = _render_markdown(calibration, calibrated, rationale,
                           over, under, window_days)
    payload = {
        "generated_at":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days":          int(window_days),
        "calibrated":           bool(calibrated),
        "rationale":            rationale,
        "overstating_buckets":  over,
        "underused_buckets":    under,
        "calibration":          calibration,
    }

    md_path = out_md_path or str(_REPO_ROOT / "docs" /
                                   "confidence_calibration_LATEST.md")
    js_path = out_json_path or str(
        _REPO_ROOT / "learning-loop" / "confidence_calibration_LATEST.json"
    )

    try:
        p = Path(md_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
    except Exception:
        md_path = ""
    try:
        p = Path(js_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, sort_keys=True, indent=2),
                      encoding="utf-8")
    except Exception:
        js_path = ""

    return (md_path, js_path)


__all__ = [
    "CONFIDENCE_BUCKETS",
    "bucket_for",
    "compute_calibration_metrics",
    "is_calibrated",
    "calibration_drift",
    "detect_overstatement",
    "detect_underuse",
    "generate_calibration_report",
]

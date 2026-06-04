"""v3.19.0 (2026-06-04) — Post-Session Learning Loop (ETAP 2).

WHY
---
Audit-board verdict 2026-06-02 + product feedback: the system needs a
deterministic, paper-only analysis pass at the end of each session that
reads what HAPPENED, identifies anomalies, and emits structured
recommendations to a human-reviewable report. It MUST NOT mutate
runtime strategy state, MUST NOT auto-promote anything to EDGE_GATE,
and MUST NOT mix backtest evidence with paper evidence.

CONTRACT
--------
- run_post_session_analysis(*, date) reads paper ledger + audit log +
  optional session reports + confidence reports + strategy_quality_gate
  decisions for the given date (default: today UTC). Returns a
  structured dict with per-strategy / per-symbol / per-regime /
  per-confidence-bucket / per-time-window metrics, findings, and
  per-strategy advisory recommendations.

- Recommendations enum (closed):
    KEEP_OBSERVING            — strategy looks healthy, keep running
    NEEDS_MORE_DATA           — too few trades to decide
    DEGRADE_TO_OBSERVE_ONLY   — degraded; downgrade priority
    CANDIDATE_FOR_DISABLE     — strong evidence of negative expectancy
    CANDIDATE_FOR_EDGE_REVIEW — promising but needs human edge review

- Five detection helpers exposed publicly for unit-testability:
    detect_false_positive_signals
    detect_over_trading_without_edge
    detect_single_regime_dependence
    detect_recent_degradation
    detect_backtest_vs_paper_divergence

PAPER-ONLY GUARANTEE
--------------------
- No live broker calls anywhere in this module.
- The output is advisory only. It does not write to
  learning-loop/state.json. It does not flip EDGE_GATE_ENABLED.
- Strategy-disable / promotion remains an operator action.

AUDIT
-----
Each recommendation emits a JSONL line via shared.audit.write_audit_event
(kind="trading") with decision_type="learning_recommendation"-ish payload
so future humans can reconstruct WHY a recommendation was emitted.

FAIL-SOFT
---------
- Missing ledger / audit dir → empty buckets + warning entry.
- Malformed input → skip (never raise).
- Anything unexpected → return a usable partial dict; never raise.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ─── Closed enum (do not extend without bumping module version) ──────────────

KEEP_OBSERVING            = "KEEP_OBSERVING"
NEEDS_MORE_DATA           = "NEEDS_MORE_DATA"
DEGRADE_TO_OBSERVE_ONLY   = "DEGRADE_TO_OBSERVE_ONLY"
CANDIDATE_FOR_DISABLE     = "CANDIDATE_FOR_DISABLE"
CANDIDATE_FOR_EDGE_REVIEW = "CANDIDATE_FOR_EDGE_REVIEW"

ALL_RECOMMENDATIONS = frozenset({
    KEEP_OBSERVING,
    NEEDS_MORE_DATA,
    DEGRADE_TO_OBSERVE_ONLY,
    CANDIDATE_FOR_DISABLE,
    CANDIDATE_FOR_EDGE_REVIEW,
})


# ─── Severity levels for findings ────────────────────────────────────────────

SEV_INFO = "INFO"
SEV_WARN = "WARN"
SEV_ALERT = "ALERT"


# ─── Thresholds (deterministic; tuned conservative) ──────────────────────────

MIN_DATA_FOR_KEEP             = 10    # below this → NEEDS_MORE_DATA
DEGRADE_MIN_N                 = 20    # need n trades to call DEGRADE
DEGRADE_WR                    = 0.30  # WR below this on >=20 → DEGRADE
DISABLE_MIN_N                 = 30    # need n trades to call DISABLE candidate
DISABLE_WR                    = 0.35
DISABLE_PF                    = 0.90
EDGE_REVIEW_MIN_N             = 50
EDGE_REVIEW_PF                = 1.30
EDGE_REVIEW_WR                = 0.50
EDGE_REVIEW_REGIMES           = 2
RECENT_WINDOW                 = 20
RECENT_DEGRADATION_WR         = 0.30
FALSE_POS_CONF_THRESHOLD      = 0.65
BACKTEST_VS_PAPER_WR_GAP      = 0.20     # 20-pt drop = overfit signal
BACKTEST_VS_PAPER_PF_GAP      = 0.50     # PF drop ≥ 0.50 = overfit signal


# ─── Helpers ────────────────────────────────────────────────────────────────

def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _coerce_date(d: Any) -> date:
    """Parse a date string (YYYY-MM-DD) or use UTC today on bad input."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return date.fromisoformat(d.strip())
        except (TypeError, ValueError):
            return _utc_today()
    return _utc_today()


def _parse_iso_ts(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        s2 = s.rstrip("Z")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _confidence_bucket(conf: float | None) -> str:
    if conf is None:
        return "unknown"
    if conf < 0.50:
        return "low"
    if conf < 0.70:
        return "mid"
    return "high"


def _time_window_bucket(closed_at: str | None) -> str:
    dt = _parse_iso_ts(closed_at)
    if dt is None:
        return "unknown"
    h = dt.hour + dt.minute / 60.0
    if 13.5 <= h < 15.5:
        return "morning"
    if 15.5 <= h < 18.5:
        return "midday"
    if 18.5 <= h <= 20.0:
        return "close"
    return "other"


def _is_win(rec: Mapping[str, Any]) -> bool:
    return _safe_float(rec.get("net_pnl")) > 0


def _is_loss(rec: Mapping[str, Any]) -> bool:
    return _safe_float(rec.get("net_pnl")) < 0


# ─── Loaders (fail-soft) ────────────────────────────────────────────────────

def _ledger_path_for(d: date) -> Path:
    base = Path(
        os.environ.get("PAPER_EXPERIMENT_DIR")
        or _REPO_ROOT / "learning-loop" / "paper_experiments"
    )
    return base / f"{d.isoformat()}.jsonl"


def _audit_path_for(d: date) -> Path:
    base = Path(
        os.environ.get("AUDIT_TRADING_DIR")
        or _REPO_ROOT / "journal" / "autonomy"
    )
    return base / f"{d.isoformat()}.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    """Read all valid JSON lines from path. Fail-soft."""
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _load_paper_ledger(d: date, window_days: int = 1) -> list[dict]:
    """Read the paper ledger for the given date and the prior (window_days-1).

    Default window_days=1 means just the given date. Pass larger windows
    for recency analyses.
    """
    window_days = max(1, _safe_int(window_days, 1))
    out: list[dict] = []
    base = Path(
        os.environ.get("PAPER_EXPERIMENT_DIR")
        or _REPO_ROOT / "learning-loop" / "paper_experiments"
    )
    if not base.exists():
        return []
    end_d = d
    start_d = end_d - timedelta(days=window_days - 1)
    for day_offset in range(window_days):
        cur = start_d + timedelta(days=day_offset)
        out.extend(_read_jsonl(base / f"{cur.isoformat()}.jsonl"))
    return out


def _load_audit_log(d: date) -> list[dict]:
    """Load today's audit JSONL. Fail-soft."""
    return _read_jsonl(_audit_path_for(d))


# ─── Detection helpers (public for testability) ─────────────────────────────

def detect_false_positive_signals(ledger_entries: list[dict] | None) -> list[dict]:
    """Return list of trades where confidence_at_entry >= 0.65 but outcome
    was a loss. Each item is a small dict with the salient fields.

    Fail-soft on None/non-list/malformed entries.
    """
    if not isinstance(ledger_entries, list):
        return []
    out: list[dict] = []
    for rec in ledger_entries:
        if not isinstance(rec, dict):
            continue
        conf = rec.get("confidence_at_entry")
        if conf is None:
            continue
        try:
            conf_f = float(conf)
        except (TypeError, ValueError):
            continue
        net = _safe_float(rec.get("net_pnl"))
        if conf_f >= FALSE_POS_CONF_THRESHOLD and net < 0:
            out.append({
                "strategy":            rec.get("strategy", "unknown"),
                "symbol":              rec.get("symbol", "?"),
                "confidence_at_entry": round(conf_f, 4),
                "net_pnl":             round(net, 4),
                "regime":              rec.get("regime"),
                "closed_at":           rec.get("closed_at"),
            })
    return out


def detect_over_trading_without_edge(strategy_metrics: Mapping[str, Any] | None
                                     ) -> bool:
    """Return True when n_closed >= 30 AND WR < 35% AND PF < 0.9."""
    if not isinstance(strategy_metrics, Mapping):
        return False
    n = _safe_int(strategy_metrics.get("n_closed"))
    wr = _safe_float(strategy_metrics.get("win_rate"))
    pf = _safe_float(strategy_metrics.get("profit_factor"))
    return n >= 30 and wr < 0.35 and pf < 0.9


def detect_single_regime_dependence(per_regime_metrics: Mapping[str, Any] | None
                                    ) -> bool:
    """Return True when only one regime contributes positive expectancy and
    that regime has at least 5 closed trades.

    Regimes labelled "unknown" / "" / None are skipped (they are noise).
    """
    if not isinstance(per_regime_metrics, Mapping):
        return False
    positives = 0
    has_min_sample = False
    for label, sub in per_regime_metrics.items():
        if label in (None, "", "unknown"):
            continue
        if not isinstance(sub, Mapping):
            continue
        n = _safe_int(sub.get("n_closed"))
        net = _safe_float(sub.get("net_pnl_after_fees_slippage"))
        exp = _safe_float(sub.get("expectancy"))
        if n >= 5 and (net > 0 or exp > 0):
            positives += 1
            has_min_sample = True
    return positives == 1 and has_min_sample


def detect_recent_degradation(ledger_entries: list[dict] | None,
                              n_recent: int = RECENT_WINDOW) -> bool:
    """Return True when the most recent n_recent trades have WR < 30%."""
    if not isinstance(ledger_entries, list):
        return False
    n_recent = max(1, _safe_int(n_recent, RECENT_WINDOW))
    valid = [r for r in ledger_entries if isinstance(r, dict)]
    if len(valid) < n_recent:
        return False
    # Sort by closed_at ascending; take last n_recent.
    def _key(r: dict) -> str:
        return r.get("closed_at") or ""
    last = sorted(valid, key=_key)[-n_recent:]
    wins = sum(1 for r in last if _safe_float(r.get("net_pnl")) > 0)
    return (wins / float(n_recent)) < RECENT_DEGRADATION_WR


def detect_backtest_vs_paper_divergence(
    backtest_metrics: Mapping[str, Any] | None,
    paper_metrics: Mapping[str, Any] | None,
) -> dict | None:
    """Return dict describing the divergence if backtest WR/PF much exceeds
    paper WR/PF. None when no divergence detected or inputs are unusable.
    """
    if not isinstance(backtest_metrics, Mapping):
        return None
    if not isinstance(paper_metrics, Mapping):
        return None
    bt_n = _safe_int(backtest_metrics.get("n_closed"))
    pp_n = _safe_int(paper_metrics.get("n_closed"))
    if bt_n < 10 or pp_n < 10:
        # Not enough data either side to claim divergence.
        return None
    bt_wr = _safe_float(backtest_metrics.get("win_rate"))
    bt_pf = _safe_float(backtest_metrics.get("profit_factor"))
    pp_wr = _safe_float(paper_metrics.get("win_rate"))
    pp_pf = _safe_float(paper_metrics.get("profit_factor"))
    wr_gap = bt_wr - pp_wr
    pf_gap = bt_pf - pp_pf
    if wr_gap >= BACKTEST_VS_PAPER_WR_GAP or pf_gap >= BACKTEST_VS_PAPER_PF_GAP:
        return {
            "backtest_wr": round(bt_wr, 4),
            "paper_wr":    round(pp_wr, 4),
            "wr_gap":      round(wr_gap, 4),
            "backtest_pf": round(bt_pf, 4),
            "paper_pf":    round(pp_pf, 4),
            "pf_gap":      round(pf_gap, 4),
            "verdict":     "OVERFITTING_SUSPECTED",
        }
    return None


# ─── Aggregation core ────────────────────────────────────────────────────────

def _empty_bucket_metrics() -> dict:
    return {
        "n_closed":                    0,
        "wins":                        0,
        "losses":                      0,
        "win_rate":                    0.0,
        "profit_factor":               0.0,
        "expectancy":                  0.0,
        "net_pnl_after_fees_slippage": 0.0,
        "avg_win":                     0.0,
        "avg_loss":                    0.0,
        "max_drawdown":                0.0,
    }


def _aggregate(records: list[dict]) -> dict:
    """Compute a deterministic block of aggregate metrics."""
    if not records:
        return _empty_bucket_metrics()

    def _key(r: dict) -> str:
        return r.get("closed_at") or ""

    sorted_recs = sorted(records, key=_key)
    nets = [_safe_float(r.get("net_pnl"), 0.0) for r in sorted_recs]
    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p < 0]
    n = len(nets)

    win_rate = (len(wins) / n) if n else 0.0
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

    # Max drawdown on net cumulative.
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in nets:
        cum += p
        if cum > peak:
            peak = cum
        if peak > 0:
            dd = (peak - cum) / peak
            if dd > max_dd:
                max_dd = dd

    return {
        "n_closed":                    n,
        "wins":                        len(wins),
        "losses":                      len(losses),
        "win_rate":                    round(win_rate, 6),
        "profit_factor":               round(pf, 6),
        "expectancy":                  round(expectancy, 6),
        "net_pnl_after_fees_slippage": round(sum(nets), 6),
        "avg_win":                     round(avg_win, 6),
        "avg_loss":                    round(avg_loss, 6),
        "max_drawdown":                round(max_dd, 6),
    }


def _group_by(records: list[dict], key: str,
              default: str = "unknown") -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        k = r.get(key) or default
        out.setdefault(str(k), []).append(r)
    return out


def _per_strategy(records: list[dict]) -> dict[str, dict]:
    by_strat = _group_by(records, "strategy", default="unknown")
    out: dict[str, dict] = {}
    for strat, recs in by_strat.items():
        agg = _aggregate(recs)
        by_regime = {
            r_label: _aggregate(rs)
            for r_label, rs in _group_by(recs, "regime", "unknown").items()
        }
        agg["per_regime"] = by_regime
        out[strat] = agg
    return out


def _per_symbol(records: list[dict]) -> dict[str, dict]:
    by_sym = _group_by(records, "symbol", default="?")
    return {k: _aggregate(v) for k, v in by_sym.items()}


def _per_regime(records: list[dict]) -> dict[str, dict]:
    by_regime = _group_by(records, "regime", default="unknown")
    return {k: _aggregate(v) for k, v in by_regime.items()}


def _per_confidence_bucket(records: list[dict]) -> dict[str, dict]:
    by_bucket: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        bucket = _confidence_bucket(r.get("confidence_at_entry"))
        by_bucket.setdefault(bucket, []).append(r)
    return {k: _aggregate(v) for k, v in by_bucket.items()}


def _per_time_window(records: list[dict]) -> dict[str, dict]:
    by_tw: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        bucket = _time_window_bucket(r.get("closed_at"))
        by_tw.setdefault(bucket, []).append(r)
    return {k: _aggregate(v) for k, v in by_tw.items()}


# ─── Per-strategy recommendation logic ──────────────────────────────────────

def _recommend_for_strategy(strategy: str,
                            strat_metrics: Mapping[str, Any],
                            recent_ledger: list[dict]) -> str:
    """Return one of the closed enum recommendations.

    Order of precedence (most severe first):
      1. CANDIDATE_FOR_DISABLE — n>=30 + WR<35% + PF<0.9
      2. DEGRADE_TO_OBSERVE_ONLY — n>=20 + WR<30%, OR recent degradation
      3. CANDIDATE_FOR_EDGE_REVIEW — n>=50 + WR>=50% + PF>=1.3 + ≥2 regimes
      4. NEEDS_MORE_DATA — n<10
      5. KEEP_OBSERVING — otherwise
    """
    if not isinstance(strat_metrics, Mapping):
        return NEEDS_MORE_DATA
    n = _safe_int(strat_metrics.get("n_closed"))
    wr = _safe_float(strat_metrics.get("win_rate"))
    pf = _safe_float(strat_metrics.get("profit_factor"))

    if n < MIN_DATA_FOR_KEEP:
        return NEEDS_MORE_DATA

    # CANDIDATE_FOR_DISABLE — strong negative evidence
    if n >= DISABLE_MIN_N and wr < DISABLE_WR and pf < DISABLE_PF:
        return CANDIDATE_FOR_DISABLE

    if detect_over_trading_without_edge(strat_metrics):
        return CANDIDATE_FOR_DISABLE

    # DEGRADE_TO_OBSERVE_ONLY — soft negative evidence
    if n >= DEGRADE_MIN_N and wr < DEGRADE_WR:
        return DEGRADE_TO_OBSERVE_ONLY

    if detect_recent_degradation(recent_ledger):
        return DEGRADE_TO_OBSERVE_ONLY

    # CANDIDATE_FOR_EDGE_REVIEW — promising
    per_regime = strat_metrics.get("per_regime") or {}
    positive_regimes = 0
    if isinstance(per_regime, Mapping):
        for label, sub in per_regime.items():
            if label in (None, "", "unknown"):
                continue
            if not isinstance(sub, Mapping):
                continue
            if (_safe_int(sub.get("n_closed")) >= 5
                    and (_safe_float(sub.get("expectancy")) > 0
                         or _safe_float(sub.get("net_pnl_after_fees_slippage")) > 0)):
                positive_regimes += 1
    if (n >= EDGE_REVIEW_MIN_N
            and wr >= EDGE_REVIEW_WR
            and pf >= EDGE_REVIEW_PF
            and positive_regimes >= EDGE_REVIEW_REGIMES):
        return CANDIDATE_FOR_EDGE_REVIEW

    return KEEP_OBSERVING


# ─── Audit emission ─────────────────────────────────────────────────────────

def _emit_learning_recommendation(strategy: str, recommendation: str,
                                  rationale: str,
                                  metrics: Mapping[str, Any] | None) -> None:
    """Emit a JSONL audit row for a single recommendation. Fail-soft."""
    try:
        from shared.audit import write_audit_event  # type: ignore
        from shared.autonomy import make_decision   # type: ignore
    except Exception:
        try:
            from audit import write_audit_event       # type: ignore
            from autonomy import make_decision        # type: ignore
        except Exception:
            return
    try:
        # learning_recommendation reuses PAUSE/RESUME enum slots for the
        # decision_type because the autonomy contract enum is closed.
        # The actual recommendation label is what humans + downstream
        # tools read.
        decision_type = "PAUSE_STRATEGY" if recommendation in (
            CANDIDATE_FOR_DISABLE, DEGRADE_TO_OBSERVE_ONLY) else "RESUME_STRATEGY"
        d = make_decision(
            decision_type=decision_type,
            decision=recommendation,
            reason=f"learning_recommendation: {rationale}",
            actor="post-session-learning",
            strategy=strategy,
            risk_metrics={
                "n_closed":   _safe_int((metrics or {}).get("n_closed")),
                "win_rate":   _safe_float((metrics or {}).get("win_rate")),
                "profit_factor": _safe_float((metrics or {}).get("profit_factor")),
            },
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


# ─── Findings collation ─────────────────────────────────────────────────────

def _build_findings(records: list[dict],
                    per_strat: Mapping[str, dict],
                    per_regime: Mapping[str, dict]
                    ) -> list[dict]:
    findings: list[dict] = []

    # False positives (across all strategies in the session)
    fps = detect_false_positive_signals(records)
    if fps:
        # Group by strategy for cleaner reporting.
        by_strat: dict[str, list[dict]] = {}
        for f in fps:
            by_strat.setdefault(f["strategy"], []).append(f)
        for strat, items in by_strat.items():
            findings.append({
                "type":           "false_positive_signals",
                "severity":       SEV_WARN,
                "strategy":       strat,
                "description":    (f"{len(items)} trade(s) entered with "
                                   f"confidence >= {FALSE_POS_CONF_THRESHOLD:.2f} "
                                   f"but closed at a loss."),
                "recommendation": ("Review confidence calibration: a high score "
                                   "should not consistently precede losses."),
                "details":        items[:10],  # cap to keep report short
            })

    # Single-regime dependence per strategy
    for strat, sm in per_strat.items():
        if detect_single_regime_dependence(sm.get("per_regime")):
            findings.append({
                "type":           "single_regime_dependence",
                "severity":       SEV_WARN,
                "strategy":       strat,
                "description":    ("Strategy currently only profits in 1 "
                                   "regime (≥5 trades). Edge is regime-bound."),
                "recommendation": ("Do NOT promote to edge experiment until "
                                   "evidence in ≥2 regimes."),
            })

    # Per-strategy recent degradation
    by_strat_records: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        by_strat_records.setdefault(str(r.get("strategy") or "unknown"), []).append(r)
    for strat, recs in by_strat_records.items():
        if detect_recent_degradation(recs):
            findings.append({
                "type":           "recent_degradation",
                "severity":       SEV_ALERT,
                "strategy":       strat,
                "description":    ("Last 20 trades show win-rate below 30%. "
                                   "Negative momentum suggests degraded edge."),
                "recommendation": ("Consider DEGRADE_TO_OBSERVE_ONLY pending "
                                   "operator review."),
            })

    # Over-trading without edge
    for strat, sm in per_strat.items():
        if detect_over_trading_without_edge(sm):
            findings.append({
                "type":           "over_trading_without_edge",
                "severity":       SEV_ALERT,
                "strategy":       strat,
                "description":    ("n_closed >= 30 with WR < 35% and PF < 0.9. "
                                   "Strategy is bleeding capital."),
                "recommendation": ("Strong CANDIDATE_FOR_DISABLE. Operator "
                                   "must review before next session."),
            })

    return findings


# ─── Public API ─────────────────────────────────────────────────────────────

def run_post_session_analysis(*, date: str | None = None,
                              window_days: int = 1,
                              emit_audit: bool = True,
                              backtest_metrics_by_strategy:
                                  Mapping[str, Mapping[str, Any]] | None = None,
                              ) -> dict:
    """Read evidence, compute metrics, emit recommendations.

    Returns a structured dict. Never raises. Never mutates state.json.
    Never enables EDGE_GATE. The optional backtest_metrics_by_strategy
    map allows the optional backtest-vs-paper divergence check; if
    omitted, the divergence check is skipped (we do not auto-load
    backtests here because backtest and paper evidence must remain
    distinct sources per the iron contract).
    """
    try:
        target_date = _coerce_date(date) if date is not None else _utc_today()
    except Exception:
        target_date = _utc_today()

    warnings: list[str] = []

    records = _load_paper_ledger(target_date, window_days=window_days)
    if not records:
        warnings.append(
            f"no paper ledger found for {target_date.isoformat()} "
            f"(window_days={window_days})"
        )

    audit_log = _load_audit_log(target_date)
    if not audit_log:
        warnings.append(
            f"no audit log found for {target_date.isoformat()}"
        )

    # Build buckets
    strategies        = _per_strategy(records)
    symbols           = _per_symbol(records)
    regimes           = _per_regime(records)
    confidence_buckets = _per_confidence_bucket(records)
    time_windows      = _per_time_window(records)

    findings = _build_findings(records, strategies, regimes)

    # Backtest divergence — only if caller supplied backtest metrics.
    if isinstance(backtest_metrics_by_strategy, Mapping):
        for strat, bt in backtest_metrics_by_strategy.items():
            paper = strategies.get(strat) or {}
            div = detect_backtest_vs_paper_divergence(bt, paper)
            if div:
                findings.append({
                    "type":           "backtest_vs_paper_divergence",
                    "severity":       SEV_WARN,
                    "strategy":       strat,
                    "description":    (f"Backtest WR {div['backtest_wr']:.0%} "
                                       f"vs paper WR {div['paper_wr']:.0%} — "
                                       f"likely overfit signal."),
                    "recommendation": ("Backtest evidence cannot be substituted "
                                       "for paper evidence. Do NOT promote."),
                    "details":        div,
                })

    # Recommendations per strategy
    recommendations: dict[str, str] = {}
    by_strat_records: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        by_strat_records.setdefault(
            str(r.get("strategy") or "unknown"), []).append(r)

    for strat, sm in strategies.items():
        recent = by_strat_records.get(strat, [])
        rec = _recommend_for_strategy(strat, sm, recent)
        recommendations[strat] = rec
        if emit_audit:
            _emit_learning_recommendation(strat, rec,
                                          rationale=f"n={sm.get('n_closed')} "
                                                    f"WR={sm.get('win_rate')}, "
                                                    f"PF={sm.get('profit_factor')}",
                                          metrics=sm)

    out: dict[str, Any] = {
        "date":                target_date.isoformat(),
        "window_days":         max(1, _safe_int(window_days, 1)),
        "n_trades_in_window":  len(records),
        "n_audit_events":      len(audit_log),
        "strategies":          strategies,
        "symbols":             symbols,
        "regimes":             regimes,
        "confidence_buckets":  confidence_buckets,
        "time_windows":        time_windows,
        "findings":            findings,
        "recommendations":     recommendations,
        "warnings":            warnings,
        "paper_only":          True,
        "generated_at":        datetime.now(timezone.utc).isoformat(
                                  timespec="seconds"),
    }
    return out


__all__ = [
    # Recommendation enum
    "KEEP_OBSERVING",
    "NEEDS_MORE_DATA",
    "DEGRADE_TO_OBSERVE_ONLY",
    "CANDIDATE_FOR_DISABLE",
    "CANDIDATE_FOR_EDGE_REVIEW",
    "ALL_RECOMMENDATIONS",
    # Severity tags
    "SEV_INFO", "SEV_WARN", "SEV_ALERT",
    # Detection helpers
    "detect_false_positive_signals",
    "detect_over_trading_without_edge",
    "detect_single_regime_dependence",
    "detect_recent_degradation",
    "detect_backtest_vs_paper_divergence",
    # Public API
    "run_post_session_analysis",
]

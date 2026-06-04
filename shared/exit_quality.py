"""v3.20.0 (2026-06-04) — ETAP 8 — Exit Quality module.

Closes audit-board STRAT-002 / RISK-002 follow-up: the system needs an
honest, deterministic picture of HOW each closed trade actually exited.
"Did we exit too early and leave dollars on the table?" "Did we exit too
late and give back most of the peak?" "How efficient was the stop?"
"Where did the position spend time before resolving?"

WHY
---
ETAP 8 introduces `exit_quality.py` — a read-only, fail-soft, paper /
shadow ledger analyser. It loads closed trades from the existing
`shared/paper_experiment.py` ledger directories, computes per-trade
post-mortem fields, aggregates per-strategy / symbol / regime /
confidence_bucket, and emits a recommendations list (free-form strings)
the operator can read.

CONTRACT
--------
- Reads JSONL only. NEVER calls the broker. NEVER calls a paid API.
- NEVER mutates state. NEVER auto-disables strategies. NEVER touches
  config. Output is a dict + report — period.
- Evidence boundary is respected: PAPER / BACKTEST / REPLAY are loaded
  via separate `source_filter` and `paper_only` is preserved in every
  per-trade row so downstream consumers (or visual reports) can refuse
  to blend.
- Recommendations are strings. They are not promises of profit and they
  are not instructions to enable live trading.
- Pure functions. Deterministic given the same input ledger.

PER-TRADE FIELDS COMPUTED
-------------------------
Given a closed trade with optional price_series (intra-trade marks)
and optional explicit MFE/MAE fields, compute:

  - mfe              Maximum favourable excursion (price units, per side)
  - mae              Maximum adverse excursion   (price units, per side)
  - mfe_pct          MFE expressed as a fraction of entry
  - mae_pct          MAE expressed as a fraction of entry
  - profit_giveback_usd   max(0, mfe*qty - net_pnl)
  - profit_giveback_pct   profit_giveback_usd / max(mfe*qty, 1e-9)
  - stop_efficiency       For losing trades: actual loss / planned SL loss.
                          1.0 = stopped exactly at planned SL. <1.0 = exited
                          better than SL. >1.0 = exited worse (gap).
  - target_efficiency     For winning trades: net_pnl / planned TP profit.
                          1.0 = hit exactly the TP. <1.0 = exited short of TP.
                          >1.0 = exited beyond TP.
  - exit_too_early   True iff trade closed for a profit AND giveback>=20%
                          relative to MFE — i.e. we had a real winner and
                          surrendered most of it.
  - exit_too_late    True iff trade closed for a loss AND |actual loss|
                          exceeds planned stop loss by more than 25%.
  - time_in_trade_minutes  closed_at - opened_at, rounded to minute.
  - trailing_stop_candidate  Synthetic: WOULD an 8% trail off MFE peak
                          have left us better off than what actually
                          happened? Returns True/False/None.
  - regime_at_entry  Mirror of the record's `regime` field.
  - confidence_bucket_at_entry  low / mid / high / unknown.

AGGREGATIONS
------------
- per_strategy
- per_symbol
- per_regime
- per_confidence_bucket

Each aggregation reports n, win_rate, avg_mfe_pct, avg_mae_pct,
avg_giveback_pct, mean_stop_efficiency, mean_target_efficiency,
share_exit_too_early, share_exit_too_late, share_trailing_helps.

RECOMMENDATIONS
---------------
A small set of deterministic rules that translate the aggregates into
human-readable strings. No code path here mutates anything. Examples:

  - "regime=RISK_ON: exit_too_early share 35%>20% — review TP early-take
     vs trailing rule before flipping any gate."
  - "confidence_bucket=high: trailing_stop_candidate fires in 42% of
     trades — collect more samples before adjusting the trail rule."

PAPER-ONLY GUARANTEE
--------------------
This module obeys the v3.19.0 EvidenceSource boundary. Callers pass
``source_filter`` (default PAPER) and BACKTEST / REPLAY data is loaded
from separate directories. Mixing is refused; the per-trade row carries
``source`` so consumers can verify.

FAIL-SOFT
---------
- Missing fields → safe defaults, never raise.
- Malformed numeric input → coerce or drop, never raise.
- Missing price_series → MFE/MAE fall back to entry+exit only (best
  case for a winner equals exit; worst case for a loser equals exit).
- Missing planned_sl / planned_tp → stop_efficiency / target_efficiency
  return None; aggregates exclude None.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from evidence_source import EvidenceSource, parse_source  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from shared.evidence_source import (  # type: ignore
            EvidenceSource, parse_source,
        )
    except ImportError:  # pragma: no cover
        class EvidenceSource(str):  # type: ignore[no-redef]
            BACKTEST = "BACKTEST"
            REPLAY = "REPLAY"
            PAPER = "PAPER"

        def parse_source(v, *, default="PAPER"):  # type: ignore[no-redef]
            if isinstance(v, str):
                u = v.strip().upper()
                if u in ("PAPER", "BACKTEST", "REPLAY"):
                    return u
            return default


# ─── Constants ────────────────────────────────────────────────────────────────

# Thresholds — tunable but conservative. Documented in docs/EXIT_QUALITY.md.
EARLY_EXIT_GIVEBACK_THRESHOLD = 0.20   # >=20% of MFE surrendered → "too early"
LATE_EXIT_OVERSHOOT_THRESHOLD = 0.25   # actual loss >25% over planned SL → "too late"
TRAILING_STOP_TRAIL_PCT = 0.08         # 8% trail off MFE peak (LLM proposal 2026-05-07)
TRAILING_STOP_MIN_HOLD_MIN = 12 * 60   # 12h min-hold (matches options-exit-monitor)


# ─── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ledger_dir_for(source: Any) -> Path:
    """Map EvidenceSource → ledger directory.

    Honours the env overrides used by `paper_experiment.py` so tests can
    redirect both modules to the same temporary directory.
    """
    val = parse_source(source, default=EvidenceSource.PAPER)
    sv = val.value if hasattr(val, "value") else str(val).upper()
    if sv == "BACKTEST":
        return Path(
            os.environ.get("BACKTEST_LEDGER_DIR")
            or _REPO_ROOT / "learning-loop" / "backtest_results"
        )
    if sv == "REPLAY":
        return Path(
            os.environ.get("REPLAY_LEDGER_DIR")
            or _REPO_ROOT / "learning-loop" / "replay_results"
        )
    return Path(
        os.environ.get("PAPER_EXPERIMENT_DIR")
        or _REPO_ROOT / "learning-loop" / "paper_experiments"
    )


# ─── Safe coercion ────────────────────────────────────────────────────────────

def _safe_float(x: Any, default: float | None = 0.0) -> float | None:
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


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


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


def _confidence_bucket(conf: Any) -> str:
    val = _safe_float(conf, default=None)
    if val is None:
        return "unknown"
    if val < 0.50:
        return "low"
    if val < 0.70:
        return "mid"
    return "high"


# ─── Loader ───────────────────────────────────────────────────────────────────

def _iter_trades_in_window(window_days: int,
                            *,
                            source: Any = EvidenceSource.PAPER) -> Iterable[dict]:
    """Yield closed-trade JSON rows within the last ``window_days``.

    Mirrors `paper_experiment._iter_trades_in_window` so the two modules
    stay aligned. Fail-soft on missing dirs / bad lines / bad dates.
    """
    d = _ledger_dir_for(source)
    if not d.exists():
        return
    today = _utc_today()
    earliest = today - timedelta(days=max(1, _safe_int(window_days, 180)))
    for entry_path in sorted(d.glob("*.jsonl")):
        try:
            fd = date.fromisoformat(entry_path.stem)
        except ValueError:
            continue
        if fd < earliest:
            continue
        try:
            with open(entry_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    closed = _parse_iso_ts(rec.get("closed_at"))
                    if closed is None:
                        closed = datetime.combine(
                            fd, datetime.min.time(), tzinfo=timezone.utc
                        )
                    if closed.date() < earliest:
                        continue
                    yield rec
        except OSError:
            continue


# ─── Per-trade analytics ──────────────────────────────────────────────────────

def _mfe_mae_from_series(side: str, entry: float,
                          series: Iterable[Any]) -> tuple[float, float]:
    """MFE / MAE in price units given a list of intra-trade marks.

    side = "long":  MFE = max(price) - entry, MAE = entry - min(price)
    side = "short": MFE = entry - min(price), MAE = max(price) - entry

    Returns (mfe, mae), both non-negative.
    """
    highs = []
    lows = []
    for p in series:
        v = _safe_float(p, default=None)
        if v is None:
            continue
        highs.append(v)
        lows.append(v)
    if not highs:
        return 0.0, 0.0
    hi = max(highs)
    lo = min(lows)
    if side == "short":
        mfe = max(0.0, entry - lo)
        mae = max(0.0, hi - entry)
    else:
        mfe = max(0.0, hi - entry)
        mae = max(0.0, entry - lo)
    return mfe, mae


def _planned_sl_loss_usd(side: str, entry: float, planned_sl: float | None,
                          qty: float) -> float | None:
    """Compute planned loss in $ if SL hit exactly.

    Returns None if planned_sl missing / invalid.
    """
    if planned_sl is None or qty <= 0 or entry <= 0:
        return None
    if planned_sl <= 0:
        return None
    if side == "short":
        # Short: SL is above entry → planned loss = (sl - entry) * qty
        if planned_sl <= entry:
            return None
        return (planned_sl - entry) * qty
    # Long: SL is below entry → planned loss = (entry - sl) * qty
    if planned_sl >= entry:
        return None
    return (entry - planned_sl) * qty


def _planned_tp_profit_usd(side: str, entry: float, planned_tp: float | None,
                            qty: float) -> float | None:
    """Compute planned profit in $ if TP hit exactly.

    Returns None if planned_tp missing / invalid.
    """
    if planned_tp is None or qty <= 0 or entry <= 0:
        return None
    if planned_tp <= 0:
        return None
    if side == "short":
        # Short TP is below entry
        if planned_tp >= entry:
            return None
        return (entry - planned_tp) * qty
    # Long TP is above entry
    if planned_tp <= entry:
        return None
    return (planned_tp - entry) * qty


def _gross_pnl(side: str, entry: float, exit_: float, qty: float) -> float:
    if side == "short":
        return (entry - exit_) * qty
    return (exit_ - entry) * qty


def _trailing_stop_helps(side: str, entry: float, actual_exit: float,
                          mfe: float, qty: float,
                          minutes_in_trade: int) -> bool | None:
    """Simulate an 8% trail off MFE peak with 12h min-hold and report
    whether it would have produced a better net dollar outcome than the
    actual exit.

    Returns:
        True  — trailing stop would have closed at a better price
        False — trailing stop would have been worse (or equal)
        None  — not enough data to simulate (mfe=0 or pre min-hold)

    The simulation is deliberately simple: peak price during the trade
    is approximated as `entry + mfe` (long) or `entry - mfe` (short).
    A trail at TRAILING_STOP_TRAIL_PCT off that peak gives a synthetic
    exit price. Real intra-trade dynamics may differ — this is a hint,
    not a prediction.
    """
    if mfe <= 0:
        return None
    if minutes_in_trade < TRAILING_STOP_MIN_HOLD_MIN:
        # Below the min-hold rule the trail rule would have never armed.
        return None
    if side == "short":
        peak_price = entry - mfe
        trail_exit = peak_price * (1.0 + TRAILING_STOP_TRAIL_PCT)
        # Better trail = LOWER trail_exit relative to actual_exit for shorts.
        trail_pnl = (entry - trail_exit) * qty
    else:
        peak_price = entry + mfe
        trail_exit = peak_price * (1.0 - TRAILING_STOP_TRAIL_PCT)
        trail_pnl = (trail_exit - entry) * qty
    actual_pnl = _gross_pnl(side, entry, actual_exit, qty)
    return trail_pnl > actual_pnl


def analyse_trade(rec: dict) -> dict:
    """Return a per-trade post-mortem dict for a single ledger record.

    Pure function. Fail-soft. The returned dict ALWAYS contains the
    keys listed in ETAP 8 spec (some may be None when data is missing).
    """
    safe = dict(rec) if isinstance(rec, dict) else {}
    strategy = str(safe.get("strategy") or "unknown")
    symbol = str(safe.get("symbol") or "?")
    side = (str(safe.get("side") or "long")).lower()
    entry = _safe_float(safe.get("entry"), 0.0) or 0.0
    exit_ = _safe_float(safe.get("exit"), 0.0) or 0.0
    qty = _safe_float(safe.get("qty"), 0.0) or 0.0
    net_pnl = _safe_float(safe.get("net_pnl"), None)
    if net_pnl is None:
        net_pnl = _gross_pnl(side, entry, exit_, qty)

    regime = safe.get("regime") or None
    conf_raw = safe.get("confidence_at_entry")
    confidence_bucket = _confidence_bucket(conf_raw)

    # MFE / MAE — prefer explicit fields, fall back to series, fall back
    # to the entry-exit envelope (best case for a winner = exit; worst
    # case for a loser = exit).
    mfe = _safe_float(safe.get("mfe"), None)
    mae = _safe_float(safe.get("mae"), None)
    series = safe.get("price_series")
    if (mfe is None or mae is None) and isinstance(series, list) and series:
        ser_mfe, ser_mae = _mfe_mae_from_series(side, entry, series)
        if mfe is None:
            mfe = ser_mfe
        if mae is None:
            mae = ser_mae
    if mfe is None or mae is None:
        # Envelope fallback. For a long winner, MFE >= exit-entry. For a
        # long loser, MAE >= entry-exit. We use the actual exit only —
        # so MFE for a loser is 0 (conservative).
        gross = _gross_pnl(side, entry, exit_, qty)
        if side == "short":
            up_move = max(0.0, entry - exit_)   # favourable
            down_move = max(0.0, exit_ - entry)  # adverse
        else:
            up_move = max(0.0, exit_ - entry)
            down_move = max(0.0, entry - exit_)
        if mfe is None:
            mfe = up_move if gross >= 0 else 0.0
        if mae is None:
            mae = down_move if gross <= 0 else 0.0

    mfe = max(0.0, _safe_float(mfe, 0.0) or 0.0)
    mae = max(0.0, _safe_float(mae, 0.0) or 0.0)

    mfe_pct = (mfe / entry) if entry > 0 else 0.0
    mae_pct = (mae / entry) if entry > 0 else 0.0

    # Profit giveback (only meaningful for closed-positive trades but
    # we compute it generically so callers can inspect both sides).
    peak_dollar = mfe * qty
    profit_giveback_usd = max(0.0, peak_dollar - max(0.0, net_pnl))
    if peak_dollar > 0:
        profit_giveback_pct = profit_giveback_usd / peak_dollar
    else:
        profit_giveback_pct = 0.0

    # Planned SL/TP and efficiency.
    planned_sl = _safe_float(safe.get("planned_sl"), None)
    planned_tp = _safe_float(safe.get("planned_tp"), None)
    sl_loss = _planned_sl_loss_usd(side, entry, planned_sl, qty)
    tp_profit = _planned_tp_profit_usd(side, entry, planned_tp, qty)

    stop_efficiency: float | None = None
    target_efficiency: float | None = None
    if net_pnl < 0 and sl_loss is not None and sl_loss > 0:
        stop_efficiency = abs(net_pnl) / sl_loss
    if net_pnl > 0 and tp_profit is not None and tp_profit > 0:
        target_efficiency = net_pnl / tp_profit

    # Exit-quality flags.
    exit_too_early = bool(
        net_pnl > 0
        and peak_dollar > 0
        and profit_giveback_pct >= EARLY_EXIT_GIVEBACK_THRESHOLD
    )
    exit_too_late = False
    if net_pnl < 0 and sl_loss is not None and sl_loss > 0:
        # actual loss exceeds planned SL by more than threshold
        overshoot = (abs(net_pnl) - sl_loss) / sl_loss
        exit_too_late = overshoot > LATE_EXIT_OVERSHOOT_THRESHOLD

    # Time in trade
    opened = _parse_iso_ts(safe.get("opened_at"))
    closed = _parse_iso_ts(safe.get("closed_at"))
    minutes_in_trade = 0
    if opened is not None and closed is not None and closed >= opened:
        minutes_in_trade = int((closed - opened).total_seconds() // 60)

    # Trailing-stop simulation
    trail = _trailing_stop_helps(
        side, entry, exit_, mfe, qty, minutes_in_trade
    )

    return {
        "strategy":                  strategy,
        "symbol":                    symbol,
        "side":                      side,
        "source":                    str(safe.get("source") or "PAPER"),
        "paper_only":                bool(safe.get("paper_only", True)),
        "entry":                     entry,
        "exit":                      exit_,
        "qty":                       qty,
        "net_pnl":                   round(net_pnl, 6),
        "mfe":                       round(mfe, 6),
        "mae":                       round(mae, 6),
        "mfe_pct":                   round(mfe_pct, 6),
        "mae_pct":                   round(mae_pct, 6),
        "profit_giveback_usd":       round(profit_giveback_usd, 6),
        "profit_giveback_pct":       round(profit_giveback_pct, 6),
        "stop_efficiency":           (round(stop_efficiency, 6)
                                       if stop_efficiency is not None else None),
        "target_efficiency":         (round(target_efficiency, 6)
                                       if target_efficiency is not None else None),
        "exit_too_early":            exit_too_early,
        "exit_too_late":             exit_too_late,
        "time_in_trade_minutes":     minutes_in_trade,
        "trailing_stop_candidate":   trail,
        "regime_at_entry":           regime,
        "confidence_bucket_at_entry": confidence_bucket,
    }


# ─── Aggregations ────────────────────────────────────────────────────────────

def _empty_aggregate() -> dict:
    return {
        "n":                          0,
        "wins":                       0,
        "losses":                     0,
        "win_rate":                   0.0,
        "avg_mfe_pct":                0.0,
        "avg_mae_pct":                0.0,
        "avg_giveback_pct":           0.0,
        "mean_stop_efficiency":       None,
        "mean_target_efficiency":     None,
        "share_exit_too_early":       0.0,
        "share_exit_too_late":        0.0,
        "share_trailing_helps":       0.0,
        "avg_time_in_trade_minutes":  0.0,
    }


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return _empty_aggregate()
    n = len(rows)
    wins = sum(1 for r in rows if r.get("net_pnl", 0.0) > 0)
    losses = sum(1 for r in rows if r.get("net_pnl", 0.0) < 0)
    win_rate = wins / n if n else 0.0
    avg_mfe_pct = sum(r.get("mfe_pct", 0.0) for r in rows) / n
    avg_mae_pct = sum(r.get("mae_pct", 0.0) for r in rows) / n
    avg_giveback_pct = sum(r.get("profit_giveback_pct", 0.0) for r in rows) / n

    se = [r["stop_efficiency"] for r in rows
          if r.get("stop_efficiency") is not None]
    te = [r["target_efficiency"] for r in rows
          if r.get("target_efficiency") is not None]
    mean_se = (sum(se) / len(se)) if se else None
    mean_te = (sum(te) / len(te)) if te else None

    share_early = sum(1 for r in rows if r.get("exit_too_early")) / n
    share_late = sum(1 for r in rows if r.get("exit_too_late")) / n
    trail_known = [r for r in rows if r.get("trailing_stop_candidate") is not None]
    share_trail = (
        sum(1 for r in trail_known if r["trailing_stop_candidate"]) / len(trail_known)
        if trail_known else 0.0
    )
    avg_time = sum(r.get("time_in_trade_minutes", 0) for r in rows) / n

    return {
        "n":                          n,
        "wins":                       wins,
        "losses":                     losses,
        "win_rate":                   round(win_rate, 6),
        "avg_mfe_pct":                round(avg_mfe_pct, 6),
        "avg_mae_pct":                round(avg_mae_pct, 6),
        "avg_giveback_pct":           round(avg_giveback_pct, 6),
        "mean_stop_efficiency":       (round(mean_se, 6) if mean_se is not None
                                        else None),
        "mean_target_efficiency":     (round(mean_te, 6) if mean_te is not None
                                        else None),
        "share_exit_too_early":       round(share_early, 6),
        "share_exit_too_late":        round(share_late, 6),
        "share_trailing_helps":       round(share_trail, 6),
        "avg_time_in_trade_minutes":  round(avg_time, 6),
    }


# ─── Recommendations ─────────────────────────────────────────────────────────

# Recommendations are STRINGS only. They are NOT runtime mutations and
# NOT instructions to enable any gate. They are guidance for the
# learning-loop / operator review process.
MIN_BUCKET_N_FOR_RECO = 5
EARLY_SHARE_RECO_THRESHOLD = 0.30
LATE_SHARE_RECO_THRESHOLD = 0.20
TRAILING_HELP_RECO_THRESHOLD = 0.40
STOP_EFFICIENCY_RECO_THRESHOLD = 1.20    # avg overshoot of 20% on stops
TARGET_EFFICIENCY_RECO_LOW = 0.50         # winners cashing < half the target


def _bucket_recommendations(label: str, key: str, agg: dict) -> list[str]:
    """Generate human-readable recommendations for one aggregate row.

    Always returns strings. NEVER mutates anything. The wording
    deliberately frames every recommendation as a topic to review — it
    is not a directive to flip a flag or to enable live trading.
    """
    out: list[str] = []
    n = int(agg.get("n", 0))
    if n < MIN_BUCKET_N_FOR_RECO:
        return out  # too few samples to opine

    early = agg.get("share_exit_too_early", 0.0)
    if isinstance(early, (int, float)) and early >= EARLY_SHARE_RECO_THRESHOLD:
        out.append(
            f"{label}={key}: exit_too_early share {early*100:.0f}% across "
            f"{n} trades. Topic for review: TP placement / partial-take rule. "
            "Does not enable live trading."
        )

    late = agg.get("share_exit_too_late", 0.0)
    if isinstance(late, (int, float)) and late >= LATE_SHARE_RECO_THRESHOLD:
        out.append(
            f"{label}={key}: exit_too_late share {late*100:.0f}% across "
            f"{n} trades. Topic for review: stop placement / gap protection. "
            "Does not enable live trading."
        )

    trail = agg.get("share_trailing_helps", 0.0)
    if isinstance(trail, (int, float)) and trail >= TRAILING_HELP_RECO_THRESHOLD:
        out.append(
            f"{label}={key}: 8% trailing stop would have helped in "
            f"{trail*100:.0f}% of trades (n={n}). Topic for review: "
            "trailing rule. Does not enable live trading."
        )

    se = agg.get("mean_stop_efficiency")
    if isinstance(se, (int, float)) and se >= STOP_EFFICIENCY_RECO_THRESHOLD:
        out.append(
            f"{label}={key}: mean stop_efficiency {se:.2f}> "
            f"{STOP_EFFICIENCY_RECO_THRESHOLD:.2f} (losses overshoot the "
            "planned SL). Topic for review: gap / slippage assumptions. "
            "Does not enable live trading."
        )

    te = agg.get("mean_target_efficiency")
    if isinstance(te, (int, float)) and 0 < te <= TARGET_EFFICIENCY_RECO_LOW:
        out.append(
            f"{label}={key}: mean target_efficiency {te:.2f} (winners only "
            "cashing a small fraction of the planned TP). Topic for review: "
            "TP placement vs realistic targets. Does not enable live trading."
        )

    return out


# ─── Public API ──────────────────────────────────────────────────────────────

def analyse_ledger(window_days: int = 180,
                    *,
                    source: Any = EvidenceSource.PAPER,
                    records: list[dict] | None = None) -> dict:
    """Analyse the closed-trade ledger and return a per-trade list +
    aggregations + recommendations.

    Parameters
    ----------
    window_days : int
        Look-back window in calendar days. Default 180.
    source : EvidenceSource
        Which ledger directory to read from. Default PAPER. BACKTEST /
        REPLAY are loaded from their dedicated directories and are
        NEVER mixed into PAPER aggregates.
    records : list[dict] | None
        If provided, bypasses disk and analyses the in-memory list (used
        by tests). Each record is treated as belonging to ``source``.

    Returns
    -------
    dict
        {
          "window_days": int,
          "source": str,
          "trades": [ per_trade_dict, ... ],
          "per_strategy": { strategy: aggregate, ... },
          "per_symbol":   { symbol:   aggregate, ... },
          "per_regime":   { regime:   aggregate, ... },
          "per_confidence_bucket": { bucket: aggregate, ... },
          "overall": aggregate,
          "recommendations": [ str, ... ],
        }
    """
    src = parse_source(source, default=EvidenceSource.PAPER)
    sv = src.value if hasattr(src, "value") else str(src).upper()

    if records is None:
        raw = list(_iter_trades_in_window(window_days, source=src))
    else:
        raw = [r for r in records if isinstance(r, dict)]

    # Honour the evidence boundary: refuse to count records that declare
    # a non-matching source even if they ended up in the directory.
    filtered: list[dict] = []
    for r in raw:
        rec_src = parse_source(r.get("source"), default=EvidenceSource.PAPER)
        rec_sv = (rec_src.value if hasattr(rec_src, "value")
                  else str(rec_src).upper())
        if rec_sv != sv:
            continue
        filtered.append(r)

    trades = [analyse_trade(r) for r in filtered]

    by_strategy: dict[str, list[dict]] = {}
    by_symbol: dict[str, list[dict]] = {}
    by_regime: dict[str, list[dict]] = {}
    by_conf: dict[str, list[dict]] = {}
    for t in trades:
        by_strategy.setdefault(t["strategy"], []).append(t)
        by_symbol.setdefault(t["symbol"], []).append(t)
        rk = t["regime_at_entry"] or "unknown"
        by_regime.setdefault(str(rk), []).append(t)
        by_conf.setdefault(t["confidence_bucket_at_entry"], []).append(t)

    per_strategy = {k: _aggregate(v) for k, v in by_strategy.items()}
    per_symbol = {k: _aggregate(v) for k, v in by_symbol.items()}
    per_regime = {k: _aggregate(v) for k, v in by_regime.items()}
    per_conf = {k: _aggregate(v) for k, v in by_conf.items()}
    overall = _aggregate(trades)

    recs: list[str] = []
    for k in sorted(per_strategy.keys()):
        recs.extend(_bucket_recommendations("strategy", k, per_strategy[k]))
    for k in sorted(per_regime.keys()):
        recs.extend(_bucket_recommendations("regime", k, per_regime[k]))
    for k in sorted(per_conf.keys()):
        recs.extend(_bucket_recommendations("confidence_bucket",
                                              k, per_conf[k]))

    return {
        "window_days":             max(1, _safe_int(window_days, 180)),
        "source":                  sv,
        "trades":                  trades,
        "per_strategy":            per_strategy,
        "per_symbol":              per_symbol,
        "per_regime":              per_regime,
        "per_confidence_bucket":   per_conf,
        "overall":                 overall,
        "recommendations":         recs,
    }


def render_report(result: dict) -> str:
    """Render a Markdown summary of the dict returned by
    `analyse_ledger`. Pure function. No file IO.
    """
    if not isinstance(result, dict):
        result = {}
    src = result.get("source", "PAPER")
    window = result.get("window_days", 180)
    overall = result.get("overall") or _empty_aggregate()
    recs = result.get("recommendations") or []

    lines: list[str] = []
    lines.append("# Exit Quality Report")
    lines.append("")
    lines.append(
        "*Read-only post-mortem of closed paper / shadow trades. "
        "NEVER a recommendation for live trading.*"
    )
    lines.append("")
    lines.append(
        f"Source: **{src}**. Window: last {window} days. "
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}."
    )
    lines.append("")
    lines.append(f"## Overall (n={overall.get('n', 0)})")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Win rate | {overall.get('win_rate', 0.0)*100:.1f}% |")
    lines.append(f"| Avg MFE | {overall.get('avg_mfe_pct', 0.0)*100:.2f}% |")
    lines.append(f"| Avg MAE | {overall.get('avg_mae_pct', 0.0)*100:.2f}% |")
    lines.append(
        f"| Avg profit giveback | "
        f"{overall.get('avg_giveback_pct', 0.0)*100:.1f}% |"
    )
    se = overall.get("mean_stop_efficiency")
    te = overall.get("mean_target_efficiency")
    lines.append(
        f"| Mean stop efficiency | "
        f"{(f'{se:.2f}' if isinstance(se, (int, float)) else '–')} |"
    )
    lines.append(
        f"| Mean target efficiency | "
        f"{(f'{te:.2f}' if isinstance(te, (int, float)) else '–')} |"
    )
    lines.append(
        f"| Exit-too-early share | "
        f"{overall.get('share_exit_too_early', 0.0)*100:.1f}% |"
    )
    lines.append(
        f"| Exit-too-late share | "
        f"{overall.get('share_exit_too_late', 0.0)*100:.1f}% |"
    )
    lines.append(
        f"| Trailing-stop-would-help share | "
        f"{overall.get('share_trailing_helps', 0.0)*100:.1f}% |"
    )
    lines.append(
        f"| Avg time in trade | "
        f"{overall.get('avg_time_in_trade_minutes', 0.0):.0f} min |"
    )
    lines.append("")

    def _emit_breakdown(title: str, key: str) -> None:
        groups = result.get(key) or {}
        if not groups:
            return
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Bucket | n | WR | Giveback | Early | Late | Trail-helps |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for k in sorted(groups.keys()):
            a = groups[k]
            lines.append(
                f"| {k} | {a.get('n', 0)} | "
                f"{a.get('win_rate', 0.0)*100:.1f}% | "
                f"{a.get('avg_giveback_pct', 0.0)*100:.1f}% | "
                f"{a.get('share_exit_too_early', 0.0)*100:.1f}% | "
                f"{a.get('share_exit_too_late', 0.0)*100:.1f}% | "
                f"{a.get('share_trailing_helps', 0.0)*100:.1f}% |"
            )
        lines.append("")

    _emit_breakdown("Per strategy", "per_strategy")
    _emit_breakdown("Per symbol", "per_symbol")
    _emit_breakdown("Per regime", "per_regime")
    _emit_breakdown("Per confidence bucket", "per_confidence_bucket")

    lines.append("## Recommendations")
    lines.append("")
    if not recs:
        lines.append("_No bucket crossed a review threshold. Keep collecting "
                     "paper data._")
    else:
        for r in recs:
            lines.append(f"- {r}")
    lines.append("")
    lines.append(
        "> Recommendations are TOPICS FOR REVIEW. They are NOT runtime "
        "instructions. The edge gate is NEVER auto-flipped by this report."
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "EARLY_EXIT_GIVEBACK_THRESHOLD",
    "LATE_EXIT_OVERSHOOT_THRESHOLD",
    "TRAILING_STOP_TRAIL_PCT",
    "TRAILING_STOP_MIN_HOLD_MIN",
    "analyse_trade",
    "analyse_ledger",
    "render_report",
]

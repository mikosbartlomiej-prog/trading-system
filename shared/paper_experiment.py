"""v3.18.0 (2026-06-04) — Paper Trading Experiment Loop.

Closes audit-board STRAT-003 (backtest matrix evidence) + READINESS for
EDGE_GATE_ENABLED=true.

WHY
---
Trader feedback (audit-board 2026-06-02): EDGE_GATE_ENABLED is a binary
flag that gates everything downstream. The system has no honest empirical
evidence that any strategy generates positive expectancy after fees +
slippage in paper trading. The flag therefore stays false and the system
remains in OBSERVE_ONLY mode.

This module is the **paper-only** experiment ledger: a deterministic,
fee-and-slippage-aware accounting layer that watches paper trades, computes
per-strategy metrics over a rolling window, and feeds the Strategy Quality
Gate. **It never recommends live trading.** It never auto-enables anything.
It only summarises what HAPPENED, honestly.

CONTRACT
--------
- record_paper_trade(...) appends one closed-trade record to
  learning-loop/paper_experiments/<utc-date>.jsonl. Append-only.
- compute_strategy_metrics(strategy, window_days=180) reads the JSONL
  files for the window and returns a deterministic dict of metrics.
  Pure function. No external API calls. No live broker calls.
- generate_edge_evidence_report(...) renders a markdown summary across
  ALL registered strategies (via backtest.strategy_registry).

PAPER-ONLY GUARANTEE
--------------------
- The module name itself ("paper_experiment") is the contract.
- Every JSONL record carries `paper_only: true`.
- The Strategy Quality Gate refuses any status > EDGE_APPROVED_FOR_EXPERIMENT.
- No code path in this file calls the broker.

FAIL-SOFT
---------
- Missing JSONL file → return zero-counts dict (never raise).
- Malformed line → skip, never raise.
- Bad numeric input → coerce or drop; never propagate.
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

# v3.19.0 — Evidence Source Separation. Import is fail-soft because the
# module needs to keep working on a clean repo even before v3.19 ships
# everywhere; the local fallback re-implements just enough behaviour.
try:
    from evidence_source import EvidenceSource, is_paper_only, parse_source  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from shared.evidence_source import (  # type: ignore
            EvidenceSource, is_paper_only, parse_source,
        )
    except ImportError:  # pragma: no cover
        class EvidenceSource(str):  # type: ignore[no-redef]
            BACKTEST = "BACKTEST"
            REPLAY = "REPLAY"
            PAPER = "PAPER"

        def is_paper_only(s):  # type: ignore[no-redef]
            return (isinstance(s, str) and s.upper() == "PAPER")

        def parse_source(v, *, default="PAPER"):  # type: ignore[no-redef]
            if isinstance(v, str):
                u = v.strip().upper()
                if u in ("PAPER", "BACKTEST", "REPLAY"):
                    return u
            return default


# ─── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ledger_dir() -> Path:
    """Daily JSONL ledger directory. Overridable for tests.

    By default this is the **paper-only** ledger. BACKTEST records go
    under ``backtest_results/`` and REPLAY records under
    ``replay_results/`` — both ignored by edge-gate metrics.
    """
    return Path(
        os.environ.get("PAPER_EXPERIMENT_DIR")
        or _REPO_ROOT / "learning-loop" / "paper_experiments"
    )


def _backtest_dir() -> Path:
    """Directory for BACKTEST-source JSONL records (triage only)."""
    return Path(
        os.environ.get("BACKTEST_LEDGER_DIR")
        or _REPO_ROOT / "learning-loop" / "backtest_results"
    )


def _replay_dir() -> Path:
    """Directory for REPLAY-source JSONL records (triage + stress only)."""
    return Path(
        os.environ.get("REPLAY_LEDGER_DIR")
        or _REPO_ROOT / "learning-loop" / "replay_results"
    )


def _dir_for_source(source: Any) -> Path:
    """Return the ledger directory associated with a given source enum/str."""
    val = parse_source(source, default=EvidenceSource.PAPER)
    sv = val.value if hasattr(val, "value") else str(val).upper()
    if sv == "BACKTEST":
        return _backtest_dir()
    if sv == "REPLAY":
        return _replay_dir()
    return _ledger_dir()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_iso_ts(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        # tolerate ...Z suffix
        s2 = s.rstrip("Z")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


# ─── Public API: record_paper_trade ───────────────────────────────────────────

def record_paper_trade(
    strategy: str,
    symbol: str,
    entry: float,
    exit: float,                 # noqa: A002 — domain term ("exit price")
    qty: float,
    side: str,                   # "long" or "short"
    fees: float = 0.0,
    spread_at_entry: float = 0.0,
    slippage_at_entry: float = 0.0,
    regime: str | None = None,
    confidence_at_entry: float | None = None,
    opened_at: str | None = None,   # ISO 8601 UTC
    closed_at: str | None = None,   # ISO 8601 UTC
    *,
    source: Any = EvidenceSource.PAPER,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one closed trade to today's JSONL.

    v3.19.0 — accepts ``source`` (default PAPER) per Evidence Source
    Separation. BACKTEST and REPLAY records are written to *separate*
    ledger directories and are NEVER mixed into edge-gate metrics by
    default. ``paper_only`` is always True only for the PAPER ledger
    (the field is kept for backward compatibility of older readers).

    Fail-soft: invalid inputs are clamped / dropped, never raised. The
    function returns None.
    """
    try:
        src = parse_source(source, default=EvidenceSource.PAPER)
        sv = src.value if hasattr(src, "value") else str(src).upper()
        rec: dict[str, Any] = {
            "paper_only":         (sv == "PAPER"),
            "source":             sv,
            "strategy":           str(strategy or "unknown"),
            "symbol":             str(symbol or "?"),
            "entry":              _safe_float(entry),
            "exit":               _safe_float(exit),
            "qty":                _safe_float(qty),
            "side":               (str(side or "long")).lower(),
            "fees":               _safe_float(fees),
            "spread_at_entry":    _safe_float(spread_at_entry),
            "slippage_at_entry":  _safe_float(slippage_at_entry),
            "regime":             str(regime) if regime else None,
            "confidence_at_entry": _safe_float(confidence_at_entry) if confidence_at_entry is not None else None,
            "opened_at":          opened_at if isinstance(opened_at, str) else None,
            "closed_at":          closed_at if isinstance(closed_at, str) else
                                  datetime.now(timezone.utc).isoformat(),
        }
        # Compute gross / net PnL deterministically.
        gross = _compute_gross_pnl(rec)
        rec["gross_pnl"] = round(gross, 6)
        # Costs deducted: explicit fees + spread + slippage (both legs
        # of trade are *already* implied in spread/slippage if user passes
        # the round-trip estimate; we treat the supplied number as the
        # total round-trip cost in $).
        cost = abs(_safe_float(rec["fees"])) \
             + abs(_safe_float(rec["spread_at_entry"])) \
             + abs(_safe_float(rec["slippage_at_entry"]))
        rec["cost"] = round(cost, 6)
        rec["net_pnl"] = round(gross - cost, 6)
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in rec:
                    rec[str(k)] = v
        _append_line(rec, source=src)
    except Exception:
        # Hard guarantee: never raise from this module.
        return None


def _compute_gross_pnl(rec: dict) -> float:
    entry = _safe_float(rec.get("entry"))
    exit_ = _safe_float(rec.get("exit"))
    qty = _safe_float(rec.get("qty"))
    side = (rec.get("side") or "long").lower()
    if side == "short":
        return (entry - exit_) * qty
    return (exit_ - entry) * qty


def _append_line(rec: dict[str, Any], *,
                  source: Any = EvidenceSource.PAPER) -> None:
    d = _dir_for_source(source)
    _ensure_dir(d)
    iso = _utc_today().isoformat()
    path = d / f"{iso}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


# ─── Loader ───────────────────────────────────────────────────────────────────

def _iter_trades_in_window(window_days: int,
                            *,
                            source: Any = EvidenceSource.PAPER) -> Iterable[dict]:
    """Yield trade records whose `closed_at` falls in the last N days.

    v3.19.0 — defaults to the PAPER ledger directory. Pass ``source=``
    explicitly to iterate BACKTEST or REPLAY ledgers (those rows are
    NEVER counted toward edge-gate decisions).

    Fail-soft on missing dirs / malformed lines / bad dates.
    """
    d = _dir_for_source(source)
    if not d.exists():
        return
    today = _utc_today()
    earliest = today - timedelta(days=max(1, int(window_days)))
    for entry_path in sorted(d.glob("*.jsonl")):
        # Filename is YYYY-MM-DD.jsonl
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
                        # Fall back to file date if closed_at missing.
                        closed = datetime.combine(fd, datetime.min.time(), tzinfo=timezone.utc)
                    if closed.date() < earliest:
                        continue
                    yield rec
        except OSError:
            continue


def load_backtest_ledger(window_days: int = 180) -> list[dict]:
    """Read BACKTEST-source records from the dedicated ledger directory.

    Triage only. Returned records are NEVER used for edge-gate decisions.
    """
    return list(_iter_trades_in_window(window_days,
                                          source=EvidenceSource.BACKTEST))


def load_replay_ledger(window_days: int = 180) -> list[dict]:
    """Read REPLAY-source records from the dedicated ledger directory.

    Triage + stress only. Returned records are NEVER used for edge
    approval.
    """
    return list(_iter_trades_in_window(window_days,
                                          source=EvidenceSource.REPLAY))


def load_paper_ledger(window_days: int = 180) -> list[dict]:
    """Read PAPER-source records from the canonical ledger directory."""
    return list(_iter_trades_in_window(window_days,
                                          source=EvidenceSource.PAPER))


# ─── Metrics ──────────────────────────────────────────────────────────────────

def _empty_metrics(strategy: str, window_days: int) -> dict:
    return {
        "strategy":                       strategy,
        "window_days":                    window_days,
        "n_closed":                       0,
        "win_rate":                       0.0,
        "profit_factor":                  0.0,
        "expectancy":                     0.0,
        "avg_win":                        0.0,
        "avg_loss":                       0.0,
        "max_drawdown":                   0.0,
        "longest_losing_streak":          0,
        "net_pnl_after_fees_slippage":    0.0,
        "gross_pnl":                      0.0,
        "total_costs":                    0.0,
        "per_regime":                     {},
        "per_confidence_bucket":          {},
        "per_symbol":                     {},
        "per_time_window":                {},
        "last_20_win_rate":               0.0,
    }


def _confidence_bucket(conf: float | None) -> str:
    if conf is None:
        return "unknown"
    if conf < 0.50:
        return "low"
    if conf < 0.70:
        return "mid"
    return "high"


def _time_window_bucket(closed_at: str | None) -> str:
    """US market time-of-day bucket. Best-effort, fail-soft."""
    dt = _parse_iso_ts(closed_at)
    if dt is None:
        return "unknown"
    # Use UTC hour (rough proxy — operator can refine later):
    # 13:30-15:30 UTC = morning, 15:30-18:30 = midday, 18:30-20:00 = close
    h = dt.hour + dt.minute / 60.0
    if 13.5 <= h < 15.5:
        return "morning"
    if 15.5 <= h < 18.5:
        return "midday"
    if 18.5 <= h <= 20.0:
        return "close"
    return "other"


def _aggregate(records: list[dict]) -> dict:
    """Compute aggregate metrics from a list of trade records.

    All inputs assumed already filtered to a single bucket if the caller
    wants per-bucket stats. This function is the inner core of
    compute_strategy_metrics.
    """
    if not records:
        return {
            "n_closed":                       0,
            "win_rate":                       0.0,
            "profit_factor":                  0.0,
            "expectancy":                     0.0,
            "avg_win":                        0.0,
            "avg_loss":                       0.0,
            "max_drawdown":                   0.0,
            "longest_losing_streak":          0,
            "net_pnl_after_fees_slippage":    0.0,
            "gross_pnl":                      0.0,
            "total_costs":                    0.0,
            "last_20_win_rate":               0.0,
        }

    # Sort by closed_at to make streak + drawdown deterministic.
    def _sort_key(rec: dict) -> str:
        return rec.get("closed_at") or ""

    sorted_recs = sorted(records, key=_sort_key)

    nets = [_safe_float(r.get("net_pnl"), 0.0) for r in sorted_recs]
    grosses = [_safe_float(r.get("gross_pnl"), 0.0) for r in sorted_recs]
    costs = [_safe_float(r.get("cost"), 0.0) for r in sorted_recs]

    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p < 0]
    n = len(nets)

    win_rate = (len(wins) / n) if n else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0  # negative
    expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss

    gross_wins = sum(wins)
    gross_losses = -sum(losses)  # positive
    if gross_losses > 0:
        profit_factor = gross_wins / gross_losses
    elif gross_wins > 0:
        # No losses but some wins → undefined PF; use a very large but
        # finite value so consumers can sort. Cap at 999 to keep things sane.
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    # Equity curve max drawdown (peak-to-trough percent of peak),
    # built from net pnl cumulative sum.
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in nets:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        if peak > 0:
            dd = (peak - cumulative) / peak  # 0..1
            if dd > max_dd:
                max_dd = dd
        elif cumulative < 0:
            # If we've never had a positive peak, treat |drawdown| relative
            # to absolute value of trough as 100% conservative measure.
            denom = max(abs(cumulative), 1.0)
            dd = abs(cumulative) / denom
            if dd > max_dd:
                max_dd = dd

    # Longest losing streak (consecutive count of net_pnl <= 0)
    longest = 0
    current = 0
    for p in nets:
        if p <= 0:
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0

    last_20 = nets[-20:]
    last_20_wr = (
        (sum(1 for p in last_20 if p > 0) / len(last_20))
        if last_20 else 0.0
    )

    return {
        "n_closed":                       n,
        "win_rate":                       round(win_rate, 6),
        "profit_factor":                  round(profit_factor, 6),
        "expectancy":                     round(expectancy, 6),
        "avg_win":                        round(avg_win, 6),
        "avg_loss":                       round(avg_loss, 6),
        "max_drawdown":                   round(max_dd, 6),
        "longest_losing_streak":          longest,
        "net_pnl_after_fees_slippage":    round(sum(nets), 6),
        "gross_pnl":                      round(sum(grosses), 6),
        "total_costs":                    round(sum(costs), 6),
        "last_20_win_rate":               round(last_20_wr, 6),
    }


def compute_strategy_metrics(strategy: str, window_days: int = 180,
                             *,
                             source_filter: Any = EvidenceSource.PAPER) -> dict:
    """Return a deterministic dict of metrics for `strategy` over `window_days`.

    v3.19.0 — accepts ``source_filter`` (default PAPER). The function
    reads JSONL only and ENFORCES that records from a non-matching
    source are excluded from the aggregate. BACKTEST and REPLAY
    aggregates can be computed by callers that explicitly pass
    ``source_filter=EvidenceSource.BACKTEST`` etc., but the result is
    annotated with ``source_filter`` so downstream consumers know
    whether a metric is paper-only.

    Pure function: reads JSONL only. Fail-soft on missing file / bad data.
    """
    if not strategy or not isinstance(strategy, str):
        return _empty_metrics("?", window_days)
    window_days = max(1, _safe_int(window_days, 180))

    flt = parse_source(source_filter, default=EvidenceSource.PAPER)
    flt_val = flt.value if hasattr(flt, "value") else str(flt).upper()

    # Read from the dedicated ledger for the requested source. Then also
    # accept legacy rows in the PAPER ledger that predate the `source`
    # field (treated as PAPER per the EvidenceSource.parse_source default).
    candidates = list(_iter_trades_in_window(window_days, source=flt))
    records: list[dict] = []
    for r in candidates:
        if r.get("strategy") != strategy:
            continue
        rec_source = parse_source(r.get("source"), default=EvidenceSource.PAPER)
        rec_source_val = (
            rec_source.value if hasattr(rec_source, "value")
            else str(rec_source).upper()
        )
        if rec_source_val != flt_val:
            # Record landed in the wrong directory (legacy data) or has
            # an explicit different source field. EITHER way: refuse.
            continue
        records.append(r)
    base = _empty_metrics(strategy, window_days)
    base["source_filter"] = flt_val
    base.update(_aggregate(records))

    # ── per-regime breakdown ─────────────────────────────────────────────
    by_regime: dict[str, list[dict]] = {}
    for r in records:
        key = r.get("regime") or "unknown"
        by_regime.setdefault(str(key), []).append(r)
    base["per_regime"] = {
        k: _aggregate(v) for k, v in by_regime.items()
    }

    # ── per-confidence-bucket breakdown ─────────────────────────────────
    by_conf: dict[str, list[dict]] = {}
    for r in records:
        key = _confidence_bucket(r.get("confidence_at_entry"))
        by_conf.setdefault(key, []).append(r)
    base["per_confidence_bucket"] = {
        k: _aggregate(v) for k, v in by_conf.items()
    }

    # ── per-symbol breakdown ────────────────────────────────────────────
    by_sym: dict[str, list[dict]] = {}
    for r in records:
        key = r.get("symbol") or "?"
        by_sym.setdefault(str(key), []).append(r)
    base["per_symbol"] = {
        k: _aggregate(v) for k, v in by_sym.items()
    }

    # ── per-time-window breakdown ──────────────────────────────────────
    by_tw: dict[str, list[dict]] = {}
    for r in records:
        key = _time_window_bucket(r.get("closed_at"))
        by_tw.setdefault(key, []).append(r)
    base["per_time_window"] = {
        k: _aggregate(v) for k, v in by_tw.items()
    }

    return base


# ─── Report generator ─────────────────────────────────────────────────────────

def _strategies_for_report() -> list[str]:
    """List of strategy names to include in the report.

    Prefers the registry; falls back to whatever is in the ledger.
    """
    try:
        from backtest.strategy_registry import REGISTRY  # type: ignore
        return sorted(REGISTRY.keys())
    except Exception:
        names: set[str] = set()
        for r in _iter_trades_in_window(180):
            s = r.get("strategy")
            if isinstance(s, str):
                names.add(s)
        return sorted(names)


def generate_edge_evidence_report(out_path: str | None = None,
                                  window_days: int = 180) -> str:
    """Render a markdown report summarising every strategy's evidence.

    Optionally writes to `out_path`. Returns the markdown string.
    """
    try:
        from backtest.strategy_registry import REGISTRY, NOT_APPLICABLE  # type: ignore
        registry = REGISTRY
        not_applicable_tag = NOT_APPLICABLE
    except Exception:
        registry = {}
        not_applicable_tag = "NOT_APPLICABLE"

    # Lazy import — avoid circular dep at module load time
    try:
        from strategy_quality_gate import classify_strategy  # type: ignore
    except Exception:
        try:
            from shared.strategy_quality_gate import classify_strategy  # type: ignore
        except Exception:
            classify_strategy = None  # type: ignore

    lines: list[str] = []
    lines.append("# Edge Evidence Report (paper trading)")
    lines.append("")
    lines.append(
        "*Paper trading only. This report summarises empirical edge evidence "
        "based on closed paper trades. No statement here is a recommendation "
        "for live trading.*"
    )
    lines.append("")
    lines.append(f"Window: last {window_days} days. "
                 f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}.")
    lines.append("")
    lines.append("| Strategy | n_closed | WR | PF | Expectancy | NetPnL | MaxDD | Regimes | Status |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")

    names = sorted(registry.keys()) if registry else _strategies_for_report()
    for name in names:
        reg = registry.get(name) if registry else None
        if reg is not None and getattr(reg, "readiness", None) == not_applicable_tag:
            lines.append(f"| {name} | – | – | – | – | – | – | – | DISABLED (NOT_APPLICABLE) |")
            continue
        m = compute_strategy_metrics(name, window_days=window_days)
        status = "OBSERVE_ONLY"
        if classify_strategy is not None:
            try:
                status = classify_strategy(name, m, paper_metrics=m,
                                            audit_complete=True)
            except Exception:
                status = "OBSERVE_ONLY"
        regimes = ",".join(sorted(m.get("per_regime", {}).keys())) or "–"
        lines.append(
            f"| {name} | {m['n_closed']} | "
            f"{m['win_rate']*100:.1f}% | "
            f"{m['profit_factor']:.2f} | "
            f"{m['expectancy']:+.4f} | "
            f"{m['net_pnl_after_fees_slippage']:+.2f} | "
            f"{m['max_drawdown']*100:.1f}% | "
            f"{regimes} | {status} |"
        )

    lines.append("")
    lines.append("Strategy Quality Gate statuses:")
    lines.append("- **DISABLED** — registered as NOT_APPLICABLE or live-degraded.")
    lines.append("- **OBSERVE_ONLY** — n_closed < 10.")
    lines.append("- **PAPER_CANDIDATE** — 10 ≤ n < 50.")
    lines.append("- **PAPER_ENABLED** — n ≥ 30 + PF ≥ 1.0.")
    lines.append("- **EDGE_CANDIDATE** — n ≥ 50 + PF ≥ 1.1 but missing regime stability.")
    lines.append("- **EDGE_APPROVED_FOR_EXPERIMENT** — meets all empirical criteria.")
    lines.append("- **REJECTED** — audit incomplete or recent risk violations.")
    lines.append("")
    lines.append("> EDGE_GATE_ENABLED is NEVER auto-flipped by this report.")

    md = "\n".join(lines) + "\n"
    if out_path:
        try:
            p = Path(out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(md, encoding="utf-8")
        except Exception:
            pass
    return md


__all__ = [
    "record_paper_trade",
    "compute_strategy_metrics",
    "generate_edge_evidence_report",
    # v3.19.0 — Evidence Source Separation
    "load_backtest_ledger",
    "load_replay_ledger",
    "load_paper_ledger",
]

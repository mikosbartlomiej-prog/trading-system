#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Near-miss seeder from REAL local evidence.

Reads three sources of evidence and emits NearMiss rows when a
strategy-specific gating metric is within ``NEAR_MISS_WINDOW_PCT`` of
the documented threshold:

1. ``learning-loop/opportunity_ledger/*.jsonl`` (last 7 days) →
   source label ``REAL_MARKET_NEAR_MISS``.
2. ``learning-loop/replay_discovery_latest.json`` (per-pair RSI
   recompute from backfill snapshots) → source label
   ``REPLAY_NEAR_MISS``.
3. ``learning-loop/backfill_snapshots/*.json`` (RSI walk over every
   bar in lookback window) → source label ``BACKFILL_NEAR_MISS``.

Each row written to ``learning-loop/near_miss/<YYYY-MM-DD>.jsonl``
matches the schema produced by
``shared/near_miss_tracker.record_near_miss`` plus a ``source``
field for downstream reporting.

HARD SAFETY (test-asserted)
---------------------------
- NEVER imports ``alpaca_orders`` / ``requests`` / ``urllib`` / sockets.
- NEVER places orders. NEVER counts as paper / shadow evidence.
- ``is_paper_trade=False`` AND ``is_signal=False`` AND
  ``is_real_market_opportunity=False`` hard-coded on every row.
- NEVER auto-adjusts a strategy threshold; only persists observations.
- Honest verdict ``NO_LOCAL_EVIDENCE_AVAILABLE`` when sources are empty.

USAGE
-----
::

    python3 scripts/seed_near_miss_from_evidence.py
    python3 scripts/build_near_miss_report.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
REPLAY_DISCOVERY_PATH = (
    REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
)
BACKFILL_DIR = REPO_ROOT / "learning-loop" / "backfill_snapshots"

NEAR_MISS_DIR_DEFAULT = REPO_ROOT / "learning-loop" / "near_miss"
STATUS_MD_PATH = REPO_ROOT / "docs" / "NEAR_MISS_STATUS.md"  # rebuilt elsewhere

VERSION = "v3.27.0"

# ─── Standing markers ─────────────────────────────────────────────────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "NEAR_MISS_NEVER_COUNTS_AS_TRADE",
    "NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS",
    "SEEDER_DOES_NOT_FETCH_NETWORK",
    "SEEDER_DOES_NOT_FABRICATE_OHLCV",
)

# Allowed source labels (the test asserts every row carries one of these).
SOURCE_REAL_MARKET = "REAL_MARKET_NEAR_MISS"
SOURCE_REPLAY = "REPLAY_NEAR_MISS"
SOURCE_BACKFILL = "BACKFILL_NEAR_MISS"
ALLOWED_SOURCES: frozenset[str] = frozenset({
    SOURCE_REAL_MARKET, SOURCE_REPLAY, SOURCE_BACKFILL,
})

# Default capture window — fraction of |threshold|. Matches
# NEAR_MISS_WINDOW_RATIO_DEFAULT in shared/near_miss_tracker.py.
NEAR_MISS_WINDOW_PCT = 0.15


# Strategy threshold catalogue. Each entry:
#   (metric_name, threshold_value, direction)
# direction == "above" → trigger when metric > threshold;
#              "below" → trigger when metric < threshold.
STRATEGY_THRESHOLDS: dict[str, tuple[str, float, str]] = {
    "crypto-oversold-bounce": ("rsi",          30.0, "below"),
    "crypto-momentum":        ("rsi",          60.0, "above"),
    "momentum-long":          ("breakout_pct",  0.02, "above"),
    "momentum-long-loose":    ("breakout_pct",  0.02, "above"),
    "overbought-short":       ("rsi",          72.0, "above"),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True, check=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:        # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def _safe_read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _within_window(
    current: float, threshold: float, direction: str,
    *, window_pct: float = NEAR_MISS_WINDOW_PCT,
) -> bool:
    """Within distance bound AND did NOT trigger.

    Above-direction near-miss: current < threshold AND dist <= window.
    Below-direction near-miss: current > threshold AND dist <= window.
    """
    if threshold == 0.0:
        return False
    dist_pct = abs(current - threshold) / abs(threshold)
    if dist_pct > window_pct:
        return False
    if direction == "above":
        return current < threshold
    if direction == "below":
        return current > threshold
    return False


# ─── RSI helper (lazy import) ─────────────────────────────────────────────────


_strategies_mod = None


def _load_strategies_module():
    """Lazy-load backtest.strategies for ``_rsi``. No network — pure stdlib."""
    global _strategies_mod
    if _strategies_mod is not None:
        return _strategies_mod
    added = []
    for p in (str(REPO_ROOT), str(REPO_ROOT / "backtest")):
        if p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    try:
        try:
            from backtest import strategies as sm    # type: ignore
        except ImportError:
            import strategies as sm                  # type: ignore
        _strategies_mod = sm
        return sm
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


# ─── Source 1: opportunity_ledger ─────────────────────────────────────────────


def collect_real_market_near_misses(
    *,
    base_dir: Path = LEDGER_DIR,
    as_of: Optional[datetime] = None,
    lookback_days: int = 7,
) -> list[dict]:
    """Walk last 7 days of ledger JSONLs, emit near-miss rows.

    A ledger row qualifies if its ``raw_signal`` carries a metric
    value (e.g. ``rsi``) that is within ``NEAR_MISS_WINDOW_PCT`` of
    the strategy's documented threshold but did NOT trigger.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    rows: list[dict] = []
    if not base_dir.exists():
        return rows
    for delta in range(lookback_days):
        d = (as_of - timedelta(days=delta)).date().isoformat()
        f = base_dir / f"{d}.jsonl"
        if not f.exists():
            continue
        try:
            with f.open(encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    nm = _maybe_real_market_near_miss(rec)
                    if nm is not None:
                        rows.append(nm)
        except OSError:
            continue
    return rows


def _maybe_real_market_near_miss(rec: dict) -> Optional[dict]:
    if not isinstance(rec, dict):
        return None
    strategy = rec.get("strategy")
    symbol = rec.get("symbol")
    raw = rec.get("raw_signal")
    if (not isinstance(strategy, str)
            or not isinstance(symbol, str)
            or not isinstance(raw, dict)):
        return None
    if strategy not in STRATEGY_THRESHOLDS:
        return None
    metric_name, threshold, direction = STRATEGY_THRESHOLDS[strategy]
    current = _safe_float(raw.get(metric_name))
    if current is None:
        return None
    if not _within_window(current, threshold, direction):
        return None
    return _make_row(
        strategy_id=strategy,
        symbol=symbol,
        metric_name=metric_name,
        current_value=current,
        threshold=threshold,
        timestamp_iso=rec.get("timestamp") or _utc_now_iso(),
        source=SOURCE_REAL_MARKET,
    )


# ─── Source 2: replay_discovery_latest.json ───────────────────────────────────


def collect_replay_near_misses(
    *,
    replay_path: Path = REPLAY_DISCOVERY_PATH,
    backfill_dir: Path = BACKFILL_DIR,
    max_per_pair: int = 60,
) -> list[dict]:
    """Re-walk each (strategy, symbol) bar series from the backfill
    snapshots and emit near-miss rows when RSI is within window. The
    replay_discovery_latest.json only stores counts, so we recompute
    RSI here for full row detail.
    """
    rep = _safe_read_json(replay_path)
    if not isinstance(rep, dict):
        return []
    rows_meta = rep.get("rows")
    if not isinstance(rows_meta, list):
        return []

    sm = _load_strategies_module()
    if sm is None:
        return []

    out: list[dict] = []
    for r in rows_meta:
        if not isinstance(r, dict):
            continue
        strategy = r.get("strategy")
        symbol = r.get("symbol")
        if not isinstance(strategy, str) or not isinstance(symbol, str):
            continue
        if strategy not in STRATEGY_THRESHOLDS:
            continue
        metric_name, threshold, direction = STRATEGY_THRESHOLDS[strategy]
        # Reload bars from backfill snapshot (compatible with seeder layout)
        snap_path = backfill_dir / f"{_safe_symbol_to_filename(symbol)}.json"
        bars = _safe_read_json(snap_path)
        if not isinstance(bars, dict):
            continue
        closes = bars.get("close")
        times = bars.get("time")
        if not isinstance(closes, list) or len(closes) < 14:
            continue

        emitted = 0
        for idx in range(14, len(closes)):
            try:
                rsi = sm._rsi(closes[:idx + 1])
            except Exception:
                continue
            if rsi is None:
                continue
            # Only RSI-style metrics here; breakout-pct metrics need
            # high/low which the partial snapshots don't carry.
            if metric_name != "rsi":
                continue
            if not _within_window(float(rsi), threshold, direction):
                continue
            ts = (times[idx] if isinstance(times, list) and idx < len(times)
                  else _utc_now_iso())
            out.append(_make_row(
                strategy_id=strategy,
                symbol=symbol,
                metric_name=metric_name,
                current_value=float(rsi),
                threshold=threshold,
                timestamp_iso=str(ts),
                source=SOURCE_REPLAY,
            ))
            emitted += 1
            if emitted >= max_per_pair:
                break
    return out


def _safe_symbol_to_filename(symbol: str) -> str:
    """Mirror the snapshot seeder's filename rule (/ → __)."""
    return symbol.replace("/", "__")


# ─── Source 3: backfill_snapshots/*.json (volume + RSI walk) ─────────────────


def collect_backfill_near_misses(
    *,
    backfill_dir: Path = BACKFILL_DIR,
    max_per_pair: int = 40,
) -> list[dict]:
    """Walk every snapshot file and emit near-miss rows.

    This catches symbols that did NOT appear in the replay output
    (e.g. because the replay strategy filtered them out structurally
    on volume/breakout requirements). Pure RSI proximity.
    """
    if not backfill_dir.exists():
        return []

    sm = _load_strategies_module()
    if sm is None:
        return []

    out: list[dict] = []
    for snap_file in sorted(backfill_dir.glob("*.json")):
        bars = _safe_read_json(snap_file)
        if not isinstance(bars, dict):
            continue
        meta = bars.get("__seed_meta__") or {}
        if not isinstance(meta, dict):
            meta = {}
        symbol = meta.get("symbol") or snap_file.stem.replace("__", "/")
        closes = bars.get("close")
        times = bars.get("time")
        if not isinstance(closes, list) or len(closes) < 14:
            continue

        asset_class = (
            "crypto" if isinstance(symbol, str) and "/" in symbol
            else "us_equity"
        )
        # Filter strategies whose asset class matches.
        eligible_strats: list[str] = []
        for sid, (mname, _thr, _dir) in STRATEGY_THRESHOLDS.items():
            if mname != "rsi":
                continue
            if sid.startswith("crypto-") and asset_class != "crypto":
                continue
            if not sid.startswith("crypto-") and asset_class != "us_equity":
                continue
            eligible_strats.append(sid)
        if not eligible_strats:
            continue

        for strategy in eligible_strats:
            metric_name, threshold, direction = STRATEGY_THRESHOLDS[strategy]
            emitted = 0
            for idx in range(14, len(closes)):
                try:
                    rsi = sm._rsi(closes[:idx + 1])
                except Exception:
                    continue
                if rsi is None:
                    continue
                if not _within_window(float(rsi), threshold, direction):
                    continue
                ts = (times[idx] if isinstance(times, list) and idx < len(times)
                      else _utc_now_iso())
                out.append(_make_row(
                    strategy_id=strategy,
                    symbol=symbol,
                    metric_name=metric_name,
                    current_value=float(rsi),
                    threshold=threshold,
                    timestamp_iso=str(ts),
                    source=SOURCE_BACKFILL,
                ))
                emitted += 1
                if emitted >= max_per_pair:
                    break
    return out


# ─── Row constructor (HARD invariants enforced here) ─────────────────────────


def _make_row(
    *,
    strategy_id: str,
    symbol: str,
    metric_name: str,
    current_value: float,
    threshold: float,
    timestamp_iso: str,
    source: str,
) -> dict:
    """Build the canonical near-miss row. ALL HARD invariants
    hard-coded — callers cannot override."""
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"refusing to build row with non-whitelisted source={source!r}"
        )
    return {
        "strategy_id":                str(strategy_id),
        "symbol":                     str(symbol),
        "metric_name":                str(metric_name),
        "current_value":              float(current_value),
        "threshold":                  float(threshold),
        "distance_to_trigger":        float(current_value) - float(threshold),
        "timestamp_iso":              str(timestamp_iso),
        "source":                     source,
        # HARD INVARIANTS — never overridable.
        "is_paper_trade":             False,
        "is_signal":                  False,
        "is_real_market_opportunity": False,
    }


# ─── Persistence ──────────────────────────────────────────────────────────────


def write_rows(
    rows: list[dict],
    *,
    near_miss_dir: Path = NEAR_MISS_DIR_DEFAULT,
    date_iso: Optional[str] = None,
) -> tuple[Path, int]:
    """Append rows to ``<near_miss_dir>/<YYYY-MM-DD>.jsonl``."""
    _ensure_dir(near_miss_dir)
    if date_iso is None:
        date_iso = _utc_today_iso()
    target = near_miss_dir / f"{date_iso}.jsonl"
    written = 0
    try:
        with target.open("a", encoding="utf-8") as f:
            for r in rows:
                # Defensive: re-stamp hard invariants on every write.
                r["is_paper_trade"] = False
                r["is_signal"] = False
                r["is_real_market_opportunity"] = False
                f.write(json.dumps(r, sort_keys=True) + "\n")
                written += 1
    except OSError:
        # Fail-soft per HARD safety — caller still sees count from
        # the rows list (no need to break the rest of the pipeline).
        return target, written
    return target, written


# ─── Orchestration ────────────────────────────────────────────────────────────


def run(
    *,
    near_miss_dir: Path = NEAR_MISS_DIR_DEFAULT,
    ledger_dir: Path = LEDGER_DIR,
    replay_path: Path = REPLAY_DISCOVERY_PATH,
    backfill_dir: Path = BACKFILL_DIR,
    as_of: Optional[datetime] = None,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Top-level entry — read all sources, write rows, return summary."""
    real_rows = collect_real_market_near_misses(
        base_dir=ledger_dir, as_of=as_of, lookback_days=lookback_days,
    )
    replay_rows = collect_replay_near_misses(
        replay_path=replay_path, backfill_dir=backfill_dir,
    )
    backfill_rows = collect_backfill_near_misses(
        backfill_dir=backfill_dir,
    )

    all_rows = real_rows + replay_rows + backfill_rows
    target, written = write_rows(all_rows, near_miss_dir=near_miss_dir)

    by_source: Counter[str] = Counter(r["source"] for r in all_rows)
    by_strategy: Counter[str] = Counter(r["strategy_id"] for r in all_rows)

    if not all_rows:
        verdict = "NO_LOCAL_EVIDENCE_AVAILABLE"
    else:
        verdict = "NEAR_MISSES_SEEDED"

    summary = {
        "version":          VERSION,
        "generated_at_iso": _utc_now_iso(),
        "git_head":         _git_head(),
        "verdict":          verdict,
        "rows_written":     int(written),
        "rows_total":       len(all_rows),
        "by_source":        dict(by_source),
        "by_strategy":      dict(by_strategy),
        "target_path":      str(target),
        "standing_markers": list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":          False,
            "allow_broker_paper":         False,
            "live_trading_supported":     False,
            "fabricates_data":            False,
            "fetches_network":            False,
            "places_orders":              False,
            "writes_opportunity_ledger":  False,
            "writes_state_json":          False,
            "auto_adjusts_thresholds":    False,
        },
    }
    return summary


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--near-miss-dir", type=Path, default=NEAR_MISS_DIR_DEFAULT,
        help="Output directory for daily near_miss JSONLs",
    )
    parser.add_argument(
        "--ledger-dir", type=Path, default=LEDGER_DIR,
        help="opportunity_ledger source directory",
    )
    parser.add_argument(
        "--replay", type=Path, default=REPLAY_DISCOVERY_PATH,
        help="replay_discovery_latest.json path",
    )
    parser.add_argument(
        "--backfill-dir", type=Path, default=BACKFILL_DIR,
        help="backfill_snapshots directory",
    )
    parser.add_argument("--lookback-days", type=int, default=7)
    args = parser.parse_args(argv)

    summary = run(
        near_miss_dir=args.near_miss_dir,
        ledger_dir=args.ledger_dir,
        replay_path=args.replay,
        backfill_dir=args.backfill_dir,
        lookback_days=args.lookback_days,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

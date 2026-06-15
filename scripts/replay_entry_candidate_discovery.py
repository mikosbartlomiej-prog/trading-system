#!/usr/bin/env python3
"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 5 — Replay entry-candidate discovery.

Reads cached daily-bar snapshots from ``learning-loop/backfill_snapshots/<symbol>.json``
and runs pure-function strategy signals against them to surface:

  * candidates       — bars where the signal function returned a non-None dict
  * near_misses      — bars where the signal returned None but the relevant
                       metric (RSI, volume, etc.) was within 15% of the
                       threshold band (heuristic, strategy-specific)
  * threshold_crosses — bars where a threshold was met but a co-condition failed

EVERY emitted record carries ``evidence_source="REPLAY"`` — NEVER ``PAPER``
or ``REAL_MARKET_DATA``.

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER fetches live market data. If a snapshot file is missing it
  emits a `MISSING_SNAPSHOT` diagnostic and skips.
- NEVER writes to ``learning-loop/opportunity_ledger``.
- NEVER counts toward shadow eligibility, paper_experiments, or
  real_market_opportunities.
- NEVER makes network calls. NEVER imports ``alpaca_orders``.
- NEVER modifies state.json or runtime_state.json.
- Standing markers footer reproduced in every artefact.

Outputs:

- ``learning-loop/replay_discovery_latest.json``
- ``docs/REPLAY_ENTRY_CANDIDATE_DISCOVERY.md``
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR_DEFAULT = REPO_ROOT / "learning-loop" / "backfill_snapshots"
LATEST_JSON_PATH = REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
LATEST_MD_PATH = REPO_ROOT / "docs" / "REPLAY_ENTRY_CANDIDATE_DISCOVERY.md"

# ─── Standing markers ─────────────────────────────────────────────────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "REPLAY_NEVER_COUNTS_AS_PAPER",
    "REPLAY_NEVER_COUNTS_AS_REAL_MARKET",
    "REPLAY_NEVER_AUTO_ENABLES_STRATEGY",
)

VERSION = "v3.26.0"
NEAR_MISS_TOLERANCE = 0.15  # 15% of threshold band

# Default universe — mirrors shared/market_data_provider.py.
DEFAULT_EQUITY_UNIVERSE: tuple[str, ...] = (
    "SPY", "QQQ", "GLD", "AMD", "CRWD", "NOW", "PANW", "ORCL",
)
DEFAULT_CRYPTO_UNIVERSE: tuple[str, ...] = (
    "BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD",
)


# ─── Strategy registry view (replay-eligible only) ────────────────────────────


@dataclass(frozen=True)
class ReplayStrategy:
    name: str
    signal_fn_name: str
    asset_class: str  # "us_equity" | "crypto"


REPLAY_STRATEGIES: tuple[ReplayStrategy, ...] = (
    ReplayStrategy("momentum-long",
                   "momentum_long_signal_at",       "us_equity"),
    ReplayStrategy("momentum-long-loose",
                   "momentum_long_loose_signal_at", "us_equity"),
    ReplayStrategy("overbought-short",
                   "overbought_short_signal_at",    "us_equity"),
    ReplayStrategy("crypto-momentum",
                   "crypto_momentum_signal_at",     "crypto"),
    ReplayStrategy("crypto-oversold-bounce",
                   "crypto_oversold_bounce_signal_at", "crypto"),
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


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


def _load_strategies_module():
    """Import the pure-function backtest strategies module from disk.

    We add REPO_ROOT to sys.path so ``import backtest.strategies`` works
    when this script is invoked from anywhere.
    """
    added = False
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
        added = True
    try:
        from backtest import strategies as strategies_mod  # type: ignore
        return strategies_mod
    finally:
        if added:
            try:
                sys.path.remove(str(REPO_ROOT))
            except ValueError:
                pass


def _read_snapshot(symbol: str, snapshot_dir: Path) -> Optional[dict]:
    """Read a cached bar snapshot for `symbol`.

    Returns None if the file is missing or the JSON is malformed. NEVER
    fetches live data.
    """
    # Stocks: file name == symbol. Crypto: replace "/" with "_".
    safe = symbol.replace("/", "_")
    path = snapshot_dir / f"{safe}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _bars_length(bars: dict) -> int:
    if not isinstance(bars, dict):
        return 0
    closes = bars.get("close")
    if not isinstance(closes, list):
        return 0
    return len(closes)


def _rsi_distance_to_band(
    bars: dict, idx: int, rsi_min: float, rsi_max: float,
) -> Optional[float]:
    """Distance from current RSI to the nearest band edge, as a ratio of
    the band width. Returns None if RSI cannot be computed.
    """
    if idx < 14:
        return None
    sm = _load_strategies_module()
    try:
        rsi = sm._rsi(bars["close"][:idx + 1])
    except Exception:
        return None
    if rsi is None:
        return None
    if rsi_min <= rsi <= rsi_max:
        return 0.0
    width = max(1.0, rsi_max - rsi_min)
    if rsi < rsi_min:
        return (rsi_min - rsi) / width
    return (rsi - rsi_max) / width


# ─── Replay per-strategy ───────────────────────────────────────────────────────


def _replay_one_symbol_one_strategy(
    strategy: ReplayStrategy,
    symbol: str,
    bars: dict,
    *,
    lookback_days: int,
    sm,
) -> dict:
    """Return aggregate counts + a small list of candidate records for one
    (strategy, symbol) pair. Pure compute. Every emitted candidate record
    carries ``evidence_source=REPLAY``.
    """
    fn = getattr(sm, strategy.signal_fn_name, None)
    if not callable(fn):
        return {
            "strategy":        strategy.name,
            "symbol":          symbol,
            "asset_class":     strategy.asset_class,
            "bars_total":      _bars_length(bars),
            "bars_replayed":   0,
            "candidates":      0,
            "near_misses":     0,
            "threshold_crosses": 0,
            "candidate_records": [],
            "diagnostic":      f"NO_SIGNAL_FN:{strategy.signal_fn_name}",
        }

    n = _bars_length(bars)
    if n == 0:
        return {
            "strategy":        strategy.name,
            "symbol":          symbol,
            "asset_class":     strategy.asset_class,
            "bars_total":      0,
            "bars_replayed":   0,
            "candidates":      0,
            "near_misses":     0,
            "threshold_crosses": 0,
            "candidate_records": [],
            "diagnostic":      "EMPTY_BARS",
        }

    # Restrict replay window to lookback_days (or full series if smaller).
    start_idx = max(0, n - int(lookback_days))
    candidates: list[dict] = []
    candidate_count = 0
    near_miss_count = 0
    threshold_cross_count = 0

    # Strategy-specific near-miss helpers — we use RSI distance as the
    # canonical near-miss heuristic for all strategies. Each strategy
    # exposes an RSI band (or single threshold).
    if strategy.name == "momentum-long":
        rsi_min, rsi_max = sm.RSI_LONG_MIN, sm.RSI_LONG_MAX
    elif strategy.name == "momentum-long-loose":
        rsi_min, rsi_max = sm.LOOSE_RSI_LONG_MIN, sm.LOOSE_RSI_LONG_MAX
    elif strategy.name == "overbought-short":
        # Single threshold: > 72. Treat as a half-open band.
        rsi_min, rsi_max = sm.RSI_SHORT_MIN, 100.0
    elif strategy.name == "crypto-momentum":
        rsi_min = float(getattr(sm, "CRYPTO_RSI_LONG_MIN", 50.0))
        rsi_max = float(getattr(sm, "CRYPTO_RSI_LONG_MAX_DEFAULT", 70.0))
    elif strategy.name == "crypto-oversold-bounce":
        rsi_min, rsi_max = 0.0, 30.0  # deep-oversold band
    else:
        rsi_min, rsi_max = 0.0, 100.0  # safe default

    last_close = None
    for idx in range(start_idx, n):
        try:
            result = fn(idx, bars)
        except Exception as exc:  # never fatal — replay must not crash
            result = {"_replay_error": str(exc)}

        if result and isinstance(result, dict) and "_replay_error" not in result:
            candidate_count += 1
            # Cap stored record list to last 5 to keep artifact compact.
            rec = {
                "idx":             idx,
                "strategy":        strategy.name,
                "symbol":          symbol,
                "asset_class":     strategy.asset_class,
                "action":          result.get("action"),
                "entry_price":     result.get("entry_price"),
                "stop_loss":       result.get("stop_loss"),
                "take_profit":     result.get("take_profit"),
                "rsi":             result.get("rsi"),
                "evidence_source": "REPLAY",
                "is_paper_trade":  False,
                "is_real_market":  False,
                "is_signal_observation": False,
                "snapshot_source":       "backfill_snapshots",
                "replay_version":        VERSION,
            }
            candidates.append(rec)
            continue

        # Near-miss check via RSI band distance.
        dist = _rsi_distance_to_band(bars, idx, rsi_min, rsi_max)
        if dist is not None and 0.0 < dist <= NEAR_MISS_TOLERANCE:
            near_miss_count += 1

        # Threshold-cross check: did close cross the 20-bar high but
        # volume/co-condition prevented entry? Cheap heuristic.
        try:
            closes = bars["close"][:idx + 1]
            highs = bars["high"][:idx + 1]
            if idx >= 22:
                cur = closes[-1]
                high_20 = max(highs[-21:-1])
                if cur > high_20:
                    threshold_cross_count += 1
        except Exception:
            pass
        last_close = bars.get("close", [None])[idx] if n > idx else None

    # Trim candidates to last 5 (most recent) for compact artifact.
    candidates_trimmed = candidates[-5:]

    return {
        "strategy":          strategy.name,
        "symbol":            symbol,
        "asset_class":       strategy.asset_class,
        "bars_total":        n,
        "bars_replayed":     max(0, n - start_idx),
        "candidates":        candidate_count,
        "near_misses":       near_miss_count,
        "threshold_crosses": threshold_cross_count,
        "candidate_records": candidates_trimmed,
        "diagnostic":        "OK",
    }


# ─── Build report ─────────────────────────────────────────────────────────────


def build_report(
    *,
    as_of: datetime,
    lookback_days: int = 7,
    snapshot_dir: Path | None = None,
    strategies_filter: tuple[str, ...] | None = None,
    universe: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run replay across (strategy x symbol) pairs and aggregate.

    Pure function — no network, no file writes.
    """
    sd = snapshot_dir if snapshot_dir is not None else SNAPSHOT_DIR_DEFAULT
    sm = _load_strategies_module()

    strategies = [
        s for s in REPLAY_STRATEGIES
        if strategies_filter is None or s.name in strategies_filter
    ]

    # Default universe = equities + crypto.
    if universe is None:
        universe_tuple = tuple(DEFAULT_EQUITY_UNIVERSE + DEFAULT_CRYPTO_UNIVERSE)
    else:
        universe_tuple = tuple(universe)

    rows: list[dict] = []
    missing_snapshots: list[str] = []
    total_candidates = 0
    total_near_misses = 0
    total_threshold_crosses = 0

    for symbol in universe_tuple:
        bars = _read_snapshot(symbol, sd)
        if bars is None:
            missing_snapshots.append(symbol)
            continue
        for strategy in strategies:
            # Filter out asset_class mismatches.
            is_crypto = "/" in symbol
            if strategy.asset_class == "us_equity" and is_crypto:
                continue
            if strategy.asset_class == "crypto" and not is_crypto:
                continue

            row = _replay_one_symbol_one_strategy(
                strategy, symbol, bars,
                lookback_days=lookback_days, sm=sm,
            )
            rows.append(row)
            total_candidates += int(row["candidates"])
            total_near_misses += int(row["near_misses"])
            total_threshold_crosses += int(row["threshold_crosses"])

    return {
        "version":              VERSION,
        "generated_at_iso":     datetime.now(timezone.utc).isoformat(),
        "as_of":                as_of.isoformat(),
        "git_head":             _git_head(),
        "lookback_days":        lookback_days,
        "snapshot_dir":         str(sd.relative_to(REPO_ROOT)
                                    if sd.is_absolute()
                                    and str(sd).startswith(str(REPO_ROOT))
                                    else sd),
        "universe":             list(universe_tuple),
        "strategies_considered": [s.name for s in strategies],
        "missing_snapshots":    missing_snapshots,
        "totals": {
            "candidates":        total_candidates,
            "near_misses":       total_near_misses,
            "threshold_crosses": total_threshold_crosses,
            "rows":              len(rows),
        },
        "rows":                 rows,
        "standing_markers":     list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":         False,
            "allow_broker_paper":        False,
            "live_trading_supported":    False,
            "modifies_state_json":       False,
            "writes_opportunity_ledger": False,
            "auto_enables_strategy":     False,
            "evidence_source":           "REPLAY",
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Replay entry-candidate discovery ({rep['version']})")
    lines.append("")
    lines.append(f"**Generated:** `{rep['generated_at_iso']}`")
    lines.append(f"**As of:** `{rep['as_of']}`")
    lines.append(f"**Git HEAD:** `{rep['git_head']}`")
    lines.append(f"**Lookback days:** `{rep['lookback_days']}`")
    lines.append(f"**Snapshot dir:** `{rep['snapshot_dir']}`")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    t = rep["totals"]
    lines.append(f"- Candidates (replay): **{t['candidates']}**")
    lines.append(f"- Near-misses (within 15%): **{t['near_misses']}**")
    lines.append(f"- Threshold crosses: **{t['threshold_crosses']}**")
    lines.append(f"- (strategy, symbol) pairs scanned: **{t['rows']}**")
    if rep["missing_snapshots"]:
        lines.append("")
        lines.append("## Missing snapshots")
        lines.append("")
        lines.append(
            "These symbols have no cached bars at "
            f"`{rep['snapshot_dir']}`. Replay skipped — NEVER fetched live."
        )
        lines.append("")
        for sym in rep["missing_snapshots"]:
            lines.append(f"- `{sym}` (MISSING_SNAPSHOT)")

    lines.append("")
    lines.append("## Per strategy + symbol")
    lines.append("")
    lines.append("| Strategy | Symbol | Asset | Bars | Replayed | Cands | Near | Cross | Diag |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    if not rep["rows"]:
        lines.append("| (no rows — no snapshots or universe empty) | | | | | | | | |")
    for r in rep["rows"]:
        lines.append(
            f"| `{r['strategy']}` | `{r['symbol']}` | {r['asset_class']} "
            f"| {r['bars_total']} | {r['bars_replayed']} | "
            f"{r['candidates']} | {r['near_misses']} | "
            f"{r['threshold_crosses']} | {r['diagnostic']} |"
        )

    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- Every record carries `evidence_source=REPLAY`.")
    lines.append("- This script NEVER fetches live data.")
    lines.append("- This script NEVER writes to opportunity_ledger.")
    lines.append("- This script NEVER counts toward shadow eligibility, paper experiments, or real-market opportunities.")
    lines.append("- This script NEVER imports `alpaca_orders`.")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in rep["standing_markers"]:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="v3.26 — Replay entry-candidate discovery (Agent 3B / ETAP 5).",
    )
    p.add_argument("--as-of", default=None,
                   help="ISO timestamp; defaults to now (UTC).")
    p.add_argument("--lookback-days", type=int, default=7,
                   help="Replay window length in bars (default 7).")
    p.add_argument("--strategies", default=None,
                   help="Comma-separated list of strategies "
                        "(default: all replay-eligible).")
    p.add_argument("--universe", default=None,
                   help="Comma-separated symbols (default: equity+crypto universe).")
    p.add_argument("--snapshot-dir", default=None,
                   help="Directory of <symbol>.json snapshots "
                        "(default: learning-loop/backfill_snapshots).")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    strategies_filter = None
    if args.strategies:
        strategies_filter = tuple(
            s.strip() for s in args.strategies.split(",") if s.strip()
        )
    universe = None
    if args.universe:
        universe = tuple(
            s.strip() for s in args.universe.split(",") if s.strip()
        )
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else None

    rep = build_report(
        as_of=as_of,
        lookback_days=args.lookback_days,
        snapshot_dir=snapshot_dir,
        strategies_filter=strategies_filter,
        universe=universe,
    )
    md = render_md(rep)

    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        t = rep["totals"]
        print(
            f"Candidates: {t['candidates']} | "
            f"Near-misses: {t['near_misses']} | "
            f"Threshold-crosses: {t['threshold_crosses']} | "
            f"Pairs scanned: {t['rows']} | "
            f"Missing snapshots: {len(rep['missing_snapshots'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

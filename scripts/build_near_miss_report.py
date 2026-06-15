#!/usr/bin/env python3
"""v3.24 (2026-06-15) — Near-miss aggregate reporter (ETAP 10).

Reads ``learning-loop/near_miss/*.jsonl`` for the last 7 days,
aggregates by (strategy, metric), and renders:

- ``learning-loop/near_miss_status_latest.json``
- ``docs/NEAR_MISS_STATUS.md``

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders`` (verified by test).
- NEVER makes network calls.
- NEVER auto-adjusts a strategy threshold; it only surfaces
  "operator review" advisory flags.
- Pure read-only aggregation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "near_miss_status_latest.json")
LATEST_MD_PATH = REPO_ROOT / "docs" / "NEAR_MISS_STATUS.md"
NEAR_MISS_DIR = REPO_ROOT / "learning-loop" / "near_miss"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "NEAR_MISS_NEVER_COUNTS_AS_TRADE",
    "NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS",
)

VERSION = "v3.24.0"


# ─── Import helper ────────────────────────────────────────────────────────────


def _load_tracker():
    """Add ``shared/`` to sys.path then import.

    This script is invoked as ``python3 scripts/build_near_miss_report.py``
    so ``sys.path[0]`` is ``scripts/``; we must add ``REPO_ROOT/shared``
    so ``near_miss_tracker`` is importable.
    """
    added = []
    for p in (str(REPO_ROOT), str(REPO_ROOT / "shared")):
        if p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    try:
        import near_miss_tracker as nm  # type: ignore
        return nm
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


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


# ─── Build ────────────────────────────────────────────────────────────────────


def build_report(
    *,
    as_of: datetime,
    days: int = 7,
    base_dir: Path | None = None,
    flag_distance_ratio: float = 0.40,
    min_sample: int = 10,
) -> dict[str, Any]:
    nm = _load_tracker()
    base = base_dir if base_dir is not None else NEAR_MISS_DIR
    rows = nm.load_recent_rows(
        days=days,
        base_dir=base,
        as_of=as_of,
    )
    realism = nm.evaluate_threshold_realism(
        rows,
        flag_distance_ratio=flag_distance_ratio,
        min_sample=min_sample,
    )
    return {
        "version":           VERSION,
        "tracker_version":   getattr(nm, "NEAR_MISS_VERSION", "unknown"),
        "generated_at_iso":  datetime.now(timezone.utc).isoformat(),
        "as_of":             as_of.isoformat(),
        "git_head":          _git_head(),
        "window_days":       days,
        "rows_total":        len(rows),
        "pairs":             realism["pairs"],
        "flagged":           realism["flagged"],
        "params":            realism["params"],
        "standing_markers":  list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":      False,
            "allow_broker_paper":     False,
            "live_trading_supported": False,
            "modifies_state_json":    False,
            "auto_adjusts_thresholds": False,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    pair_rows = [
        "| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in rep["pairs"]:
        flag = "yes — operator review" if p["advisory_flag"] else "no"
        pair_rows.append(
            f"| `{p['strategy_id']}` | `{p['metric_name']}` | "
            f"{p['sample_size']} | {p['p95_abs_distance']} | "
            f"{p['median_threshold']} | "
            f"{round(p['abs_distance_ratio'] * 100, 1)}% | "
            f"{flag} |"
        )
    if len(pair_rows) == 2:
        pair_rows.append("| (none) | | | | | | |")

    flagged_rows = [
        "| Strategy | Metric | Sample | Reason |",
        "|---|---|---|---|",
    ]
    for f in rep["flagged"]:
        flagged_rows.append(
            f"| `{f['strategy_id']}` | `{f['metric_name']}` | "
            f"{f['sample_size']} | {f['advisory_reason']} |"
        )
    if len(flagged_rows) == 2:
        flagged_rows.append("| (none) | | | |")

    standing = "\n".join(f"- `{m}`" for m in rep["standing_markers"])
    params = rep["params"]

    return f"""# Near-Miss Status ({rep["version"]})

**Generated:** `{rep["generated_at_iso"]}`
**As of:** `{rep["as_of"]}`
**Git HEAD:** `{rep["git_head"]}`
**Window:** last {rep["window_days"]} days
**Tracker version:** `{rep["tracker_version"]}`
**Total rows ingested:** `{rep["rows_total"]}`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `{params["flag_distance_ratio"]}` of median |threshold| AND sample >= `{params["min_sample"]}` |
|---|

{chr(10).join(flagged_rows)}

## Per-pair detail

{chr(10).join(pair_rows)}

## Safety contract

- Each near-miss record carries `is_paper_trade=False`, `is_signal=False`.
- This reporter NEVER auto-adjusts a strategy threshold.
- This reporter NEVER places orders.

## Standing markers

{standing}
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.24 near-miss status report.")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--flag-distance-ratio", type=float,
                          default=0.40)
    parser.add_argument("--min-sample", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(
                args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    rep = build_report(
        as_of=as_of,
        days=args.days,
        flag_distance_ratio=args.flag_distance_ratio,
        min_sample=args.min_sample,
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
        print(f"Pairs: {len(rep['pairs'])} | Flagged: {len(rep['flagged'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

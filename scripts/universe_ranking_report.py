#!/usr/bin/env python3
"""v3.19.0 (2026-06-04) — Universe Ranking CLI.

WHY
---
Generate a ranked universe report for operator review. Paper-analysis only.
Never auto-trades. Cannot raise risk limits.

The script reads candidate symbols (from watchlist, CLI, or stdin) and any
available ranking inputs from local JSON dumps, then writes
`docs/universe_ranking_LATEST.{md,json}`.

CRITICAL
--------
- No live broker calls.
- No paid services.
- Risk engine is NOT bypassed by this report.
- All inputs are optional → fail-soft to neutral 0.5 scores.

USAGE
-----
  python3 scripts/universe_ranking_report.py
  python3 scripts/universe_ranking_report.py --symbols AAPL MSFT SPY
  python3 scripts/universe_ranking_report.py --inputs-json path/to/inputs.json
  python3 scripts/universe_ranking_report.py --dry-run  # stdout only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
for _p in (_SHARED_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_watchlist_symbols(symbols_arg: list[str] | None) -> list[str]:
    if symbols_arg:
        return sorted({s.upper() for s in symbols_arg if s})
    syms: set[str] = set()
    wl_path = os.path.join(_REPO_ROOT, "config", "watchlists.json")
    try:
        with open(wl_path, encoding="utf-8") as f:
            data = json.load(f) or {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            tickers = v.get("tickers") or v.get("symbols") or []
            if isinstance(tickers, list):
                for t in tickers:
                    if isinstance(t, str) and t:
                        syms.add(t.upper())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    if not syms:
        return ["SPY", "QQQ", "AAPL", "MSFT"]
    return sorted(syms)


def _load_inputs(inputs_path: str | None) -> dict[str, Any]:
    """Load optional ranking inputs from a JSON file. Fail-soft to {}."""
    if not inputs_path:
        return {}
    try:
        with open(inputs_path, encoding="utf-8") as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="Override watchlist with explicit symbols.")
    ap.add_argument("--universe-id", default=None,
                    help="Override active universe (US_LARGE / CRYPTO).")
    ap.add_argument("--inputs-json", default=None,
                    help=("Optional JSON file with ranking input dicts: "
                          "{spread_data, volume_data, paper_performance, "
                          "strategy_compat, confidence_calibration, "
                          "regime_fit, drawdown_history, recent_anomalies}."))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print ranking JSON to stdout; do NOT write files.")
    ap.add_argument("--out-md", default=None,
                    help="Override markdown output path.")
    ap.add_argument("--out-json", default=None,
                    help="Override JSON output path.")
    args = ap.parse_args(argv)

    try:
        import universe_selector as us  # type: ignore
    except ImportError:  # pragma: no cover
        from shared import universe_selector as us  # type: ignore

    symbols = _load_watchlist_symbols(args.symbols)
    print(f"[universe-ranking] ranking {len(symbols)} symbols",
          file=sys.stderr)

    inputs = _load_inputs(args.inputs_json)

    ranking = us.rank_symbols(
        symbols,
        spread_data=inputs.get("spread_data"),
        volume_data=inputs.get("volume_data"),
        paper_performance=inputs.get("paper_performance"),
        strategy_compat=inputs.get("strategy_compat"),
        confidence_calibration=inputs.get("confidence_calibration"),
        regime_fit=inputs.get("regime_fit"),
        drawdown_history=inputs.get("drawdown_history"),
        recent_anomalies=inputs.get("recent_anomalies"),
        universe_id=args.universe_id,
        audit=True,
    )

    if args.dry_run:
        print(json.dumps(ranking, indent=2, sort_keys=True, default=str))
        return 0

    md_path, json_path = us.write_universe_report(
        ranking,
        out_md_path=args.out_md,
        out_json_path=args.out_json,
        universe_id=args.universe_id,
    )
    print(f"[universe-ranking] wrote md={md_path or '(failed)'} "
          f"json={json_path or '(failed)'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

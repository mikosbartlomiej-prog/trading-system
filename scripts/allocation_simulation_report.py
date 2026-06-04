#!/usr/bin/env python3
"""v3.19.0 (2026-06-04) — Allocation Simulation CLI.

Reads the paper-experiment ledger via shared.paper_experiment + runs all
6 allocation modes via shared.allocation_simulator + writes the
comparison report to `docs/allocation_simulation_LATEST.{md,json}`.

CRITICAL: paper analysis only. Cannot raise risk limits. Cannot auto-
allocate capital. Risk engine retains final say.

USAGE
-----
  python3 scripts/allocation_simulation_report.py
  python3 scripts/allocation_simulation_report.py --window-days 90 \\
      --capital-usd 50000 --current-regime RISK_ON
  python3 scripts/allocation_simulation_report.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
for _p in (_SHARED_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window-days", type=int, default=180,
                    help="Paper ledger window (default 180).")
    ap.add_argument("--capital-usd", type=float, default=100_000.0,
                    help="Hypothetical capital base (default $100k).")
    ap.add_argument("--current-regime", default="NEUTRAL",
                    help="Regime for regime_aware mode (default NEUTRAL).")
    ap.add_argument("--top-n", type=int, default=5,
                    help="N for top_n allocation mode (default 5).")
    ap.add_argument("--drawdown-cap-pct", type=float, default=0.20,
                    help="MaxDD cap for drawdown_capped mode (default 0.20).")
    ap.add_argument("--disabled", nargs="*", default=None,
                    help="Strategies to exclude.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print JSON to stdout; do NOT write reports.")
    ap.add_argument("--out-md", default=None,
                    help="Override markdown output path.")
    ap.add_argument("--out-json", default=None,
                    help="Override JSON output path.")
    args = ap.parse_args(argv)

    try:
        import allocation_simulator as alloc  # type: ignore
    except ImportError:  # pragma: no cover
        from shared import allocation_simulator as alloc  # type: ignore

    if args.dry_run:
        # Compute without writing — read ledger inline.
        try:
            try:
                from paper_experiment import compute_strategy_metrics  # type: ignore
            except ImportError:
                from shared.paper_experiment import compute_strategy_metrics  # type: ignore
            try:
                from backtest.strategy_registry import REGISTRY  # type: ignore
                names = sorted(REGISTRY.keys())
            except Exception:
                names = []
            per_strategy = {}
            for n in names:
                try:
                    per_strategy[n] = compute_strategy_metrics(
                        n, window_days=args.window_days)
                except Exception:
                    continue
        except Exception:
            per_strategy = {}
        comparison = alloc.compare_allocation_modes(
            per_strategy,
            current_regime=args.current_regime,
            capital_usd=args.capital_usd,
            top_n=args.top_n,
            drawdown_cap_pct=args.drawdown_cap_pct,
            disabled_strategies=args.disabled,
        )
        print(json.dumps(comparison, indent=2, sort_keys=True, default=str))
        return 0

    md_path, json_path = alloc.generate_allocation_report(
        out_md_path=args.out_md,
        out_json_path=args.out_json,
        capital_usd=args.capital_usd,
        current_regime=args.current_regime,
        top_n=args.top_n,
        drawdown_cap_pct=args.drawdown_cap_pct,
        disabled_strategies=args.disabled,
        window_days=args.window_days,
    )
    print(f"[allocation-simulation] wrote md={md_path or '(failed)'} "
          f"json={json_path or '(failed)'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

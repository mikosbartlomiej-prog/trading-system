#!/usr/bin/env python3
"""v3.21.0 (2026-06-04) — Fill model calibration CLI.

Reads paired (shadow, broker_paper) fill records from disk (when the
operator points the script at a paired ledger) and writes a deterministic
markdown report at::

    docs/FILL_MODEL_CALIBRATION_LATEST.md

The runtime is NEVER mutated. The shadow model parameters are NEVER
changed by this script. The calibration is review-gated and governed by
Multi-Agent Audit Board.

Usage::

    python3 scripts/fill_model_calibration_report.py
    python3 scripts/fill_model_calibration_report.py --window-days 60
    python3 scripts/fill_model_calibration_report.py \
        --pairs-json /tmp/paired_fills.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from fill_model_calibration import (  # type: ignore  # noqa: E402
    build_calibration_report,
    render_report_markdown,
)


def _load_pairs(path: Path | None) -> list[dict]:
    if path is None:
        return []
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict) and isinstance(data.get("pairs"), list):
            return [d for d in data["pairs"] if isinstance(d, dict)]
    except (OSError, json.JSONDecodeError):
        return []
    return []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--window-days", type=int, default=90,
                   help="Lookback window in days (default 90)")
    p.add_argument("--pairs-json", type=str, default=None,
                   help="Optional path to a JSON list of paired fills")
    p.add_argument("--symbol-filter", type=str, default=None,
                   help="Optional substring filter on symbol")
    p.add_argument("--out-md", type=str, default=None,
                   help="Output markdown path "
                        "(default: docs/FILL_MODEL_CALIBRATION_LATEST.md)")
    p.add_argument("--out-json", type=str, default=None,
                   help="Optional JSON output path "
                        "(default: learning-loop/"
                        "FILL_MODEL_CALIBRATION_LATEST.json)")
    args = p.parse_args()

    pairs_path = Path(args.pairs_json) if args.pairs_json else None
    pairs = _load_pairs(pairs_path)

    report = build_calibration_report(
        pairs,
        window_days=int(args.window_days),
        symbol_filter=args.symbol_filter,
    )

    md_path = Path(args.out_md) if args.out_md else (
        _REPO_ROOT / "docs" / "FILL_MODEL_CALIBRATION_LATEST.md"
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_report_markdown(report), encoding="utf-8")
    print(f"Wrote {md_path}")

    json_path = Path(args.out_json) if args.out_json else (
        _REPO_ROOT / "learning-loop"
        / "FILL_MODEL_CALIBRATION_LATEST.json"
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, default=str, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

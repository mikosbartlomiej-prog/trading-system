#!/usr/bin/env python3
"""v3.19.0 (2026-06-04) — CLI wrapper around shared.confidence_calibration.

Reads the paper ledger only (per v3.19.0 ETAP 3 Evidence Source
Separation) and writes two local artefacts:

  - docs/confidence_calibration_LATEST.md
  - learning-loop/confidence_calibration_LATEST.json

Never calls a paid API. Never raises a confidence threshold on its
own. The output is consumed by the Strategy Quality Gate and reviewed
by an operator.

Usage:
    python3 scripts/confidence_calibration_report.py
    python3 scripts/confidence_calibration_report.py --window-days 90
    python3 scripts/confidence_calibration_report.py \
        --md /tmp/calib.md --json /tmp/calib.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from confidence_calibration import (  # type: ignore  # noqa: E402
    generate_calibration_report,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--window-days", type=int, default=180,
                    help="Lookback window in days (default 180)")
    p.add_argument("--min-n-per-bucket", type=int, default=10,
                    help="Minimum bucket sample size for monotonicity "
                         "check (default 10)")
    p.add_argument("--md", type=str, default=None,
                    help="Output Markdown path "
                         "(default: docs/confidence_calibration_LATEST.md)")
    p.add_argument("--json", type=str, default=None,
                    help="Output JSON path "
                         "(default: learning-loop/confidence_calibration_LATEST.json)")
    args = p.parse_args()

    md_path, json_path = generate_calibration_report(
        out_md_path=args.md,
        out_json_path=args.json,
        window_days=int(args.window_days),
        min_n_per_bucket=int(args.min_n_per_bucket),
    )
    if md_path:
        print(f"Wrote {md_path}")
    if json_path:
        print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

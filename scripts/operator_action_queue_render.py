#!/usr/bin/env python3
"""v3.21.0 (2026-06-04) — Operator Action Queue renderer.

Reads the append-only JSONL queue at
``learning-loop/operator_action_queue.jsonl`` and writes a deterministic
markdown rollup to ``docs/operator_action_queue_LATEST.md``.

The queue is non-auto-apply by design: this script SURFACES open items
so the operator can sweep them; it NEVER mutates strategies, risk
gates, or runtime config. Governed by Multi-Agent Audit Board.

Usage::

    python3 scripts/operator_action_queue_render.py
    python3 scripts/operator_action_queue_render.py \
        --out docs/operator_action_queue_LATEST.md
    python3 scripts/operator_action_queue_render.py --status OPEN
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from operator_action_queue import (  # type: ignore  # noqa: E402
    assert_invariants,
    list_actions,
    write_markdown_report,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=str, default=None,
                   help="Output markdown path "
                        "(default: docs/operator_action_queue_LATEST.md)")
    p.add_argument("--status", type=str, default=None,
                   help="Filter by status (OPEN/ACKNOWLEDGED/...)")
    p.add_argument("--severity", type=str, default=None,
                   help="Filter by severity (P0/P1/P2/P3)")
    p.add_argument("--limit", type=int, default=None,
                   help="Limit number of actions in the report")
    args = p.parse_args()

    # Hard invariants — fail loud if anyone tampered with the queue
    # auto-apply flags.
    assert_invariants()

    records = list_actions(
        status=args.status,
        severity=args.severity,
        limit=args.limit,
    )

    out_path = Path(args.out) if args.out else None
    written = write_markdown_report(out_path, records=records)
    print(f"Wrote {written} ({len(records)} action(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

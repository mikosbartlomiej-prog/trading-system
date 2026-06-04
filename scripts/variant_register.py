#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — CLI for shared/strategy_variant_quarantine.py.

Lets operator (or learning-loop) register a new strategy variant via
command line. Persists the variant JSON in
`learning-loop/variant_quarantine/<id>.json` and prints the resulting
record. NEVER places trades, NEVER raises risk, NEVER enables anything
on the runtime trading path.

USAGE
-----
    python3 scripts/variant_register.py \\
        --parent momentum_long_strict \\
        --rationale "tighten breakout threshold for chop days" \\
        --evidence-source REPLAY \\
        --param threshold=0.65 \\
        --param cooldown=180

The variant id is deterministic: sha256(parent + json(params))[:12].
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _parse_param(s: str) -> tuple[str, object]:
    if "=" not in s:
        raise argparse.ArgumentTypeError(
            f"--param expects key=value, got: {s!r}")
    k, raw = s.split("=", 1)
    k = k.strip()
    # Try to parse as JSON literal first (so "true"/"123"/"0.5" coerce),
    # then fall back to raw string.
    try:
        v = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        v = raw
    return k, v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Register a strategy variant (quarantine only).")
    p.add_argument("--parent", required=True,
                   help="Parent strategy name (must exist).")
    p.add_argument("--rationale", required=True,
                   help="Plain-language reason for this variant.")
    p.add_argument("--evidence-source", required=True,
                   choices=["REPLAY", "BACKTEST"],
                   help="Evidence basis. PAPER is forbidden here.")
    p.add_argument("--param", action="append", default=[], type=_parse_param,
                   metavar="KEY=VALUE",
                   help=("Override param. Repeatable. Allowed keys: "
                         "threshold, regime_filter, confidence_cap, "
                         "universe_filter, exit_rule, cooldown."))
    p.add_argument("--promotion", action="append", default=[],
                   metavar="CRITERION",
                   help="Promotion criterion (repeatable).")
    p.add_argument("--rejection", action="append", default=[],
                   metavar="CRITERION",
                   help="Rejection criterion (repeatable).")
    p.add_argument("--status", default="QUARANTINED",
                   choices=["QUARANTINED", "REPLAY_TESTING",
                            "SHADOW_OBSERVE", "REJECTED",
                            "CANDIDATE_FOR_MANUAL_REVIEW"],
                   help="Initial status. LIVE_APPROVED is not a valid choice.")
    p.add_argument("--out", default="-",
                   help="Path to write the JSON record (default stdout).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        try:
            from strategy_variant_quarantine import register_variant
        except ImportError:
            from shared.strategy_variant_quarantine import register_variant
    except ImportError as e:
        print(f"ERROR: cannot import strategy_variant_quarantine: {e}",
              file=sys.stderr)
        return 2

    params = dict(args.param)
    try:
        record = register_variant(
            parent_strategy=args.parent,
            change_rationale=args.rationale,
            params=params,
            evidence_source=args.evidence_source,
            promotion_criteria=args.promotion,
            rejection_criteria=args.rejection,
            status=args.status,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    body = json.dumps(record, indent=2, sort_keys=True, default=str)
    if args.out == "-":
        print(body)
    else:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

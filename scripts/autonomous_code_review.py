#!/usr/bin/env python3
"""
CLI wrapper around `learning-loop/code_autonomy.py` — reads a patch from
disk or stdin, runs the validator, prints the verdict.

Used by:
  - .github/workflows/autonomous-code-loop.yml (CI step)
  - operator who wants to see what would happen with a patch

Usage:
    python scripts/autonomous_code_review.py path/to/patch.diff
    cat patch.diff | python scripts/autonomous_code_review.py -

Exit codes:
  0 — APPROVE_AUTO_MERGE or APPROVE_PR_ONLY
  1 — REJECT_HIGH_RISK
  2 — REJECT_FORBIDDEN (most serious)
  3 — invalid invocation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "learning-loop"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from patch_validator import PatchMetadata, validate_patch  # noqa: E402


EXIT_CODES = {
    "APPROVE_AUTO_MERGE": 0,
    "APPROVE_PR_ONLY":    0,
    "REJECT_HIGH_RISK":   1,
    "REJECT_FORBIDDEN":   2,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("patch_path", help='Path to unified diff, or "-" for stdin')
    p.add_argument("--title", default="autonomous patch")
    p.add_argument("--summary", default="")
    p.add_argument("--author", default="autonomous_code_loop")
    p.add_argument("--tests-added", action="store_true",
                    help="Mark that this patch ships its own tests")
    p.add_argument("--json", action="store_true",
                    help="Emit JSON instead of human text")
    args = p.parse_args()

    if args.patch_path == "-":
        diff = sys.stdin.read()
    else:
        try:
            diff = Path(args.patch_path).read_text()
        except OSError as e:
            print(f"FATAL: cannot read {args.patch_path}: {e}", file=sys.stderr)
            return 3

    result = validate_patch(diff, PatchMetadata(
        title=args.title, summary=args.summary, author=args.author,
        test_coverage_added=args.tests_added,
    ))

    if args.json:
        out = {
            "verdict":        result.verdict,
            "risk_category":  result.risk_category,
            "touched_files":  result.touched_files,
            "reasons":        result.reasons,
            "warnings":       result.warnings,
            "forbidden_hits": result.forbidden_hits,
            "deleted_tests":  result.deleted_tests,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"=== verdict: {result.verdict} ({result.risk_category}) ===")
        print(f"touched files ({len(result.touched_files)}):")
        for f in result.touched_files:
            print(f"  - {f}")
        if result.reasons:
            print("\nreasons:")
            for r in result.reasons:
                print(f"  - {r}")
        if result.warnings:
            print("\nwarnings:")
            for w in result.warnings:
                print(f"  - {w}")
        if result.forbidden_hits:
            print("\nforbidden content hits:")
            for h in result.forbidden_hits:
                print(f"  - {h['pattern']}: {h['snippet']}")
        if result.deleted_tests:
            print("\ndeleted tests:")
            for t in result.deleted_tests:
                print(f"  - {t}")

    return EXIT_CODES.get(result.verdict, 1)


if __name__ == "__main__":
    sys.exit(main())

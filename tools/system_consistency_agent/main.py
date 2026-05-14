"""Orchestrator + CLI for the system consistency agent."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checks import CATEGORY_MODULES
from .models import AuditReport, CategoryResult
from .report import render_json, render_markdown, write_outputs
from .utils import git_sha, repo_root


def run(root: Path | None = None, *, only_category: str | None = None) -> AuditReport:
    """Run every (or a single) category check and assemble the report."""
    root = root or repo_root()
    report = AuditReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        repo_sha=git_sha(root),
    )

    for name, mod, weight in CATEGORY_MODULES:
        if only_category and name != only_category:
            continue
        try:
            findings = mod.run(root)
        except Exception as exc:  # pragma: no cover — defensive
            from .models import Finding
            findings = [Finding(
                id=f"{name.upper()}_CHECK_CRASHED",
                category=name, severity="FAIL", status="FAIL",
                message=f"{name} check crashed: {type(exc).__name__}: {exc}",
                principle=name.upper(),
                recommendation="Open an issue — agent itself crashed.",
            )]
        report.categories[name] = CategoryResult(
            name=name, weight=weight, findings=list(findings),
        )

    # Compute totals
    total_weight = sum(w for _, _, w in CATEGORY_MODULES if not only_category or _ == only_category)
    earned = sum(c.score() for c in report.categories.values())
    report.score = (earned / total_weight * 100.0) if total_weight else 0.0

    # Overall status
    if any(c.has_blocking_fail for c in report.categories.values()):
        report.overall_status = "BLOCKED"
    elif any(c.fail_count > 0 for c in report.categories.values()):
        report.overall_status = "FAIL"
    elif any(c.warn_count > 0 for c in report.categories.values()):
        report.overall_status = "WARN"
    else:
        report.overall_status = "PASS"

    return report


def _exit_code_for(status: str, *, strict: bool, non_blocking: bool) -> int:
    if status == "BLOCKED":
        return 2
    if status == "FAIL":
        return 1 if non_blocking else 2
    if status == "WARN":
        return 1 if strict else 0
    return 0


def run_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="system_consistency_agent")
    p.add_argument("--format", choices=("json", "markdown", "both"), default="both")
    p.add_argument("--json", action="store_true",
                   help="Emit only JSON to stdout (legacy alias)")
    p.add_argument("--markdown", action="store_true",
                   help="Emit only Markdown to stdout (legacy alias)")
    p.add_argument("--strict", action="store_true",
                   help="WARN escalates exit code to 1")
    p.add_argument("--non-blocking", action="store_true",
                   help="Non-blocking FAIL exits 1 instead of 2")
    p.add_argument("--category", default=None,
                   help="Run only the named category (paper_only, workflows, ...)")
    p.add_argument("--output-dir", default="reports/system-consistency",
                   help="Where to write latest.json/latest.md + timestamped copies")
    p.add_argument("--no-files", action="store_true",
                   help="Skip writing files; only emit to stdout")
    args = p.parse_args(argv)

    report = run(only_category=args.category)
    out_dir = Path(args.output_dir)
    paths: dict[str, str] = {}
    if not args.no_files:
        paths = write_outputs(
            report, out_dir,
            json_only=args.json or args.format == "json",
            md_only=args.markdown or args.format == "markdown",
        )

    if args.json or args.format == "json":
        sys.stdout.write(render_json(report) + "\n")
    elif args.markdown or args.format == "markdown":
        sys.stdout.write(render_markdown(report))
    else:
        # both: write files (already done) and emit Markdown to stdout for terminal
        sys.stdout.write(render_markdown(report))

    if paths:
        sys.stderr.write(f"\nReports written to: {paths}\n")

    return _exit_code_for(report.overall_status,
                          strict=args.strict, non_blocking=args.non_blocking)


if __name__ == "__main__":
    sys.exit(run_cli())

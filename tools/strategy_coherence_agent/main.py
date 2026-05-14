"""Orchestrator + CLI for the Strategy Coherence Agent."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checks import CATEGORY_MODULES, collect_conflicting_values
from .models import CategoryResult, Finding, StrategyCoherenceReport
from .report import render_json, render_markdown, write_outputs
from .utils import git_sha, repo_root


def run(root: Path | None = None,
        *,
        only_category: str | None = None) -> StrategyCoherenceReport:
    """Execute every (or one) category check and assemble the report."""
    root = root or repo_root()
    report = StrategyCoherenceReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        repo_sha=git_sha(root),
    )

    selected = [
        (name, mod, weight) for name, mod, weight in CATEGORY_MODULES
        if not only_category or name == only_category
    ]
    if only_category and not selected:
        # Surface the typo cleanly instead of silently producing 0/0.
        report.overall_status = "FAIL"
        report.categories[only_category] = CategoryResult(
            name=only_category, weight=1,
            findings=[Finding(
                id="UNKNOWN_CATEGORY",
                category=only_category,
                severity="FAIL",
                status="FAIL",
                message=f"Unknown category '{only_category}'. "
                        f"Allowed: {sorted(n for n, _, _ in CATEGORY_MODULES)}",
                recommendation="Pick one of the allowed category names.",
            )],
        )
        return report

    for name, mod, weight in selected:
        try:
            findings = mod.run(root)
        except Exception as exc:  # pragma: no cover — defensive
            findings = [Finding(
                id=f"{name.upper()}_CHECK_CRASHED",
                category=name,
                severity="FAIL",
                status="FAIL",
                message=f"{name} check crashed: {type(exc).__name__}: {exc}",
                principle=name.upper(),
                recommendation="File an issue — the strategy-coherence "
                               "agent itself failed to evaluate this category.",
            )]
        report.categories[name] = CategoryResult(
            name=name, weight=weight, findings=list(findings),
        )

    # Cross-category: detect conflicting numeric values across docs/config/code.
    try:
        report.conflicting_values = collect_conflicting_values(root)
    except Exception as exc:                                       # pragma: no cover
        # Don't take down the whole report just because the value scanner
        # tripped on a malformed file; flag it as a low-severity finding.
        report.categories.setdefault(
            "documentation_parity",
            CategoryResult(name="documentation_parity", weight=4),
        ).findings.append(Finding(
            id="CONFLICT_SCAN_CRASHED",
            category="documentation_parity",
            severity="WARN",
            status="WARN",
            message=f"Numeric-conflict scanner crashed: {type(exc).__name__}: {exc}",
            recommendation="Inspect the offending file manually; the rest "
                           "of the report is still valid.",
        ))

    # Score & overall status — name the loop vars properly; `_, _, w` shadows
    # `_` so the filter would compare the module against the string.
    total_weight = sum(w for name, _, w in CATEGORY_MODULES
                       if not only_category or name == only_category)
    earned = sum(c.score() for c in report.categories.values())
    report.score = (earned / total_weight * 100.0) if total_weight else 0.0

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
    """Exit-code policy (spec §25).

    BLOCKED          → 2
    FAIL             → 2 unless --non-blocking → 1
    WARN             → 1 if --strict else 0
    PASS             → 0
    """
    if status == "BLOCKED":
        return 2
    if status == "FAIL":
        return 1 if non_blocking else 2
    if status == "WARN":
        return 1 if strict else 0
    return 0


def run_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="strategy_coherence_agent")
    p.add_argument("--format", choices=("json", "markdown", "both"), default="both")
    p.add_argument("--json", action="store_true",
                   help="Emit only JSON to stdout (overrides --format)")
    p.add_argument("--markdown", action="store_true",
                   help="Emit only Markdown to stdout (overrides --format)")
    p.add_argument("--strict", action="store_true",
                   help="Treat WARN as a failure (exit 1)")
    p.add_argument("--non-blocking", action="store_true",
                   help="Non-blocking FAIL exits 1 instead of 2")
    p.add_argument("--category", default=None,
                   help="Run only the named category (see report for allowed values)")
    p.add_argument("--output-dir", default="reports/strategy-coherence",
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
        sys.stdout.write(render_markdown(report))

    if paths:
        sys.stderr.write(f"\nReports written: {paths}\n")

    return _exit_code_for(report.overall_status,
                          strict=args.strict,
                          non_blocking=args.non_blocking)


if __name__ == "__main__":
    sys.exit(run_cli())

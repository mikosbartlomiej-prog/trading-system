"""Orchestrator + CLI for e2e_system_test_agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover, repo_root
from .inventory import scan as scan_tests
from .runners import run_default_suites, run_unittest
from .report import build_report, render_markdown, write_outputs


def run(*, run_tests: bool = True,
        suite_filter: str | None = None,
        network_blocked: bool = True,
        cwd: Path | None = None) -> dict:
    cwd = cwd or repo_root()
    discovery = discover(cwd)
    inventory = scan_tests(cwd)
    runs = []
    if run_tests:
        if suite_filter:
            runs.append(run_unittest(suite_filter, cwd=cwd))
        else:
            runs = run_default_suites(cwd)
    return build_report(discovery, inventory, runs, network_blocked=network_blocked)


def run_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="e2e_system_test_agent")
    p.add_argument("--all", action="store_true")
    p.add_argument("--discover", action="store_true",
                   help="Skip test execution; only emit discovery + inventory.")
    p.add_argument("--inventory", action="store_true",
                   help="Same as --discover (tests not executed).")
    p.add_argument("--run-e2e", action="store_true",
                   help="Only run tests/e2e/")
    p.add_argument("--run-unit", action="store_true",
                   help="Only run tests/architecture_vnext/")
    p.add_argument("--category", default=None,
                   help="Filter to a single tests/e2e/test_*<category>* file")
    p.add_argument("--no-network", action="store_true",
                   help="Belt+braces: set NO_NETWORK=1 before running")
    p.add_argument("--report-only", action="store_true",
                   help="Read latest.json from --output-dir and just re-render Markdown")
    p.add_argument("--output-dir", default="reports/e2e")
    p.add_argument("--format", choices=("json", "markdown", "both"),
                    default="both")
    p.add_argument("--no-files", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.output_dir)

    if args.report_only:
        jpath = out_dir / "latest.json"
        if not jpath.exists():
            print("FATAL: no latest.json present.", file=sys.stderr)
            return 2
        report = json.loads(jpath.read_text())
        sys.stdout.write(render_markdown(report))
        return _exit_for(report)

    import os
    if args.no_network:
        os.environ["NO_NETWORK"] = "1"

    suite_filter = None
    run_tests = True
    if args.discover or args.inventory:
        run_tests = False
    elif args.run_e2e:
        suite_filter = "tests/e2e"
    elif args.run_unit:
        suite_filter = "tests/architecture_vnext"

    report = run(run_tests=run_tests, suite_filter=suite_filter,
                  network_blocked=args.no_network or
                                  os.environ.get("NO_NETWORK") == "1")

    if not args.no_files:
        paths = write_outputs(report, out_dir)
        sys.stderr.write(f"\nReports written to: {paths}\n")

    if args.format in ("json",):
        sys.stdout.write(json.dumps(report, indent=2, default=str) + "\n")
    elif args.format in ("markdown",):
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(render_markdown(report))

    return _exit_for(report)


def _exit_for(report: dict) -> int:
    st = report.get("overall_status", "PASS")
    if st == "BLOCKED" or st == "FAIL":
        return 2
    if st == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())

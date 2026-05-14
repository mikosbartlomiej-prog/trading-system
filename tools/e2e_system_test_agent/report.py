"""JSON + Markdown report renderer for E2E agent output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_model import CAPABILITIES, CAPABILITIES_BY_AREA
from .discovery import DiscoveryResult
from .inventory import TestRecord, summary as inventory_summary
from .runners import TestRunResult


def _coverage_table(discovery: DiscoveryResult) -> list[dict]:
    rows = []
    for c in CAPABILITIES:
        st = discovery.capability_status.get(c.id, {})
        tests_present = st.get("tests_present", [])
        unit_present = any("architecture_vnext" in t or t.startswith("tests/test_")
                            or "learning-loop/test_" in t for t in tests_present)
        e2e_present = any("/e2e/" in t for t in tests_present)
        status = "PASS"
        if not st.get("module_exists"):
            status = "MISSING_MODULE"
        elif not tests_present:
            status = "UNCOVERED"
        elif not e2e_present and unit_present:
            status = "PARTIAL"
        rows.append({
            "capability":   c.id,
            "area":         c.area,
            "module":       c.module_path or "",
            "module_ok":    bool(st.get("module_exists")),
            "unit":         "yes" if unit_present else "no",
            "e2e":          "yes" if e2e_present else "no",
            "tests":        tests_present,
            "status":       status,
            "description":  c.description,
        })
    return rows


def build_report(
    discovery: DiscoveryResult,
    test_records: list[TestRecord],
    run_results: list[TestRunResult],
    *,
    network_blocked: bool = True,
) -> dict[str, Any]:
    coverage = _coverage_table(discovery)
    summary_counts = {
        "capabilities_total":     len(coverage),
        "capabilities_pass":      sum(1 for c in coverage if c["status"] == "PASS"),
        "capabilities_partial":   sum(1 for c in coverage if c["status"] == "PARTIAL"),
        "capabilities_uncovered": sum(1 for c in coverage if c["status"] == "UNCOVERED"),
        "capabilities_missing":   sum(1 for c in coverage if c["status"] == "MISSING_MODULE"),
    }
    test_inv = inventory_summary(test_records)
    runs = [{
        "suite":   r.suite, "ran": r.ran, "failed": r.failed,
        "errors":  r.errors, "skipped": r.skipped, "seconds": r.seconds,
        "ok":      r.ok,
    } for r in run_results]
    overall_ok = all(r.ok for r in run_results) and summary_counts["capabilities_missing"] == 0
    overall_status = "PASS" if overall_ok else (
        "FAIL" if any(not r.ok for r in run_results) else "WARN"
    )
    return {
        "overall_status":   overall_status,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "network_blocked":  network_blocked,
        "summary":          summary_counts,
        "test_inventory":   test_inv,
        "test_runs":        runs,
        "coverage":         coverage,
        "discovery": {
            "monitors":       discovery.monitors,
            "shared_modules": discovery.shared_modules,
            "learning_loop":  discovery.learning_loop,
            "scripts":        discovery.scripts,
            "workflows":      discovery.workflows,
        },
    }


def render_markdown(report: dict) -> str:
    L: list[str] = []
    L.append("# End-to-End System Test Agent Report\n")
    L.append(f"- **Overall**: `{report['overall_status']}`")
    L.append(f"- **Generated**: `{report['generated_at']}`")
    L.append(f"- **Network blocked in tests**: `{report['network_blocked']}`")
    L.append("")

    L.append("## Summary\n")
    s = report["summary"]
    L.append(f"- Capabilities: {s['capabilities_total']} total, "
              f"{s['capabilities_pass']} fully covered, "
              f"{s['capabilities_partial']} partial, "
              f"{s['capabilities_uncovered']} uncovered, "
              f"{s['capabilities_missing']} missing module")
    inv = report["test_inventory"]
    L.append(f"- Tests: {inv['total']} total — "
              f"unit {inv['by_classification'].get('unit', 0)}, "
              f"integration {inv['by_classification'].get('integration', 0)}, "
              f"e2e {inv['by_classification'].get('e2e', 0)}, "
              f"weak {inv['by_classification'].get('weak', 0)}")
    L.append("")

    L.append("## Test runs\n")
    L.append("| Suite | Ran | Failed | Errors | Skipped | Seconds | OK |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for r in report["test_runs"]:
        L.append(f"| {r['suite']} | {r['ran']} | {r['failed']} | {r['errors']} | "
                  f"{r['skipped']} | {r['seconds']:.2f} | "
                  f"{'✅' if r['ok'] else '❌'} |")
    L.append("")

    L.append("## Functional coverage\n")
    L.append("| Capability | Area | Module OK | Unit | E2E | Status |")
    L.append("|---|---|---|---|---|---|")
    for c in report["coverage"]:
        L.append(f"| {c['capability']} | {c['area']} | "
                  f"{'✅' if c['module_ok'] else '❌'} | {c['unit']} | "
                  f"{c['e2e']} | {c['status']} |")
    L.append("")

    L.append("## Discovery\n")
    d = report["discovery"]
    L.append(f"- Monitors: {', '.join(d['monitors'])}")
    L.append(f"- Shared modules: {len(d['shared_modules'])}")
    L.append(f"- Learning-loop modules: {len(d['learning_loop'])}")
    L.append(f"- Scripts: {len(d['scripts'])}")
    L.append(f"- Workflows: {len(d['workflows'])}")
    L.append("")

    return "\n".join(L) + "\n"


def write_outputs(report: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_json = out_dir / "latest.json"
    latest_md   = out_dir / "latest.md"
    latest_json.write_text(json.dumps(report, indent=2, default=str))
    latest_md.write_text(render_markdown(report))
    ts = report["generated_at"].replace(":", "").replace("-", "")[:15]
    (out_dir / f"{ts}.json").write_text(latest_json.read_text())
    (out_dir / f"{ts}.md").write_text(latest_md.read_text())
    return {"json": str(latest_json), "md": str(latest_md)}

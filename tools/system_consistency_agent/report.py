"""JSON + Markdown report rendering."""

from __future__ import annotations

import json
from pathlib import Path

from .models import AuditReport, Finding


# ─── Markdown rendering ───────────────────────────────────────────────────────

def render_markdown(report: AuditReport) -> str:
    findings = report.all_findings
    blocking = [f for f in findings if f.blocking and f.status == "FAIL"]
    fails = [f for f in findings if f.status == "FAIL" and not f.blocking]
    warns = [f for f in findings if f.status == "WARN"]

    lines: list[str] = []
    lines.append("# System Consistency Audit Report\n")
    lines.append(f"- **Overall**: `{report.overall_status}`")
    lines.append(f"- **Score**: `{report.score:.1f}/100`")
    lines.append(f"- **Generated**: `{report.generated_at}`")
    lines.append(f"- **Repo SHA**: `{report.repo_sha}`")
    lines.append("")

    # 1. Executive summary
    lines.append("## Executive summary\n")
    total = len(findings)
    summary = report.to_dict()["summary"]
    lines.append(
        f"Across {len(report.categories)} categories and {total} checks: "
        f"**{summary['pass']} PASS · {summary['warn']} WARN · "
        f"{summary['fail']} FAIL · {summary['skip']} SKIP**."
    )
    lines.append("")

    # 2. Principle scorecard
    lines.append("## Principle scorecard\n")
    lines.append("| Principle | Status |")
    lines.append("|---|---|")
    for principle, ok in _principles_scorecard(report).items():
        emoji = "✅" if ok == "PASS" else ("⚠️" if ok == "WARN" else "❌")
        lines.append(f"| {principle} | {emoji} {ok} |")
    lines.append("")

    # 3. Blocking fails
    lines.append("## Blocking failures\n")
    if not blocking:
        lines.append("*None — no blocking issue found.*")
    else:
        for f in blocking:
            _emit_finding(lines, f)
    lines.append("")

    # 4. Non-blocking fails
    lines.append("## Non-blocking failures\n")
    if not fails:
        lines.append("*None.*")
    else:
        for f in fails:
            _emit_finding(lines, f)
    lines.append("")

    # 5. Warnings
    lines.append("## Warnings\n")
    if not warns:
        lines.append("*None.*")
    else:
        for f in warns[:30]:
            _emit_finding(lines, f)
        if len(warns) > 30:
            lines.append(f"\n*…and {len(warns) - 30} more (see JSON for full list)*")
    lines.append("")

    # 6. Per-category scorecard
    lines.append("## Category scorecard\n")
    lines.append("| Category | Weight | Score | Status | PASS | WARN | FAIL | SKIP |")
    lines.append("|---|---:|---:|---|---:|---:|---:|---:|")
    for name, cat in report.categories.items():
        lines.append(
            f"| {name} | {cat.weight} | {cat.score():.1f} | {cat.overall_status()} | "
            f"{cat.pass_count} | {cat.warn_count} | {cat.fail_count} | {cat.skip_count} |"
        )
    lines.append("")

    # 7. Recommendations
    recs = [f for f in findings if f.recommendation and f.status in ("FAIL", "WARN")]
    if recs:
        lines.append("## Recommended fixes\n")
        for f in recs[:25]:
            lines.append(f"- **[{f.status}] {f.id}** — {f.recommendation}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _emit_finding(lines: list[str], f: Finding) -> None:
    lines.append(f"### `{f.id}` — {f.status}\n")
    lines.append(f"- category: `{f.category}`")
    lines.append(f"- principle: `{f.principle}`")
    lines.append(f"- message: {f.message}")
    if f.recommendation:
        lines.append(f"- fix: {f.recommendation}")
    if f.evidence:
        lines.append("- evidence:")
        for e in f.evidence[:5]:
            lines.append(f"    - `{e.file}:{e.line}` — `{e.snippet}`")
    lines.append("")


def _principles_scorecard(report: AuditReport) -> dict[str, str]:
    """Top-level Y/N answers per spec §AKCEPTACJA #8."""
    cats = report.categories

    def status_of(name: str) -> str:
        c = cats.get(name)
        return c.overall_status() if c else "SKIP"

    return {
        "paper-only":                       status_of("paper_only"),
        "fully autonomous trading":         status_of("trading_autonomy"),
        "bounded autonomous code changes":  status_of("code_autonomy"),
        "deterministic execution":          status_of("deterministic_execution"),
        "free-first":                       status_of("free_tier"),
        "risk-managed":                     status_of("portfolio_risk"),
        "auditable":                        status_of("auditability"),
        "spójny (workflows + docs)":        _combined([cats.get("workflows"),
                                                       cats.get("documentation")]),
    }


def _combined(cats) -> str:
    statuses = [c.overall_status() for c in cats if c]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    if not statuses:
        return "SKIP"
    return "PASS"


# ─── JSON rendering ───────────────────────────────────────────────────────────

def render_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, default=str, sort_keys=False)


def write_outputs(report: AuditReport, out_dir: Path,
                  *, json_only: bool = False, md_only: bool = False) -> dict:
    """Write JSON / Markdown to `out_dir` and return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    if not md_only:
        latest_json = out_dir / "latest.json"
        latest_json.write_text(render_json(report))
        paths["latest_json"] = latest_json
        ts = report.generated_at.replace(":", "").replace("-", "")[:15]
        snap = out_dir / f"{ts}.json"
        snap.write_text(latest_json.read_text())
        paths["snapshot_json"] = snap

    if not json_only:
        latest_md = out_dir / "latest.md"
        latest_md.write_text(render_markdown(report))
        paths["latest_md"] = latest_md
        ts = report.generated_at.replace(":", "").replace("-", "")[:15]
        snap = out_dir / f"{ts}.md"
        snap.write_text(latest_md.read_text())
        paths["snapshot_md"] = snap

    return {k: str(v) for k, v in paths.items()}

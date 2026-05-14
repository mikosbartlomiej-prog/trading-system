"""JSON + Markdown rendering for StrategyCoherenceReport.

The Markdown report opens with an executive summary and the principle
scorecard, then lists critical findings first (BLOCKED → FAIL → WARN).
A dedicated section surfaces conflicting numeric values across docs/
config/code so an operator can reconcile them in one pass.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Finding, StrategyCoherenceReport


# ─── Markdown ────────────────────────────────────────────────────────────────

_STATUS_EMOJI = {
    "PASS":    "✅",
    "WARN":    "⚠️",
    "FAIL":    "❌",
    "BLOCKED": "⛔",
    "SKIP":    "·",
}


def render_markdown(report: StrategyCoherenceReport) -> str:
    findings = report.all_findings
    blocked  = [f for f in findings if f.status == "BLOCKED"
                or (f.status == "FAIL" and f.blocking)]
    fails    = [f for f in findings if f.status == "FAIL" and not f.blocking]
    warns    = [f for f in findings if f.status == "WARN"]

    lines: list[str] = []
    lines.append("# Strategy Coherence Audit Report\n")
    lines.append(f"- **Overall**: `{report.overall_status}` {_STATUS_EMOJI.get(report.overall_status, '')}")
    lines.append(f"- **Score**: `{report.score:.1f}/100`")
    lines.append(f"- **Generated**: `{report.generated_at}`")
    lines.append(f"- **Repo SHA**: `{report.repo_sha}`")
    lines.append("")

    # 1. Executive summary
    lines.append("## Executive summary\n")
    summary = report.to_dict()["summary"]
    total = len(findings)
    lines.append(
        f"Across {len(report.categories)} categories and {total} checks: "
        f"**{summary['pass']} PASS · {summary['warn']} WARN · "
        f"{summary['fail']} FAIL · {summary['blocked']} BLOCKED · {summary['skip']} SKIP**."
    )
    lines.append("")
    lines.append(
        "_Question this agent answers: does the current trading **strategy** "
        "actually realise the aggressive, account-aware, portfolio-aware, "
        "regime-aware, intraday-aware, fully-deployed, deterministic, paper-only "
        "contract laid out in `docs/STRATEGY.md` + `docs/INTRADAY_PROTECTION.md` "
        "+ `config/aggressive_profile.json`?_"
    )
    lines.append("")

    # 2. Principle scorecard
    lines.append("## Principle scorecard\n")
    lines.append("| Principle | Status |")
    lines.append("|---|---|")
    for principle, ok in report.principle_coverage().items():
        lines.append(f"| {principle} | {_STATUS_EMOJI.get(ok, '·')} {ok} |")
    lines.append("")

    # 3. Critical (BLOCKED + blocking FAIL)
    lines.append("## Critical findings (BLOCKED + blocking FAIL)\n")
    if not blocked:
        lines.append("*None — no blocking strategy regression detected.*")
    else:
        for f in blocked:
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

    # 5. Conflicting numeric values (one-shot operator reconciliation)
    lines.append("## Conflicting values\n")
    if not report.conflicting_values:
        lines.append("*No same-name numeric setting was found with diverging values across files.*")
    else:
        lines.append("| Setting | Expected | Occurrences |")
        lines.append("|---|---|---|")
        for cv in report.conflicting_values:
            occs = "<br/>".join(
                f"`{o['file']}:{o.get('line','?')}` = `{o['value']}`"
                for o in cv.occurrences
            )
            lines.append(f"| `{cv.name}` | {cv.expected or '—'} | {occs} |")
    lines.append("")

    # 6. Warnings
    lines.append("## Warnings\n")
    if not warns:
        lines.append("*None.*")
    else:
        for f in warns[:40]:
            _emit_finding(lines, f)
        if len(warns) > 40:
            lines.append(f"\n*…and {len(warns) - 40} more (see JSON for full list)*")
    lines.append("")

    # 7. Per-category scorecard
    lines.append("## Category scorecard\n")
    lines.append("| Category | Weight | Score | Status | PASS | WARN | FAIL | BLOCKED | SKIP |")
    lines.append("|---|---:|---:|---|---:|---:|---:|---:|---:|")
    for name, cat in report.categories.items():
        lines.append(
            f"| {name} | {cat.weight} | {cat.score():.1f} | "
            f"{_STATUS_EMOJI.get(cat.overall_status(), '')} {cat.overall_status()} | "
            f"{cat.pass_count} | {cat.warn_count} | {cat.fail_count} | "
            f"{cat.blocked_count} | {cat.skip_count} |"
        )
    lines.append("")

    # 8. Recommended fixes — concrete next steps
    recs = [f for f in findings
            if f.recommendation and f.status in ("FAIL", "WARN", "BLOCKED")]
    if recs:
        lines.append("## Recommended fixes\n")
        for f in recs[:30]:
            lines.append(f"- **[{f.status}] {f.id}** — {f.recommendation}")
        if len(recs) > 30:
            lines.append(f"\n*…and {len(recs) - 30} more in the JSON report*")
        lines.append("")

    return "\n".join(lines) + "\n"


def _emit_finding(lines: list[str], f: Finding) -> None:
    icon = _STATUS_EMOJI.get(f.status, "·")
    lines.append(f"### {icon} `{f.id}` — {f.status}\n")
    lines.append(f"- category: `{f.category}`")
    if f.principle:
        lines.append(f"- principle: `{f.principle}`")
    lines.append(f"- message: {f.message}")
    if f.expected:
        lines.append(f"- expected: {f.expected}")
    if f.observed:
        lines.append(f"- observed: {f.observed}")
    if f.recommendation:
        lines.append(f"- fix: {f.recommendation}")
    if f.evidence:
        lines.append("- evidence:")
        for e in f.evidence[:5]:
            line_str = f":{e.line}" if e.line else ""
            snip = (": `" + e.snippet + "`") if e.snippet else ""
            lines.append(f"    - `{e.file}{line_str}`{snip}")
    lines.append("")


# ─── JSON ────────────────────────────────────────────────────────────────────

def render_json(report: StrategyCoherenceReport) -> str:
    return json.dumps(report.to_dict(), indent=2, default=str, sort_keys=False)


# ─── File output ─────────────────────────────────────────────────────────────

def write_outputs(report: StrategyCoherenceReport, out_dir: Path,
                  *, json_only: bool = False, md_only: bool = False) -> dict:
    """Write JSON / Markdown to `out_dir` (latest + timestamped)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # Timestamp slug from generated_at (`2026-05-14T18:23:45Z` → `20260514T182345Z`)
    ts = (report.generated_at
          .replace("-", "").replace(":", ""))
    if not ts.endswith("Z"):
        ts = ts + "Z"

    if not md_only:
        latest_json = out_dir / "latest.json"
        latest_json.write_text(render_json(report))
        paths["latest_json"] = latest_json
        snap = out_dir / f"{ts}.json"
        snap.write_text(latest_json.read_text())
        paths["snapshot_json"] = snap

    if not json_only:
        latest_md = out_dir / "latest.md"
        latest_md.write_text(render_markdown(report))
        paths["latest_md"] = latest_md
        snap = out_dir / f"{ts}.md"
        snap.write_text(latest_md.read_text())
        paths["snapshot_md"] = snap

    return {k: str(v) for k, v in paths.items()}

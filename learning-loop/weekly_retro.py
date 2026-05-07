"""
Weekly Retrospective — Sunday 22:00 UTC.

Reads last 7 daily history reports + rationale tail + current state,
forwards to Learning Loop Strategist routine (type=weekly_retrospective),
parses the JSON response and writes:
  - learning-loop/weekly-retros/<week_end>.md (full retro)
  - applies state_overrides via the same whitelist-enforced helper
  - appends key insights to rationale.md
  - appends experiments_next_week to heuristic_proposals.md

Fail-soft: if LLM unavailable, writes a minimal retro from local data
so the file is never empty — operator still gets a Sunday summary.

Budget: 1 routine call/week. Combined with daily annotator (1/day) =
~1.14 routine calls/day → 13.86 unused budget vs the 15/day Anthropic
limit.
"""

import json
import os
import subprocess
import sys
import glob
from datetime import datetime, timezone, timedelta


def _git_current_branch() -> str:
    """Best-effort detection of the workflow's branch (used in LLM payload)."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "main"

LEARNING_DIR    = os.path.dirname(os.path.abspath(__file__))
STATE_PATH      = os.path.join(LEARNING_DIR, "state.json")
RATIONALE_PATH  = os.path.join(LEARNING_DIR, "rationale.md")
HISTORY_DIR     = os.path.join(LEARNING_DIR, "history")
RETROS_DIR      = os.path.join(LEARNING_DIR, "weekly-retros")
PROPOSALS_PATH  = os.path.join(LEARNING_DIR, "heuristic_proposals.md")

sys.path.insert(0, LEARNING_DIR)
from llm_client import (   # noqa: E402
    call_routine, safe_apply_overrides, append_heuristic_proposals,
)


def collect_inputs() -> dict:
    """Gather last 7 daily history files, rationale tail, current state."""
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=6)
    week_end   = today

    daily_reports: list[str] = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        path = os.path.join(HISTORY_DIR, f"{d.isoformat()}.md")
        try:
            with open(path) as f:
                daily_reports.append(f.read())
        except FileNotFoundError:
            daily_reports.append(f"# (missing report for {d.isoformat()})\n")

    # Rationale tail — last 50 bullets
    rationale_tail: list[str] = []
    try:
        with open(RATIONALE_PATH) as f:
            for ln in f.readlines():
                if ln.startswith("- "):
                    rationale_tail.append(ln[2:].strip())
        rationale_tail = rationale_tail[-50:]
    except FileNotFoundError:
        pass

    # Current state
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    return {
        "type":           "weekly_retrospective",
        "week_start":     week_start.isoformat(),
        "week_end":       week_end.isoformat(),
        "daily_reports":  daily_reports,
        "rationale_tail": rationale_tail,
        "current_state":  state,
        "target_branch":  os.environ.get("GITHUB_REF_NAME") or _git_current_branch(),
    }


def write_retro_file(week_end: str, payload: dict, llm_resp: dict | None) -> str:
    """Write the markdown retro file. Returns path."""
    os.makedirs(RETROS_DIR, exist_ok=True)
    path = os.path.join(RETROS_DIR, f"{week_end}.md")

    lines = [
        f"# Weekly Retrospective — week ending {week_end}",
        "",
        f"**Week:** {payload['week_start']} → {payload['week_end']}",
        "",
    ]

    if llm_resp:
        confidence = llm_resp.get("confidence", "?")
        lines.append(f"**Strategist confidence:** {confidence}")
        lines.append(f"**Market regime:** {llm_resp.get('market_regime', '?')}")
        lines.append("")
        lines.append("## P&L story")
        lines.append("")
        lines.append(llm_resp.get("week_pl_story", "(no narrative)"))
        lines.append("")

        sc = llm_resp.get("strategy_scorecard") or []
        if sc:
            lines.append("## Strategy scorecard")
            lines.append("")
            lines.append("| Rank | Strategy | P&L $ | Verdict |")
            lines.append("|---|---|---|---|")
            for s in sc:
                lines.append(
                    f"| {s.get('rank', '?')} | {s.get('name', '?')} | "
                    f"${s.get('pnl_usd', 0):,.2f} | {s.get('verdict', '?')} |"
                )
            lines.append("")

        ar = llm_resp.get("allocation_recommendation") or {}
        if ar:
            lines.append("## Allocation recommendation (gross %)")
            lines.append("")
            for k in ("stocks_pct", "leveraged_etf_pct", "crypto_pct",
                       "options_pct", "defense_geo_pct", "twitter_pct"):
                if k in ar:
                    lines.append(f"- **{k}**: {ar[k]:.0f}%")
            if ar.get("rationale"):
                lines.append("")
                lines.append(f"_{ar['rationale']}_")
            lines.append("")

        bs = llm_resp.get("best_sources") or []
        ws = llm_resp.get("worst_sources") or []
        if bs or ws:
            lines.append("## Source quality")
            lines.append("")
            if bs:
                lines.append("**Best (boost weight):**")
                for s in bs:
                    lines.append(f"- {s.get('source', '?')} — "
                                 f"win rate {s.get('win_rate', 0)*100:.0f}%, "
                                 f"P&L ${s.get('pnl', 0):,.2f}")
            if ws:
                lines.append("")
                lines.append("**Worst (cut weight or silence):**")
                for s in ws:
                    lines.append(f"- {s.get('source', '?')} — "
                                 f"win rate {s.get('win_rate', 0)*100:.0f}%, "
                                 f"P&L ${s.get('pnl', 0):,.2f}")
            lines.append("")

        mistakes = llm_resp.get("structural_mistakes") or []
        if mistakes:
            lines.append("## Structural mistakes")
            lines.append("")
            for m in mistakes:
                lines.append(f"- **${m.get('lost_usd', 0):,.0f}** — "
                             f"{m.get('description', '')}")
                if m.get("remediation"):
                    lines.append(f"  - Remediation: {m['remediation']}")
            lines.append("")

        exps = llm_resp.get("experiments_next_week") or []
        if exps:
            lines.append("## Experiments for next week")
            lines.append("")
            for e in exps:
                if isinstance(e, dict):
                    lines.append(f"- **Hypothesis:** {e.get('hypothesis', '')}")
                    if e.get("metric"):
                        lines.append(f"  - Metric: {e['metric']}")
                    if e.get("revert_if"):
                        lines.append(f"  - Revert if: {e['revert_if']}")
                else:
                    lines.append(f"- {e}")
            lines.append("")
    else:
        # Fail-soft retro from local data only
        lines.append("> ⚠️ LLM strategist unavailable this run (rate-limit or 429).")
        lines.append("> Falling back to local statistics; no qualitative overlay.")
        lines.append("")
        cur = payload["current_state"]
        cum = cur.get("cumulative", {})
        lines.append("## Current state snapshot")
        lines.append("")
        lines.append(f"- Total trades (lifetime): {cum.get('total_trades', 0)}")
        lines.append(f"- Total P&L (lifetime):    ${cum.get('total_pnl_usd', 0):,.2f}")
        lines.append(f"- Strategies tracked:      {len(cur.get('strategies', {}))}")
        lines.append("")
        lines.append("### Per-strategy stats (current)")
        lines.append("")
        lines.append("| Strategy | Trades 7d | Win rate | P&L 7d | Mult | Enabled |")
        lines.append("|---|---|---|---|---|---|")
        for name, s in cur.get("strategies", {}).items():
            lines.append(
                f"| {name} | {s.get('trades_7d', 0)} | "
                f"{s.get('win_rate_7d', 0)*100:.0f}% | "
                f"${s.get('pnl_usd_7d', 0):,.2f} | "
                f"{s.get('size_multiplier', 1.0):.2f} | "
                f"{'yes' if s.get('enabled', True) else 'NO'} |"
            )
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def append_rationale_lines(lines: list[str]) -> None:
    """Append weekly retro entries to rationale.md (top of file)."""
    if not lines:
        return
    blob = "\n".join(f"- {ln}" for ln in lines) + "\n\n"
    try:
        with open(RATIONALE_PATH) as f:
            existing = f.read()
    except FileNotFoundError:
        existing = "# Learning Loop — Rationale Log\n\n"
    if "## " in existing:
        head, _, body = existing.partition("## ")
        new_content = head + blob + "## " + body
    else:
        new_content = existing + blob
    with open(RATIONALE_PATH, "w") as f:
        f.write(new_content)


def run():
    now = datetime.now(timezone.utc)
    print(f"\n[{now.isoformat()}] === WEEKLY RETROSPECTIVE ===")
    payload = collect_inputs()
    week_end = payload["week_end"]
    print(f"  Week: {payload['week_start']} → {week_end}")
    print(f"  Daily reports collected: {sum(1 for r in payload['daily_reports'] if not r.startswith('# (missing'))} / 7")
    print(f"  Rationale entries available: {len(payload['rationale_tail'])}")

    print("\n  Calling Learning Loop Strategist (weekly retro)...")
    llm_resp = call_routine(payload)

    # Apply state overrides (whitelist)
    state = payload["current_state"]
    rationale_lines = []
    if llm_resp:
        overrides = llm_resp.get("state_overrides") or {}
        state, applied = safe_apply_overrides(state, overrides)
        if applied:
            print("  Weekly state overrides applied:")
            for line in applied:
                print(f"    {line}")
            rationale_lines.extend(applied)

        # Headline rationale entry
        story = llm_resp.get("week_pl_story") or ""
        regime = llm_resp.get("market_regime", "?")
        confidence = llm_resp.get("confidence", "?")
        if story:
            rationale_lines.insert(
                0,
                f"{week_end} · WEEKLY[{confidence}] regime={regime}: {story.strip()[:200]}"
            )

        # Save state if overrides changed it
        if applied:
            with open(STATE_PATH, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")

        # Append experiments to heuristic_proposals
        exps = llm_resp.get("experiments_next_week") or []
        proposals = []
        for e in exps:
            if isinstance(e, dict):
                hyp = e.get("hypothesis", "")
                metric = e.get("metric", "")
                if hyp:
                    proposals.append(f"WEEKLY EXP: {hyp} (metric: {metric})")
            else:
                proposals.append(f"WEEKLY EXP: {e}")
        added = append_heuristic_proposals(proposals, PROPOSALS_PATH)
        if added:
            print(f"  Queued {added} weekly experiment(s) -> heuristic_proposals.md")
    else:
        rationale_lines.append(
            f"{week_end} · WEEKLY RETRO: LLM unavailable — fallback report only"
        )

    if rationale_lines:
        append_rationale_lines(rationale_lines)

    path = write_retro_file(week_end, payload, llm_resp)
    print(f"\n  Wrote retro: {path}")
    print(f"  Workflow will commit + push.")


if __name__ == "__main__":
    run()

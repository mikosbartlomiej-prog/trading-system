#!/usr/bin/env python3
"""
scripts/monitor_health.py — workflow health introspection.

Runs INSIDE a GitHub Actions workflow (uses the auto-injected GITHUB_TOKEN
to call the REST API). Polls /actions/workflows/{file}/runs for every
monitor workflow we care about, classifies status, computes observed
cadence, and writes a Markdown report to:

    learning-loop/health/<UTC datetime>.md
    learning-loop/health/latest.md       (always overwritten — easy read)

Per workflow output:
  - last_run_ts (UTC)
  - last_run_status (queued | in_progress | completed)
  - last_run_conclusion (success | failure | cancelled | skipped | startup_failure)
  - runs_last_24h
  - success_rate_last_24h
  - observed_cadence_minutes (median gap between last 10 consecutive runs)
  - expected_cadence_minutes (parsed from workflow file's cron expr)
  - cadence_drift_ratio (observed / expected; ≥2.0 = monitor likely stuck)
  - last_failure_summary (run id + URL + first error line if any)
  - first_2_log_lines_of_last_run (best-effort, for sanity)

Exit codes:
  0 — report written
  2 — GITHUB_TOKEN missing or API unreachable

Usage in a workflow step:
  env:
    GITHUB_TOKEN:           ${{ secrets.GITHUB_TOKEN }}
    GH_REPO:                ${{ github.repository }}    # owner/repo
  run: python scripts/monitor_health.py

For local smoke test with mocked data:
  python scripts/monitor_health.py --self-test
"""

import argparse
import json
import os
import sys
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HEALTH_DIR = _REPO_ROOT / "learning-loop" / "health"
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# Workflows to check + label + which asset class they target. Order = report order.
_WORKFLOWS = [
    ("price-monitor.yml",          "price-monitor",          "us_equity"),
    ("crypto-monitor.yml",         "crypto-monitor",         "crypto"),
    ("defense-monitor.yml",        "defense-monitor",        "us_equity"),
    ("geo-monitor.yml",            "geo-monitor",            "us_equity"),
    ("reddit-monitor.yml",         "reddit-monitor",         "mixed"),
    ("twitter-monitor.yml",        "twitter-monitor",        "mixed"),
    ("options-monitor.yml",        "options-monitor",        "us_option"),
    ("options-exit-monitor.yml",   "options-exit-monitor",   "us_option"),
    ("exit-monitor.yml",           "exit-monitor",           "mixed"),
    ("daily-learning.yml",         "daily-learning",         "ops"),
    ("weekly-retro.yml",           "weekly-retro",           "ops"),
    ("auto-merge.yml",             "auto-merge",             "ops"),
    ("keep-alive.yml",             "keep-alive",             "ops"),
    ("snapshot.yml",               "snapshot",               "ops"),
]


# ─── GitHub API helpers ──────────────────────────────────────────────

def _api_get(path: str, token: str, repo: str) -> dict | list:
    url = f"https://api.github.com/repos/{repo}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization":       f"Bearer {token}",
        "Accept":              "application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":          "trading-system-monitor-health",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def _list_runs(workflow_file: str, token: str, repo: str, per_page: int = 20) -> list[dict]:
    """Return list of recent runs for a workflow file."""
    resp = _api_get(f"/actions/workflows/{workflow_file}/runs?per_page={per_page}",
                     token, repo)
    if isinstance(resp, dict) and "_error" in resp:
        return [{"_error": resp["_error"]}]
    return resp.get("workflow_runs", [])


# ─── Cron parsing (best-effort cadence prediction) ─────────────────────

def _parse_cron_to_minutes(workflow_path: Path) -> int | None:
    """
    Read the workflow YAML, find cron lines, return the SMALLEST cadence
    in minutes implied. Recognizes:
      '*/N * * * *'             → N
      'M,N,...,Z * * * *'        → smallest gap (cyclic)
      '0,30 * * * *'             → 30
      '30 12-21 * * 1-5'         → 60 (hourly window)
      'M HH * * *' (single hour) → ~1440 (daily)
    Returns None if can't parse.
    """
    try:
        content = workflow_path.read_text()
    except FileNotFoundError:
        return None
    crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", content)
    if not crons:
        return None
    cadences = []
    for cron in crons:
        parts = cron.split()
        if len(parts) < 5:
            continue
        m_field = parts[0]
        # */N pattern
        if m_field.startswith("*/"):
            try:
                cadences.append(int(m_field[2:]))
            except ValueError:
                pass
            continue
        # Comma list pattern: 0,30 or 0,15,30,45
        if "," in m_field:
            try:
                nums = sorted(int(x) for x in m_field.split(","))
                gaps = [(nums[i+1] - nums[i]) for i in range(len(nums) - 1)]
                if gaps:
                    cadences.append(min(gaps))
                else:
                    cadences.append(60)
            except ValueError:
                pass
            continue
        # Hour-only window (e.g. '30 12-21 * * 1-5') → hourly
        if m_field.isdigit():
            cadences.append(60)
            continue
    return min(cadences) if cadences else None


# ─── Report computation ────────────────────────────────────────────────

def _median(nums: list[float]) -> float:
    if not nums:
        return 0.0
    s = sorted(nums)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _parse_ts(s: str) -> datetime:
    """ISO 8601 from GitHub API."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _classify_workflow(workflow_file: str, label: str, asset_class: str,
                        runs: list[dict], expected_min: int | None,
                        now: datetime) -> dict:
    """Compute summary stats for one workflow."""
    out = {
        "workflow_file":    workflow_file,
        "label":            label,
        "asset_class":      asset_class,
        "expected_cadence_min": expected_min,
        "runs_total_returned":  len(runs),
    }

    # API error case
    if runs and isinstance(runs[0], dict) and "_error" in runs[0]:
        out["status"] = "API_ERROR"
        out["error"] = runs[0]["_error"]
        return out

    if not runs:
        out["status"] = "NO_RUNS"
        return out

    # Sort newest first (API does this, but be defensive)
    runs = sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)
    last = runs[0]

    out["last_run_id"]         = last.get("id")
    out["last_run_status"]     = last.get("status")        # queued|in_progress|completed
    out["last_run_conclusion"] = last.get("conclusion")    # success|failure|cancelled|skipped|None
    out["last_run_url"]        = last.get("html_url")
    out["last_run_ts"]         = last.get("created_at")
    out["last_run_event"]      = last.get("event")

    # Drift
    last_ts = _parse_ts(last["created_at"])
    minutes_since = int((now - last_ts).total_seconds() / 60)
    out["minutes_since_last_run"] = minutes_since
    if expected_min:
        out["staleness_ratio"] = round(minutes_since / expected_min, 2)

    # Last 24h subset
    cutoff = now - timedelta(hours=24)
    recent = [r for r in runs if _parse_ts(r["created_at"]) >= cutoff]
    out["runs_last_24h"] = len(recent)
    succ = sum(1 for r in recent if r.get("conclusion") == "success")
    fail = sum(1 for r in recent if r.get("conclusion") == "failure")
    out["successes_last_24h"] = succ
    out["failures_last_24h"]  = fail
    if recent:
        out["success_rate_last_24h"] = round(succ / len(recent), 2)

    # Observed cadence — median gap between last 10 runs
    timestamps = [_parse_ts(r["created_at"]) for r in runs[:10]]
    if len(timestamps) >= 2:
        gaps = [(timestamps[i] - timestamps[i+1]).total_seconds() / 60
                for i in range(len(timestamps) - 1)]
        out["observed_cadence_min"] = round(_median(gaps), 1)
        if expected_min:
            out["cadence_drift_ratio"] = round(out["observed_cadence_min"] / expected_min, 2)

    # Last failure
    last_fail = next((r for r in runs if r.get("conclusion") == "failure"), None)
    if last_fail:
        out["last_failure_id"]  = last_fail.get("id")
        out["last_failure_url"] = last_fail.get("html_url")
        out["last_failure_ts"]  = last_fail.get("created_at")

    # Health status verdict
    out["status"] = _verdict(out)
    return out


def _verdict(s: dict) -> str:
    """
    HEALTHY / STALE / FAILING / IDLE / API_ERROR per stats:
      - API_ERROR if API failed
      - FAILING if last conclusion is failure
      - STALE if last run > 3x expected cadence ago AND expected cadence known
      - IDLE if no runs in last 24h
      - else HEALTHY
    """
    if s.get("error"):
        return "API_ERROR"
    last_conc = s.get("last_run_conclusion")
    if last_conc == "failure":
        return "FAILING"
    if s.get("expected_cadence_min") and s.get("staleness_ratio") is not None:
        if s["staleness_ratio"] > 3.0:
            return "STALE"
    if s.get("runs_last_24h", 0) == 0:
        return "IDLE"
    return "HEALTHY"


# ─── Markdown report ───────────────────────────────────────────────────

def _emoji(status: str) -> str:
    return {
        "HEALTHY":   "OK",
        "FAILING":   "FAIL",
        "STALE":     "STALE",
        "IDLE":      "IDLE",
        "API_ERROR": "ERR",
        "NO_RUNS":   "NONE",
    }.get(status, "?")


def _to_md(stats: list[dict], now: datetime) -> str:
    lines = []
    lines.append(f"# Monitor health report — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("Generated by `scripts/monitor_health.py` from a GitHub Actions runner.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    totals = {}
    for s in stats:
        totals[s["status"]] = totals.get(s["status"], 0) + 1
    for status, count in sorted(totals.items()):
        lines.append(f"- **{status}**: {count}")
    lines.append("")
    lines.append("## Per-workflow detail")
    lines.append("")
    lines.append("| Status | Workflow | Last run | Mins ago | Expected | Observed | Drift | 24h S/F |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for s in stats:
        last_ts = (s.get("last_run_ts") or "—")[:16].replace("T", " ")
        mins    = s.get("minutes_since_last_run", "—")
        exp_c   = s.get("expected_cadence_min", "—")
        obs_c   = s.get("observed_cadence_min", "—")
        drift   = s.get("cadence_drift_ratio", "—")
        sf      = f"{s.get('successes_last_24h',0)}/{s.get('failures_last_24h',0)}"
        lines.append(
            f"| {_emoji(s['status'])} | {s['label']} | {last_ts} | {mins} | {exp_c} | {obs_c} | {drift} | {sf} |"
        )
    lines.append("")

    # Failing detail
    failing = [s for s in stats if s["status"] == "FAILING"]
    if failing:
        lines.append("## Failing workflows — last conclusion")
        lines.append("")
        for s in failing:
            lines.append(f"### {s['label']}")
            lines.append(f"- Last failure: {s.get('last_failure_ts','?')} (id `{s.get('last_failure_id','?')}`)")
            lines.append(f"- URL: {s.get('last_failure_url','—')}")
            lines.append(f"- Last run conclusion: **{s.get('last_run_conclusion')}** at {s.get('last_run_ts')}")
            lines.append("")

    # Stale / Idle
    stale = [s for s in stats if s["status"] in ("STALE", "IDLE")]
    if stale:
        lines.append("## Stale or idle (likely not running)")
        lines.append("")
        for s in stale:
            lines.append(f"- **{s['label']}** ({s['status']}) — last run "
                          f"{s.get('minutes_since_last_run','?')} min ago, "
                          f"expected every {s.get('expected_cadence_min','?')} min")
        lines.append("")

    # API errors
    api_errs = [s for s in stats if s["status"] == "API_ERROR"]
    if api_errs:
        lines.append("## API errors")
        lines.append("")
        for s in api_errs:
            lines.append(f"- **{s['label']}**: {s.get('error','?')}")
        lines.append("")

    # Quick links
    lines.append("## Quick links")
    lines.append("")
    lines.append("- All runs: https://github.com/mikosbartlomiej-prog/trading-system/actions")
    lines.append("- Latest: `learning-loop/health/latest.md`")
    lines.append("")
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────

def _run(repo: str, token: str) -> int:
    now = datetime.now(timezone.utc)
    stats = []
    for wf_file, label, asset_class in _WORKFLOWS:
        wf_path = _WORKFLOWS_DIR / wf_file
        expected = _parse_cron_to_minutes(wf_path)
        runs = _list_runs(wf_file, token, repo)
        stats.append(_classify_workflow(wf_file, label, asset_class, runs, expected, now))

    _HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    md = _to_md(stats, now)
    ts = now.strftime("%Y-%m-%d_%H%M")
    dated_path  = _HEALTH_DIR / f"{ts}.md"
    latest_path = _HEALTH_DIR / "latest.md"
    json_path   = _HEALTH_DIR / "latest.json"
    dated_path.write_text(md)
    latest_path.write_text(md)
    json_path.write_text(json.dumps({"generated_at": now.isoformat(),
                                       "workflows": stats}, indent=2))
    print(f"[health] wrote {dated_path.name} + latest.md + latest.json")
    # Echo summary verdicts to stdout for cron log
    for s in stats:
        print(f"  {_emoji(s['status']):<5} {s['label']:<22} "
                f"last_run={s.get('minutes_since_last_run','?'):>4}min  "
                f"drift={s.get('cadence_drift_ratio','—')}  "
                f"24h={s.get('successes_last_24h',0)}/{s.get('failures_last_24h',0)}")
    return 0


def _self_test() -> int:
    """Run with no API access — produce a report with fake data."""
    now = datetime.now(timezone.utc)
    fake = [
        {"label": "price-monitor", "asset_class": "us_equity",
         "status": "HEALTHY", "expected_cadence_min": 5, "observed_cadence_min": 5.1,
         "minutes_since_last_run": 3, "cadence_drift_ratio": 1.02,
         "last_run_ts": "2026-05-12T17:30:00Z", "last_run_conclusion": "success",
         "successes_last_24h": 78, "failures_last_24h": 0, "runs_last_24h": 78},
        {"label": "defense-monitor", "asset_class": "us_equity",
         "status": "FAILING", "expected_cadence_min": 5, "observed_cadence_min": 5.0,
         "minutes_since_last_run": 4, "cadence_drift_ratio": 1.0,
         "last_run_ts": "2026-05-12T17:31:00Z", "last_run_conclusion": "failure",
         "successes_last_24h": 280, "failures_last_24h": 3, "runs_last_24h": 288,
         "last_failure_id": 12345, "last_failure_ts": "2026-05-12T17:31:00Z",
         "last_failure_url": "https://example.com/actions/runs/12345",
         "workflow_file": "defense-monitor.yml"},
    ]
    _HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    (_HEALTH_DIR / "selftest.md").write_text(_to_md(fake, now))
    print("[health] self-test wrote selftest.md")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true",
                    help="Generate report with fake data (no API call); local smoke test")
    args = p.parse_args()

    if args.self_test:
        return _self_test()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo  = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("[health] ERROR: GITHUB_TOKEN + GH_REPO required (set in workflow env)")
        return 2
    return _run(repo, token)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""v3.12.0 (2026-05-30) — Local end-of-session reporter.

WHY
---
Per audit spec ETAP 0-12: "lokalne raportowanie" + "Wygenerowanie
raportu końcowego" are required for autonomous-session contract.
We have daily history files written by analyzer.py, but those are
calendar-day-end after market close (22:24 UTC). We need a
*session-end* report that an operator can trigger ANYTIME (or that
runs after the 20:00 UTC market close) summarizing:

  * Equity / intraday P&L
  * Intraday governor state + peak / giveback
  * Open positions + concentration
  * Decisions in last 24h (PLACED / SKIPPED / BLOCKED / FAILED) by actor
  * Confidence score distribution (if confidence_history populated)
  * Safe-mode events
  * Incident detector findings
  * Routine budget usage
  * Heartbeat liveness
  * Top risk flags

OUTPUT
------
1. Markdown report: reports/sessions/<date>_<time>.md
2. Latest symlink:  reports/sessions/latest.md
3. (Optional) email if notify available and operator wants it
4. Exit code 0 on success (even if findings are negative — emitting
   the report IS the success).

NO PAID DEPS. Uses only local files: runtime_state.json, audit JSONL,
state.json, allocations/*.json, incidents/*.md, learning-loop/health/.

USAGE
-----
python3 scripts/session_report.py                 # generates current
python3 scripts/session_report.py --date 2026-05-30  # historical
python3 scripts/session_report.py --no-write      # stdout only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ─── Data collectors ─────────────────────────────────────────────────────────

def collect_runtime_state() -> dict:
    """Read runtime_state.json. Fail-soft → empty dict."""
    try:
        with open(_REPO_ROOT / "learning-loop" / "runtime_state.json") as f:
            return json.load(f)
    except Exception:
        return {}


def collect_audit_jsonl(date_iso: str) -> list[dict]:
    """Read journal/autonomy/<date>.jsonl. Returns list[event]."""
    path = _REPO_ROOT / "journal" / "autonomy" / f"{date_iso}.jsonl"
    if not path.exists():
        return []
    events = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return events


def collect_allocation(date_iso: str) -> tuple[dict | None, dict | None]:
    """Read today's allocation plan + execution log. (plan, exec)."""
    plan_path = _REPO_ROOT / "learning-loop" / "allocations" / f"{date_iso}.json"
    exec_path = _REPO_ROOT / "learning-loop" / "allocations" / f"{date_iso}.execution.json"
    plan = None
    execution = None
    if plan_path.exists():
        try:
            with open(plan_path) as f:
                plan = json.load(f)
        except Exception:
            pass
    if exec_path.exists():
        try:
            with open(exec_path) as f:
                execution = json.load(f)
        except Exception:
            pass
    return plan, execution


def collect_incidents(date_iso: str) -> str:
    """Read incidents/<date>.md if any. Returns text or empty string."""
    path = _REPO_ROOT / "learning-loop" / "incidents" / f"{date_iso}.md"
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except Exception:
        return ""


def collect_state_json() -> dict:
    """Read learning-loop/state.json. Fail-soft → empty dict."""
    try:
        with open(_REPO_ROOT / "learning-loop" / "state.json") as f:
            return json.load(f)
    except Exception:
        return {}


# ─── Analytics ───────────────────────────────────────────────────────────────

def summarize_audit_events(events: list[dict]) -> dict:
    """Bucket audit events by decision_type + decision + actor."""
    by_type = Counter()
    by_actor = Counter()
    by_decision = Counter()
    safe_mode_transitions = []
    failures = []
    confidence_blocks = []
    for e in events:
        dt = e.get("decision_type") or "?"
        actor = e.get("actor") or "?"
        dec = e.get("decision") or "?"
        by_type[dt] += 1
        by_actor[actor] += 1
        by_decision[dec] += 1
        # Surface specific events
        if "SAFE_MODE" in dt:
            safe_mode_transitions.append({
                "ts":   e.get("timestamp", "")[:19],
                "type": dt,
                "reason": (e.get("reason") or "")[:120],
            })
        if dec == "FAILED":
            failures.append({
                "ts":     e.get("timestamp", "")[:19],
                "type":   dt,
                "reason": (e.get("reason") or "")[:120],
                "symbol": (e.get("affected_symbols") or [None])[0],
            })
        if dec == "BLOCK" and "CONFIDENCE" in dt:
            confidence_blocks.append({
                "ts":     e.get("timestamp", "")[:19],
                "reason": (e.get("reason") or "")[:120],
            })
    return {
        "total":              len(events),
        "by_type":            dict(by_type.most_common(20)),
        "by_actor":           dict(by_actor.most_common(20)),
        "by_decision":        dict(by_decision),
        "safe_mode_events":   safe_mode_transitions,
        "failures":           failures[:10],
        "confidence_blocks":  confidence_blocks[:10],
    }


def summarize_positions(rs: dict, plan: dict | None) -> dict:
    """Position summary from plan (most accurate snapshot)."""
    if not plan:
        return {"count": 0, "symbols": [], "invested_ratio": None}
    positions = plan.get("current_positions") or []
    invested = plan.get("invested_ratio_before")
    return {
        "count": len(positions),
        "symbols": sorted(set(
            p.get("symbol", "") for p in positions if p.get("symbol")
        )),
        "invested_ratio":  invested,
        "account_equity":  plan.get("account_equity"),
        "buying_power":    plan.get("buying_power"),
        "pdt_mode":        plan.get("pdt_mode"),
        "regime":          plan.get("market_regime"),
    }


def summarize_governor(rs: dict) -> dict:
    """IntradayProfitGovernor snapshot."""
    g = rs.get("intraday_governor") or {}
    return {
        "state":              g.get("pnl_state"),
        "intraday_pnl_usd":   g.get("current_intraday_pnl"),
        "intraday_pnl_pct":   g.get("current_intraday_pnl_pct"),
        "intraday_peak_pnl":  g.get("intraday_peak_pnl"),
        "giveback_pct":       g.get("giveback_pct_of_peak"),
        "max_gross_target":   g.get("max_gross_target"),
        "block_new_entries":  g.get("block_new_entries"),
        "profit_floor_usd":   g.get("profit_floor_usd"),
    }


def summarize_safe_mode(rs: dict) -> dict:
    """Safe-mode snapshot."""
    s = rs.get("safe_mode") or {}
    return {
        "active":     bool(s.get("active", False)),
        "trigger":    s.get("trigger"),
        "reason":     s.get("reason"),
        "entered_at": s.get("entered_at"),
        "forced":     bool(s.get("forced", False)),
    }


def summarize_heartbeat(rs: dict, max_age: int = 600) -> dict:
    """Heartbeat liveness from runtime_state."""
    hb = rs.get("heartbeat") or {}
    now = datetime.now(timezone.utc)
    alive = []
    stale = []
    for component, entry in hb.items():
        try:
            last_iso = entry.get("last_seen_iso") or ""
            last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
            age = (now - last).total_seconds()
            if age <= max_age:
                alive.append({"component": component, "age_s": int(age)})
            else:
                stale.append({"component": component, "age_s": int(age)})
        except Exception:
            stale.append({"component": component, "age_s": -1})
    return {
        "alive": sorted(alive, key=lambda x: x["age_s"]),
        "stale": sorted(stale, key=lambda x: x["component"]),
    }


def summarize_routine_budget(rs: dict) -> dict:
    """Routine budget snapshot."""
    rb = rs.get("routine_budget") or {}
    return rb


def summarize_strategies(state: dict) -> dict:
    """Enabled / disabled strategy snapshot."""
    strats = state.get("strategies") or {}
    enabled = [n for n, c in strats.items() if c.get("enabled")]
    disabled = [n for n, c in strats.items() if not c.get("enabled")]
    return {
        "enabled":  sorted(enabled),
        "disabled": sorted(disabled),
        "total":    len(strats),
    }


# ─── v3.13.x — Readiness gaps detection ─────────────────────────────────────
#
# Auto-detected known system-readiness gaps from backlog
# `learning-loop/heuristic_proposals.md::v3.13.x — System-readiness gaps`.
# Each gap is checked from real state; if it persists, surfaced as 🟡 info
# badge so operator sees it daily and remembers to implement.

def check_readiness_gaps(rs: dict, state: dict) -> list:
    """Surface the 4 known readiness gaps from v3.13.x backlog.

    Returns a list of {key, status, badge, message} dicts. Each gap auto-
    resolves when its definition-of-done is met (no manual close needed).
    """
    gaps = []
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    # READINESS-1 — heartbeat wired in monitors?
    hb = rs.get("heartbeat") or {}
    expected_min = 5   # at least 5 of 11 monitors must ping for "wired"
    gaps.append({
        "key":     "READINESS-1",
        "title":   "Heartbeat module wiring",
        "status":  "OPEN" if len(hb) < expected_min else "RESOLVED",
        "badge":   "🟡" if len(hb) < expected_min else "✅",
        "message": (
            f"Heartbeat empty ({len(hb)}/11 monitors registered). "
            f"`confidence.system_health` falls back to neutral 0.5 — one "
            f"of 5 confidence components is blind. See heuristic_proposals.md "
            f"READINESS-1 for sketch (3 LOC per monitor)."
            if len(hb) < expected_min
            else f"Heartbeat wired ({len(hb)} monitors active)."
        ),
    })

    # READINESS-2 — edge gate disabled?
    import os
    edge_disabled = os.environ.get("EDGE_GATE_DISABLED", "true").lower() == "true"
    gaps.append({
        "key":     "READINESS-2",
        "title":   "EDGE_GATE_DISABLED flip required",
        "status":  "OPEN" if edge_disabled else "RESOLVED",
        "badge":   "🟡" if edge_disabled else "✅",
        "message": (
            "Edge gate disabled — strategies fire without statistical "
            "(WR≥50%, PF≥1.3, MDD<20%, n≥10) gate. To enable: run "
            "backtests for each enabled strategy, then flip "
            "EDGE_GATE_DISABLED=false in daily-learning.yml."
            if edge_disabled
            else "Edge gate enabled — strategies validated by backtest."
        ),
    })

    # READINESS-3 — 30+ paper trades milestone
    cumulative = 0
    try:
        cumulative = int(state.get("cumulative", {}).get("total_trades", 0) or 0)
    except (TypeError, ValueError):
        pass
    # Also tally strategy trades_lifetime for cross-check
    strat_trades = 0
    try:
        for cfg in (state.get("strategies") or {}).values():
            if isinstance(cfg, dict):
                strat_trades += int(cfg.get("trades_lifetime", 0) or 0)
    except (TypeError, ValueError):
        pass
    paper_count = max(cumulative, strat_trades)
    gaps.append({
        "key":     "READINESS-3",
        "title":   "30+ paper trades for empirical edge validation",
        "status":  "OPEN" if paper_count < 30 else "RESOLVED",
        "badge":   "🟡" if paper_count < 30 else "✅",
        "message": (
            f"Only {paper_count} paper trades to date. System has been "
            f"recovering from 45-day SILENT period (v3.11.3 fix unblocked "
            f"crypto pipeline). Need ≥30 closed trades + WR≥50% + PF≥1.3 "
            f"per strategy before any capital escalation discussion."
            if paper_count < 30
            else f"{paper_count} paper trades — edge validation possible."
        ),
    })

    # READINESS-4 — Multi-Agent Audit Board ran?
    audit_reports_dir = Path(__file__).resolve().parent.parent / "agents" / "reports"
    fa_reports = []
    if audit_reports_dir.exists():
        fa_reports = sorted(audit_reports_dir.glob("final_decision_*.md"))
    # Check if any final decision is ≤ 7 days old
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    has_recent = False
    latest_date = "never"
    for p in fa_reports:
        try:
            # Filename: final_decision_2026-06-07.md
            ds = p.stem.split("_", 2)[-1]  # 2026-06-07
            d  = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
            if d > cutoff:
                has_recent = True
            latest_date = ds
        except Exception:
            continue
    gaps.append({
        "key":     "READINESS-4",
        "title":   "Multi-Agent Audit Board first run / weekly cadence",
        "status":  "OPEN" if not has_recent else "RESOLVED",
        "badge":   "🟡" if not has_recent else "✅",
        "message": (
            f"Audit Board last run: {latest_date}. Need fresh "
            f"final_decision ≤ 7 days old before any capital escalation. "
            f"To run: `python3 agents/run_agent_board.py init <date>` then "
            f"work through 11 area prompts + Final Arbiter."
            if not has_recent
            else f"Audit Board last final_decision: {latest_date} (≤7d old, OK)."
        ),
    })

    return gaps


# ─── Risk flags ──────────────────────────────────────────────────────────────

def derive_risk_flags(governor: dict, safe_mode: dict, hb: dict,
                       audit_summary: dict, allocation_exec: dict | None) -> list:
    """List of human-readable risk flags surfaced in the report."""
    flags = []
    # Governor states
    if governor.get("state") in ("PROFIT_LOCK", "DEFEND_DAY", "RED_DAY_AFTER_GREEN"):
        flags.append(f"🟠 IntradayGovernor state = {governor['state']} "
                      f"(block_new_entries={governor.get('block_new_entries')})")
    # Safe mode
    if safe_mode.get("active"):
        flags.append(f"🔴 SAFE_MODE ACTIVE — trigger={safe_mode.get('trigger')}: "
                      f"{safe_mode.get('reason','')}")
    # Heartbeat staleness
    if len(hb.get("stale", [])) >= 3:
        flags.append(f"🟠 {len(hb['stale'])} components stale: "
                      f"{[x['component'] for x in hb['stale'][:5]]}")
    # Recent failures
    if len(audit_summary.get("failures", [])) >= 3:
        flags.append(f"🟠 {len(audit_summary['failures'])} FAILED decisions "
                      f"in audit JSONL")
    # Allocator failures
    if allocation_exec and allocation_exec.get("n_failed", 0) > 0 and \
       allocation_exec.get("n_placed", 0) == 0:
        flags.append(f"🟠 morning-allocator: 0 placed / "
                      f"{allocation_exec.get('n_failed')} failed")
    # Confidence blocks
    if audit_summary.get("confidence_blocks"):
        flags.append(f"🟡 {len(audit_summary['confidence_blocks'])} trades "
                      f"BLOCKED by confidence gate today")
    return flags


# ─── Markdown report ─────────────────────────────────────────────────────────

def render_markdown(date_iso: str, generated_at: str,
                     governor: dict, positions: dict, safe_mode: dict,
                     hb: dict, audit_summary: dict, routine_budget: dict,
                     strategies: dict, incidents_text: str,
                     allocation_plan: dict | None, allocation_exec: dict | None,
                     risk_flags: list,
                     readiness_gaps: list | None = None) -> str:
    """Render the full markdown session report."""

    def fmt_pct(v):
        if v is None: return "—"
        try: return f"{float(v)*100:.2f}%"
        except (TypeError, ValueError): return str(v)

    def fmt_usd(v):
        if v is None: return "—"
        try: return f"${float(v):,.2f}"
        except (TypeError, ValueError): return str(v)

    lines = []
    lines.append(f"# Session Report — {date_iso}")
    lines.append("")
    lines.append(f"_Generated at {generated_at}_")
    lines.append("")

    # ── Risk flags first (most important)
    if risk_flags:
        lines.append("## ⚠️ Risk flags")
        for f in risk_flags:
            lines.append(f"- {f}")
        lines.append("")
    else:
        lines.append("## ✅ No risk flags surfaced")
        lines.append("")

    # ── Readiness gaps (v3.13.x — known but not blocking)
    if readiness_gaps:
        open_gaps = [g for g in readiness_gaps if g["status"] == "OPEN"]
        resolved_gaps = [g for g in readiness_gaps if g["status"] == "RESOLVED"]
        lines.append(f"## Readiness gaps ({len(open_gaps)} open / {len(resolved_gaps)} resolved)")
        lines.append("")
        lines.append("_Backlog source: `learning-loop/heuristic_proposals.md` "
                      "(v3.13.x — System-readiness gaps section)._")
        lines.append("")
        for g in readiness_gaps:
            lines.append(f"- {g['badge']} **{g['key']}** — {g['title']}: {g['message']}")
        lines.append("")

    # ── Account snapshot
    lines.append("## Account")
    lines.append(f"- Equity: {fmt_usd(positions.get('account_equity'))}")
    lines.append(f"- Buying power: {fmt_usd(positions.get('buying_power'))}")
    lines.append(f"- Open positions: {positions.get('count', 0)}")
    if positions.get('symbols'):
        lines.append(f"- Symbols: {', '.join(positions['symbols'])}")
    lines.append(f"- Invested ratio: {fmt_pct(positions.get('invested_ratio'))}")
    lines.append(f"- Regime: {positions.get('regime')}")
    lines.append(f"- PDT mode: {positions.get('pdt_mode')}")
    lines.append("")

    # ── Intraday governor
    lines.append("## Intraday governor")
    lines.append(f"- FSM state: **{governor.get('state', 'unknown')}**")
    lines.append(f"- Intraday P&L: {fmt_usd(governor.get('intraday_pnl_usd'))} "
                  f"({fmt_pct(governor.get('intraday_pnl_pct'))})")
    lines.append(f"- Intraday peak P&L: {fmt_usd(governor.get('intraday_peak_pnl'))}")
    lines.append(f"- Giveback from peak: {fmt_pct(governor.get('giveback_pct'))}")
    lines.append(f"- Max gross target: {governor.get('max_gross_target')}")
    lines.append(f"- Profit floor: {fmt_usd(governor.get('profit_floor_usd'))}")
    lines.append(f"- Block new entries: {governor.get('block_new_entries')}")
    lines.append("")

    # ── Safe mode
    lines.append("## Safe mode")
    if safe_mode.get('active'):
        lines.append(f"- **ACTIVE** since {safe_mode.get('entered_at')}")
        lines.append(f"- Trigger: {safe_mode.get('trigger')}")
        lines.append(f"- Reason: {safe_mode.get('reason')}")
        lines.append(f"- Operator-forced: {safe_mode.get('forced')}")
    else:
        lines.append("- inactive")
    lines.append("")

    # ── Strategies
    lines.append("## Strategies")
    lines.append(f"- Total: {strategies.get('total', 0)}")
    lines.append(f"- Enabled ({len(strategies.get('enabled', []))}): "
                  f"{', '.join(strategies.get('enabled', []))}")
    lines.append(f"- Disabled ({len(strategies.get('disabled', []))}): "
                  f"{', '.join(strategies.get('disabled', []))}")
    lines.append("")

    # ── Allocator
    if allocation_plan or allocation_exec:
        lines.append("## Allocator")
        if allocation_plan:
            orders = allocation_plan.get("rebalance_orders") or []
            lines.append(f"- Plan generated: {allocation_plan.get('generated_at')}")
            lines.append(f"- Orders in plan: {len(orders)}")
        if allocation_exec:
            lines.append(f"- Executed at: {allocation_exec.get('executed_at')}")
            lines.append(f"- Placed: {allocation_exec.get('n_placed', 0)}")
            lines.append(f"- Skipped: {allocation_exec.get('n_skipped', 0)}")
            lines.append(f"- Failed: {allocation_exec.get('n_failed', 0)}")
        lines.append("")

    # ── Decisions / audit summary
    lines.append("## Decisions (audit JSONL)")
    lines.append(f"- Total events today: {audit_summary.get('total', 0)}")
    if audit_summary.get('by_decision'):
        lines.append("- By decision:")
        for k, v in audit_summary['by_decision'].items():
            lines.append(f"  - `{k}`: {v}")
    if audit_summary.get('by_actor'):
        lines.append("- By actor:")
        for k, v in list(audit_summary['by_actor'].items())[:10]:
            lines.append(f"  - `{k}`: {v}")
    if audit_summary.get('failures'):
        lines.append("- Recent FAILED events:")
        for f in audit_summary['failures'][:5]:
            sym = f.get('symbol') or '-'
            lines.append(f"  - {f['ts']}  {f['type']:25s}  {sym:8s}  {f['reason'][:80]}")
    if audit_summary.get('safe_mode_events'):
        lines.append("- Safe-mode transitions:")
        for e in audit_summary['safe_mode_events']:
            lines.append(f"  - {e['ts']}  {e['type']}: {e['reason']}")
    if audit_summary.get('confidence_blocks'):
        lines.append("- Confidence BLOCKs:")
        for c in audit_summary['confidence_blocks'][:5]:
            lines.append(f"  - {c['ts']}: {c['reason']}")
    lines.append("")

    # ── Heartbeat
    lines.append("## Heartbeat")
    lines.append(f"- Alive ({len(hb.get('alive', []))}): "
                  f"{', '.join(x['component'] for x in hb.get('alive', []))}")
    if hb.get('stale'):
        lines.append(f"- Stale ({len(hb['stale'])}):")
        for x in hb['stale']:
            age = x['age_s']
            age_str = f"{age}s" if age >= 0 else "never pinged"
            lines.append(f"  - {x['component']}: {age_str}")
    lines.append("")

    # ── Routine budget
    if routine_budget:
        lines.append("## Routine budget (Anthropic 15/day cap)")
        for tier, vals in routine_budget.items():
            if isinstance(vals, dict):
                used = vals.get('used', 0)
                cap = vals.get('cap', '-')
                lines.append(f"- {tier}: {used}/{cap}")
        lines.append("")

    # ── Incidents
    if incidents_text:
        lines.append("## Incidents (Layer 1)")
        # Show first 60 lines max
        excerpt = "\n".join(incidents_text.splitlines()[:60])
        lines.append("```")
        lines.append(excerpt)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("_Local report — no paid services. Cost: ~$0 / run._")
    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Local session report")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--no-write", action="store_true",
                          help="Print to stdout, don't write file")
    parser.add_argument("--out-dir", default=str(_REPO_ROOT / "reports" / "sessions"))
    args = parser.parse_args()

    date_iso = args.date or datetime.now(timezone.utc).date().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()

    # Collect
    rs       = collect_runtime_state()
    events   = collect_audit_jsonl(date_iso)
    plan, ex = collect_allocation(date_iso)
    incidents = collect_incidents(date_iso)
    state    = collect_state_json()

    # Analyze
    governor       = summarize_governor(rs)
    positions      = summarize_positions(rs, plan)
    safe_mode      = summarize_safe_mode(rs)
    hb             = summarize_heartbeat(rs)
    audit_summary  = summarize_audit_events(events)
    routine_budget = summarize_routine_budget(rs)
    strategies     = summarize_strategies(state)
    risk_flags     = derive_risk_flags(governor, safe_mode, hb, audit_summary, ex)
    # v3.13.x: surface 4 known readiness gaps so they appear daily until resolved
    readiness_gaps = check_readiness_gaps(rs, state)

    # Render
    md = render_markdown(date_iso, generated_at, governor, positions, safe_mode,
                          hb, audit_summary, routine_budget, strategies,
                          incidents, plan, ex, risk_flags,
                          readiness_gaps=readiness_gaps)

    if args.no_write:
        print(md)
        return 0

    # Write to disk
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out_path = out_dir / f"{date_iso}_{ts}.md"
    out_path.write_text(md)
    # latest symlink (overwrite atomically via os.replace on Posix)
    latest = out_dir / "latest.md"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out_path.name)
    except OSError:
        # Symlinks may not work on all FS — just write a copy
        latest.write_text(md)
    print(f"✓ Wrote session report: {out_path}")
    print(f"✓ Latest: {latest}")
    if risk_flags:
        print(f"⚠ {len(risk_flags)} risk flag(s) surfaced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

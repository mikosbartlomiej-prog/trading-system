#!/usr/bin/env python3
"""v3.19.0 (2026-06-04) — Daily Operator Dashboard (ETAP 10).

WHY
---
Audit-board final_decision 2026-06-02 (v3.14.0 cycle) marked the
system as APPROVE_PAPER_TRADING_WITH_WARNINGS + NOT_SAFE_FOR_LIVE_TRADING.
The operator now needs ONE single read-only file that answers all of
the obvious questions before each paper trading session:

  1. System health summary
  2. Heartbeat 11/11
  3. Paper workflow live?
  4. How many paper trades collected
  5. Strongest strategies by evidence
  6. Weakest strategies (WR/PF/recent_degradation)
  7. Confidence buckets actually-working
  8. Best instruments to observe
  9. Can EDGE_GATE flip?
  10. Why not?
  11. Active P0/P1 backlog items
  12. Is the system still free?
  13. Is live trading disabled?

The dashboard is **READ ONLY**. It cannot:
  - modify runtime_state
  - modify strategies
  - modify trading config
  - recommend live trading
  - call external APIs (everything is local file reads)

CONTRACT
--------
collect_dashboard_data()  → dict  (pure read)
render_dashboard_markdown(data) → str
render_dashboard_json(data)     → str
main(args)                → int   CLI entrypoint

Outputs:
  docs/operator_dashboard_LATEST.md
  docs/operator_dashboard_LATEST.json

All sections fail-soft. Missing inputs produce
{"available": False, "reason": "..."} so the report never crashes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SHARED = _REPO_ROOT / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


# ─── Output paths ─────────────────────────────────────────────────────────────

_DOCS_DIR = _REPO_ROOT / "docs"
_LATEST_MD = _DOCS_DIR / "operator_dashboard_LATEST.md"
_LATEST_JSON = _DOCS_DIR / "operator_dashboard_LATEST.json"


# ─── Fail-soft section helper ─────────────────────────────────────────────────

def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Section 1: System health summary ─────────────────────────────────────────

def _section_system_health() -> dict:
    out: dict[str, Any] = {"available": True}
    try:
        import heartbeat as hb  # type: ignore
        snap = hb.health_snapshot()
        out["heartbeat_alive"] = int(snap.get("alive") or 0)
        out["heartbeat_total"] = int(snap.get("total") or 0)
        out["heartbeat_ratio"] = float(snap.get("ratio") or 0.0)
        out["stale_components"] = list(snap.get("stale_components") or [])
    except Exception as e:  # fail-soft
        out["heartbeat_alive"] = 0
        out["heartbeat_total"] = 0
        out["heartbeat_ratio"] = 0.0
        out["stale_components"] = []
        out["heartbeat_error"] = str(e)

    # Last safe_mode transition (read from runtime_state)
    try:
        import safe_mode  # type: ignore
        s = safe_mode.read_state()
        out["safe_mode_active"] = bool(s.active)
        out["safe_mode_reason"] = s.reason or ""
        out["safe_mode_trigger"] = s.trigger or ""
        out["safe_mode_entered_at"] = s.entered_at or ""
    except Exception as e:
        out["safe_mode_active"] = False
        out["safe_mode_reason"] = ""
        out["safe_mode_trigger"] = ""
        out["safe_mode_entered_at"] = ""
        out["safe_mode_error"] = str(e)

    # Last incident from audit (best-effort)
    out["last_incident"] = _last_incident_from_audit()
    return out


def _last_incident_from_audit() -> dict:
    """Look at journal/autonomy/<today>.jsonl for the most recent
    P_INCIDENT_* or SAFE_MODE_ENTERED event. Fail-soft."""
    try:
        today_iso = datetime.now(timezone.utc).date().isoformat()
        path = _REPO_ROOT / "journal" / "autonomy" / f"{today_iso}.jsonl"
        if not path.exists():
            return {"present": False, "reason": "no audit JSONL today"}
        last: dict | None = None
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                kind = (rec.get("decision_type") or "").upper()
                if "INCIDENT" in kind or kind == "SAFE_MODE_ENTERED":
                    last = rec
        if last is None:
            return {"present": False, "reason": "no incident events today"}
        return {
            "present": True,
            "decision_type": last.get("decision_type"),
            "reason": last.get("reason"),
            "ts": last.get("ts") or last.get("timestamp"),
        }
    except Exception as e:
        return {"present": False, "reason": f"audit read failed: {e}"}


# ─── Section 2: Heartbeat 11/11 ───────────────────────────────────────────────

def _section_heartbeat() -> dict:
    try:
        import heartbeat as hb  # type: ignore
    except Exception as e:
        return _unavailable(f"heartbeat module import failed: {e}")
    try:
        snap = hb.health_snapshot()
        alive = int(snap.get("alive") or 0)
        total = int(snap.get("total") or 0)
        stale = list(snap.get("stale_components") or [])
        all_components = list(getattr(hb, "EXPECTED_COMPONENTS", ()))
        per_comp: list[dict] = []
        for c in all_components:
            age = hb.age_seconds(c)
            per_comp.append({
                "name": c,
                "stale": hb.stale(c),
                "age_seconds": age,
            })
        return {
            "available": True,
            "alive": alive,
            "total": total,
            "ratio": (alive / total) if total else 0.0,
            "stale_components": stale,
            "expected_components": all_components,
            "per_component": per_comp,
        }
    except Exception as e:
        return _unavailable(f"heartbeat snapshot failed: {e}")


# ─── Section 3: Paper workflow status ─────────────────────────────────────────

def _section_paper_workflow() -> dict:
    out: dict[str, Any] = {"available": True}
    template = _REPO_ROOT / "scripts" / "workflow-templates" / "paper-experiment-update.yml"
    deployed = _REPO_ROOT / ".github" / "workflows" / "paper-experiment-update.yml"
    out["template_exists"] = template.exists()
    out["deployed_exists"] = deployed.exists()
    if not template.exists():
        out["status"] = "MISSING_TEMPLATE"
    elif not deployed.exists():
        out["status"] = "TEMPLATE_READY_NOT_DEPLOYED"
    else:
        out["status"] = "DEPLOYED"
    return out


# ─── Section 4: Paper trades collected ────────────────────────────────────────

def _section_paper_trades_collected() -> dict:
    """Count records from learning-loop/paper_experiments/*.jsonl"""
    try:
        ledger_dir = Path(os.environ.get(
            "PAPER_EXPERIMENT_DIR",
            str(_REPO_ROOT / "learning-loop" / "paper_experiments"),
        ))
        if not ledger_dir.exists():
            return {
                "available": True,
                "total_records": 0,
                "files": 0,
                "ledger_dir": str(ledger_dir),
                "empty": True,
            }
        files = sorted(ledger_dir.glob("*.jsonl"))
        total = 0
        per_strategy: dict[str, int] = {}
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        total += 1
                        try:
                            rec = json.loads(line)
                            s = rec.get("strategy") or "unknown"
                            per_strategy[s] = per_strategy.get(s, 0) + 1
                        except Exception:
                            continue
            except OSError:
                continue
        return {
            "available": True,
            "total_records": total,
            "files": len(files),
            "ledger_dir": str(ledger_dir),
            "empty": total == 0,
            "per_strategy": per_strategy,
        }
    except Exception as e:
        return _unavailable(f"paper_experiments read failed: {e}")


# ─── Sections 5 + 6: Strategies by evidence ───────────────────────────────────

def _collect_per_strategy_metrics() -> dict:
    """Pull metrics for each known strategy. Returns dict name → metrics OR
    {'_error': '...'}.
    """
    try:
        import paper_experiment as pe  # type: ignore
    except Exception as e:
        return {"_error": f"paper_experiment import failed: {e}"}

    names: list[str] = []
    try:
        from backtest.strategy_registry import REGISTRY  # type: ignore
        names = sorted(REGISTRY.keys())
    except Exception:
        # Fall back to whatever the ledger has
        try:
            section = _section_paper_trades_collected()
            per = section.get("per_strategy") or {}
            names = sorted(per.keys())
        except Exception:
            names = []

    metrics: dict[str, dict] = {}
    for n in names:
        try:
            metrics[n] = pe.compute_strategy_metrics(n, window_days=180)
        except Exception as e:
            metrics[n] = {"_error": str(e)}
    return metrics


def _section_strongest_strategies(per_strategy: dict, top_n: int = 5) -> dict:
    """Top N strategies by n_closed (most evidence)."""
    if "_error" in per_strategy:
        return _unavailable(per_strategy["_error"])
    rows: list[dict] = []
    for name, m in per_strategy.items():
        if not isinstance(m, dict) or "_error" in m:
            continue
        rows.append({
            "strategy": name,
            "n_closed": int(m.get("n_closed") or 0),
            "win_rate": float(m.get("win_rate") or 0.0),
            "profit_factor": float(m.get("profit_factor") or 0.0),
            "net_pnl_after_fees_slippage": float(
                m.get("net_pnl_after_fees_slippage") or 0.0),
        })
    rows.sort(key=lambda r: r["n_closed"], reverse=True)
    return {
        "available": True,
        "top": rows[:top_n],
        "total_strategies": len(rows),
    }


def _section_weakest_strategies(per_strategy: dict, bottom_n: int = 5) -> dict:
    """Strategies with lowest WR + lowest PF + recent degradation flag.

    Only strategies with n_closed >= 5 are considered (else any 0/0 strategy
    would dominate).
    """
    if "_error" in per_strategy:
        return _unavailable(per_strategy["_error"])

    rows: list[dict] = []
    for name, m in per_strategy.items():
        if not isinstance(m, dict) or "_error" in m:
            continue
        n = int(m.get("n_closed") or 0)
        if n < 5:
            continue
        wr = float(m.get("win_rate") or 0.0)
        pf = float(m.get("profit_factor") or 0.0)
        l20 = float(m.get("last_20_win_rate") or 0.0)
        degraded = (n >= 20 and l20 < 0.30)
        rows.append({
            "strategy": name,
            "n_closed": n,
            "win_rate": wr,
            "profit_factor": pf,
            "last_20_win_rate": l20,
            "recent_degradation": degraded,
        })
    # Sort by composite: lowest PF then lowest WR
    rows.sort(key=lambda r: (r["profit_factor"], r["win_rate"]))
    return {
        "available": True,
        "bottom": rows[:bottom_n],
        "with_recent_degradation": [
            r["strategy"] for r in rows if r["recent_degradation"]],
        "total_eligible": len(rows),
    }


# ─── Section 7: Confidence buckets actually-working ───────────────────────────

def _section_confidence_buckets(per_strategy: dict) -> dict:
    """Aggregate per_confidence_bucket across strategies.

    Returns bucket → {n_closed, win_rate, net_pnl}.
    """
    if "_error" in per_strategy:
        return _unavailable(per_strategy["_error"])

    agg: dict[str, dict] = {}
    for _name, m in per_strategy.items():
        if not isinstance(m, dict):
            continue
        for bucket, sub in (m.get("per_confidence_bucket") or {}).items():
            if not isinstance(sub, dict):
                continue
            row = agg.setdefault(str(bucket), {
                "n_closed": 0, "wins": 0, "net_pnl": 0.0,
            })
            n = int(sub.get("n_closed") or 0)
            wr = float(sub.get("win_rate") or 0.0)
            row["n_closed"] += n
            row["wins"] += int(round(wr * n)) if n else 0
            row["net_pnl"] += float(sub.get("net_pnl_after_fees_slippage") or 0.0)

    # Post-process to win_rate
    pretty: list[dict] = []
    for bucket, row in sorted(agg.items()):
        n = row["n_closed"]
        wr = (row["wins"] / n) if n else 0.0
        pretty.append({
            "bucket": bucket,
            "n_closed": n,
            "win_rate": wr,
            "net_pnl_after_fees_slippage": row["net_pnl"],
            "working": (n >= 10 and row["net_pnl"] > 0 and wr >= 0.5),
        })
    note = (
        "A bucket is 'working' iff n_closed≥10 AND net_pnl>0 AND win_rate≥50%. "
        "Until n grows for each bucket, treat as informational only."
    )
    return {
        "available": True,
        "buckets": pretty,
        "note": note,
        "empty": all(r["n_closed"] == 0 for r in pretty),
    }


# ─── Section 8: Best instruments to observe ───────────────────────────────────

def _section_best_instruments() -> dict:
    """Read docs/universe_ranking_LATEST.md if present, otherwise read the
    active universe from config and return its symbol list.
    """
    out: dict[str, Any] = {"available": True}
    ranking = _REPO_ROOT / "docs" / "universe_ranking_LATEST.md"
    if ranking.exists():
        try:
            text = ranking.read_text(encoding="utf-8")
            # Extract first markdown table row of symbols (best-effort heuristic)
            lines = text.splitlines()
            sample = [ln.strip() for ln in lines[:50]]
            out["source"] = "universe_ranking_LATEST.md"
            out["sample_top_lines"] = sample[:15]
            return out
        except OSError:
            pass

    # Fall back to universe selector
    try:
        import universe_selector as us  # type: ignore
        # Probe a default universe id (filter helper does paper-only sanitisation)
        u = us.get_universe("US_LARGE")
        if u is not None:
            symbols = list(getattr(u, "symbols", []) or [])
            out["source"] = "config/market_universes.json::US_LARGE"
            out["symbols"] = symbols[:25]
            out["count"] = len(symbols)
            return out
    except Exception as e:
        out["universe_selector_error"] = str(e)

    # Final fall back: config/watchlists.json
    try:
        wl_path = _REPO_ROOT / "config" / "watchlists.json"
        if wl_path.exists():
            wl = json.loads(wl_path.read_text(encoding="utf-8"))
            buckets = {k: v for k, v in wl.items()
                       if isinstance(v, dict) and "symbols" in v}
            sample = {}
            for name, bucket in list(buckets.items())[:3]:
                sample[name] = (bucket.get("symbols") or [])[:8]
            out["source"] = "config/watchlists.json (buckets sample)"
            out["sample_buckets"] = sample
            return out
    except Exception as e:
        out["watchlists_error"] = str(e)

    return _unavailable("no instrument source available")


# ─── Sections 9 + 10: EDGE_GATE flip ──────────────────────────────────────────

def _section_edge_gate(per_strategy: dict) -> dict:
    """Call strategy_quality_gate.edge_gate_decision().

    Returns dict with allow_flip + blockers + per-strategy statuses.
    """
    try:
        import strategy_quality_gate as sqg  # type: ignore
    except Exception as e:
        return _unavailable(f"strategy_quality_gate import failed: {e}")

    if "_error" in per_strategy:
        # Without metrics we cannot classify → blocker
        return {
            "available": True,
            "allow_flip": False,
            "blockers": [f"metrics unavailable: {per_strategy['_error']}"],
            "per_strategy_status": {},
        }

    statuses: dict[str, str] = {}
    for name, m in per_strategy.items():
        if not isinstance(m, dict):
            continue
        try:
            statuses[name] = sqg.classify_strategy(
                name, m,
                paper_metrics=m,
                audit_complete=True,
                emit_audit=False,
            )
        except Exception as e:
            statuses[name] = sqg.REJECTED
            statuses[name + "__error"] = str(e)  # type: ignore

    try:
        allow, blockers = sqg.edge_gate_decision(statuses)
    except Exception as e:
        return {
            "available": True,
            "allow_flip": False,
            "blockers": [f"edge_gate_decision raised: {e}"],
            "per_strategy_status": statuses,
        }
    return {
        "available": True,
        "allow_flip": bool(allow),
        "blockers": list(blockers),
        "per_strategy_status": statuses,
    }


# ─── Section 11: Active P0/P1 backlog items ───────────────────────────────────

_P0P1_BULLET_RE = re.compile(r"^\s*-\s*\[\s\]\s*(.*)")


def _section_backlog() -> dict:
    """Scan learning-loop/heuristic_proposals.md for OPEN P0/P1 items.

    Heuristic: open box `- [ ]` and the line contains P0/P1 marker.
    """
    path = _REPO_ROOT / "learning-loop" / "heuristic_proposals.md"
    if not path.exists():
        return _unavailable("heuristic_proposals.md not found")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return _unavailable(f"read failed: {e}")

    p0: list[str] = []
    p1: list[str] = []
    for line in text.splitlines():
        m = _P0P1_BULLET_RE.match(line)
        if not m:
            continue
        body = m.group(1)
        upper = body.upper()
        # Look for P0/P1 markers in the bullet text
        if "P0" in upper or "P0-" in upper:
            p0.append(body.strip()[:220])
        elif "P1" in upper or "P1-" in upper:
            p1.append(body.strip()[:220])
    return {
        "available": True,
        "p0_open": p0,
        "p1_open": p1,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "source": "learning-loop/heuristic_proposals.md",
    }


# ─── Section 12: Is system still free? ────────────────────────────────────────

_PAID_HINTS = (
    "stripe", "billing", "openai.com/v1", "anthropic.com/v1",
    "twitter.com/v2", "tradingview.com/api", "datadog", "sentry",
    "newrelic", "polygon.io",
)


def _section_free_operation() -> dict:
    out: dict[str, Any] = {"available": True, "is_free": True, "evidence": []}
    free_doc = _REPO_ROOT / "docs" / "FREE_TIER_LIMITS.md"
    out["free_tier_doc_exists"] = free_doc.exists()
    if free_doc.exists():
        out["evidence"].append("docs/FREE_TIER_LIMITS.md present")

    # Scan config/*.json for paid-host hints (deterministic — files only)
    cfg_dir = _REPO_ROOT / "config"
    findings: list[str] = []
    if cfg_dir.exists():
        for p in sorted(cfg_dir.glob("*.json")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for h in _PAID_HINTS:
                if h in text:
                    findings.append(f"{p.name} mentions {h!r}")
    out["paid_host_hits_in_config"] = findings
    if findings:
        out["is_free"] = False
        out["evidence"].append(
            f"paid-host hints found in config: {len(findings)}")
    else:
        out["evidence"].append("no paid-host hints in config/")
    return out


# ─── Section 13: Is live trading disabled? ────────────────────────────────────

def _section_live_trading_disabled() -> dict:
    out: dict[str, Any] = {"available": True, "live_disabled": False, "evidence": []}
    # Verify PAPER_BASE_URL invariant
    try:
        import autonomy  # type: ignore
        url = getattr(autonomy, "PAPER_BASE_URL", "")
        out["paper_base_url"] = url
        if url == "https://paper-api.alpaca.markets":
            out["evidence"].append(
                "shared/autonomy.PAPER_BASE_URL == paper-api.alpaca.markets")
        else:
            out["evidence"].append(
                f"WARN: PAPER_BASE_URL={url} (not canonical paper URL)")
    except Exception as e:
        out["autonomy_import_error"] = str(e)

    # Verify assert_paper_only refuses non-paper
    try:
        import autonomy  # type: ignore
        ok_non_paper = False
        try:
            autonomy.assert_paper_only("https://api.alpaca.markets")
            ok_non_paper = True
        except Exception:
            pass
        if ok_non_paper:
            out["evidence"].append(
                "BUG: assert_paper_only accepted live URL")
        else:
            out["evidence"].append(
                "assert_paper_only correctly refuses live URL")
    except Exception:
        pass

    # No LIVE_APPROVED status anywhere
    try:
        import strategy_quality_gate as sqg  # type: ignore
        live_in_set = any("LIVE" in s.upper() for s in sqg.ALL_STATUSES)
        out["evidence"].append(
            "strategy_quality_gate has no LIVE_APPROVED status"
            if not live_in_set else
            "WARN: strategy_quality_gate contains a LIVE_* status"
        )
    except Exception:
        pass

    # Final verdict — live is disabled when both URL is paper AND
    # assert_paper_only refuses non-paper AND no LIVE_* status
    out["live_disabled"] = all(
        e.startswith(("shared/autonomy", "assert_paper_only", "strategy_quality_gate"))
        and not e.startswith(("BUG", "WARN"))
        for e in out["evidence"]
        if e
    ) and out.get("paper_base_url") == "https://paper-api.alpaca.markets"
    return out


# ─── Aggregator ───────────────────────────────────────────────────────────────

def collect_dashboard_data() -> dict:
    """Read all sources + return structured dashboard data dict."""
    per_strategy = _collect_per_strategy_metrics()
    data: dict[str, Any] = {
        "version": "v3.19.0",
        "generated_at": _now_iso(),
        "sections": {
            "system_health":          _section_system_health(),
            "heartbeat":              _section_heartbeat(),
            "paper_workflow":         _section_paper_workflow(),
            "paper_trades_collected": _section_paper_trades_collected(),
            "strongest_strategies":   _section_strongest_strategies(per_strategy),
            "weakest_strategies":     _section_weakest_strategies(per_strategy),
            "confidence_buckets":     _section_confidence_buckets(per_strategy),
            "best_instruments":       _section_best_instruments(),
            "edge_gate":              _section_edge_gate(per_strategy),
            "backlog_p0_p1":          _section_backlog(),
            "free_operation":         _section_free_operation(),
            "live_trading_disabled":  _section_live_trading_disabled(),
        },
    }
    return data


# ─── Renderers ────────────────────────────────────────────────────────────────

def _section_marker(title: str) -> str:
    return f"\n## {title}\n"


def _render_unavailable(d: dict) -> str:
    return f"_unavailable — {d.get('reason', '?')}_\n"


def render_dashboard_markdown(data: dict) -> str:
    """Render Markdown dashboard from dict."""
    sec = (data or {}).get("sections") or {}
    out: list[str] = []
    out.append("# Operator Dashboard\n")
    out.append(f"> Version {data.get('version', '?')} — "
               f"generated at {data.get('generated_at', '?')}\n")
    out.append("> Read-only daily situational overview. NEVER recommends live trading.\n")

    # 1
    s = sec.get("system_health") or {}
    out.append(_section_marker("1. System health summary"))
    if s.get("available"):
        out.append(
            f"- Heartbeat: {s.get('heartbeat_alive', 0)}/"
            f"{s.get('heartbeat_total', 0)} "
            f"({s.get('heartbeat_ratio', 0.0):.0%})\n")
        out.append(
            f"- Safe mode active: **{s.get('safe_mode_active', False)}**\n")
        if s.get("safe_mode_active"):
            out.append(f"  - Trigger: `{s.get('safe_mode_trigger', '')}`\n")
            out.append(f"  - Reason: {s.get('safe_mode_reason', '')}\n")
        li = s.get("last_incident") or {}
        if li.get("present"):
            out.append(
                f"- Last incident today: `{li.get('decision_type')}` — "
                f"{li.get('reason')}\n")
        else:
            out.append("- Last incident today: none recorded\n")
    else:
        out.append(_render_unavailable(s))

    # 2
    s = sec.get("heartbeat") or {}
    out.append(_section_marker("2. Heartbeat 11/11"))
    if s.get("available"):
        out.append(
            f"- **{s.get('alive', 0)}/{s.get('total', 0)}** components alive\n")
        stale = s.get("stale_components") or []
        if stale:
            out.append(f"- Stale: {', '.join(stale)}\n")
        else:
            out.append("- All expected components fresh\n")
        for row in (s.get("per_component") or []):
            age = row.get("age_seconds")
            age_s = f"{age:.0f}s" if age is not None else "never"
            flag = "STALE" if row.get("stale") else "ok"
            out.append(f"  - `{row['name']}`: {flag} (age={age_s})\n")
    else:
        out.append(_render_unavailable(s))

    # 3
    s = sec.get("paper_workflow") or {}
    out.append(_section_marker("3. Paper workflow status"))
    if s.get("available"):
        out.append(f"- Status: **{s.get('status', '?')}**\n")
        out.append(f"- Template exists: {s.get('template_exists')}\n")
        out.append(f"- Deployed in .github/workflows/: {s.get('deployed_exists')}\n")
    else:
        out.append(_render_unavailable(s))

    # 4
    s = sec.get("paper_trades_collected") or {}
    out.append(_section_marker("4. Paper trades collected"))
    if s.get("available"):
        out.append(f"- Total records: **{s.get('total_records', 0)}** "
                   f"across {s.get('files', 0)} ledger file(s)\n")
        out.append(f"- Ledger dir: `{s.get('ledger_dir')}`\n")
        if s.get("empty"):
            out.append(
                "- **Ledger empty — no closed paper trades yet.** "
                "EDGE_GATE flip is blocked until n ≥ 50 per enabled strategy.\n")
        else:
            ps = s.get("per_strategy") or {}
            for k, v in sorted(ps.items(), key=lambda kv: -kv[1])[:10]:
                out.append(f"  - `{k}`: {v}\n")
    else:
        out.append(_render_unavailable(s))

    # 5
    s = sec.get("strongest_strategies") or {}
    out.append(_section_marker("5. Strategies with most evidence"))
    if s.get("available"):
        rows = s.get("top") or []
        if not rows:
            out.append("- No strategies have closed trades yet.\n")
        else:
            for r in rows:
                out.append(
                    f"- `{r['strategy']}` — n={r['n_closed']} "
                    f"WR={r['win_rate']:.0%} PF={r['profit_factor']:.2f} "
                    f"netP&L={r['net_pnl_after_fees_slippage']:+.2f}\n")
    else:
        out.append(_render_unavailable(s))

    # 6
    s = sec.get("weakest_strategies") or {}
    out.append(_section_marker("6. Weakest strategies"))
    if s.get("available"):
        rows = s.get("bottom") or []
        if not rows:
            out.append("- No strategies eligible (need n_closed ≥ 5).\n")
        else:
            for r in rows:
                deg = " — recent degradation" if r["recent_degradation"] else ""
                out.append(
                    f"- `{r['strategy']}` — n={r['n_closed']} "
                    f"WR={r['win_rate']:.0%} PF={r['profit_factor']:.2f} "
                    f"last20WR={r['last_20_win_rate']:.0%}{deg}\n")
    else:
        out.append(_render_unavailable(s))

    # 7
    s = sec.get("confidence_buckets") or {}
    out.append(_section_marker("7. Confidence buckets actually-working"))
    if s.get("available"):
        if s.get("empty"):
            out.append("- No bucket has data yet — calibration is uncalibrated.\n")
        else:
            for r in s.get("buckets") or []:
                mark = "WORKING" if r["working"] else "informational"
                out.append(
                    f"- `{r['bucket']}` — n={r['n_closed']} "
                    f"WR={r['win_rate']:.0%} netP&L="
                    f"{r['net_pnl_after_fees_slippage']:+.2f} ({mark})\n")
        out.append(f"- Note: {s.get('note', '')}\n")
    else:
        out.append(_render_unavailable(s))

    # 8
    s = sec.get("best_instruments") or {}
    out.append(_section_marker("8. Best instruments to observe"))
    if s.get("available"):
        out.append(f"- Source: `{s.get('source', '?')}`\n")
        if s.get("symbols"):
            out.append(f"- Symbols ({s.get('count', 0)}): "
                       f"{', '.join(s['symbols'][:25])}\n")
        elif s.get("sample_buckets"):
            for k, syms in s["sample_buckets"].items():
                out.append(f"  - `{k}`: {', '.join(syms)}\n")
        elif s.get("sample_top_lines"):
            out.append("  - Top excerpt:\n")
            for line in s["sample_top_lines"][:10]:
                out.append(f"    {line}\n")
    else:
        out.append(_render_unavailable(s))

    # 9
    s = sec.get("edge_gate") or {}
    out.append(_section_marker("9. Can EDGE_GATE_ENABLED flip?"))
    if s.get("available"):
        out.append(f"- Allow flip? **{s.get('allow_flip', False)}**\n")
        # Statuses summary
        st = s.get("per_strategy_status") or {}
        if st:
            out.append("- Per-strategy status:\n")
            for k, v in sorted(st.items()):
                if k.endswith("__error"):
                    continue
                out.append(f"  - `{k}`: {v}\n")
        out.append(
            "\nThis dashboard is read-only — EDGE_GATE_ENABLED is **never** "
            "auto-flipped by this script.\n")
    else:
        out.append(_render_unavailable(s))

    # 10
    out.append(_section_marker("10. Why not?"))
    if s.get("available"):
        blockers = s.get("blockers") or []
        if not blockers:
            out.append("- No blockers — but operator must still set env var manually.\n")
        else:
            for b in blockers:
                out.append(f"- {b}\n")
    else:
        out.append(_render_unavailable(s))

    # 11
    s = sec.get("backlog_p0_p1") or {}
    out.append(_section_marker("11. Active P0/P1 backlog items"))
    if s.get("available"):
        out.append(
            f"- P0 open: **{s.get('p0_count', 0)}**, "
            f"P1 open: **{s.get('p1_count', 0)}**\n")
        for line in (s.get("p0_open") or [])[:10]:
            out.append(f"  - **P0** {line}\n")
        for line in (s.get("p1_open") or [])[:10]:
            out.append(f"  - **P1** {line}\n")
    else:
        out.append(_render_unavailable(s))

    # 12
    s = sec.get("free_operation") or {}
    out.append(_section_marker("12. Is system still free?"))
    if s.get("available"):
        out.append(f"- Free? **{'YES' if s.get('is_free') else 'NO'}**\n")
        for ev in s.get("evidence") or []:
            out.append(f"  - {ev}\n")
        hits = s.get("paid_host_hits_in_config") or []
        if hits:
            out.append("\nPaid-host hints in config/:\n")
            for h in hits:
                out.append(f"  - {h}\n")
    else:
        out.append(_render_unavailable(s))

    # 13
    s = sec.get("live_trading_disabled") or {}
    out.append(_section_marker("13. Is live trading disabled?"))
    if s.get("available"):
        out.append(
            f"- Live trading disabled? "
            f"**{'YES' if s.get('live_disabled') else 'NO'}**\n")
        out.append(f"- PAPER_BASE_URL: `{s.get('paper_base_url', '?')}`\n")
        for ev in s.get("evidence") or []:
            out.append(f"  - {ev}\n")
        out.append(
            "\n**Reminder: this system NEVER recommends live trading. "
            "It is paper-only by contract.**\n")
    else:
        out.append(_render_unavailable(s))

    out.append("\n---\n")
    out.append(
        "_Read-only dashboard — for operator situational awareness only._\n"
        "_Does not modify any runtime state. Cannot enable live trading._\n"
    )
    return "".join(out)


def render_dashboard_json(data: dict) -> str:
    """Render JSON dashboard from dict (stable key order)."""
    return json.dumps(data, sort_keys=True, indent=2, default=str)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _write_outputs(data: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "operator_dashboard_LATEST.md"
    json_path = out_dir / "operator_dashboard_LATEST.json"
    md_path.write_text(render_dashboard_markdown(data), encoding="utf-8")
    json_path.write_text(render_dashboard_json(data), encoding="utf-8")
    return md_path, json_path


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint — writes both files."""
    parser = argparse.ArgumentParser(
        prog="daily_operator_dashboard",
        description="Generate the daily operator dashboard (read-only).",
    )
    parser.add_argument(
        "--out-dir", default=str(_DOCS_DIR),
        help="Directory to write LATEST.md/.json (default: docs/)",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Print markdown to stdout instead of writing files.",
    )
    ns = parser.parse_args(args)
    try:
        data = collect_dashboard_data()
    except Exception as e:
        print(f"ERROR: collect_dashboard_data failed: {e}", file=sys.stderr)
        return 1

    if ns.no_write:
        sys.stdout.write(render_dashboard_markdown(data))
        return 0

    out_dir = Path(ns.out_dir)
    try:
        md, js = _write_outputs(data, out_dir)
    except Exception as e:
        print(f"ERROR: write failed: {e}", file=sys.stderr)
        return 1
    print(f"wrote: {md}")
    print(f"wrote: {js}")
    return 0


__all__ = [
    "collect_dashboard_data",
    "render_dashboard_markdown",
    "render_dashboard_json",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

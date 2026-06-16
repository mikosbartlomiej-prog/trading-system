#!/usr/bin/env python3
"""v3.29 ETAP 7 (2026-06-16) — Daily Operational Brief generator.

Reads exclusively from on-disk artefacts emitted by other components
(system activation gate, equity reconciliation, position
reconciliation, safe-mode consistency, allocator gate, broker-repair,
operator confirmation, trigger watchlist, shadow candidate queue,
LLM advisory mesh) and produces a single markdown brief at
``briefs/<YYYY-MM-DD>.md`` plus a JSON sidecar at
``learning-loop/system_activation_status_latest.json``.

EVIDENCE DISCIPLINE
-------------------
Every numeric or factual claim MUST cite the artefact path it came
from, e.g. ``$90,523 [source: runtime_state.json::intraday_governor.
current_equity]``. Unverified claims are flagged ``CLAIM_UNSUPPORTED``
or omitted entirely. The brief refuses to invent figures.

HARD INVARIANTS
---------------
* NEVER imports ``shared/alpaca_orders.py``.
* NEVER calls broker.
* NEVER mutates state (no flag flips, no safe_mode auto-clear, no
  threshold writes).
* NEVER recommends a trade. The brief is purely operational.
* NEVER claims "92 % readiness" or "80-day LLM failure" or any other
  unverified figure — those are flagged ``CLAIM_UNSUPPORTED``.
* Standing markers footer is always present.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
- ``NO_LLM_STATE_MUTATION``
- ``TRADING_EXECUTION_ON=false``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

try:
    from llm_advisory_authority import (   # noqa: E402
        redact_secrets, STANDING_MARKERS as AUTH_MARKERS)
except Exception:
    AUTH_MARKERS = ()
    def redact_secrets(t: str) -> str:  # type: ignore
        return t or ""

CLAIM_UNSUPPORTED = "CLAIM_UNSUPPORTED"

STANDING_MARKERS = tuple(sorted(set(list(AUTH_MARKERS) + [
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    "NO_LLM_STATE_MUTATION",
    "TRADING_EXECUTION_ON=false",
])))


def _safe_load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".jsonl":
            out: list[dict] = []
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
            return out
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _cite(value: Any, source: str) -> str:
    """Render a numeric / factual value with a source citation."""
    if value is None:
        return f"`{CLAIM_UNSUPPORTED}` [source: `{source}` missing]"
    return f"`{value}` [source: `{source}`]"


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


# ─── Section builders ──────────────────────────────────────────────────────

def _section_system_activation(art: dict) -> list[str]:
    out = ["## System activation gate\n"]
    v = art.get("system_activation_latest")
    if v is None:
        out.append("- " + _cite(None,
                                 "learning-loop/system_activation_status_latest.json"))
        return out
    dec = v.get("decision") if isinstance(v, dict) else None
    out.append("- **Decision:** "
                 + _cite(dec,
                          "learning-loop/system_activation_status_latest.json::decision"))
    out.append("- **Allocator allowed:** "
                 + _cite(dec == "ALLOCATOR_ALLOWED",
                          "derived from decision"))
    return out


def _section_safe_mode(art: dict) -> list[str]:
    out = ["## Safe-mode consistency\n"]
    rs = art.get("runtime_state")
    sm = art.get("safe_mode_consistency_latest")
    rs_sm = None
    if isinstance(rs, dict):
        rs_sm = (rs.get("safe_mode") or {}).get("state")
    out.append("- **runtime_state.safe_mode.state:** "
                 + _cite(rs_sm,
                          "learning-loop/runtime_state.json::safe_mode.state"))
    if isinstance(sm, dict):
        out.append("- **Verdict:** "
                     + _cite(sm.get("verdict") or sm.get("status"),
                              "learning-loop/safe_mode_consistency_latest.json::verdict"))
        out.append("- **Inconsistencies:** "
                     + _cite(sm.get("inconsistencies_found"),
                              "learning-loop/safe_mode_consistency_latest.json::inconsistencies_found"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/safe_mode_consistency_latest.json"))
    return out


def _section_broker_repair(art: dict) -> list[str]:
    out = ["## Broker-repair queue\n"]
    br = art.get("broker_repair_required_latest")
    if not isinstance(br, dict):
        out.append("- " + _cite(None,
                                 "learning-loop/broker_repair_required_latest.json"))
    else:
        entries = br.get("entries") or br.get("symbols") or []
        if isinstance(entries, dict):
            entries = list(entries.keys())
        out.append("- **Symbols requiring manual repair:** "
                     + _cite(len(entries) if entries is not None else None,
                              "learning-loop/broker_repair_required_latest.json::entries"))
        if isinstance(entries, list):
            for sym in entries[:10]:
                out.append(f"  - `{sym}`")
    # AVAXUSD-specific check.
    op = art.get("operator_repair_avaxusd")
    if isinstance(op, dict):
        out.append("- **AVAXUSD operator confirmation:** "
                     + _cite(op.get("confirmed_at") or op.get("status"),
                              "learning-loop/operator_markers/avaxusd_repair_confirmed.json"))
    else:
        out.append("- **AVAXUSD operator confirmation:** "
                     + _cite(None,
                              "learning-loop/operator_markers/avaxusd_repair_confirmed.json"))
    return out


def _section_allocator(art: dict) -> list[str]:
    out = ["## Allocator gate decision\n"]
    g = art.get("allocator_gate_latest")
    if isinstance(g, dict):
        out.append("- **Decision:** "
                     + _cite(g.get("decision") or g.get("verdict"),
                              "learning-loop/allocator_gate_latest.json::decision"))
        out.append("- **Reason:** "
                     + _cite(g.get("reason") or g.get("block_reason"),
                              "learning-loop/allocator_gate_latest.json::reason"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/allocator_gate_latest.json"))
    return out


def _section_equity(art: dict) -> list[str]:
    out = ["## Equity reconciliation\n"]
    eq = art.get("equity_gap_report_latest")
    if isinstance(eq, dict):
        out.append("- **Verdict:** "
                     + _cite(eq.get("verdict") or eq.get("status"),
                              "learning-loop/equity_gap_report_latest.json::verdict"))
        out.append("- **gap_amount:** "
                     + _cite(eq.get("gap_amount"),
                              "learning-loop/equity_gap_report_latest.json::gap_amount"))
        out.append("- **confidence:** "
                     + _cite(eq.get("confidence"),
                              "learning-loop/equity_gap_report_latest.json::confidence"))
        out.append("- **block_allocator:** "
                     + _cite(eq.get("block_allocator"),
                              "learning-loop/equity_gap_report_latest.json::block_allocator"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/equity_gap_report_latest.json"))
    return out


def _section_position(art: dict) -> list[str]:
    out = ["## Position reconciliation\n"]
    pr = art.get("position_reconciliation_latest")
    if isinstance(pr, dict):
        out.append("- **Status:** "
                     + _cite(pr.get("status") or pr.get("verdict"),
                              "learning-loop/position_reconciliation/latest.json::status"))
        out.append("- **mismatch_count:** "
                     + _cite(pr.get("mismatch_count"),
                              "learning-loop/position_reconciliation/latest.json::mismatch_count"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/position_reconciliation/latest.json"))
    return out


def _section_trigger_watchlist(art: dict) -> list[str]:
    out = ["## Trigger watchlist (top 5)\n"]
    tw = art.get("trigger_watchlist_latest")
    items: list = []
    if isinstance(tw, dict):
        items = tw.get("entries") or tw.get("symbols") or tw.get(
            "items") or []
    if not items:
        out.append("- " + _cite(None,
                                 "learning-loop/trigger_watchlist/latest.json"))
        return out
    for entry in items[:5]:
        if isinstance(entry, dict):
            sym = entry.get("symbol") or entry.get("ticker") or "?"
            score = entry.get("score") or entry.get("confidence") or ""
            out.append(
                f"- `{sym}` "
                + _cite(score,
                          "learning-loop/trigger_watchlist/latest.json::entries"))
        else:
            out.append(f"- `{entry}`")
    return out


def _section_shadow_candidates(art: dict) -> list[str]:
    out = ["## Shadow candidate queue (top 5)\n"]
    sc = art.get("shadow_candidate_queue_latest")
    items: list = []
    if isinstance(sc, dict):
        items = sc.get("entries") or sc.get("candidates") or sc.get(
            "items") or []
    if not items:
        out.append("- " + _cite(None,
                                 "learning-loop/shadow_candidate_queue/latest.json"))
        return out
    for entry in items[:5]:
        if isinstance(entry, dict):
            sym = entry.get("symbol") or entry.get("ticker") or "?"
            strat = entry.get("strategy") or ""
            out.append(
                f"- `{sym}` strategy=`{strat}` "
                + _cite(entry.get("score"),
                          "learning-loop/shadow_candidate_queue/latest.json::entries"))
        else:
            out.append(f"- `{entry}`")
    return out


def _section_confidence_calibration(art: dict) -> list[str]:
    out = ["## Confidence pre-calibration readiness\n"]
    cc = art.get("calibration_status_latest")
    if isinstance(cc, dict):
        out.append("- **Status:** "
                     + _cite(cc.get("status"),
                              "learning-loop/llm_advisory/calibration_status_latest.json::status"))
        out.append("- **Acceptable runs:** "
                     + _cite(cc.get("acceptable_runs"),
                              "learning-loop/llm_advisory/calibration_status_latest.json::acceptable_runs"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/llm_advisory/calibration_status_latest.json"))
    return out


def _section_llm_advisory() -> list[str]:
    out = ["## LLM advisory summary (v3.29 ETAP 6 mesh)\n"]
    advisory_dir = REPO_ROOT / "learning-loop" / "llm_advisory"
    roles = (
        "INCIDENT_REVIEW", "RISK_REVIEW", "STRATEGY_REVIEW",
        "NO_SIGNAL_DIAGNOSTIC", "SHADOW_CANDIDATE_REVIEW",
        "TRIGGER_WATCHLIST_REVIEW", "DAILY_BRIEF",
        "ALLOCATOR_PLAN_CRITIC", "EQUITY_RECONCILIATION_CRITIC",
        "FINAL_ARBITER",
    )
    out.append("| Agent | Recommendation | Risk | Confidence | Veto |")
    out.append("|---|---|---|---|---|")
    any_seen = False
    for role in roles:
        p = advisory_dir / f"{role}_latest.json"
        v = _safe_load(p)
        if isinstance(v, dict):
            any_seen = True
            out.append(
                f"| `{role}` | `{v.get('recommendation')}` "
                f"| `{v.get('risk_level')}` "
                f"| `{v.get('confidence')}` "
                f"| `{v.get('veto_recommendation', False)}` |")
        else:
            out.append(
                f"| `{role}` | `{CLAIM_UNSUPPORTED}` "
                f"[source: `{p.relative_to(REPO_ROOT)}` missing] "
                f"| | | |")
    if not any_seen:
        out.append("")
        out.append("**No advisory rows seen.** "
                     "The mesh has not been run for this brief.")
    return out


def _section_discovery(art: dict) -> list[str]:
    out = ["## Discovery status\n"]
    d = art.get("discovery_status_latest")
    if isinstance(d, dict):
        out.append("- **Status:** "
                     + _cite(d.get("status"),
                              "learning-loop/discovery_status_latest.json::status"))
    else:
        out.append("- " + _cite(None,
                                 "learning-loop/discovery_status_latest.json"))
    return out


# ─── Top blockers + operator actions ───────────────────────────────────────

def _top_blockers(art: dict) -> list[str]:
    """Collect deterministic blockers from artefacts. LLM CANNOT add
    or remove items from this list."""
    blockers: list[str] = []
    sag = art.get("system_activation_latest")
    if isinstance(sag, dict):
        dec = sag.get("decision")
        if dec and dec != "ALLOCATOR_ALLOWED":
            blockers.append(
                f"system_activation_gate.decision = `{dec}` "
                f"[source: `learning-loop/"
                f"system_activation_status_latest.json::decision`]")
    g = art.get("allocator_gate_latest")
    if isinstance(g, dict):
        dec = g.get("decision") or g.get("verdict") or ""
        if isinstance(dec, str) and dec.startswith("BLOCK"):
            blockers.append(
                f"allocator_gate.decision = `{dec}` "
                f"[source: `learning-loop/allocator_gate_latest.json"
                f"::decision`]")
    eq = art.get("equity_gap_report_latest")
    if isinstance(eq, dict):
        if eq.get("block_allocator") is True:
            blockers.append(
                "equity_gap_report.block_allocator = `true` "
                "[source: `learning-loop/"
                "equity_gap_report_latest.json::block_allocator`]")
    sm = art.get("safe_mode_consistency_latest")
    if isinstance(sm, dict):
        if sm.get("inconsistencies_found") and int(
                sm.get("inconsistencies_found") or 0) > 0:
            blockers.append(
                f"safe_mode_consistency.inconsistencies_found = "
                f"`{sm.get('inconsistencies_found')}` [source: "
                f"`learning-loop/safe_mode_consistency_latest.json`]")
    br = art.get("broker_repair_required_latest")
    if isinstance(br, dict):
        ents = br.get("entries") or br.get("symbols") or []
        if isinstance(ents, dict):
            ents = list(ents.keys())
        if ents:
            blockers.append(
                f"broker_repair_required = {len(ents)} symbols "
                f"[source: `learning-loop/"
                f"broker_repair_required_latest.json`]")
    return blockers


def _operator_actions(blockers: list[str]) -> list[str]:
    actions: list[str] = []
    for b in blockers:
        if "broker_repair_required" in b:
            actions.append(
                "- [ ] Open Alpaca dashboard, manually close orphaned "
                "OCO legs / dust positions for the listed symbols, "
                "then run "
                "`python3 scripts/record_operator_repair_confirmation.py`.")
        if "safe_mode_consistency" in b:
            actions.append(
                "- [ ] Investigate why runtime_state.safe_mode does "
                "not match audit JSONL. Do NOT auto-clear safe_mode.")
        if "equity_gap_report" in b:
            actions.append(
                "- [ ] Investigate equity gap; review "
                "`learning-loop/equity_gap_report_latest.json` and "
                "the upstream account/equity sources.")
        if "allocator_gate" in b:
            actions.append(
                "- [ ] Resolve the allocator_gate block reason "
                "before re-enabling allocator.")
    if not actions:
        actions.append(
            "- [ ] No deterministic blocker is gating the allocator. "
            "Operator may still review LLM advisory recommendations "
            "(advisory-only).")
    return actions


# ─── Gather artefacts ──────────────────────────────────────────────────────

def _gather_artefacts() -> dict:
    art: dict = {}
    base = REPO_ROOT / "learning-loop"
    art["system_activation_latest"] = _safe_load(
        base / "system_activation_status_latest.json")
    art["runtime_state"] = _safe_load(base / "runtime_state.json")
    art["safe_mode_consistency_latest"] = _safe_load(
        base / "safe_mode_consistency_latest.json")
    art["broker_repair_required_latest"] = _safe_load(
        base / "broker_repair_required_latest.json")
    art["allocator_gate_latest"] = _safe_load(
        base / "allocator_gate_latest.json")
    art["equity_gap_report_latest"] = _safe_load(
        base / "equity_gap_report_latest.json")
    art["position_reconciliation_latest"] = _safe_load(
        base / "position_reconciliation" / "latest.json")
    art["trigger_watchlist_latest"] = _safe_load(
        base / "trigger_watchlist" / "latest.json")
    art["shadow_candidate_queue_latest"] = _safe_load(
        base / "shadow_candidate_queue" / "latest.json")
    art["calibration_status_latest"] = _safe_load(
        base / "llm_advisory" / "calibration_status_latest.json")
    art["discovery_status_latest"] = _safe_load(
        base / "discovery_status_latest.json")
    art["operator_repair_avaxusd"] = _safe_load(
        base / "operator_markers" / "avaxusd_repair_confirmed.json")
    return art


def render_brief(*, as_of: str) -> str:
    art = _gather_artefacts()
    blockers = _top_blockers(art)
    actions = _operator_actions(blockers)
    lines: list[str] = []
    lines.append(f"# Daily Operational Brief — {as_of}\n")
    lines.append("**Source-of-truth document.** Every numeric or "
                   "factual claim cites the artefact path it came "
                   "from. Unverified claims are flagged "
                   "`CLAIM_UNSUPPORTED`.\n")
    lines.append("**Trading execution status:** "
                   f"`TRADING_EXECUTION_ON={str(_env_truthy('TRADING_EXECUTION_ON')).lower()}` "
                   "(brief is generated read-only; live execution "
                   "remains unsupported).\n")
    lines.append("## Top blockers (deterministic)\n")
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("- (No deterministic blocker found.)")
    lines.append("")
    lines.append("## Operator action list\n")
    lines.extend(actions)
    lines.append("")
    lines.extend(_section_system_activation(art))
    lines.append("")
    lines.extend(_section_safe_mode(art))
    lines.append("")
    lines.extend(_section_broker_repair(art))
    lines.append("")
    lines.extend(_section_allocator(art))
    lines.append("")
    lines.extend(_section_equity(art))
    lines.append("")
    lines.extend(_section_position(art))
    lines.append("")
    lines.extend(_section_trigger_watchlist(art))
    lines.append("")
    lines.extend(_section_shadow_candidates(art))
    lines.append("")
    lines.extend(_section_confidence_calibration(art))
    lines.append("")
    lines.extend(_section_llm_advisory())
    lines.append("")
    lines.extend(_section_discovery(art))
    lines.append("")
    lines.append("## Standing markers\n")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    return redact_secrets("\n".join(lines)) + "\n"


def write_system_activation_status_sidecar(*, as_of: str) -> None:
    """Write the canonical system_activation_status_latest.json sidecar
    referenced by the brief.

    The brief itself does NOT mutate the underlying decision — the
    sidecar simply mirrors the latest artefact for downstream
    consumers (Cloudflare dashboard, etc.). When the upstream gate
    artefact exists the existing decision is preserved verbatim.
    """
    art = _gather_artefacts()
    sag = art.get("system_activation_latest") or {}
    payload = {
        "version":         "v3.29-ETAP-7",
        "as_of":           as_of,
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "decision":         sag.get("decision") if isinstance(sag, dict) else None,
        "blockers_count":   len(_top_blockers(art)),
        "standing_markers": list(STANDING_MARKERS),
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
            "trading_execution_on":              False,
        },
    }
    p = REPO_ROOT / "learning-loop" / "system_activation_status_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                  encoding="utf-8")


def write_status_doc(*, as_of: str) -> None:
    """Mirror the brief's blocker summary at
    docs/SYSTEM_ACTIVATION_STATUS.md."""
    art = _gather_artefacts()
    blockers = _top_blockers(art)
    p = REPO_ROOT / "docs" / "SYSTEM_ACTIVATION_STATUS.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# System Activation Status — {as_of}\n"]
    sag = art.get("system_activation_latest") or {}
    lines.append(
        "- **Decision:** "
        + _cite(sag.get("decision") if isinstance(sag, dict) else None,
                 "learning-loop/system_activation_status_latest.json::decision"))
    lines.append("- **Blocker count:** " + str(len(blockers)))
    lines.append("")
    lines.append("## Blockers")
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Standing markers")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v3.29 ETAP 7 daily operational brief generator.")
    parser.add_argument("--as-of", default=None,
                          help="Date in YYYY-MM-DD. Default today UTC.")
    parser.add_argument("--no-write-sidecar", action="store_true")
    parser.add_argument("--no-write-doc", action="store_true")
    args = parser.parse_args(argv)

    today = datetime.now(timezone.utc).date().isoformat()
    as_of = args.as_of or today
    brief = render_brief(as_of=as_of)
    out_path = REPO_ROOT / "briefs" / f"{as_of}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(brief, encoding="utf-8")
    if not args.no_write_sidecar:
        try:
            write_system_activation_status_sidecar(as_of=as_of)
        except Exception as e:
            print(f"  [v3.29] sidecar write failed: {e}")
    if not args.no_write_doc:
        try:
            write_status_doc(as_of=as_of)
        except Exception as e:
            print(f"  [v3.29] status doc write failed: {e}")
    print(json.dumps({
        "status":   "DAILY_BRIEF_WRITTEN",
        "path":     str(out_path.relative_to(REPO_ROOT)),
        "as_of":    as_of,
        "standing_markers": list(STANDING_MARKERS),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

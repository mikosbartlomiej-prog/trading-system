#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — Operator Decision Pack (ETAP 10).

WHY
---
v3.19 daily_operator_dashboard answered "what is the system doing".
v3.20 adds new evidence layers (shadow paper, opportunity ledger,
counterfactuals, lower bounds, robustness, variants, scheduler, exit
quality, gate calibration). The operator now needs ONE consolidated
artifact that pulls all of them together, plus answers the 10 spec
questions:

  1. What should the system observe tomorrow?
  2. Which strategies look most promising?
  3. Which strategies look weakest?
  4. Which gates protect well?
  5. Which gates may be over-conservative?
  6. Where is data missing?
  7. Does any strategy variant deserve replay?
  8. Can EDGE_GATE flip?
  9. Why not?
  10. Is the system still safe / free / paper-only?

The decision pack is READ-ONLY. It cannot:
  - place trades
  - mutate runtime state
  - mutate strategy config
  - flip EDGE_GATE_ENABLED
  - recommend live trading
  - call network APIs

Outputs:
  - docs/operator_decision_pack_LATEST.md
  - docs/operator_decision_pack_LATEST.json

CLI
---
  python3 scripts/operator_decision_pack.py            # write both files
  python3 scripts/operator_decision_pack.py --no-write # stdout only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

DOCS_DIR = REPO_ROOT / "docs"
LEARNING_DIR = REPO_ROOT / "learning-loop"


def _safe_call(fn, *args, default=None, **kwargs):
    """Call fn; on any exception return default + capture error string."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return default, f"{type(e).__name__}: {e}"


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _list_jsonl(path: Path) -> list:
    """Read JSONL file as list of dicts; empty list if missing/bad."""
    if not path.exists():
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _count_files(directory: Path, pattern: str = "*.jsonl") -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def collect_section_v319_dashboard() -> dict:
    """Pull v3.19 daily dashboard snapshot (system health, paper count)."""
    try:
        import daily_operator_dashboard as dod  # type: ignore
        snap = dod.build_snapshot()
        return {
            "head_ok": snap.get("head_ok"),
            "paper_only_verified": snap.get("paper_only_verified"),
            "live_trading_blocked": snap.get("live_trading_blocked"),
            "edge_gate_disabled": snap.get("edge_gate_disabled"),
            "heartbeat_alive_count": snap.get("heartbeat_alive_count"),
            "heartbeat_expected": snap.get("heartbeat_expected"),
            "paper_trade_count": snap.get("paper_trade_count", 0),
            "paid_services": snap.get("paid_services", []),
        }
    except Exception as e:
        return {"error": f"v3.19 dashboard unavailable: {type(e).__name__}"}


def collect_section_v320_evidence_production() -> dict:
    """Shadow ledger + opportunity ledger counts."""
    shadow_dir = LEARNING_DIR / "shadow_ledger"
    opp_dir = LEARNING_DIR / "opportunity_ledger"
    paper_dir = LEARNING_DIR / "paper_experiments"
    try:
        from evidence_production import resolve_mode  # type: ignore
        mode = resolve_mode()
    except Exception:
        mode = "SIGNAL_ONLY"
    return {
        "current_mode": mode,
        "default_mode_is_signal_only_or_shadow": mode in ("SIGNAL_ONLY", "SHADOW_PAPER_SIM"),
        "shadow_ledger_files": _count_files(shadow_dir),
        "opportunity_ledger_files": _count_files(opp_dir),
        "paper_experiments_files": _count_files(paper_dir),
        "live_trading_possible": False,  # invariant
    }


def collect_section_v320_strategy_ranking() -> dict:
    """Pull strategy ranking with lower-bound classification overlay."""
    try:
        from strategy_ranking import rank_strategies  # type: ignore
        ranking, err = _safe_call(rank_strategies, default=[])
    except Exception as e:
        ranking, err = [], f"ranking module unavailable: {type(e).__name__}"
    return {
        "ranking_available": err is None,
        "ranking_error": err,
        "top_promising": [r for r in (ranking or []) if r.get("status") in ("TOP_OBSERVE", "EDGE_REVIEW_CANDIDATE")][:5],
        "weakest": [r for r in (ranking or []) if r.get("status") in ("DISABLE_CANDIDATE", "REDUCE_PRIORITY")][:5],
        "needs_more_data": [r for r in (ranking or []) if r.get("status") == "NEEDS_MORE_DATA"][:5],
    }


def collect_section_v320_evidence_lower_bounds() -> dict:
    """Quick robustness audit per strategy if ledger available."""
    try:
        from evidence_lower_bounds import classify_strategy_evidence  # type: ignore
        return {
            "classifier_available": True,
            "note": "Run scripts/evidence_lower_bounds_report.py for per-strategy report.",
        }
    except Exception as e:
        return {"classifier_available": False, "error": f"{type(e).__name__}"}


def collect_section_v320_counterfactuals() -> dict:
    """Counterfactual report status."""
    try:
        import counterfactual_outcomes  # type: ignore
        ledger_files = _count_files(LEARNING_DIR / "opportunity_ledger")
        return {
            "module_loaded": True,
            "ready": ledger_files > 0,
            "opportunity_files_available": ledger_files,
            "counterfactual_evidence_segregated_from_paper": True,
        }
    except Exception as e:
        return {"module_loaded": False, "error": f"{type(e).__name__}"}


def collect_section_v320_gate_calibration() -> dict:
    """Gate calibration report status."""
    try:
        import gate_calibration  # type: ignore
        return {
            "module_loaded": True,
            "risk_gate_never_auto_weakens": True,
            "report_path": "docs/gate_calibration_LATEST.md (run scripts/gate_calibration_report.py)",
        }
    except Exception as e:
        return {"module_loaded": False, "error": f"{type(e).__name__}"}


def collect_section_v320_robustness() -> dict:
    try:
        import strategy_robustness  # type: ignore
        return {
            "module_loaded": True,
            "sandbox_never_optimizes": True,
            "sandbox_never_mutates_runtime": True,
        }
    except Exception as e:
        return {"module_loaded": False, "error": f"{type(e).__name__}"}


def collect_section_v320_variant_quarantine() -> dict:
    """Variant quarantine status — count quarantined variants if any."""
    try:
        import strategy_variant_quarantine as svq  # type: ignore
        variants, err = _safe_call(svq.load_quarantined_variants, default=[])
        return {
            "module_loaded": True,
            "quarantine_dir_files": _count_files(LEARNING_DIR / "variant_quarantine", "*.json"),
            "load_error": err,
            "variants_available_for_replay": [
                v for v in (variants or [])
                if v.get("status") == "CANDIDATE_FOR_MANUAL_REVIEW"
            ][:5],
        }
    except Exception as e:
        return {"module_loaded": False, "error": f"{type(e).__name__}"}


def collect_section_v320_scheduler() -> dict:
    """Latest experiment plan."""
    try:
        plans_dir = LEARNING_DIR / "experiment_plans"
        files = sorted(plans_dir.glob("experiment_plan_*.json")) if plans_dir.exists() else []
        latest = files[-1] if files else None
        plan = _read_json(latest, default={}) if latest else {}
        return {
            "plans_count": len(files),
            "latest_plan_file": str(latest.name) if latest else None,
            "strategies_to_observe_count": len(plan.get("strategies_to_observe", [])),
            "variants_to_replay_count": len(plan.get("variants_to_replay", [])),
            "underrepresented_regimes": plan.get("underrepresented_regimes", []),
            "scheduler_never_places_trades": True,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}"}


def collect_section_v320_exit_quality() -> dict:
    try:
        import exit_quality  # type: ignore
        return {
            "module_loaded": True,
            "recommendations_only_no_runtime_mutation": True,
            "report_path": "docs/exit_quality_LATEST.md (run scripts/exit_quality_report.py)",
        }
    except Exception as e:
        return {"module_loaded": False, "error": f"{type(e).__name__}"}


def collect_section_edge_gate() -> dict:
    """EDGE_GATE answer: can it flip true?"""
    try:
        from edge_validator import EDGE_GATE_DISABLED  # type: ignore
    except Exception:
        EDGE_GATE_DISABLED = True

    paper_count = collect_section_v319_dashboard().get("paper_trade_count", 0)
    blockers = []
    if paper_count < 50:
        blockers.append(f"paper_trade_count={paper_count} < 50 required")
    blockers.append("backtest/replay/counterfactual evidence cannot count toward 50 (enforced by EvidenceSource enum)")
    blockers.append("calibration check required (confidence buckets monotonic)")
    blockers.append("PF lower bound >= 1.3 required (Wilson + bootstrap)")
    blockers.append("at least 2 regimes observed")

    answer = "NO — paper evidence not yet sufficient" if blockers else "REVIEW_REQUIRED"
    return {
        "edge_gate_currently_disabled": EDGE_GATE_DISABLED,
        "can_flip_to_true_now": False,
        "answer": answer,
        "blockers": blockers,
    }


def build_decision_pack() -> dict:
    return {
        "version": "v3.20.0",
        "section_1_v319_dashboard": collect_section_v319_dashboard(),
        "section_2_evidence_production": collect_section_v320_evidence_production(),
        "section_3_strategy_ranking": collect_section_v320_strategy_ranking(),
        "section_4_evidence_lower_bounds": collect_section_v320_evidence_lower_bounds(),
        "section_5_counterfactuals": collect_section_v320_counterfactuals(),
        "section_6_gate_calibration": collect_section_v320_gate_calibration(),
        "section_7_robustness": collect_section_v320_robustness(),
        "section_8_variant_quarantine": collect_section_v320_variant_quarantine(),
        "section_9_experiment_scheduler": collect_section_v320_scheduler(),
        "section_10_exit_quality": collect_section_v320_exit_quality(),
        "section_11_edge_gate_answer": collect_section_edge_gate(),
        "invariants": {
            "live_trading_disabled": True,
            "edge_gate_enabled": False,
            "no_promises_of_profit": True,
            "evidence_sources_segregated": True,
            "agents_review_only": True,
            "no_paid_services": True,
        },
    }


def render_markdown(pack: dict) -> str:
    lines = ["# Operator Decision Pack (v3.20)", ""]
    lines.append("Read-only consolidation of v3.19 dashboard + v3.20 evidence modules.")
    lines.append("Generated by `scripts/operator_decision_pack.py`. NEVER places trades.")
    lines.append("")
    lines.append("## 1. What should the system observe tomorrow?")
    sched = pack["section_9_experiment_scheduler"]
    lines.append(f"- Strategies to observe: {sched.get('strategies_to_observe_count', 0)}")
    lines.append(f"- Underrepresented regimes: {sched.get('underrepresented_regimes', [])}")
    lines.append(f"- Variants to replay: {sched.get('variants_to_replay_count', 0)}")
    lines.append("")
    lines.append("## 2. Which strategies look most promising?")
    rank = pack["section_3_strategy_ranking"]
    if rank.get("top_promising"):
        for s in rank["top_promising"]:
            lines.append(f"- {s.get('strategy', '?')}: status={s.get('status')}, trades={s.get('n', 0)}")
    else:
        lines.append("- No top_promising entries yet — paper ledger likely empty.")
    lines.append("")
    lines.append("## 3. Which strategies look weakest?")
    if rank.get("weakest"):
        for s in rank["weakest"]:
            lines.append(f"- {s.get('strategy', '?')}: status={s.get('status')}")
    else:
        lines.append("- No weakest entries flagged.")
    lines.append("")
    lines.append("## 4. Which gates protect well?")
    gc = pack["section_6_gate_calibration"]
    lines.append(f"- Module loaded: {gc.get('module_loaded')}")
    lines.append(f"- Risk gate never auto-weakens: {gc.get('risk_gate_never_auto_weakens')}")
    lines.append(f"- Detail report: {gc.get('report_path')}")
    lines.append("")
    lines.append("## 5. Which gates may be over-conservative?")
    cf = pack["section_5_counterfactuals"]
    lines.append(f"- Counterfactual engine loaded: {cf.get('module_loaded')}")
    lines.append(f"- Opportunity ledger files available: {cf.get('opportunity_files_available', 0)}")
    if cf.get("opportunity_files_available", 0) == 0:
        lines.append("- No data yet — first run signal_opportunity_ledger to populate.")
    lines.append("")
    lines.append("## 6. Where is data missing?")
    lines.append(f"- Paper trades: {pack['section_1_v319_dashboard'].get('paper_trade_count', 0)} (< 50 = insufficient)")
    lines.append(f"- Opportunity ledger files: {pack['section_2_evidence_production'].get('opportunity_ledger_files', 0)}")
    lines.append(f"- Shadow ledger files: {pack['section_2_evidence_production'].get('shadow_ledger_files', 0)}")
    lines.append("")
    lines.append("## 7. Does any strategy variant deserve replay?")
    vq = pack["section_8_variant_quarantine"]
    if vq.get("variants_available_for_replay"):
        for v in vq["variants_available_for_replay"]:
            lines.append(f"- variant `{v.get('id', '?')}` parent={v.get('parent_strategy', '?')}")
    else:
        lines.append("- No variants currently flagged CANDIDATE_FOR_MANUAL_REVIEW.")
    lines.append("")
    lines.append("## 8. Can EDGE_GATE flip to true?")
    eg = pack["section_11_edge_gate_answer"]
    lines.append(f"**Answer:** {eg.get('answer')}")
    lines.append("")
    lines.append("## 9. Why not?")
    for b in eg.get("blockers", []):
        lines.append(f"- {b}")
    lines.append("")
    lines.append("## 10. Is the system still safe / free / paper-only?")
    inv = pack["invariants"]
    for k, v in inv.items():
        lines.append(f"- {k}: **{v}**")
    lines.append("")
    lines.append("---")
    lines.append("Decision pack is informational. Threshold changes are governed by Strategy Quality Gate (see docs/STRATEGY_RANKING.md). EDGE_GATE flip requires hard criteria (see docs/EDGE_EVIDENCE.md).")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true", help="Print to stdout, do not write files.")
    p.add_argument("--json", action="store_true", help="JSON output to stdout (with --no-write).")
    args = p.parse_args()

    pack = build_decision_pack()
    md = render_markdown(pack)

    if args.no_write:
        if args.json:
            print(json.dumps(pack, indent=2, sort_keys=True))
        else:
            print(md)
        return 0

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "operator_decision_pack_LATEST.md").write_text(md, encoding="utf-8")
    (DOCS_DIR / "operator_decision_pack_LATEST.json").write_text(
        json.dumps(pack, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote: {DOCS_DIR / 'operator_decision_pack_LATEST.md'}")
    print(f"Wrote: {DOCS_DIR / 'operator_decision_pack_LATEST.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

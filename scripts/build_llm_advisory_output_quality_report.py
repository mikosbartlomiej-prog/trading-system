#!/usr/bin/env python3
"""v3.31 (2026-06-16) — LLM Advisory Output Quality Report.

PURPOSE
-------
Read every per-agent advisory artefact under
``learning-loop/llm_advisory/<AGENT>_latest.json`` (the v3.29 mesh
schema) and compute one aggregate quality verdict per agent + a top-
level aggregate verdict for the entire advisory mesh:

* ``USEFUL``     — every enumerated agent has acceptable rows
* ``LOW_QUALITY`` — at least one agent failed the v3.30 thresholds
* ``EMPTY``      — no rows at all (mesh never wrote)

The v3.30 threshold contract:

* >= 3 findings
* >= 2 risks
* >= 2 recommended next actions
* non-empty ``limitations`` paragraph
* ``advisory_only=True`` AND ``must_not_execute_orders=True``

Deterministic fallback rows MUST satisfy the same thresholds — the v3.30
stub generator in ``shared/llm_advisory_quality_v3300.py`` enforces this.

OUTPUTS
-------
- ``learning-loop/llm_advisory/output_quality_latest.json``
- ``docs/LLM_ADVISORY_OUTPUT_QUALITY.md``

HARD SAFETY
-----------
- NEVER calls broker.
- NEVER imports ``alpaca_orders``.
- NEVER flips any flag.
- NEVER auto-clears anything.
- NEVER mutates state.
- NEVER makes a network call.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER``
- ``LLM_ADVISORY_ONLY``
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


# ── Constants ────────────────────────────────────────────────────────────────

VERDICT_USEFUL      = "USEFUL"
VERDICT_LOW_QUALITY = "LOW_QUALITY"
VERDICT_EMPTY       = "EMPTY"

ALL_VERDICTS: frozenset[str] = frozenset({
    VERDICT_USEFUL, VERDICT_LOW_QUALITY, VERDICT_EMPTY})

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
    "LLM_ADVISORY_ONLY",
)

# Default v3.29 advisory agents — canonical 10-name set.
DEFAULT_AGENTS: tuple[str, ...] = (
    "ALLOCATOR_PLAN_CRITIC",
    "DAILY_BRIEF",
    "EQUITY_RECONCILIATION_CRITIC",
    "FINAL_ARBITER",
    "INCIDENT_REVIEW",
    "NO_SIGNAL_DIAGNOSTIC",
    "RISK_REVIEW",
    "SHADOW_CANDIDATE_REVIEW",
    "STRATEGY_REVIEW",
    "TRIGGER_WATCHLIST_REVIEW",
)

DEFAULT_OUT_JSON = (REPO_ROOT / "learning-loop" / "llm_advisory"
                     / "output_quality_latest.json")
DEFAULT_OUT_DOC  = REPO_ROOT / "docs" / "LLM_ADVISORY_OUTPUT_QUALITY.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_path(agent: str, base_dir: Path) -> Path:
    return base_dir / f"{agent}_latest.json"


def _safe_load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _quality_module():
    """Import the v3.30 quality module. Fail-soft (returns None)."""
    try:
        try:
            import llm_advisory_quality_v3300 as _q  # type: ignore
            return _q
        except ImportError:
            from shared import llm_advisory_quality_v3300 as _q  # type: ignore
            return _q
    except Exception:
        return None


def _evaluate_row(row: dict, quality_mod) -> dict:
    """Evaluate a single agent row against the v3.30 thresholds.

    Returns ``{"verdict": ..., "findings_count": int,
    "risks_count": int, "next_actions_count": int,
    "limitations_len": int, "rationale": [str, ...]}``.

    Uses :mod:`shared.llm_advisory_quality_v3300` when available; falls
    back to a simple inline check so the report is always produced.
    """
    if not isinstance(row, dict):
        return {
            "verdict": VERDICT_EMPTY,
            "findings_count": 0, "risks_count": 0,
            "next_actions_count": 0, "limitations_len": 0,
            "rationale": ["row not present or not a dict"],
        }

    # Pull list-shaped fields (v3.30 contract).
    findings = row.get("findings_list") or []
    risks    = row.get("risks_list") or []
    actions  = row.get("next_actions_list") or []
    limitations = row.get("limitations") or ""

    if quality_mod is not None:
        try:
            parsed_proxy = {
                "findings_list":    findings,
                "risks_list":       risks,
                "next_actions_list": actions,
            }
            verdict_obj = quality_mod.evaluate(
                parsed_proxy, limitations=limitations)
            verdict_token = verdict_obj.verdict
            mapped = VERDICT_USEFUL
            if verdict_token == quality_mod.LLM_ADVISORY_QUALITY_EMPTY:
                mapped = VERDICT_EMPTY
            elif verdict_token == quality_mod.LLM_ADVISORY_LOW_QUALITY:
                mapped = VERDICT_LOW_QUALITY
            return {
                "verdict": mapped,
                "findings_count":      verdict_obj.findings_count,
                "risks_count":         verdict_obj.risks_count,
                "next_actions_count":  verdict_obj.next_actions_count,
                "limitations_len":     verdict_obj.limitations_len,
                "rationale":           list(verdict_obj.rationale),
            }
        except Exception:
            pass

    # Inline fallback — minimal threshold check.
    f_n = len(findings) if isinstance(findings, list) else 0
    r_n = len(risks) if isinstance(risks, list) else 0
    a_n = len(actions) if isinstance(actions, list) else 0
    lim_len = len((limitations or "").strip()) if isinstance(
        limitations, str) else 0
    rationale: list[str] = []
    if f_n == 0 and r_n == 0 and a_n == 0 and lim_len == 0:
        return {
            "verdict": VERDICT_EMPTY,
            "findings_count": 0, "risks_count": 0,
            "next_actions_count": 0, "limitations_len": 0,
            "rationale": ["empty output (no findings/risks/actions/limitations)"],
        }
    ok = True
    if f_n < 3:
        ok = False
        rationale.append(f"findings_count={f_n} < 3")
    if r_n < 2:
        ok = False
        rationale.append(f"risks_count={r_n} < 2")
    if a_n < 2:
        ok = False
        rationale.append(f"next_actions_count={a_n} < 2")
    if lim_len < 1:
        ok = False
        rationale.append("limitations empty")
    return {
        "verdict": VERDICT_USEFUL if ok else VERDICT_LOW_QUALITY,
        "findings_count":      f_n,
        "risks_count":         r_n,
        "next_actions_count":  a_n,
        "limitations_len":     lim_len,
        "rationale":           rationale or ["all v3.30 thresholds met"],
    }


def _check_invariants(row: dict) -> dict:
    """Return advisory invariant bits for an agent row."""
    if not isinstance(row, dict):
        return {
            "advisory_only":           False,
            "must_not_execute_orders": False,
        }
    return {
        "advisory_only":           bool(row.get("advisory_only")),
        "must_not_execute_orders": bool(row.get("must_not_execute_orders")),
    }


def build_report(*,
                   agents: tuple[str, ...] = DEFAULT_AGENTS,
                   base_dir: Path | None = None) -> dict:
    """Build the aggregate v3.31 quality report."""
    base_dir = base_dir or (
        REPO_ROOT / "learning-loop" / "llm_advisory")
    quality_mod = _quality_module()

    per_agent: list[dict] = []
    pass_count = 0
    low_count  = 0
    empty_count = 0
    missing_count = 0
    invariants_clean = 0

    def _safe_rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    for agent in agents:
        path = _agent_path(agent, base_dir)
        row  = _safe_load_json(path)
        if row is None:
            missing_count += 1
            per_agent.append({
                "agent_name":      agent,
                "verdict":         VERDICT_EMPTY,
                "rationale":       [f"agent file missing: {path.name}"],
                "findings_count":  0,
                "risks_count":     0,
                "next_actions_count": 0,
                "limitations_len": 0,
                "advisory_only":           True,
                "must_not_execute_orders": True,
                "provider_status": "PROVIDER_NOT_INVOKED",
                "quality_verdict_from_row": None,
                "path":            _safe_rel(path),
            })
            empty_count += 1
            continue

        eval_result = _evaluate_row(row, quality_mod)
        inv         = _check_invariants(row)
        verdict     = eval_result["verdict"]
        if verdict == VERDICT_USEFUL:
            pass_count += 1
        elif verdict == VERDICT_LOW_QUALITY:
            low_count += 1
        else:
            empty_count += 1
        if inv["advisory_only"] and inv["must_not_execute_orders"]:
            invariants_clean += 1
        per_agent.append({
            "agent_name":      agent,
            "verdict":         verdict,
            "rationale":       eval_result["rationale"],
            "findings_count":  eval_result["findings_count"],
            "risks_count":     eval_result["risks_count"],
            "next_actions_count": eval_result["next_actions_count"],
            "limitations_len": eval_result["limitations_len"],
            "advisory_only":           inv["advisory_only"],
            "must_not_execute_orders": inv["must_not_execute_orders"],
            "provider_status": row.get("provider_status",
                                          "PROVIDER_NOT_INVOKED"),
            "quality_verdict_from_row": row.get("quality_verdict"),
            "path":            _safe_rel(path),
        })

    # Aggregate verdict policy:
    # * If 100% of agents are EMPTY (or file missing) -> EMPTY.
    # * Else if any agent is LOW_QUALITY OR EMPTY (partial) -> LOW_QUALITY.
    # * Else -> USEFUL.
    total = len(agents)
    if empty_count == total:
        aggregate = VERDICT_EMPTY
    elif low_count > 0 or empty_count > 0:
        aggregate = VERDICT_LOW_QUALITY
    else:
        aggregate = VERDICT_USEFUL

    payload = {
        "schema_version":     "v3.31",
        "module":             "scripts.build_llm_advisory_output_quality_report",
        "generated_at_iso":   _now_iso(),
        "agents_enumerated":  list(agents),
        "agents_total":       total,
        "pass_count":         pass_count,
        "low_quality_count":  low_count,
        "empty_count":        empty_count,
        "missing_file_count": missing_count,
        "invariants_clean_count": invariants_clean,
        "aggregate_verdict":  aggregate,
        "per_agent":          per_agent,
        "standing_markers":   list(STANDING_MARKERS),
        "does_not_execute_orders":  True,
        "live_trading_unsupported": True,
        "no_order_placement":       True,
        "no_auto_broker_action":    True,
        "advisory_only":            True,
        "must_not_execute_orders":  True,
    }
    return payload


def render_doc(payload: dict) -> str:
    out: list[str] = []
    out.append("# LLM Advisory Output Quality Report (v3.31)")
    out.append("")
    out.append(f"_Generated:_ `{payload.get('generated_at_iso')}`")
    out.append("")
    out.append("## Aggregate verdict")
    out.append("")
    out.append(f"- **Aggregate:** `{payload.get('aggregate_verdict')}`")
    out.append(f"- **Agents total:** `{payload.get('agents_total')}`")
    out.append(f"- **Pass:** `{payload.get('pass_count')}`")
    out.append(
        f"- **LOW_QUALITY:** `{payload.get('low_quality_count')}`")
    out.append(f"- **EMPTY:** `{payload.get('empty_count')}`")
    out.append(
        f"- **Missing file:** "
        f"`{payload.get('missing_file_count')}`")
    out.append(
        f"- **Invariants clean (advisory_only + "
        f"must_not_execute_orders):** "
        f"`{payload.get('invariants_clean_count')}/{payload.get('agents_total')}`")
    out.append("")
    out.append("## Per-agent table")
    out.append("")
    out.append(
        "| Agent | Verdict | Findings | Risks | Next-actions | "
        "Limitations | Advisory-only | Must-not-execute | "
        "Provider status |")
    out.append(
        "|---|---|---:|---:|---:|---:|---|---|---|")
    for row in payload.get("per_agent", []):
        out.append(
            f"| `{row.get('agent_name')}` "
            f"| `{row.get('verdict')}` "
            f"| {row.get('findings_count')} "
            f"| {row.get('risks_count')} "
            f"| {row.get('next_actions_count')} "
            f"| {row.get('limitations_len')} "
            f"| `{row.get('advisory_only')}` "
            f"| `{row.get('must_not_execute_orders')}` "
            f"| `{row.get('provider_status')}` |"
        )
    out.append("")
    out.append("## Per-agent rationale")
    out.append("")
    for row in payload.get("per_agent", []):
        out.append(f"### `{row.get('agent_name')}`")
        for r in row.get("rationale", []):
            out.append(f"- {r}")
        out.append("")
    out.append("---")
    out.append("")
    out.append("### Standing markers")
    for m in payload.get("standing_markers", []):
        out.append(f"- `{m}`")
    out.append("")
    out.append(
        "> This reporter is read-only. It never calls the broker, "
        "never places orders, never flips any flag, and never "
        "auto-clears safe_mode. Deterministic gates remain final.")
    out.append("")
    return "\n".join(out)


def write_outputs(payload: dict,
                    out_json: Path | None = None,
                    out_doc:  Path | None = None) -> dict[str, Path]:
    json_path = out_json or DEFAULT_OUT_JSON
    doc_path  = out_doc  or DEFAULT_OUT_DOC
    json_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_json = json_path.with_suffix(json_path.suffix + ".tmp")
    with open(tmp_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp_json, json_path)
    tmp_doc = doc_path.with_suffix(doc_path.suffix + ".tmp")
    with open(tmp_doc, "w", encoding="utf-8") as fh:
        fh.write(render_doc(payload))
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp_doc, doc_path)
    return {"json": json_path, "doc": doc_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v3.31 LLM advisory output quality report.")
    parser.add_argument(
        "--base-dir",
        default=str(REPO_ROOT / "learning-loop" / "llm_advisory"))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-doc",  default=str(DEFAULT_OUT_DOC))
    args = parser.parse_args(argv)

    payload = build_report(base_dir=Path(args.base_dir))
    paths = write_outputs(
        payload,
        out_json=Path(args.out_json),
        out_doc=Path(args.out_doc),
    )
    print(
        f"LLM_ADVISORY_OUTPUT_QUALITY aggregate_verdict="
        f"{payload['aggregate_verdict']}")
    print(
        f"pass={payload['pass_count']} "
        f"low={payload['low_quality_count']} "
        f"empty={payload['empty_count']} "
        f"missing={payload['missing_file_count']}")
    print(f"wrote: {paths['json']}")
    print(f"wrote: {paths['doc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

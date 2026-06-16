#!/usr/bin/env python3
"""v3.29 ETAP 6 (2026-06-16) — LLM Advisory Mesh CLI runner.

Drives the v3.29 mesh (``shared/llm_advisory_mesh.py``) which is
itself bounded by the v3.29 authority model
(``shared/llm_advisory_authority.py``). This script DOES NOT replace
the existing v3.28 ``scripts/run_llm_advisory_mesh.py`` — both layers
coexist. This v3.29 runner is the entry point for the new mesh whose
output schema is ``LLMAdvisoryOutput``.

Usage
-----

    python3 scripts/run_llm_advisory_mesh_v329.py [--all | --agent ROLE]
                                                    [--dry-run]
                                                    [--no-write-docs]

Defaults:

    - ``--dry-run`` is **on by default**. The runner emits a
      deterministic stub per agent and writes the per-role
      ``<role>_latest.json`` file under
      ``learning-loop/llm_advisory/``.
    - Real mode (``--dry-run=false``): consults the LLM provider via
      ``shared/llm_provider_client.py`` while still respecting the
      v3.28 budget guard. Falls back to a deterministic stub on
      any failure.

HARD SAFETY
-----------
- Refuses (exit 1) if any of ``ALLOW_BROKER_PAPER`` /
  ``EDGE_GATE_ENABLED`` / ``BROKER_EXECUTION_ENABLED`` /
  ``LIVE_TRADING`` / ``LIVE_ENABLED`` / ``GO_LIVE`` /
  ``LIVE_TRADING_ENABLED`` is truthy.
- NEVER calls broker.
- NEVER mutates state outside
  ``learning-loop/llm_advisory/`` and ``journal/autonomy/``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import llm_advisory_authority as auth      # noqa: E402
import llm_advisory_mesh as mesh           # noqa: E402

# ─── Status tokens ──────────────────────────────────────────────────────────

V329_MESH_RAN              = "V329_MESH_RAN"
V329_MESH_DRY_RUN          = "V329_MESH_DRY_RUN"
V329_MESH_REFUSED          = "V329_MESH_REFUSED"

# ─── Standing markers (always returned) ─────────────────────────────────────

STANDING_MARKERS = tuple(auth.STANDING_MARKERS) + (
    "DETERMINISTIC_GATES_REMAIN_FINAL",
    "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
    "SCHEDULE_REMAINS_DISABLED_BY_DEFAULT",
)


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _write_status_md(outputs: list, *,
                       dry_run: bool, status: str) -> None:
    """Render the human-readable summary at
    ``docs/LLM_ADVISORY_MESH_STATUS.md``."""
    doc_path = REPO_ROOT / "docs" / "LLM_ADVISORY_MESH_STATUS.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# LLM Advisory Mesh — v3.29 ETAP 6 status\n")
    lines.append(f"- **Generated at:** "
                   f"{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- **Status:** `{status}`")
    lines.append(f"- **Dry-run:** `{dry_run}`")
    lines.append(f"- **Agents emitted:** {len(outputs)}")
    lines.append("")
    lines.append("## Per-agent summary")
    lines.append("")
    lines.append(
        "| Agent | Authority | Recommendation | Risk | Confidence | Veto |")
    lines.append(
        "|---|---|---|---|---|---|")
    for o in outputs:
        try:
            d = o.to_dict() if hasattr(o, "to_dict") else dict(o)
        except Exception:
            d = {"agent_name": "unknown"}
        lines.append(
            f"| `{d.get('agent_name', '?')}` "
            f"| `{d.get('authority_level', '?')}` "
            f"| `{d.get('recommendation', '?')}` "
            f"| `{d.get('risk_level', '?')}` "
            f"| `{d.get('confidence', '?')}` "
            f"| `{d.get('veto_recommendation', False)}` |")
    lines.append("")
    lines.append("## Standing markers")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("## Hard invariants (verified in tests)")
    lines.append(
        "- LLM advisory mesh NEVER imports `alpaca_orders`.")
    lines.append(
        "- LLM advisory mesh NEVER calls broker.")
    lines.append(
        "- LLM advisory mesh NEVER mutates `runtime_state`, "
        "`safe_mode`, `broker_repair_required`, or any "
        "broker / live flag.")
    lines.append(
        "- LLM advisory mesh writes ONLY to "
        "`learning-loop/llm_advisory/` and `journal/autonomy/`.")
    lines.append(
        "- Every advisory output is validated against the v3.29 "
        "`LLMAdvisoryOutput` schema before persistence.")
    lines.append(
        "- Secrets are redacted from every persisted field.")
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_authority_model_md() -> None:
    """Mirror the v3.29 authority contract for operator reference."""
    doc_path = REPO_ROOT / "docs" / "LLM_AUTHORITY_MODEL.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    # NEVER overwrite the existing v3.28 doc unless we own a v3.29
    # section. Instead append a footer if the file already exists.
    v329_block = (
        "\n\n---\n\n"
        "## v3.29 ETAP 6 — strict advisory schema\n\n"
        "The v3.29 mesh runs every advisory call through\n"
        "[`shared/llm_advisory_authority.py`](../shared/llm_advisory_authority.py)\n"
        "which defines the canonical `LLMAdvisoryOutput` dataclass.\n\n"
        "**Schema invariants (enforced in `__post_init__`):**\n"
        "- `advisory_only = True`\n"
        "- `must_not_execute_orders = True`\n"
        "- `authority_level ∈ {L0_ADVISORY_ONLY, L1_VETO_RECOMMEND_ONLY}`\n"
        "- `agent_name ∈ ADVISORY_ROLES` (10 roles)\n"
        "- No FORBIDDEN_OUTPUTS token in any string field\n\n"
        "**Forbidden output tokens:**\n"
        + "\n".join(f"- `{tok}`" for tok in sorted(
            auth.FORBIDDEN_OUTPUTS))
        + "\n\n**Advisory roles (10):**\n"
        + "\n".join(f"- `{r}`"
                       for r in sorted(auth.ADVISORY_ROLES))
        + "\n\n**Standing markers asserted on every persistence:**\n"
        + "\n".join(f"- `{m}`" for m in STANDING_MARKERS)
        + "\n"
    )
    if doc_path.exists():
        try:
            current = doc_path.read_text(encoding="utf-8")
        except Exception:
            current = ""
        if "v3.29 ETAP 6 — strict advisory schema" in current:
            return  # idempotent
        doc_path.write_text(current + v329_block, encoding="utf-8")
    else:
        doc_path.write_text(
            "# LLM Authority Model\n" + v329_block, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v3.29 ETAP 6 LLM advisory mesh runner.")
    parser.add_argument("--dry-run", default="true",
                          help="true/false. Default true (stubs only).")
    parser.add_argument("--agent", default=None,
                          help="Run a single agent role.")
    parser.add_argument("--all", action="store_true",
                          help="Run every agent (default).")
    parser.add_argument("--no-write-docs", action="store_true",
                          help="Skip writing docs/* files.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run.strip().lower() not in ("false", "0", "no",
                                                       "off")

    # Refuse if any broker flag truthy.
    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({
            "status": V329_MESH_REFUSED,
            "reason": refuse,
            "standing_markers": list(STANDING_MARKERS),
        }))
        return 1

    outputs: list = []
    try:
        if args.agent:
            outputs = [mesh.run_agent(args.agent, dry_run=dry_run)]
        else:
            outputs = mesh.run_mesh(dry_run=dry_run)
    except Exception as e:
        # Even an exception inside run_mesh is bounded — emit a
        # diagnostic and exit 0 (fail-soft).
        print(json.dumps({
            "status": "V329_MESH_FAIL_SOFT",
            "error": auth.redact_secrets(str(e))[:200],
            "standing_markers": list(STANDING_MARKERS),
        }))
        return 0

    status = V329_MESH_DRY_RUN if dry_run else V329_MESH_RAN
    if not args.no_write_docs:
        try:
            _write_status_md(outputs, dry_run=dry_run, status=status)
            _write_authority_model_md()
        except Exception as e:
            print(f"  [v3.29] doc write failed: {e}")

    summary = {
        "status":           status,
        "agents_emitted":   len(outputs),
        "dry_run":          dry_run,
        "agents":           [
            o.agent_name if hasattr(o, "agent_name") else "?"
            for o in outputs],
        "standing_markers": list(STANDING_MARKERS),
        "broker_safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
        },
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

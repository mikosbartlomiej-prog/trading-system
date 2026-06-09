#!/usr/bin/env python3
"""v3.30 (2026-06-09) — broker-paper canary pre-executor CLI.

Default mode is ``--preflight-only --dry-run``. In v3.30 there is NO
order-placement path. Even an all-green preflight returns the verdict
``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED`` and exits.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER calls submit_order / place_order / safe_close.
- NEVER places, modifies, or closes a position.
- Refuses (exit 1) on any truthy broker-execution / live env flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_live_truthy() -> str | None:
    # CLI-level refusal: live env flags are an absolute no-go.
    for name in (
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _current_unlock_status() -> str | None:
    path = (REPO_ROOT / "learning-loop" / "broker_paper_canary"
             / "unlock_readiness_latest.json")
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("unlock_status")
    except Exception:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Broker-paper canary pre-executor CLI (v3.30).")
    parser.add_argument("--preflight-only", action="store_true",
                          default=True,
                          help="Default: preflight only.")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", dest="dry_run",
                       action="store_true",
                       help="(default) preflight gates inspected but "
                              "no order placement possible.")
    grp.add_argument("--no-dry-run", dest="dry_run",
                       action="store_false",
                       help="Walk the full gate stack. v3.30 still "
                              "stops at "
                              "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED "
                              "— no order is placed.")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--unlock-status", default=None,
                          help="Override the unlock_status read from "
                                "the latest artefact.")
    args = parser.parse_args(argv)

    refuse = _refuse_if_live_truthy()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    import broker_paper_canary_preflight as pf  # type: ignore
    unlock_status = (args.unlock_status
                       or _current_unlock_status())
    result = pf.run_preflight(
        unlock_status=unlock_status,
        dry_run_only=args.dry_run,
    )
    out = {
        "version": "v3.30",
        "verdict": result.verdict,
        "rationale": result.rationale,
        "gates":   result.gates,
        "unlock_status": unlock_status,
        "standing_markers": [
            "CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY",
            "NO_ORDER_PLACEMENT_IN_V330",
            "LLM_ADVISORY_ONLY_CONFIRMED",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
        ],
    }
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

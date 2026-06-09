#!/usr/bin/env python3
"""v3.29.1 (2026-06-09) — real-market evidence acceleration evaluator.

Read-only. Emits a recommendation artefact telling the operator why
real-market opportunity records are not landing yet and which SAFE
actions could accelerate collection.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER mutates readiness counters or shadow evidence counters.
- NEVER places orders.
- NEVER fabricates records.
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Real-market evidence acceleration evaluator "
                     "(v3.29.1).")
    parser.add_argument("--write-artifacts", action="store_true",
                          default=True,
                          help="Default: write acceleration_latest.json "
                                "+ REAL_MARKET_EVIDENCE_ACCELERATION.md.")
    args = parser.parse_args(argv)
    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1
    import real_market_evidence_accelerator as a  # type: ignore
    rep = a.evaluate_acceleration()
    if args.write_artifacts:
        try:
            a.write_artifacts(rep)
        except Exception as e:
            print(f"  [accel] artifact write failed: {e}")
    out = {
        "version":             "v3.29.1",
        "acceleration_status": rep.status,
        "successful_runs":     rep.successful_runs_observed,
        "dominant_token":      rep.dominant_diagnostic_token,
        "recommended_actions": rep.recommended_actions,
        "standing_markers": [
            "LLM_STRATEGY_ALIGNMENT_ENFORCED",
            "LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
        ],
    }
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

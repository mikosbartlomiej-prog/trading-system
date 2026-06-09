#!/usr/bin/env python3
"""v3.29 (2026-06-09) — one-call Gemini smoke test.

Used by the v3.29 workflow before running the full 11-agent mesh. Lets
the workflow short-circuit when the provider isn't reachable instead
of writing 11 fail-soft rows.

HARD SAFETY
-----------
- NEVER prints the API key.
- NEVER prints the full URL.
- NEVER imports the broker-orders module.
- NEVER touches trading state or readiness counters.
- Fail-soft on any error — always exits 0.
- Refuses (exit 1) if any of
  ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING`` /
  ``LIVE_ENABLED`` / ``GO_LIVE`` / ``LIVE_TRADING_ENABLED``
  is truthy.
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


# ─── Status enum ────────────────────────────────────────────────────────────

GEMINI_SMOKE_OK                    = "GEMINI_SMOKE_OK"
GEMINI_SMOKE_MODEL_UNAVAILABLE     = "GEMINI_SMOKE_MODEL_UNAVAILABLE"
GEMINI_SMOKE_AUTH_FAILED           = "GEMINI_SMOKE_AUTH_FAILED"
GEMINI_SMOKE_QUOTA_OR_RATE_LIMIT   = "GEMINI_SMOKE_QUOTA_OR_RATE_LIMIT"
GEMINI_SMOKE_PERMISSION_DENIED     = "GEMINI_SMOKE_PERMISSION_DENIED"
GEMINI_SMOKE_TIMEOUT               = "GEMINI_SMOKE_TIMEOUT"
GEMINI_SMOKE_FAILED                = "GEMINI_SMOKE_FAILED"
GEMINI_SMOKE_SKIPPED_NO_KEY        = "GEMINI_SMOKE_SKIPPED_NO_KEY"

ALL_SMOKE_STATUSES: frozenset[str] = frozenset({
    GEMINI_SMOKE_OK,
    GEMINI_SMOKE_MODEL_UNAVAILABLE,
    GEMINI_SMOKE_AUTH_FAILED,
    GEMINI_SMOKE_QUOTA_OR_RATE_LIMIT,
    GEMINI_SMOKE_PERMISSION_DENIED,
    GEMINI_SMOKE_TIMEOUT,
    GEMINI_SMOKE_FAILED,
    GEMINI_SMOKE_SKIPPED_NO_KEY,
})


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


def _category_to_smoke(category: str | None) -> str:
    import gemini_model_selector as sel  # type: ignore
    return {
        sel.GEMINI_MODEL_UNAVAILABLE:
            GEMINI_SMOKE_MODEL_UNAVAILABLE,
        sel.GEMINI_AUTH_FAILED:
            GEMINI_SMOKE_AUTH_FAILED,
        sel.GEMINI_QUOTA_OR_RATE_LIMIT:
            GEMINI_SMOKE_QUOTA_OR_RATE_LIMIT,
        sel.GEMINI_PERMISSION_DENIED:
            GEMINI_SMOKE_PERMISSION_DENIED,
        sel.GEMINI_ENDPOINT_ERROR:
            GEMINI_SMOKE_FAILED,
        sel.GEMINI_TIMEOUT:
            GEMINI_SMOKE_TIMEOUT,
        sel.GEMINI_UNKNOWN_PROVIDER_FAILURE:
            GEMINI_SMOKE_FAILED,
    }.get(category or "", GEMINI_SMOKE_FAILED)


def run_smoke(*,
                configured_model: str | None = None,
                prompt: str = "Reply with the JSON object {\"ok\": true}",
                ) -> dict:
    """Execute the smoke test. Returns a status dict — never raises."""
    out: dict = {
        "version":           "v3.29",
        "generated_at_iso":  datetime.now(timezone.utc).isoformat(),
        "smoke_status":      GEMINI_SMOKE_FAILED,
        "selected_model":    None,
        "configured_model":  configured_model,
        "discovered_models_count": 0,
        "failure_category":  None,
        "failure_http":      None,
        "error_redacted":    "",
        "safe_to_schedule":  False,
        "free_only":         True,
        "secret_values_logged": False,
        "standing_markers": [
            "BROKER_PAPER_CANARY_STILL_BLOCKED",
            "LIVE_TRADING_UNSUPPORTED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
            "SCHEDULE_REMAINS_DISABLED",
        ],
    }
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        out["smoke_status"] = GEMINI_SMOKE_SKIPPED_NO_KEY
        return out
    try:
        import gemini_model_selector as sel  # type: ignore
        import llm_provider_client as p       # type: ignore
    except Exception as e:
        out["smoke_status"] = GEMINI_SMOKE_FAILED
        out["error_redacted"] = f"import error: {type(e).__name__}"
        return out
    # Discovery + selection.
    disc = sel.select_model(
        configured_model=configured_model,
        api_key=key, timeout_seconds=10.0)
    out["selected_model"]          = disc.selected_model
    out["discovered_models_count"] = len(disc.discovered)
    if disc.status not in (
            sel.GEMINI_MODEL_SELECTED, sel.GEMINI_MODEL_DISCOVERY_OK):
        # Discovery failed — still try the configured/candidate model
        # so the operator can see a real call status. If even that
        # fails we'll fall through with the failure category.
        out["failure_category"] = disc.failure_category
    # One real generateContent call.
    resp = p.call_provider(prompt=prompt,
                              model=disc.selected_model,
                              max_tokens=128, timeout_seconds=15.0)
    if resp.status == p.LLM_PROVIDER_CALL_OK:
        out["smoke_status"] = GEMINI_SMOKE_OK
        out["safe_to_schedule"] = False  # still operator-gated
        return out
    if resp.status in (p.LLM_PROVIDER_OFFLINE_MOCK,):
        out["smoke_status"] = GEMINI_SMOKE_SKIPPED_NO_KEY
        return out
    out["failure_category"] = (
        resp.provider_error_category or out["failure_category"])
    out["failure_http"]     = resp.provider_http_status
    out["smoke_status"]     = _category_to_smoke(
        out["failure_category"])
    out["error_redacted"]   = resp.text[:300]
    return out


def write_artifacts(result: dict) -> None:
    json_path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                  / "gemini_smoke_latest.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path = REPO_ROOT / "docs" / "GEMINI_PROVIDER_STATUS.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "# Gemini Provider Status (v3.29)\n",
        f"- **Smoke status:** `{result.get('smoke_status')}`",
        f"- **Selected model:** `{result.get('selected_model')}`",
        f"- **Configured model:** `{result.get('configured_model')}`",
        f"- **Discovered models count:** "
        f"{result.get('discovered_models_count')}",
        f"- **Failure category:** "
        f"`{result.get('failure_category')}`",
        f"- **Failure HTTP:** {result.get('failure_http')}",
        f"- **Safe to schedule:** "
        f"{str(result.get('safe_to_schedule', False)).lower()}",
        "",
        "## Standing markers\n",
        "- `BROKER_PAPER_CANARY_STILL_BLOCKED`",
        "- `LIVE_TRADING_UNSUPPORTED`",
        "- `DETERMINISTIC_GATES_REMAIN_FINAL`",
        "- `SCHEDULE_REMAINS_DISABLED`",
        "",
        "## Hard safety\n",
        "- API key never printed.",
        "- Full URL never logged.",
        "- No broker imports.",
        "- No trading state touched.",
    ]
    doc_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Gemini provider smoke test (v3.29).")
    parser.add_argument(
        "--model", default=None,
        help="GEMINI_MODEL override; defaults to env GEMINI_MODEL.")
    parser.add_argument(
        "--write-artifacts", action="store_true",
        help="Persist gemini_smoke_latest.json + "
              "GEMINI_PROVIDER_STATUS.md")
    args = parser.parse_args(argv)
    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1
    configured = (args.model
                    or os.environ.get("GEMINI_MODEL", "").strip()
                    or None)
    result = run_smoke(configured_model=configured)
    if args.write_artifacts:
        try:
            write_artifacts(result)
        except Exception as e:
            print(f"  [smoke] artifact write failed: {e}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

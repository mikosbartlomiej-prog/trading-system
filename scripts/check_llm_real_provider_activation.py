#!/usr/bin/env python3
"""v3.31 (2026-06-16) — LLM Real-Provider Activation Check.

PURPOSE
-------
Detect whether the LLM advisory mesh has a real provider key available.
Emit:

* ``learning-loop/llm_advisory/provider_activation_latest.json``
* ``docs/LLM_PROVIDER_HEALTH_STATUS.md`` (regenerated with v3.31 stamp)

When the operator passes ``--smoke-test`` AND a key is detected, run ONE
safe smoke prompt (literal "Reply with the literal string
PROVIDER_SMOKE_OK"), validate non-empty output, and route everything
through ``redact_secrets`` before persisting.

HARD SAFETY
-----------
- NEVER prints the secret value.
- NEVER writes the secret value to disk.
- All output passes through :func:`redact_secrets`.
- ``--smoke-test`` defaults to False (operator must opt-in explicitly).
- ``--dry-run`` defaults to True (informational only).
- NEVER imports ``alpaca_orders``.
- NEVER calls broker.
- NEVER mutates state / runtime_state / safe_mode / broker_repair / flags.
- NEVER places, modifies, or cancels any order.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER``
- ``LLM_ADVISORY_ONLY``
- ``NO_LLM_STATE_MUTATION``
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

# Verdict tokens.
VERDICT_DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET = (
    "DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET")
VERDICT_PROVIDER_KEY_DETECTED_NO_SMOKE_TEST = (
    "PROVIDER_KEY_DETECTED_NO_SMOKE_TEST")
VERDICT_REAL_PROVIDER_READY        = "REAL_PROVIDER_READY"
VERDICT_REAL_PROVIDER_SMOKE_FAILED = "REAL_PROVIDER_SMOKE_FAILED"

ALL_VERDICTS: frozenset[str] = frozenset({
    VERDICT_DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET,
    VERDICT_PROVIDER_KEY_DETECTED_NO_SMOKE_TEST,
    VERDICT_REAL_PROVIDER_READY,
    VERDICT_REAL_PROVIDER_SMOKE_FAILED,
})

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
    "LLM_ADVISORY_ONLY",
    "NO_LLM_STATE_MUTATION",
)

OPERATOR_INSTRUCTIONS_FOR_MISSING_SECRET: tuple[str, ...] = (
    "GitHub repo: Settings -> Secrets and variables -> Actions -> "
    "New repository secret",
    "Name: GEMINI_API_KEY",
    "Value: <obtain from https://aistudio.google.com/apikey>",
    "After saving, the daily llm-advisory-mesh.yml workflow will use "
    "the secret automatically",
)

DEFAULT_OUT_JSON = (REPO_ROOT / "learning-loop" / "llm_advisory"
                     / "provider_activation_latest.json")
DEFAULT_OUT_DOC  = REPO_ROOT / "docs" / "LLM_PROVIDER_HEALTH_STATUS.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_secret_presence() -> tuple[bool, str]:
    """Detect ``GEMINI_API_KEY`` presence. NEVER returns the value.

    Returns ``(present, source)`` where ``source`` is a non-secret
    descriptor of where the key was discovered ("env"/"absent").
    """
    raw = os.environ.get("GEMINI_API_KEY", "")
    if not isinstance(raw, str):
        return False, "absent"
    stripped = raw.strip()
    if not stripped:
        return False, "absent"
    return True, "env"


def _redact_module():
    """Import the canonical redaction helper. Fail-soft: returns a
    minimal identity-with-token-scrub fallback if the shared module is
    unavailable.
    """
    try:
        from llm_advisory_authority import redact_secrets  # type: ignore
        return redact_secrets
    except Exception:
        try:
            from shared.llm_advisory_authority import (  # type: ignore
                redact_secrets)
            return redact_secrets
        except Exception:
            import re
            _alnum = re.compile(r"\b[A-Z0-9]{20,}\b")
            def _fallback(text):  # noqa: E306
                if text is None:
                    return ""
                if not isinstance(text, str):
                    text = str(text)
                return _alnum.sub("[REDACTED]", text)
            return _fallback


def _run_smoke_test(redact_secrets):
    """Run ONE safe smoke call via the shared provider client. Returns
    a dict ``{"ok": bool, "text": redacted_string, "status": str,
    "provider_called": True}``. NEVER raises. NEVER returns the secret
    value.
    """
    try:
        try:
            import llm_provider_client as _p   # type: ignore
        except ImportError:
            from shared import llm_provider_client as _p   # type: ignore
    except Exception as e:
        return {
            "ok": False,
            "text": "",
            "status": "PROVIDER_CLIENT_IMPORT_FAILED",
            "diagnostic": redact_secrets(f"{type(e).__name__}"),
            "provider_called": False,
        }

    # Pin the provider to gemini for the smoke test only if not already
    # set. The smoke test does NOT persist this pin to the env file.
    prov_before = os.environ.get("LLM_PROVIDER", "").strip()
    if not prov_before:
        os.environ["LLM_PROVIDER"] = "gemini"
    # Allow paid providers? No — keep the free-only default.
    # (The user might select gemini which is free.)
    try:
        resp = _p.call_provider(
            prompt=("Reply with the literal string PROVIDER_SMOKE_OK"),
            max_tokens=64,
        )
    except Exception as e:
        return {
            "ok": False,
            "text": "",
            "status": "PROVIDER_CALL_EXCEPTION",
            "diagnostic": redact_secrets(f"{type(e).__name__}"),
            "provider_called": True,
        }

    status = getattr(resp, "status", "") or ""
    text   = getattr(resp, "text",   "") or ""
    redacted_text = redact_secrets(text)
    ok = (status == getattr(_p, "LLM_PROVIDER_CALL_OK", "OK")
          and bool(redacted_text and redacted_text.strip()))
    return {
        "ok":     bool(ok),
        "text":   redacted_text[:600],
        "status": status,
        "provider_called": True,
    }


def build_payload(*, smoke_test: bool, dry_run: bool) -> dict:
    """Build the activation payload. NEVER raises. NEVER prints secret."""
    redact_secrets = _redact_module()

    secret_present, secret_source = _detect_secret_presence()

    payload: dict = {
        "schema_version":           "v3.31",
        "module":                   "scripts.check_llm_real_provider_activation",
        "generated_at_iso":         _now_iso(),
        "dry_run":                  bool(dry_run),
        "smoke_test_requested":     bool(smoke_test),
        "smoke_test_executed":      False,
        "smoke_text_redacted":      "",
        "smoke_status":             "",
        "gemini_api_key_present":   bool(secret_present),
        "gemini_api_key_source":    secret_source,
        # NEVER include the secret value or its length.
        "operator_instructions":    [],
        "standing_markers":         list(STANDING_MARKERS),
        "live_trading_unsupported": True,
        "no_order_placement":       True,
        "no_auto_broker_action":    True,
        "advisory_only":            True,
        "must_not_execute_orders":  True,
    }

    if not secret_present:
        payload["verdict"] = VERDICT_DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET
        payload["operator_instructions"] = list(
            OPERATOR_INSTRUCTIONS_FOR_MISSING_SECRET)
        payload["reason"] = (
            "GEMINI_API_KEY not present in env; LLM advisory mesh "
            "remains in deterministic fallback. Deterministic gates "
            "remain final.")
        return payload

    # Secret detected.
    if not smoke_test:
        payload["verdict"] = VERDICT_PROVIDER_KEY_DETECTED_NO_SMOKE_TEST
        payload["reason"] = (
            "GEMINI_API_KEY detected in env, but --smoke-test was not "
            "set. Re-run with --smoke-test to verify provider "
            "reachability. Default is dry-run/no-smoke for safety.")
        return payload

    # Smoke test path. Default --dry-run is True; require explicit
    # opt-in via --no-dry-run or --smoke-test (which is itself opt-in).
    result = _run_smoke_test(redact_secrets)
    payload["smoke_test_executed"]   = True
    payload["smoke_text_redacted"]   = result.get("text", "")
    payload["smoke_status"]          = result.get("status", "")
    payload["smoke_provider_called"] = bool(result.get(
        "provider_called", False))
    if result.get("ok"):
        payload["verdict"] = VERDICT_REAL_PROVIDER_READY
        payload["reason"] = (
            "Smoke call returned a non-empty response from the "
            "configured provider. Mesh can now run with real "
            "evaluation; deterministic gates remain final.")
    else:
        payload["verdict"] = VERDICT_REAL_PROVIDER_SMOKE_FAILED
        payload["reason"] = (
            "Smoke call failed or returned empty text. The mesh will "
            "stay in deterministic fallback. Inspect "
            "learning-loop/llm_provider_health_latest.json for "
            "diagnostics.")
        # Even on failure, include the operator instructions so the
        # operator can recheck the secret or rotate.
        payload["operator_instructions"] = list(
            OPERATOR_INSTRUCTIONS_FOR_MISSING_SECRET)
    return payload


def render_doc(payload: dict) -> str:
    out: list[str] = []
    out.append("# LLM Provider Activation Check (v3.31)")
    out.append("")
    out.append(f"_Generated:_ `{payload.get('generated_at_iso')}`")
    out.append("")
    out.append("## Verdict")
    out.append("")
    out.append(f"- **Verdict:** `{payload.get('verdict')}`")
    out.append(f"- **Dry-run:** `{payload.get('dry_run')}`")
    out.append(
        f"- **Smoke-test requested:** "
        f"`{payload.get('smoke_test_requested')}`")
    out.append(
        f"- **Smoke-test executed:** "
        f"`{payload.get('smoke_test_executed')}`")
    out.append(
        f"- **GEMINI_API_KEY present:** "
        f"`{payload.get('gemini_api_key_present')}` "
        f"(value NEVER printed)")
    reason = payload.get("reason") or ""
    if reason:
        out.append("")
        out.append(f"**Reason:** {reason}")
    if payload.get("smoke_test_executed"):
        out.append("")
        out.append("## Smoke output (redacted)")
        out.append("")
        out.append(f"- Status: `{payload.get('smoke_status')}`")
        snippet = payload.get("smoke_text_redacted") or ""
        if snippet:
            out.append("- Redacted text excerpt:")
            out.append("")
            out.append("```text")
            out.append(snippet[:400])
            out.append("```")
    ops = payload.get("operator_instructions") or []
    if ops:
        out.append("")
        out.append("## Operator instructions (missing/failed key)")
        out.append("")
        for i, line in enumerate(ops, 1):
            out.append(f"{i}. {line}")
    out.append("")
    out.append("---")
    out.append("")
    out.append("### Standing markers")
    for m in payload.get("standing_markers", []):
        out.append(f"- `{m}`")
    out.append("")
    out.append(
        "> This reporter is read-only. It never calls the broker, "
        "never places orders, never flips any flag, never auto-clears "
        "safe_mode, and never prints the secret value.")
    out.append("")
    return "\n".join(out)


def _write_outputs(payload: dict,
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
        description=(
            "v3.31 LLM real-provider activation check. NEVER prints "
            "the secret value. Default dry-run, no smoke-test."))
    parser.add_argument(
        "--dry-run", default="true",
        help="Default true; informational only. Pass --dry-run=false "
             "to mark the run as non-dry (still read-only/no broker).")
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Opt-in. If set AND GEMINI_API_KEY is present, runs ONE "
             "safe smoke call. Default false.")
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-doc",  default=str(DEFAULT_OUT_DOC))
    args = parser.parse_args(argv)

    dry_raw = str(args.dry_run).strip().lower()
    dry_run = dry_raw in ("", "true", "1", "yes", "on")
    smoke_test = bool(args.smoke_test)

    payload = build_payload(smoke_test=smoke_test, dry_run=dry_run)
    paths = _write_outputs(
        payload,
        out_json=Path(args.out_json),
        out_doc=Path(args.out_doc),
    )

    # Operator-facing print. NEVER prints the secret.
    verdict = payload.get("verdict", "")
    print(f"LLM_REAL_PROVIDER_ACTIVATION verdict={verdict}")
    print(
        f"gemini_api_key_present="
        f"{payload.get('gemini_api_key_present')}")
    print(f"dry_run={payload.get('dry_run')}")
    print(f"smoke_test_executed={payload.get('smoke_test_executed')}")
    if payload.get("operator_instructions"):
        for i, line in enumerate(payload["operator_instructions"], 1):
            print(f"  [op-{i}] {line}")
    print(f"wrote: {paths['json']}")
    print(f"wrote: {paths['doc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

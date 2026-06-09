#!/usr/bin/env python3
"""v3.28.2 (2026-06-09) — LLM advisory mesh activation helper.

Lets the operator / Claude / GitHub automation check whether the
cloud LLM advisory mesh is ready to activate using a free-first
Gemini provider, set the non-secret repo variables, and optionally
trigger the workflow — without ever printing secret values.

HARD SAFETY (cannot be opted out of)
------------------------------------
- NEVER submits orders.
- NEVER imports the broker-orders module.
- NEVER prints or persists secret values — the script asks ``gh`` for
  the *list* of secret names only, never their values.
- NEVER sets a GitHub Secret (the operator did that out-of-band).
- NEVER enables broker paper or live trading.
- NEVER mutates risk config, readiness counters, or shadow evidence.
- Exits 0 if blocked by missing permissions / missing secret / missing
  ``gh`` CLI — this is operator-side environment, not a code failure.
- Refuses (exit 1) only if any of
  ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING`` /
  ``LIVE_ENABLED`` / ``GO_LIVE`` / ``LIVE_TRADING_ENABLED``
  is truthy — that combination is a configuration error, not a
  permission issue.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Status tokens ──────────────────────────────────────────────────────────

LLM_ACTIVATION_READY_GEMINI_SECRET_PRESENT  = (
    "LLM_ACTIVATION_READY_GEMINI_SECRET_PRESENT")
LLM_ACTIVATION_BLOCKED_NO_GITHUB_AUTH        = (
    "LLM_ACTIVATION_BLOCKED_NO_GITHUB_AUTH")
LLM_ACTIVATION_BLOCKED_NO_PROVIDER_SECRET    = (
    "LLM_ACTIVATION_BLOCKED_NO_PROVIDER_SECRET")
LLM_ACTIVATION_VARIABLES_SET                 = (
    "LLM_ACTIVATION_VARIABLES_SET")
LLM_ACTIVATION_VARIABLES_FAILED              = (
    "LLM_ACTIVATION_VARIABLES_FAILED")
LLM_ACTIVATION_WORKFLOW_TRIGGERED            = (
    "LLM_ACTIVATION_WORKFLOW_TRIGGERED")
LLM_ACTIVATION_WORKFLOW_SUCCESS              = (
    "LLM_ACTIVATION_WORKFLOW_SUCCESS")
LLM_ACTIVATION_WORKFLOW_FAILED               = (
    "LLM_ACTIVATION_WORKFLOW_FAILED")
LLM_ACTIVATION_SCHEDULE_LEFT_DISABLED        = (
    "LLM_ACTIVATION_SCHEDULE_LEFT_DISABLED")

# Standing markers — always emitted.
BROKER_PAPER_CANARY_STILL_BLOCKED = "BROKER_PAPER_CANARY_STILL_BLOCKED"
LIVE_TRADING_UNSUPPORTED          = "LIVE_TRADING_UNSUPPORTED"
DETERMINISTIC_GATES_REMAIN_FINAL  = "DETERMINISTIC_GATES_REMAIN_FINAL"


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


# ─── gh CLI shell helpers ──────────────────────────────────────────────────

def _run(cmd: list[str],
          *, timeout: float = 30.0) -> tuple[int, str, str]:
    """Run a subprocess capturing stdout + stderr. Never raises."""
    try:
        cp = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return cp.returncode, (cp.stdout or ""), (cp.stderr or "")
    except FileNotFoundError as e:
        return 127, "", f"file-not-found: {e}"
    except subprocess.TimeoutExpired:
        return 124, "", "subprocess-timeout"
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def gh_cli_available() -> bool:
    return shutil.which("gh") is not None


def gh_cli_authenticated() -> bool:
    if not gh_cli_available():
        return False
    rc, _, _ = _run(["gh", "auth", "status"])
    return rc == 0


def list_secret_names() -> tuple[bool, list[str], str]:
    """Returns ``(ok, names, reason)``. ``ok=False`` means the call
    failed (no auth, no repo, etc.); we treat that as "blocked", not
    "secret missing".
    """
    if not gh_cli_available():
        return False, [], "gh CLI not installed"
    rc, out, err = _run(["gh", "secret", "list",
                            "--json", "name"])
    if rc != 0:
        return False, [], (err or out or "gh secret list failed")
    try:
        rows = json.loads(out or "[]")
    except Exception:
        return False, [], "gh returned non-JSON"
    names = [r.get("name", "") for r in rows
              if isinstance(r, dict)]
    return True, [n for n in names if n], ""


def has_secret(name: str) -> tuple[bool, str]:
    ok, names, reason = list_secret_names()
    if not ok:
        return False, reason
    return name in names, ""


def set_variable(name: str, value: str) -> tuple[bool, str]:
    if not gh_cli_authenticated():
        return False, "gh not authenticated"
    rc, _, err = _run([
        "gh", "variable", "set", name, "--body", value,
    ])
    if rc != 0:
        return False, (err or f"gh variable set {name} failed")
    return True, "ok"


def trigger_workflow(workflow_file: str, run_id: str
                       ) -> tuple[bool, str]:
    if not gh_cli_authenticated():
        return False, "gh not authenticated"
    rc, _, err = _run([
        "gh", "workflow", "run", workflow_file,
        "-f", f"run_id={run_id}",
    ])
    if rc != 0:
        return False, (err or f"gh workflow run {workflow_file} failed")
    return True, "ok"


# ─── Provider auto-selection ───────────────────────────────────────────────

def auto_select_provider(secret_names: list[str],
                          *,
                          free_only: bool = True) -> str:
    """Returns the chosen provider given the visible secret names."""
    if "GEMINI_API_KEY" in secret_names:
        return "gemini"
    if not free_only:
        if "ANTHROPIC_API_KEY" in secret_names:
            return "anthropic"
        if "OPENAI_API_KEY" in secret_names:
            return "openai"
    return "offline_mock"


# ─── Status artifact writers ───────────────────────────────────────────────

def _safe_preview(text: str, n: int = 200) -> str:
    if not text:
        return ""
    import re
    cleaned = re.sub(r"sk-ant-[A-Za-z0-9_\-]{6,}", "<REDACTED>", text)
    cleaned = re.sub(r"\bsk-[A-Za-z0-9]{8,}", "<REDACTED>", cleaned)
    cleaned = re.sub(r"\b[A-Z0-9]{20,}\b", "<REDACTED>", cleaned)
    cleaned = cleaned.replace("\n", " ")
    return cleaned[:n]


def write_status(*, status: dict[str, Any],
                  status_path: Path | None = None,
                  doc_path: Path | None = None) -> None:
    if status_path is None:
        status_path = (REPO_ROOT / "learning-loop"
                        / "llm_advisory"
                        / "activation_status_latest.json")
    if doc_path is None:
        doc_path = REPO_ROOT / "docs" / "LLM_ADVISORY_ACTIVATION_STATUS.md"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    md = _render_doc(status)
    doc_path.write_text(md, encoding="utf-8")


def _render_doc(s: dict[str, Any]) -> str:
    rows = []
    for k in (
        "generated_at_iso", "gh_cli_available",
        "gh_cli_authenticated", "gemini_secret_present",
        "selected_provider", "llm_free_only",
        "variables_status", "schedule_enabled",
        "workflow_dispatch_status", "latest_run_id",
        "latest_run_conclusion", "mesh_runner_status",
        "advisory_rows_emitted",
        "agents_attempted", "agents_completed",
    ):
        rows.append(f"- **{k}:** `{s.get(k, 'n/a')}`")
    blockers = s.get("blockers") or []
    out = ["# LLM Advisory Activation Status (v3.28.2)\n"]
    out.extend(rows)
    out.append("\n## Blockers\n")
    if blockers:
        for b in blockers:
            out.append(f"- {b}")
    else:
        out.append("- (none)")
    out.append("\n## Standing markers\n")
    out.append("- `BROKER_PAPER_CANARY_STILL_BLOCKED`")
    out.append("- `LIVE_TRADING_UNSUPPORTED`")
    out.append("- `DETERMINISTIC_GATES_REMAIN_FINAL`")
    out.append("- `FREE_ONLY_POLICY_ENABLED`")
    out.append("- `PAID_PROVIDERS_BLOCKED_WHEN_FREE_ONLY`")
    out.append("- `OFFLINE_MOCK_STILL_DEFAULT`")
    out.append("- `API_KEYS_NOT_EXPOSED`")
    out.append("- `SCHEDULE_LEFT_DISABLED_BY_DEFAULT`")
    out.append("\n## Safety invariants\n")
    safety = s.get("safety") or {}
    for k, v in sorted(safety.items()):
        out.append(f"- `{k}`: **{str(v).lower()}**")
    out.append("\n## Next recommended action\n")
    out.append(f"- {s.get('next_recommended_action', 'n/a')}")
    return "\n".join(out) + "\n"


# ─── Build status (pure) ───────────────────────────────────────────────────

def build_status(*,
                   gh_avail: bool,
                   gh_auth: bool,
                   secret_names: list[str],
                   selected_provider: str,
                   llm_free_only: bool = True,
                   schedule_enabled: bool = False,
                   variables_status: str = "",
                   workflow_dispatch_status: str = "",
                   latest_run_id: str | None = None,
                   latest_run_conclusion: str | None = None,
                   mesh_runner_status: str | None = None,
                   advisory_rows_emitted: int = 0,
                   agents_attempted: int = 0,
                   agents_completed: int = 0,
                   blockers: list[str] | None = None,
                   ) -> dict[str, Any]:
    blockers = list(blockers or [])
    if not gh_avail:
        blockers.append("gh CLI not installed locally")
    if gh_avail and not gh_auth:
        blockers.append("gh CLI not authenticated")
    gemini_present = "GEMINI_API_KEY" in (secret_names or [])
    return {
        "version":                      "v3.28.2",
        "generated_at_iso":             datetime.now(timezone.utc).isoformat(),
        "gh_cli_available":             gh_avail,
        "gh_cli_authenticated":         gh_auth,
        "gemini_secret_present":        gemini_present,
        "secret_names_seen":            sorted(secret_names or []),
        "selected_provider":            selected_provider,
        "llm_free_only":                bool(llm_free_only),
        "schedule_enabled":             bool(schedule_enabled),
        "variables_status":             variables_status,
        "workflow_dispatch_status":     workflow_dispatch_status,
        "latest_run_id":                latest_run_id,
        "latest_run_conclusion":        latest_run_conclusion,
        "mesh_runner_status":           mesh_runner_status,
        "advisory_rows_emitted":        int(advisory_rows_emitted),
        "agents_attempted":             int(agents_attempted),
        "agents_completed":             int(agents_completed),
        "blockers":                     blockers,
        "next_recommended_action":      _next_action(
            gh_avail=gh_avail, gh_auth=gh_auth,
            gemini_present=gemini_present,
            selected_provider=selected_provider),
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "broker_execution_enabled":          False,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "deterministic_gates_remain_final":  True,
        },
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
            DETERMINISTIC_GATES_REMAIN_FINAL,
            "FREE_ONLY_POLICY_ENABLED",
            "PAID_PROVIDERS_BLOCKED_WHEN_FREE_ONLY",
            "OFFLINE_MOCK_STILL_DEFAULT",
            "API_KEYS_NOT_EXPOSED",
            "SCHEDULE_LEFT_DISABLED_BY_DEFAULT",
        ],
    }


def _next_action(*, gh_avail: bool, gh_auth: bool,
                  gemini_present: bool,
                  selected_provider: str) -> str:
    if not gh_avail:
        return ("Install GitHub CLI (gh) — see "
                 "https://cli.github.com/. After install, run "
                 "`gh auth login` and re-run this helper.")
    if not gh_auth:
        return ("Run `gh auth login` and re-run this helper.")
    if not gemini_present:
        return ("Add `GEMINI_API_KEY` as a GitHub Secret (Settings → "
                 "Secrets and variables → Actions → New repository "
                 "secret), then re-run with --set-vars.")
    if selected_provider == "gemini":
        return ("Run with --set-vars to set "
                 "LLM_AGENTS_ENABLED=true / LLM_PROVIDER=gemini / "
                 "LLM_FREE_ONLY=true / LLM_AGENTS_SCHEDULED=false, "
                 "then --trigger to fire the workflow.")
    return "offline_mock default; no further activation needed."


# ─── CLI ───────────────────────────────────────────────────────────────────

WORKFLOW_FILE = "llm-advisory-mesh.yml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM advisory mesh activation helper (v3.28.2).")
    parser.add_argument(
        "--check-only", action="store_true",
        help="Inspect environment and write status only (default).")
    parser.add_argument("--set-vars", action="store_true",
                          help="Set repo variables via gh CLI.")
    parser.add_argument("--trigger", action="store_true",
                          help="Trigger workflow_dispatch via gh CLI.")
    parser.add_argument(
        "--provider",
        choices=["auto", "gemini", "offline_mock",
                  "anthropic", "openai"],
        default="auto")
    parser.add_argument(
        "--enable-schedule", choices=["false", "true"],
        default="false")
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    gh_avail = gh_cli_available()
    gh_auth  = gh_cli_authenticated() if gh_avail else False
    secret_names: list[str] = []
    list_ok = False
    if gh_auth:
        list_ok, secret_names, _ = list_secret_names()

    if args.provider == "auto":
        selected = auto_select_provider(
            secret_names, free_only=True)
    else:
        selected = args.provider

    blockers: list[str] = []
    variables_status = ""
    workflow_dispatch_status = ""
    schedule_enabled = (args.enable_schedule == "true")

    # set-vars
    if args.set_vars:
        if not gh_auth:
            variables_status = LLM_ACTIVATION_VARIABLES_FAILED
            blockers.append("set-vars requires gh CLI authentication")
        elif selected == "gemini" and "GEMINI_API_KEY" not in secret_names:
            variables_status = LLM_ACTIVATION_VARIABLES_FAILED
            blockers.append(
                "set-vars requires GEMINI_API_KEY secret to exist")
        else:
            ok1, _ = set_variable("LLM_AGENTS_ENABLED", "true")
            ok2, _ = set_variable("LLM_PROVIDER", selected)
            ok3, _ = set_variable("LLM_FREE_ONLY", "true")
            ok4, _ = set_variable(
                "LLM_AGENTS_SCHEDULED",
                "true" if schedule_enabled else "false")
            if all((ok1, ok2, ok3, ok4)):
                variables_status = LLM_ACTIVATION_VARIABLES_SET
            else:
                variables_status = LLM_ACTIVATION_VARIABLES_FAILED
                blockers.append(
                    "one or more gh variable set commands failed")

    # trigger
    if args.trigger:
        if not gh_auth:
            workflow_dispatch_status = LLM_ACTIVATION_WORKFLOW_FAILED
            blockers.append("trigger requires gh CLI authentication")
        elif selected != "offline_mock" and \
                  selected not in ("gemini",) and \
                  selected not in ("anthropic", "openai"):
            workflow_dispatch_status = LLM_ACTIVATION_WORKFLOW_FAILED
        elif selected == "gemini" and "GEMINI_API_KEY" not in secret_names:
            workflow_dispatch_status = LLM_ACTIVATION_WORKFLOW_FAILED
            blockers.append(
                "trigger requires GEMINI_API_KEY secret to exist")
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            run_id = f"v3282-{selected}-activation-{stamp}"
            ok, reason = trigger_workflow(WORKFLOW_FILE, run_id)
            if ok:
                workflow_dispatch_status = LLM_ACTIVATION_WORKFLOW_TRIGGERED
            else:
                workflow_dispatch_status = LLM_ACTIVATION_WORKFLOW_FAILED
                blockers.append(f"workflow run failed: {reason[:120]}")

    if not args.set_vars and not args.trigger:
        # Default: check-only
        if gh_auth and "GEMINI_API_KEY" in secret_names:
            status_tok = LLM_ACTIVATION_READY_GEMINI_SECRET_PRESENT
        elif gh_avail and not gh_auth:
            status_tok = LLM_ACTIVATION_BLOCKED_NO_GITHUB_AUTH
        elif gh_auth and "GEMINI_API_KEY" not in secret_names:
            status_tok = LLM_ACTIVATION_BLOCKED_NO_PROVIDER_SECRET
        else:
            status_tok = LLM_ACTIVATION_BLOCKED_NO_GITHUB_AUTH
        workflow_dispatch_status = status_tok

    status = build_status(
        gh_avail=gh_avail, gh_auth=gh_auth,
        secret_names=secret_names,
        selected_provider=selected,
        llm_free_only=True,
        schedule_enabled=schedule_enabled,
        variables_status=variables_status,
        workflow_dispatch_status=workflow_dispatch_status,
        blockers=blockers,
    )
    if not schedule_enabled:
        status.setdefault("standing_markers", []).append(
            LLM_ACTIVATION_SCHEDULE_LEFT_DISABLED)
    write_status(status=status)
    print(json.dumps({
        "version":                 "v3.28.2",
        "status":                  workflow_dispatch_status,
        "selected_provider":       selected,
        "gemini_secret_present":   "GEMINI_API_KEY" in secret_names,
        "schedule_enabled":        schedule_enabled,
        "variables_status":        variables_status,
        "blockers_count":          len(blockers),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

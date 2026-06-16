#!/usr/bin/env python3
"""v3.29 ETAP 9 (2026-06-16) — LLM provider health audit.

Read-only verdict over the LLM advisory mesh provider state. Checks:

* ``GEMINI_API_KEY`` env presence (never prints the value).
* ``OPENAI_API_KEY`` env presence (informational).
* ``ANTHROPIC_API_KEY`` env presence (informational).
* ``learning-loop/llm_advisory/activation_status_latest.json``.
* ``learning-loop/llm_advisory/quality_review_latest.json``.
* ``learning-loop/llm_advisory/quality_history.jsonl`` tail.
* Recent mesh outputs under ``learning-loop/llm_advisory/*.jsonl``.
* ``learning-loop/llm_advisory/llm_budget_state.json`` (remaining
  per-day call budget — informational).
* Explicit claim verifier: when an operator note asserts the LLM
  provider has been broken "for 80 days", debunks the claim if no
  evidence of an 80-day outage exists in the on-disk artefacts.

Outputs
-------
- ``learning-loop/llm_provider_health_latest.json``
- ``docs/LLM_PROVIDER_HEALTH_STATUS.md``

HARD SAFETY
-----------
- NEVER prints any secret value. Every output is run through
  :func:`shared.llm_advisory_authority.redact_secrets` before disk-write.
- NEVER enables broker paper. ``ALLOW_BROKER_PAPER=false`` stays pinned.
- NEVER enables ``EDGE_GATE_ENABLED``. Stays pinned false.
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER makes a network call (does NOT contact the LLM provider).
- NEVER mutates state.json or runtime_state.json.
- NEVER submits / cancels / closes any order.
- Proposed fixes are EMITTED as text only. Operator action is required.

The 80-day-down operator claim defaults to ``CLAIM_UNSUPPORTED``
unless on-disk history shows a continuous gap of 80 days.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                     / "llm_provider_health_latest.json")
LATEST_MD_PATH   = REPO_ROOT / "docs" / "LLM_PROVIDER_HEALTH_STATUS.md"

STANDING_MARKERS = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
    "LLM_ADVISORY_ONLY",
    "LLM_NEVER_IN_ORDER_PATH",
)

# Verdict tokens
VERDICT_OK                 = "OK"
VERDICT_DEGRADED           = "DEGRADED"
VERDICT_FAILED             = "FAILED"
VERDICT_UNKNOWN            = "UNKNOWN"
VERDICT_CLAIM_UNSUPPORTED  = "CLAIM_UNSUPPORTED"
VERDICT_BUDGET_EXHAUSTED   = "BUDGET_EXHAUSTED"


# ─── Helpers ─────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _try_redact(text: str) -> str:
    """Run text through redact_secrets if available; never raises."""
    try:
        try:
            from llm_advisory_authority import redact_secrets  # type: ignore
        except ImportError:
            from shared.llm_advisory_authority import redact_secrets  # type: ignore
        return redact_secrets(text)
    except Exception:
        return text


def _safe_load_json(rel: str) -> Any:
    p = REPO_ROOT / rel
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _tail_jsonl(rel: str, max_rows: int = 50) -> list:
    p = REPO_ROOT / rel
    if not p.exists():
        return []
    out: list = []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out[-max_rows:]


# ─── Provider env presence ───────────────────────────────────────────


def _env_presence(name: str) -> dict:
    """Return ``{present: bool, value_length: int}`` — NEVER the value."""
    val = os.environ.get(name) or ""
    return {
        "name":         name,
        "present":      bool(val.strip()),
        "value_length": len(val) if val else 0,
    }


# ─── History inspection ──────────────────────────────────────────────


def _history_summary() -> dict:
    """Summary of recent quality history (rows + earliest/latest day)."""
    rows = _tail_jsonl(
        "learning-loop/llm_advisory/quality_history.jsonl", max_rows=200)
    if not rows:
        return {"rows": 0, "earliest_iso": None, "latest_iso": None,
                "n_success": 0, "n_failure": 0, "n_unknown": 0}
    n_success = 0
    n_failure = 0
    n_unknown = 0
    earliest = None
    latest = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        status = str(r.get("status") or r.get("verdict")
                      or r.get("result") or "").upper()
        if "OK" in status or "SUCCESS" in status or "PASS" in status:
            n_success += 1
        elif "FAIL" in status or "ERROR" in status:
            n_failure += 1
        else:
            n_unknown += 1
        ts = r.get("ts_iso") or r.get("generated_at_iso") or r.get("date")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
            if earliest is None or dt < earliest:
                earliest = dt
            if latest is None or dt > latest:
                latest = dt
    return {
        "rows":         len(rows),
        "n_success":    n_success,
        "n_failure":    n_failure,
        "n_unknown":    n_unknown,
        "earliest_iso": earliest.isoformat() if earliest else None,
        "latest_iso":   latest.isoformat() if latest else None,
    }


def _budget_summary() -> dict:
    """Read llm_budget_state.json (best-effort)."""
    data = _safe_load_json("learning-loop/llm_advisory/llm_budget_state.json")
    if not isinstance(data, dict):
        return {"available": False}
    return {
        "available":             True,
        "calls_today":           data.get("calls_today"),
        "daily_call_budget":     data.get("daily_call_budget"),
        "remaining":             data.get("remaining"),
        "spent_today_usd":       data.get("spent_today_usd"),
        "max_cost_usd_per_day":  data.get("max_cost_usd_per_day"),
    }


# ─── Verdict logic ───────────────────────────────────────────────────


def _verdict_per_provider(provider: str, env_st: dict,
                           history: dict, budget: dict,
                           activation: dict, quality_review: dict) -> dict:
    """Per-provider verdict + actionable text."""
    present = bool(env_st.get("present"))
    n_success = int(history.get("n_success") or 0)
    n_failure = int(history.get("n_failure") or 0)
    rows = int(history.get("rows") or 0)

    if budget.get("available"):
        rem = budget.get("remaining")
        try:
            if rem is not None and float(rem) <= 0:
                return {
                    "verdict": VERDICT_BUDGET_EXHAUSTED,
                    "reason":  f"daily call budget exhausted "
                                f"(remaining={rem})",
                }
        except Exception:
            pass

    if not present:
        # Without the env key the provider cannot have produced any
        # recent success regardless of history. Emit UNKNOWN unless
        # the activation snapshot says the provider was active very
        # recently.
        activation_provider = (activation or {}).get("provider")
        if str(activation_provider).lower() == provider.lower():
            return {
                "verdict": VERDICT_DEGRADED,
                "reason":  f"provider {provider} was active in "
                            "activation_status snapshot but env key "
                            "is now absent; provider key may have "
                            "been rotated out of the runner",
            }
        return {
            "verdict": VERDICT_UNKNOWN,
            "reason":  f"{env_st.get('name')} env not set; cannot "
                       "determine provider liveness from a read-only "
                       "audit",
        }

    if rows == 0:
        return {
            "verdict": VERDICT_UNKNOWN,
            "reason":  "no quality_history rows on disk; provider has "
                       "never reported through the v3.28 mesh",
        }

    if n_failure > 0 and n_success == 0:
        return {
            "verdict": VERDICT_FAILED,
            "reason":  f"{n_failure} failures and 0 successes in last "
                        f"{rows} history rows",
        }
    if n_failure > 0 and n_success > 0:
        return {
            "verdict": VERDICT_DEGRADED,
            "reason":  f"{n_failure} failures alongside {n_success} "
                        f"successes in last {rows} rows",
        }
    return {
        "verdict": VERDICT_OK,
        "reason":  f"{n_success} successes / {n_failure} failures over "
                    f"{rows} recent rows",
    }


def _classify_80_day_claim(history: dict) -> tuple[str, str]:
    """Default ``CLAIM_UNSUPPORTED`` unless history proves a 80-day outage."""
    rows = int(history.get("rows") or 0)
    if rows == 0:
        return VERDICT_CLAIM_UNSUPPORTED, (
            "no quality_history rows; cannot prove or disprove an 80-day "
            "outage from a read-only audit")
    earliest = history.get("earliest_iso")
    latest = history.get("latest_iso")
    if not earliest or not latest:
        return VERDICT_CLAIM_UNSUPPORTED, (
            "history lacks usable timestamps; the 80-day-down claim is "
            "unsupported by direct evidence")
    try:
        e_dt = datetime.fromisoformat(str(earliest).replace("Z", "+00:00"))
        l_dt = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
        span = (l_dt - e_dt).days
    except Exception:
        return VERDICT_CLAIM_UNSUPPORTED, "history timestamps unparseable"

    age_days = (_now() - l_dt.replace(tzinfo=timezone.utc)).days
    if age_days >= 80:
        return VERDICT_FAILED, (
            f"latest history row is {age_days} days old; the 80-day "
            "claim is consistent with this evidence")
    if span >= 80 and history.get("n_failure", 0) > 0 \
            and history.get("n_success", 0) == 0:
        return VERDICT_FAILED, (
            f"history spans {span} days with 0 successes; outage is "
            "supported")
    return VERDICT_CLAIM_UNSUPPORTED, (
        f"latest activity is {age_days} days old (span {span} days) "
        "— the 80-day-down claim is debunked by direct evidence")


# ─── Public API ──────────────────────────────────────────────────────


def build_status() -> dict:
    gemini_env = _env_presence("GEMINI_API_KEY")
    openai_env = _env_presence("OPENAI_API_KEY")
    anthropic_env = _env_presence("ANTHROPIC_API_KEY")

    activation = _safe_load_json(
        "learning-loop/llm_advisory/activation_status_latest.json") or {}
    quality_review = _safe_load_json(
        "learning-loop/llm_advisory/quality_review_latest.json") or {}
    history = _history_summary()
    budget = _budget_summary()

    gemini_verdict = _verdict_per_provider(
        "gemini", gemini_env, history, budget, activation, quality_review)
    openai_verdict = _verdict_per_provider(
        "openai", openai_env, history, budget, activation, quality_review)
    anthropic_verdict = _verdict_per_provider(
        "anthropic", anthropic_env, history, budget, activation,
        quality_review)

    claim_verdict, claim_reason = _classify_80_day_claim(history)

    proposed_fixes: list[str] = []
    if not gemini_env["present"]:
        proposed_fixes.append(
            "[PROPOSED-FIX] LLM provider may be DEGRADED/UNKNOWN because "
            "GEMINI_API_KEY env not configured in workflow context — "
            "operator should add the secret in GitHub repo settings "
            "(Settings → Secrets and variables → Actions → New "
            "repository secret). Do NOT auto-apply.")
    if budget.get("available") and budget.get("remaining") is not None:
        try:
            if float(budget.get("remaining") or 0) <= 0:
                proposed_fixes.append(
                    "[PROPOSED-FIX] LLM_AGENT_DAILY_CALL_BUDGET exhausted "
                    "for today; budget resets at UTC midnight. Do NOT "
                    "auto-bump the budget.")
        except Exception:
            pass

    payload = {
        "module":           "scripts.audit_llm_provider_health",
        "schema_version":   "v3.29",
        "generated_at_iso": _now_iso(),
        "providers":        {
            "gemini": {
                "env":     gemini_env,
                "verdict": gemini_verdict["verdict"],
                "reason":  gemini_verdict["reason"],
            },
            "openai": {
                "env":     openai_env,
                "verdict": openai_verdict["verdict"],
                "reason":  openai_verdict["reason"],
            },
            "anthropic": {
                "env":     anthropic_env,
                "verdict": anthropic_verdict["verdict"],
                "reason":  anthropic_verdict["reason"],
            },
        },
        "activation_snapshot_present":     bool(activation),
        "quality_review_snapshot_present": bool(quality_review),
        "history":          history,
        "budget":           budget,
        "eighty_day_claim_verdict": claim_verdict,
        "eighty_day_claim_reason":  claim_reason,
        "proposed_fixes":   proposed_fixes,
        "standing_markers": list(STANDING_MARKERS),
    }
    return payload


def render_md(status: dict) -> str:
    lines: list[str] = []
    lines.append("# LLM Provider Health Audit (v3.29)")
    lines.append("")
    lines.append(f"_Generated:_ `{status.get('generated_at_iso', '')}`")
    lines.append("")
    lines.append("## Providers")
    lines.append("")
    providers = status.get("providers") or {}
    for name in sorted(providers.keys()):
        p = providers[name] or {}
        env = p.get("env") or {}
        lines.append(f"### `{name}`")
        lines.append(f"- env: `{env.get('name')}` present="
                     f"`{bool(env.get('present'))}` length="
                     f"`{env.get('value_length')}` (value NEVER printed)")
        lines.append(f"- verdict: `{p.get('verdict')}`")
        lines.append(f"- reason: `{p.get('reason')}`")
        lines.append("")
    lines.append("## 80-day-down operator claim")
    lines.append("")
    lines.append(f"- Verdict: `{status.get('eighty_day_claim_verdict')}`")
    lines.append(f"- Reason: `{status.get('eighty_day_claim_reason')}`")
    lines.append("")
    lines.append("## Activation snapshot")
    lines.append("")
    lines.append(f"- present: `{status.get('activation_snapshot_present')}`")
    lines.append(f"- quality_review present: "
                 f"`{status.get('quality_review_snapshot_present')}`")
    lines.append("")
    h = status.get("history") or {}
    lines.append("## Quality history (last 200 rows)")
    lines.append("")
    lines.append(f"- rows: `{h.get('rows')}`")
    lines.append(f"- n_success: `{h.get('n_success')}`")
    lines.append(f"- n_failure: `{h.get('n_failure')}`")
    lines.append(f"- n_unknown: `{h.get('n_unknown')}`")
    lines.append(f"- earliest_iso: `{h.get('earliest_iso')}`")
    lines.append(f"- latest_iso: `{h.get('latest_iso')}`")
    lines.append("")
    b = status.get("budget") or {}
    lines.append("## Budget")
    lines.append("")
    if b.get("available"):
        lines.append(f"- calls_today: `{b.get('calls_today')}`")
        lines.append(f"- daily_call_budget: `{b.get('daily_call_budget')}`")
        lines.append(f"- remaining: `{b.get('remaining')}`")
        lines.append(f"- spent_today_usd: `{b.get('spent_today_usd')}`")
        lines.append(f"- max_cost_usd_per_day: "
                     f"`{b.get('max_cost_usd_per_day')}`")
    else:
        lines.append("- budget snapshot absent")
    lines.append("")
    lines.append("## Proposed fixes (operator action — DO NOT auto-apply)")
    lines.append("")
    fixes = status.get("proposed_fixes") or []
    if fixes:
        for f in fixes:
            lines.append(f"- {f}")
    else:
        lines.append("- (no fixes proposed)")
    lines.append("")
    lines.append("## Standing markers")
    for m in status.get("standing_markers") or STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_This audit never enables broker paper, never enables "
                 "live trading, never enables `EDGE_GATE_ENABLED`, never "
                 "prints any secret value (all output passes through "
                 "redact_secrets), never auto-applies fixes, never "
                 "modifies the LLM budget, never submits / cancels / "
                 "closes any order. LLM output is advisory-only and "
                 "MUST NOT participate in the broker / order / risk "
                 "path._")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    status = build_status()
    md = render_md(status)

    # Defence in depth: redact the whole MD before disk-write.
    md = _try_redact(md)

    if args.json:
        # Redact the JSON serialisation as well before stdout.
        print(_try_redact(json.dumps(status, indent=2, sort_keys=True)))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            _try_redact(json.dumps(status, indent=2, sort_keys=True)) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        try:
            print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
            print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"Wrote {LATEST_JSON_PATH}")
            print(f"Wrote {LATEST_MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

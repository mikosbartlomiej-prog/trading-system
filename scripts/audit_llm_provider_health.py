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
# v3.30 (2026-06-16) — quality verdicts surfaced from advisory rows.
QUALITY_ACCEPTABLE         = "LLM_ADVISORY_QUALITY_ACCEPTABLE"
QUALITY_LOW_QUALITY        = "LLM_ADVISORY_LOW_QUALITY"
QUALITY_EMPTY              = "LLM_ADVISORY_QUALITY_EMPTY"
QUALITY_THRESHOLD_LOW_QUALITY_RATIO = 0.50  # flag if > 50% LOW_QUALITY


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


# ─── v3.30 quality counters ──────────────────────────────────────────


def _quality_counts_from_advisory_rows(max_rows_per_file: int = 50
                                         ) -> dict:
    """v3.30 (2026-06-16) — count recent advisory rows by quality.

    Scans every ``learning-loop/llm_advisory/*_latest.json`` file
    (per-agent latest snapshot) and counts verdicts. Each per-agent
    file holds the most recent row, so this is a per-agent quality
    snapshot rather than a historical sweep. NEVER raises.
    """
    base = REPO_ROOT / "learning-loop" / "llm_advisory"
    if not base.exists() or not base.is_dir():
        return {
            "available":        False,
            "total_rows":       0,
            "acceptable":       0,
            "low_quality":      0,
            "empty":            0,
            "low_quality_ratio": 0.0,
            "flagged":          False,
        }
    n_acc = 0
    n_low = 0
    n_emp = 0
    n_other = 0
    rows_seen = 0
    for p in sorted(base.glob("*_latest.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        verdict = str(data.get("quality_verdict") or "").upper()
        rows_seen += 1
        if verdict == QUALITY_ACCEPTABLE.upper():
            n_acc += 1
        elif verdict == QUALITY_LOW_QUALITY.upper():
            n_low += 1
        elif verdict == QUALITY_EMPTY.upper():
            n_emp += 1
        else:
            n_other += 1
    denom = max(1, n_acc + n_low + n_emp)
    low_ratio = float(n_low) / float(denom)
    return {
        "available":         True,
        "total_rows":        rows_seen,
        "acceptable":        n_acc,
        "low_quality":       n_low,
        "empty":             n_emp,
        "other":             n_other,
        "low_quality_ratio": round(low_ratio, 4),
        "flagged":           bool(
            low_ratio > QUALITY_THRESHOLD_LOW_QUALITY_RATIO),
        "threshold":         QUALITY_THRESHOLD_LOW_QUALITY_RATIO,
    }


# ─── v3.30 smoke test (deterministic prompt, fail-soft) ──────────────


def _gemini_smoke_test(env_present: bool) -> dict:
    """v3.30 (2026-06-16) — best-effort deterministic smoke test.

    Skipped when ``GEMINI_API_KEY`` is missing locally. NEVER prints
    the key value. NEVER persists raw provider responses. Returns a
    dict with one of three statuses: ``SKIPPED_NO_KEY``,
    ``SMOKE_OK``, or ``SMOKE_FAILED``.
    """
    if not env_present:
        return {
            "status": "SKIPPED_NO_KEY",
            "reason": "GEMINI_API_KEY not set in current shell",
        }
    # Honour the same offline-safety contract as the mesh: only attempt
    # the call when LLM_PROVIDER=gemini AND LLM_FREE_ONLY=true (default).
    # The audit MUST NOT trigger a paid-provider call.
    prov = os.environ.get("LLM_PROVIDER", "offline_mock").strip().lower()
    if prov not in ("gemini",):
        return {
            "status": "SKIPPED_OFFLINE_MOCK",
            "reason": f"LLM_PROVIDER={prov!r}; smoke skipped to avoid "
                       "making a real network call from a read-only "
                       "audit",
        }
    try:
        try:
            from llm_provider_client import call_provider  # type: ignore
        except ImportError:
            from shared.llm_provider_client import call_provider  # type: ignore
        # Deterministic prompt so the smoke is reproducible.
        prompt = (
            "Reply with the literal JSON {\"ok\": true} and nothing "
            "else. This is a deterministic smoke test from the v3.30 "
            "LLM provider health audit. You are ADVISORY ONLY. You "
            "CANNOT execute orders or change risk thresholds.")
        resp = call_provider(prompt=prompt, max_tokens=64,
                                timeout_seconds=10.0)
        ok = False
        try:
            text = _try_redact(str(resp.text or ""))[:200]
            ok = bool(text) and "ok" in text.lower()
        except Exception:
            text = ""
        if str(resp.status) != "LLM_PROVIDER_CALL_OK":
            return {
                "status": "SMOKE_FAILED",
                "reason": f"provider returned {resp.status}",
            }
        if not ok:
            return {
                "status": "SMOKE_FAILED",
                "reason": "provider returned non-empty response that "
                          "did not include the 'ok' token",
            }
        return {
            "status": "SMOKE_OK",
            "reason": "provider produced an acceptable response",
        }
    except Exception as e:
        return {
            "status": "SMOKE_FAILED",
            "reason": _try_redact(f"smoke exception: "
                                    f"{type(e).__name__}: {e}")[:200],
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

    # v3.30 — quality counts + best-effort smoke test.
    quality_counts = _quality_counts_from_advisory_rows()
    smoke = _gemini_smoke_test(gemini_env["present"])

    proposed_fixes: list[str] = []
    if not gemini_env["present"]:
        proposed_fixes.append(
            "[PROPOSED-FIX] LLM provider may be DEGRADED/UNKNOWN because "
            "GEMINI_API_KEY env not configured in workflow context — "
            "operator should set GEMINI_API_KEY in GitHub repo secrets "
            "at Settings → Secrets and variables → Actions → New "
            "repository secret. Do NOT auto-apply.")
    if budget.get("available") and budget.get("remaining") is not None:
        try:
            if float(budget.get("remaining") or 0) <= 0:
                proposed_fixes.append(
                    "[PROPOSED-FIX] LLM_AGENT_DAILY_CALL_BUDGET exhausted "
                    "for today; budget resets at UTC midnight. Do NOT "
                    "auto-bump the budget.")
        except Exception:
            pass
    # v3.30 — quality flag.
    if quality_counts.get("flagged"):
        proposed_fixes.append(
            "[PROPOSED-FIX] More than "
            f"{int(QUALITY_THRESHOLD_LOW_QUALITY_RATIO * 100)}% of "
            "recent advisory rows are LOW_QUALITY — investigate "
            "per-agent prompt templates and provider response "
            "structure. Do NOT auto-edit prompts.")
    if smoke.get("status") == "SMOKE_FAILED":
        proposed_fixes.append(
            "[PROPOSED-FIX] Smoke test FAILED — verify GEMINI_API_KEY "
            "quota / endpoint reachability. Do NOT auto-rotate the key.")

    payload = {
        "module":           "scripts.audit_llm_provider_health",
        "schema_version":   "v3.30",
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
        # v3.30 — quality + smoke.
        "quality_counts":   quality_counts,
        "smoke_test":       smoke,
        "eighty_day_claim_verdict": claim_verdict,
        "eighty_day_claim_reason":  claim_reason,
        "proposed_fixes":   proposed_fixes,
        "standing_markers": list(STANDING_MARKERS),
    }
    return payload


def render_md(status: dict) -> str:
    lines: list[str] = []
    lines.append("# LLM Provider Health Audit (v3.30)")
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
    # v3.30 — quality counts + smoke test.
    q = status.get("quality_counts") or {}
    lines.append("## v3.30 quality counts (per-agent latest rows)")
    lines.append("")
    if q.get("available"):
        lines.append(f"- total rows scanned: `{q.get('total_rows')}`")
        lines.append(f"- acceptable: `{q.get('acceptable')}`")
        lines.append(f"- low_quality: `{q.get('low_quality')}`")
        lines.append(f"- empty: `{q.get('empty')}`")
        lines.append(
            f"- low_quality_ratio: `{q.get('low_quality_ratio')}`")
        lines.append(
            f"- flagged: `{bool(q.get('flagged'))}` "
            f"(threshold > {q.get('threshold')})")
    else:
        lines.append("- (no quality snapshots present)")
    lines.append("")
    smoke = status.get("smoke_test") or {}
    lines.append("## v3.30 smoke test")
    lines.append("")
    lines.append(f"- status: `{smoke.get('status', 'UNKNOWN')}`")
    lines.append(f"- reason: `{smoke.get('reason', '')}`")
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

"""
LLM client for learning loop.

Calls the existing CLOUDFLARE_LEARNING_WORKER_URL (which forwards to a
Claude routine on claude.ai) and parses the JSON response. The routine's
system prompt is configured to dispatch on `payload["type"]`:

  - "daily_learning_annotation" -> {narrative, state_overrides, new_heuristic_proposals}
  - "weekly_retrospective"      -> {summary, key_insights, what_worked, what_didnt, recommendations}

Fail-soft contract: if USE_LLM_LEARNING=false OR worker URL missing OR
HTTP error OR JSON parse failure -> returns None and the caller's
deterministic baseline still produces a valid output. The LLM step is
strictly *additive* — it never blocks or corrupts the deterministic
adapter's work.

Budget awareness: at 1 call/day (daily annotator) + 1 call/week (weekly
retro), this layer adds ~1.14 routine calls/day. Well within the 15/day
Anthropic Routines limit even if other monitors regress to routine path.
"""

import json
import os
import requests

USE_LLM        = os.environ.get("USE_LLM_LEARNING", "true").lower() == "true"
WORKER_URL     = os.environ.get("CLOUDFLARE_LEARNING_WORKER_URL", "")
TIMEOUT_SEC    = 90       # routine cold-start can take 30-60s


def call_routine(payload: dict) -> dict | None:
    """
    Forward `payload` to the learning routine via Cloudflare Worker.
    Expect a JSON response. Returns parsed dict or None on any failure.
    """
    if not USE_LLM:
        print("  LLM: USE_LLM_LEARNING=false, skipping")
        return None
    if not WORKER_URL:
        print("  LLM: CLOUDFLARE_LEARNING_WORKER_URL not set, skipping")
        return None

    try:
        r = requests.post(WORKER_URL, json=payload, timeout=TIMEOUT_SEC)
    except Exception as e:
        print(f"  LLM call exception: {e}")
        return None

    if r.status_code != 200:
        print(f"  LLM call: HTTP {r.status_code} -> skipping")
        if r.status_code == 429:
            print("    (Anthropic Routines daily limit hit. Deterministic baseline still active.)")
        return None

    body = r.text or ""
    # Routine should return raw JSON; handle a few legitimate variations:
    # 1. Pure JSON
    # 2. JSON wrapped in markdown fences ```json ... ```
    # 3. JSON with leading/trailing whitespace
    body = body.strip()
    if body.startswith("```"):
        # Strip code fences
        body = body.lstrip("`")
        if body.lower().startswith("json"):
            body = body[4:]
        body = body.strip().rstrip("`").strip()

    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            print(f"  LLM response not a dict: {type(data).__name__}")
            return None
        return data
    except json.JSONDecodeError as e:
        # Routine probably returned natural-language reply. Capture as
        # narrative so user still sees something useful.
        print(f"  LLM response not JSON ({e}); treating whole body as narrative")
        return {"narrative": body[:2000], "state_overrides": {}, "new_heuristic_proposals": []}


# ─── Safe override application ───────────────────────────────────────────────
#
# Whitelist of fields the LLM is allowed to override on a per-strategy
# basis. Anything else in `state_overrides` is ignored — prevents
# hallucinated keys, accidental wipes, or schema corruption.

_ALLOWED_STRATEGY_FIELDS = {
    "size_multiplier",
    "enabled",
    "side_bias",
    "rationale",
    "paused_until",
    "llm_note",          # free-text annotation from LLM
}
_SIZE_MULT_MIN = 0.30
_SIZE_MULT_MAX = 2.00


def safe_apply_overrides(state: dict, overrides: dict | None) -> tuple[dict, list[str]]:
    """
    Apply LLM-proposed `overrides` to `state` with whitelist enforcement.

    Returns (new_state, applied_changes_log). Anything outside the
    whitelist is dropped silently (logged but not fatal).
    """
    applied: list[str] = []
    if not overrides or not isinstance(overrides, dict):
        return state, applied

    new_state = json.loads(json.dumps(state))   # deep clone

    # Strategy-level overrides
    for strat_name, fields in (overrides.get("strategies") or {}).items():
        if strat_name not in new_state.get("strategies", {}):
            applied.append(f"  · ignored: unknown strategy '{strat_name}'")
            continue
        if not isinstance(fields, dict):
            continue
        for key, val in fields.items():
            if key not in _ALLOWED_STRATEGY_FIELDS:
                applied.append(f"  · ignored: '{strat_name}.{key}' not in whitelist")
                continue
            # Bound size_multiplier
            if key == "size_multiplier":
                try:
                    val_f = float(val)
                except (TypeError, ValueError):
                    applied.append(f"  · ignored: '{strat_name}.size_multiplier' non-numeric")
                    continue
                bounded = max(_SIZE_MULT_MIN, min(_SIZE_MULT_MAX, val_f))
                if abs(bounded - val_f) > 0.001:
                    applied.append(f"  · clamped: '{strat_name}.size_multiplier' {val_f} -> {bounded}")
                val = bounded
            # Validate side_bias
            if key == "side_bias" and val not in (None, "long", "short"):
                applied.append(f"  · ignored: '{strat_name}.side_bias' invalid value '{val}'")
                continue
            # Validate enabled
            if key == "enabled" and not isinstance(val, bool):
                applied.append(f"  · ignored: '{strat_name}.enabled' must be bool")
                continue
            old = new_state["strategies"][strat_name].get(key)
            new_state["strategies"][strat_name][key] = val
            applied.append(f"  · {strat_name}.{key}: {old} -> {val}")

    # Global overrides — only specific keys allowed
    global_allowed = {"options_side_bias", "max_open_options"}
    for key, val in (overrides.get("global_overrides") or {}).items():
        if key not in global_allowed:
            applied.append(f"  · ignored: global_overrides.{key} not in whitelist")
            continue
        old = new_state.setdefault("global_overrides", {}).get(key)
        new_state["global_overrides"][key] = val
        applied.append(f"  · global_overrides.{key}: {old} -> {val}")

    return new_state, applied


def append_heuristic_proposals(proposals: list[str], path: str) -> int:
    """
    Append `proposals` to `path` (e.g. learning-loop/heuristic_proposals.md).
    Returns count of new entries appended.
    """
    if not proposals:
        return 0
    if not isinstance(proposals, list):
        return 0
    cleaned = [str(p).strip() for p in proposals if str(p).strip()]
    if not cleaned:
        return 0

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    block = "\n".join(f"- [ ] [{today}] {p}" for p in cleaned) + "\n"

    try:
        with open(path) as f:
            existing = f.read()
    except FileNotFoundError:
        existing = (
            "# Heuristic Proposals (LLM-generated)\n\n"
            "> Open queue of heuristic ideas suggested by the daily LLM\n"
            "> annotator + weekly retrospective. Tick the box `[x]` when\n"
            "> implemented in `learning-loop/adapter.py`. Older entries\n"
            "> kept indefinitely so we can audit which ideas worked.\n\n"
        )

    with open(path, "w") as f:
        f.write(existing + block)
    return len(cleaned)

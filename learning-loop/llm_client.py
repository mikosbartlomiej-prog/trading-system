"""
LLM client for learning loop.

Architecture (poll-based, free-tier-compatible):

The Anthropic Routines trigger endpoint is fire-and-forget — the POST
returns immediately with a `routine_fire` receipt and a session_id. The
actual model output is produced asynchronously inside the routine
session on claude.ai. Since Claude Code routines have repo write
access, we route the output back via git:

  1. analyzer / weekly_retro POST the payload to the Cloudflare Worker
     (which forwards to the routine trigger). Receipt comes back in
     <1s; this confirms the routine started.
  2. The routine, after producing its JSON, saves it to
     `learning-loop/pending-llm-{daily|weekly}.json` and runs
     `git add && git commit && git push` to the target branch.
  3. We poll `git fetch + git pull --ff-only` every 15 s for up to
     180 s, looking for the pending file. When found, we read it,
     `git rm` it (so the next workflow commit cleans up), and return
     the parsed dict.

Fail-soft contract: USE_LLM_LEARNING=false / no Worker URL / HTTP
error / poll timeout / JSON parse failure → returns None and the
deterministic baseline alone produces a complete, valid output.

Budget: 1 routine call/day (daily) + 1 call/week (weekly retro). Well
within the 15/day Anthropic Routines limit even if other monitors
regress to routine path.
"""

import json
import os
import subprocess
import time
import requests

USE_LLM            = os.environ.get("USE_LLM_LEARNING", "true").lower() == "true"
WORKER_URL         = os.environ.get("CLOUDFLARE_LEARNING_WORKER_URL", "")
TRIGGER_TIMEOUT_S  = 30        # POST is fire-and-forget; receipt comes back <1s
POLL_INTERVAL_S    = 15        # how often we git fetch + check for pending file
POLL_MAX_S         = 180       # max wait for routine to push its JSON
GIT_OP_TIMEOUT_S   = 30

LEARNING_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT    = os.path.abspath(os.path.join(LEARNING_DIR, ".."))


def _pending_path(payload_type: str) -> str:
    """Return the file path the routine is contracted to write."""
    name = "pending-llm-weekly.json" if payload_type == "weekly_retrospective" else "pending-llm-daily.json"
    return os.path.join(LEARNING_DIR, name)


def _git(args: list[str], check: bool = False, timeout: int = GIT_OP_TIMEOUT_S) -> tuple[int, str, str]:
    """Run `git` in REPO_ROOT and return (rc, stdout, stderr). Quiet on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", REPO_ROOT, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:
        return 1, "", str(e)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.returncode, r.stdout, r.stderr


def _current_branch() -> str:
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else "main"


def _git_pull(branch: str) -> bool:
    """Fetch + fast-forward pull. Quiet on failure."""
    rc, _, err = _git(["fetch", "origin", branch])
    if rc != 0:
        # Fetch can fail in test envs — not fatal
        return False
    rc, _, err = _git(["pull", "--ff-only", "origin", branch])
    if rc != 0:
        # Already up to date is fine (rc 0); only log unexpected
        if "already up to date" not in err.lower():
            return False
    return True


def call_routine(payload: dict) -> dict | None:
    """
    Trigger the learning routine and wait for its JSON output to appear
    as a committed file in the repo.

    The routine system prompt (`routine-prompts.md`) instructs the LLM
    to save its JSON to `learning-loop/pending-llm-{daily|weekly}.json`
    and `git push` to `payload.target_branch`. We poll for that file
    here and consume it (`git rm`) so the workflow's final commit
    cleans up automatically.

    Returns parsed dict on success, None on any failure (fail-soft).
    """
    if not USE_LLM:
        print("  LLM: USE_LLM_LEARNING=false, skipping")
        return None
    if not WORKER_URL:
        print("  LLM: CLOUDFLARE_LEARNING_WORKER_URL not set, skipping")
        return None

    payload_type = payload.get("type", "daily_learning_annotation")
    pending_path = _pending_path(payload_type)
    branch       = payload.get("target_branch") or _current_branch()

    # git author identity — needed if analyzer pulls / commits before workflow's
    # final step sets it. Idempotent; failures are non-fatal.
    _git(["config", "user.name",  "github-actions[bot]"])
    _git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    # Clear any stale pending file from a prior run that wasn't consumed.
    if os.path.exists(pending_path):
        print(f"  LLM: removing stale {os.path.basename(pending_path)} before new run")
        try:
            _git(["rm", "-f", "--ignore-unmatch", os.path.relpath(pending_path, REPO_ROOT)])
            if os.path.exists(pending_path):
                os.remove(pending_path)
        except Exception:
            pass

    # 1) Fire trigger
    try:
        r = requests.post(WORKER_URL, json=payload, timeout=TRIGGER_TIMEOUT_S)
    except Exception as e:
        print(f"  LLM trigger exception: {e}")
        return None

    if r.status_code != 200:
        print(f"  LLM trigger: HTTP {r.status_code} -> skipping")
        if r.status_code == 429:
            print("    (Anthropic Routines daily limit hit. Deterministic baseline still active.)")
        return None

    receipt_preview = (r.text or "").strip()[:200]
    print(f"  LLM trigger fired (receipt: {receipt_preview})")
    print(f"  Polling origin/{branch} for {os.path.basename(pending_path)} (max {POLL_MAX_S}s)...")

    # 2) Poll for the routine's commit
    start = time.monotonic()
    while True:
        time.sleep(POLL_INTERVAL_S)
        elapsed = time.monotonic() - start
        if elapsed > POLL_MAX_S:
            print(f"  LLM: timeout after {elapsed:.0f}s — falling back to deterministic")
            return None

        _git_pull(branch)

        if os.path.exists(pending_path):
            print(f"  LLM: found {os.path.basename(pending_path)} after {elapsed:.0f}s")
            try:
                with open(pending_path) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"  LLM: pending file unreadable ({e}) — falling back to deterministic")
                return None

            if not isinstance(data, dict):
                print(f"  LLM: pending file not a dict ({type(data).__name__}) — falling back")
                return None

            # Remove the file from working tree; stage the deletion so the
            # workflow's final commit cleans it up. The workflow also runs
            # `git add -u learning-loop/` as a safety net, so even if git rm
            # below fails (e.g. file untracked locally for some reason), the
            # deletion still lands in the final commit.
            try:
                os.remove(pending_path)
            except FileNotFoundError:
                pass
            _git(["rm", "-f", "--ignore-unmatch", os.path.relpath(pending_path, REPO_ROOT)])
            print(f"  LLM: consumed + removed {os.path.basename(pending_path)}")
            return data

        print(f"  LLM: not yet ({elapsed:.0f}s / {POLL_MAX_S}s)")


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

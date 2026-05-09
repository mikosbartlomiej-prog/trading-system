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
# Max wait for routine to push its JSON. Calibrated from observed runs:
# 2026-05-08 first manual: 139 s. 2026-05-09 manual #1 (post auto-merge):
# 247 s. 2026-05-09 manual #2: 325 s (race — file arrived 25 s after the
# prior 300 s timeout fired). Bumped 180->300->480 to give 2x headroom
# over worst observed. Workflow's timeout-minutes is 10, so 480 still
# leaves ~2 min for git ops + commit.
POLL_MAX_S         = 480
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

    # Pull session URL out of the trigger receipt for post-hoc debugging
    # when polling times out — operator can open the URL on claude.ai
    # to see what the routine actually did.
    receipt_text = (r.text or "").strip()
    session_url = ""
    try:
        receipt = json.loads(receipt_text)
        if isinstance(receipt, dict):
            session_url = receipt.get("claude_code_session_url", "") or ""
    except json.JSONDecodeError:
        pass
    print(f"  LLM trigger fired (receipt: {receipt_text[:200]})")
    if session_url:
        print(f"  LLM session URL (debug if timeout): {session_url}")
    print(f"  Polling origin/{branch} for {os.path.basename(pending_path)} (max {POLL_MAX_S}s)...")

    # 2) Poll for the routine's commit
    start = time.monotonic()
    while True:
        time.sleep(POLL_INTERVAL_S)
        elapsed = time.monotonic() - start
        if elapsed > POLL_MAX_S:
            # Last-chance pickup: routine has been observed pushing 25 s
            # after our timeout (race when both auto-merge.yml and our
            # poll fire near the boundary). One final 30 s grace check
            # before returning None — costs at most 30 s on the failure
            # path, saves the run when routine is just-barely-late.
            print(f"  LLM: poll budget exhausted at {elapsed:.0f}s — "
                  f"giving routine one last 30s grace period before falling back")
            time.sleep(30)
            _git_pull(branch)
            if os.path.exists(pending_path):
                print(f"  LLM: GRACE PICKUP — found {os.path.basename(pending_path)} "
                      f"after {(time.monotonic() - start):.0f}s total")
                # Drop into the consume path below by NOT returning here
            else:
                print(f"  LLM: timeout after {(time.monotonic() - start):.0f}s "
                      f"(incl. 30s grace) — falling back to deterministic")
                return None

        if not os.path.exists(pending_path):
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


def route_proposals(proposals: list, base_branch: str = "main") -> dict:
    """
    Route LLM-proposed heuristics into the three lanes:

      - Lane 2 (auto_pr): create a PR via `lane2_pr.create_pr_from_proposal`.
        Max 1 per run — additional auto_pr proposals are bumped to Lane 3.
      - Lane 3 (backlog): append a structured entry to heuristic_proposals.md
        with title / risk / effort / revisit / sketch.
      - Old format (plain string): treated as Lane 3 with minimal metadata.

    Returns a dict summary:
      {
        "auto_pr_attempted": bool,
        "auto_pr_url": str | None,
        "backlog_added": int,
        "rejected": [reasons...],
      }

    Errors are caught per-proposal — a single bad proposal does NOT block
    the rest. PR creation failures fall back to backlog (so the proposal
    isn't lost).
    """
    summary = {
        "auto_pr_attempted": False,
        "auto_pr_url":       None,
        "backlog_added":     0,
        "rejected":          [],
    }
    if not isinstance(proposals, list) or not proposals:
        return summary

    # Lazy-import lane2_pr — keeps llm_client.py importable in test envs
    # where git/gh aren't configured.
    try:
        from lane2_pr import create_pr_from_proposal
    except ImportError as e:
        print(f"  Lane2: import error ({e}); all proposals routed to backlog")
        create_pr_from_proposal = None

    auto_pr_done = False
    backlog_lines: list[str] = []

    for idx, p in enumerate(proposals):
        # Old format — plain string
        if isinstance(p, str):
            backlog_lines.append({"title": p.strip(), "lane": "backlog"})
            continue

        if not isinstance(p, dict):
            summary["rejected"].append(f"#{idx}: not str/dict ({type(p).__name__})")
            continue

        lane = (p.get("lane") or "backlog").lower()
        title = (p.get("title") or "").strip()
        if not title:
            summary["rejected"].append(f"#{idx}: empty title")
            continue

        if lane == "auto_pr" and not auto_pr_done and create_pr_from_proposal:
            summary["auto_pr_attempted"] = True
            url = create_pr_from_proposal(p, base_branch=base_branch)
            if url:
                summary["auto_pr_url"] = url
                auto_pr_done = True
                continue  # don't also add to backlog
            else:
                # PR creation failed (validation, tests, gh, etc.) —
                # fall through and put this proposal in backlog so the
                # idea isn't lost.
                p_copy = dict(p)
                p_copy["lane"] = "backlog"
                p_copy.setdefault("rationale",
                    "(originally lane=auto_pr; PR creation failed — see workflow log)")
                backlog_lines.append(p_copy)
                continue

        # Lane 3 — backlog
        backlog_lines.append(p)

    if backlog_lines:
        summary["backlog_added"] = _append_structured_proposals(backlog_lines)

    return summary


def _append_structured_proposals(props: list) -> int:
    """Write proposals to heuristic_proposals.md in structured form."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()

    HEURISTIC_PROPOSALS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "heuristic_proposals.md",
    )

    blocks: list[str] = []
    for p in props:
        if isinstance(p, str):
            blocks.append(f"- [ ] [{today}] {p}")
            continue
        if not isinstance(p, dict):
            continue
        title  = p.get("title", "(no title)")
        risk   = p.get("risk", "?")
        effort = p.get("effort_estimate") or "?"
        revisit = p.get("revisit_date") or "no specific date"
        rationale = p.get("rationale", "")
        sketch    = p.get("implementation_sketch", "")

        b = f"- [ ] [{today}] **{title}** _(risk: {risk}, effort: {effort}, revisit: {revisit})_"
        if rationale:
            b += f"\n  - **Rationale:** {rationale}"
        if sketch:
            b += f"\n  - **Sketch:** {sketch}"
        blocks.append(b)

    if not blocks:
        return 0

    block_text = "\n".join(blocks) + "\n"

    try:
        with open(HEURISTIC_PROPOSALS_PATH) as f:
            existing = f.read()
    except FileNotFoundError:
        existing = (
            "# Heuristic Proposals (LLM-generated)\n\n"
            "> Open queue of heuristic ideas suggested by the daily LLM\n"
            "> annotator + weekly retrospective. Tick the box `[x]` when\n"
            "> implemented in `learning-loop/adapter.py`. Older entries\n"
            "> kept indefinitely so we can audit which ideas worked.\n\n"
            "> **Three-lane architecture (v2.3.2):** lane=auto_pr proposals\n"
            "> get a PR opened automatically; only lane=backlog and old-format\n"
            "> string proposals land here. See STRATEGY.md §5.6.\n\n"
        )

    with open(HEURISTIC_PROPOSALS_PATH, "w") as f:
        f.write(existing + block_text)
    return len(blocks)


def append_heuristic_proposals(proposals: list, path: str) -> int:
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

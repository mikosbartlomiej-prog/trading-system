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

# LLM toggle (spec §A.1): LLM_ENABLED is the canonical kill switch. Default
# is false — deterministic execution must work without LLM. The old
# USE_LLM_LEARNING env is honoured as a fallback for backward compatibility,
# but LLM_ENABLED wins when both are set.
def _llm_is_enabled() -> bool:
    raw = os.environ.get("LLM_ENABLED")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    # Legacy fallback. Note default flipped to FALSE per spec §A.1.
    raw = os.environ.get("USE_LLM_LEARNING")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return False


USE_LLM            = _llm_is_enabled()
WORKER_URL         = os.environ.get("CLOUDFLARE_LEARNING_WORKER_URL", "")
CHALLENGER_WORKER_URL = os.environ.get("CLOUDFLARE_LEARNING_CHALLENGER_WORKER_URL", "")
TRIGGER_TIMEOUT_S  = 30        # POST is fire-and-forget; receipt comes back <1s
POLL_INTERVAL_S    = 15        # how often we git fetch + check for pending file
# Max wait for routine to push its JSON. Calibrated from observed runs:
# 2026-05-08 first manual: 139 s. 2026-05-09 manual #1 (post auto-merge):
# 247 s. 2026-05-09 manual #2: 325 s (race — file arrived 25 s after the
# prior 300 s timeout fired). Bumped 180->300->480 to give 2x headroom
# over worst observed. With 3-round daily dialog the workflow's
# timeout-minutes is bumped to 30 so each leg gets a full 480 s budget.
POLL_MAX_S         = 480
GIT_OP_TIMEOUT_S   = 30

LEARNING_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT    = os.path.abspath(os.path.join(LEARNING_DIR, ".."))


# Per-payload-type → contracted output filename. Matches routine-prompts.md
# (Senior PM) and challenger-prompts.md.
_PENDING_FILES = {
    "daily_learning_annotation": "pending-llm-daily-draft1.json",
    "challenger_review":         "pending-llm-daily-challenge.json",
    "daily_revise":              "pending-llm-daily.json",
    "weekly_retrospective":      "pending-llm-weekly.json",
}


def _pending_path(payload_type: str) -> str:
    """Return the file path the routine is contracted to write."""
    name = _PENDING_FILES.get(payload_type, "pending-llm-daily.json")
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


# Map (payload_type, is_challenger_worker) → routine_name + priority.
# Used to resolve a stable routine identity for the budget tracker so
# tier caps work correctly regardless of which helper invokes us.
_ROUTINE_NAME_MAP = {
    ("daily_learning_annotation", False): ("daily-learning-pm",          "P0_essential"),
    ("challenger_review",         True):  ("daily-learning-challenger", "P0_essential"),
    ("daily_revise",              False): ("daily-learning-revise",     "P0_essential"),
    ("weekly_retrospective",      False): ("weekly-retro-pm",           "P1_important"),
    ("weekly_retrospective",      True):  ("weekly-retro-challenger",   "P1_important"),
    ("weekly_revise",             False): ("weekly-retro-revise",       "P1_important"),
}


def _resolve_routine_identity(payload_type: str, target_url: str) -> tuple[str, str]:
    """Return (routine_name, priority) for the budget tracker."""
    is_challenger = bool(target_url) and target_url == CHALLENGER_WORKER_URL
    key = (payload_type, is_challenger)
    if key in _ROUTINE_NAME_MAP:
        return _ROUTINE_NAME_MAP[key]
    # Unknown type defaults to P1 important (conservative — could be a new
    # call site; we'd rather throttle than starve, since P1 has more
    # headroom than P2).
    return (f"unknown-{payload_type}", "P1_important")


def call_routine(payload: dict, worker_url: str | None = None,
                 routine_name: str | None = None,
                 priority: str | None = None) -> dict | None:
    """
    Trigger the learning routine and wait for its JSON output to appear
    as a committed file in the repo.

    The routine system prompt (`routine-prompts.md` for Senior PM,
    `challenger-prompts.md` for Challenger) instructs the LLM to save
    its JSON to a per-type file and `git push` to `payload.target_branch`
    with the `[automerge]` tag. We poll for that file here and consume
    it (`git rm`) so the workflow's final commit cleans up automatically.

    `worker_url` selects which Cloudflare Worker (and therefore which
    routine) to invoke. Defaults to the Senior PM worker
    (`CLOUDFLARE_LEARNING_WORKER_URL`).

    `routine_name` / `priority` are passed to the budget tracker. Default
    resolution uses (payload_type, worker_url) lookup.

    Returns parsed dict on success, None on any failure (fail-soft).
    """
    if not USE_LLM:
        print("  LLM: USE_LLM_LEARNING=false, skipping")
        return None
    target_url = worker_url if worker_url is not None else WORKER_URL
    if not target_url:
        print("  LLM: worker URL not set, skipping")
        return None

    payload_type = payload.get("type", "daily_learning_annotation")
    pending_path = _pending_path(payload_type)
    branch       = payload.get("target_branch") or _current_branch()

    # Anthropic Routines daily budget gate. Resolves routine identity
    # from (payload_type, worker_url), checks tier + total caps,
    # records the call on ALLOW. Fail-soft if budget module unavailable.
    if routine_name is None or priority is None:
        rname, rprio = _resolve_routine_identity(payload_type, target_url)
        routine_name = routine_name or rname
        priority     = priority or rprio
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from routine_budget import check_and_record as _budget_check
        ok, b_reason, _b_state = _budget_check(routine_name, priority=priority)
        if not ok:
            print(f"  LLM: routine budget gate BLOCK ({routine_name}/{priority}) — {b_reason}")
            return None
        print(f"  LLM: routine budget OK ({routine_name}/{priority}) — {b_reason}")
    except Exception as e:
        # Fail-soft: budget tracking must never break the call path.
        print(f"  LLM: routine budget unavailable ({type(e).__name__}: {e}) — proceeding")

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
        r = requests.post(target_url, json=payload, timeout=TRIGGER_TIMEOUT_S)
    except Exception as e:
        print(f"  LLM trigger exception: {e}")
        return None

    if r.status_code != 200:
        print(f"  LLM trigger: HTTP {r.status_code} -> skipping")
        if r.status_code == 429:
            # v3.8.5 (2026-05-16): parse Retry-After header so operator can
            # see when Anthropic's rolling window clears. 3 days of 429 at
            # 21:00 UTC was the reason daily-learning was moved to 04:00 UTC.
            retry_after = r.headers.get("Retry-After") or r.headers.get("retry-after")
            anthropic_reset = (
                r.headers.get("anthropic-ratelimit-requests-reset")
                or r.headers.get("x-ratelimit-reset")
                or r.headers.get("ratelimit-reset")
            )
            print("    (Anthropic Routines daily limit hit. Deterministic baseline still active.)")
            if retry_after:
                print(f"    Retry-After: {retry_after} seconds")
            if anthropic_reset:
                print(f"    Rolling window reset: {anthropic_reset}")
            # If response body has helpful info, surface a snippet for debugging.
            body_snippet = (r.text or "")[:240].replace("\n", " ")
            if body_snippet:
                print(f"    Body: {body_snippet}")
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


# ─── 3-round daily dialog wrappers ───────────────────────────────────────────
#
# Daily flow (replaces single call_routine in the analyzer):
#
#   1. call_senior_pm_round1(payload)   -> draft analysis (Senior PM routine)
#   2. call_challenger(payload)         -> critique     (Challenger routine)
#   3. call_senior_pm_revise(payload)   -> revised final (Senior PM routine)
#
# Each leg is fail-soft: if any returns None, the analyzer must use the
# best partial product available (see analyzer.py orchestration).


def call_senior_pm_round1(payload: dict) -> dict | None:
    """
    Round 1 — Senior PM produces draft analysis.

    Payload type MUST be `daily_learning_annotation`. Output lands in
    `pending-llm-daily-draft1.json` (NOT the analyzer-consumed file).
    """
    payload = dict(payload)
    payload["type"] = "daily_learning_annotation"
    return call_routine(payload, worker_url=WORKER_URL)


def call_challenger(payload: dict) -> dict | None:
    """
    Round 2 — Challenger critiques Senior PM's draft.

    Payload shape (per challenger-prompts.md):
      {
        "type": "challenger_review",
        "today_stats": {...},
        "senior_pm_draft": {...round 1 output...},
        "target_branch": "..."
      }

    Output lands in `pending-llm-daily-challenge.json`. Returns None if
    the Challenger Worker URL isn't configured (fail-soft → round 3
    skipped, round 1 applied directly).
    """
    if not CHALLENGER_WORKER_URL:
        print("  LLM Challenger: CLOUDFLARE_LEARNING_CHALLENGER_WORKER_URL "
              "not set, skipping critique step")
        return None
    payload = dict(payload)
    payload["type"] = "challenger_review"
    return call_routine(payload, worker_url=CHALLENGER_WORKER_URL)


def call_senior_pm_revise(payload: dict) -> dict | None:
    """
    Round 3 — Senior PM reads Challenger's critique and produces FINAL
    revised analysis.

    Payload shape (per routine-prompts.md TYPE 3):
      {
        "type": "daily_revise",
        "today_stats": {...},
        "your_previous_draft": {...round 1 output...},
        "challenger_critique": {...round 2 output...},
        "target_branch": "..."
      }

    Output lands in `pending-llm-daily.json` — this is the file the
    analyzer ultimately consumes for state_overrides + heuristic
    proposals + narrative.
    """
    payload = dict(payload)
    payload["type"] = "daily_revise"
    return call_routine(payload, worker_url=WORKER_URL)


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

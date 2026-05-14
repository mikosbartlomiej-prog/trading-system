"""
Reddit Signal Curator — LLM client (poll-based, fail-soft)

Wraps the `Reddit Signal Curator` claude.ai routine. Wywoływany przez
`monitor.py::run_scan()` POMIĘDZY `detect_spike_signals()` (zbiera
kandydatów) a `_emit_signal()` (faktycznie wysyła trade).

Architektura identyczna jak `learning-loop/llm_client.py`:
  1. POST payload do Cloudflare Worker `reddit-curator-proxy`
     → Worker forwards do routine trigger
     → Trigger zwraca receipt <1s, routine startuje async
  2. Routine produces JSON, self-commits do
     `reddit-monitor/pending-curation.json` z [automerge] tagiem
  3. Tutaj polling git fetch + check for pending file (max 90s — Curator
     to prosty filter, nie wymaga deep reasoning, więc krótszy timeout
     niż learning-loop)
  4. Read + git rm + return parsed dict

Fail-soft kontrakt:
  USE_REDDIT_CURATOR=false       → return None, monitor uses heuristic
  CLOUDFLARE_REDDIT_CURATOR_*=""  → return None, monitor uses heuristic
  HTTP error                      → return None
  Poll timeout                    → return None
  JSON parse failure              → return None

Monitor.py treats None as "no LLM input" and falls back to heuristic
top-N (current pre-LLM behavior). Pipeline NEVER breaks on LLM failure.

Budget: most days have 0 candidates (no spike → no LLM call). On busy
days expect 1-3 calls. Combined with learning-loop usage (3-4/day) +
weekly-retro (1/7) we stay well within Anthropic Routines 15/day limit.
"""

import json
import os
import subprocess
import time
import requests

USE_CURATOR        = os.environ.get("USE_REDDIT_CURATOR", "true").lower() == "true"
WORKER_URL         = os.environ.get("CLOUDFLARE_REDDIT_CURATOR_WORKER_URL", "")
TRIGGER_TIMEOUT_S  = 30
POLL_INTERVAL_S    = 10                 # tighter than learning-loop (Curator faster)
POLL_MAX_S         = 90                 # 90s budget — Curator should respond <60s typically
GIT_OP_TIMEOUT_S   = 30

REDDIT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.abspath(os.path.join(REDDIT_DIR, ".."))
PENDING_PATH = os.path.join(REDDIT_DIR, "pending-curation.json")


def _git(args: list[str], timeout: int = GIT_OP_TIMEOUT_S) -> tuple[int, str, str]:
    """Run `git` in REPO_ROOT and return (rc, stdout, stderr). Quiet on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", REPO_ROOT, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def _current_branch() -> str:
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else "main"


def _git_pull(branch: str) -> bool:
    """Fetch + fast-forward pull. Quiet on failure."""
    rc, _, _ = _git(["fetch", "origin", branch])
    if rc != 0:
        return False
    _git(["pull", "--ff-only", "origin", branch])
    return True


def curate(candidates: list[dict], account_context: dict) -> dict | None:
    """
    Send candidates to Curator routine, poll for response, return parsed
    output. Returns None on any failure (fail-soft).

    Caller should treat None as "use heuristic fallback".

    `candidates` shape per curator-prompts.md INPUT spec — list of
    dicts with ticker / lane / side / skew / mentions / spike_ratio /
    best_post_url / etc.

    `account_context` shape per curator-prompts.md — equity /
    daily_pl_pct / open_positions / vix etc.
    """
    if not USE_CURATOR:
        print("  Curator: USE_REDDIT_CURATOR=false, skipping (heuristic fallback)")
        return None
    if not WORKER_URL:
        print("  Curator: CLOUDFLARE_REDDIT_CURATOR_WORKER_URL not set, "
              "skipping (heuristic fallback)")
        return None
    if not candidates:
        print("  Curator: 0 candidates — no point calling LLM")
        return None

    # Anthropic Routines daily budget gate (P2 optional tier). Reddit
    # Curator is fail-soft by design — caller already handles None via
    # heuristic fallback when budget exhausted.
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
        from routine_budget import check_and_record as _budget_check
        ok, b_reason, _b_state = _budget_check("reddit-curator", priority="P2_optional")
        if not ok:
            print(f"  Curator: routine budget BLOCK — {b_reason} → heuristic fallback")
            return None
        print(f"  Curator: routine budget OK — {b_reason}")
    except Exception as e:
        print(f"  Curator: routine budget unavailable ({type(e).__name__}: {e}) — proceeding")

    branch = os.environ.get("GITHUB_REF_NAME") or _current_branch()
    payload = {
        "type":            "reddit_curate",
        "as_of":           _utcnow(),
        "account_context": account_context,
        "candidates":      candidates,
        "target_branch":   branch,
    }

    # git author identity (idempotent)
    _git(["config", "user.name",  "github-actions[bot]"])
    _git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    # Clear any stale pending file
    if os.path.exists(PENDING_PATH):
        try:
            _git(["rm", "-f", "--ignore-unmatch",
                  os.path.relpath(PENDING_PATH, REPO_ROOT)])
            if os.path.exists(PENDING_PATH):
                os.remove(PENDING_PATH)
        except Exception:
            pass

    # 1) Fire trigger
    try:
        r = requests.post(WORKER_URL, json=payload, timeout=TRIGGER_TIMEOUT_S)
    except Exception as e:
        print(f"  Curator trigger exception: {e}")
        return None

    if r.status_code != 200:
        print(f"  Curator trigger: HTTP {r.status_code} -> heuristic fallback")
        if r.status_code == 429:
            print(f"    (Anthropic Routines daily limit hit.)")
        return None

    # Pull session URL for debugging
    receipt_text = (r.text or "").strip()
    session_url = ""
    try:
        receipt = json.loads(receipt_text)
        if isinstance(receipt, dict):
            session_url = receipt.get("claude_code_session_url", "") or ""
    except json.JSONDecodeError:
        pass
    print(f"  Curator triggered ({len(candidates)} candidates, polling max {POLL_MAX_S}s)")
    if session_url:
        print(f"    debug session: {session_url}")

    # 2) Poll for committed file
    start = time.monotonic()
    while True:
        time.sleep(POLL_INTERVAL_S)
        elapsed = time.monotonic() - start
        if elapsed > POLL_MAX_S:
            print(f"  Curator: timeout after {elapsed:.0f}s -> heuristic fallback")
            return None

        if not os.path.exists(PENDING_PATH):
            _git_pull(branch)

        if os.path.exists(PENDING_PATH):
            print(f"  Curator: response received after {elapsed:.0f}s")
            try:
                with open(PENDING_PATH) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"  Curator: pending file unreadable ({e}) -> heuristic fallback")
                return None

            if not isinstance(data, dict):
                return None

            # Consume — remove from working tree and stage deletion
            try:
                os.remove(PENDING_PATH)
            except FileNotFoundError:
                pass
            _git(["rm", "-f", "--ignore-unmatch",
                  os.path.relpath(PENDING_PATH, REPO_ROOT)])
            return data


def filter_signals_via_curator(signals: list[dict], curator_output: dict
                                ) -> list[dict]:
    """
    Apply curator's `selected_signals` to filter / re-prioritize the raw
    signal list. Curator picks 0-3 tickers; we return only those, with
    `size_multiplier` and `curator_rationale` fields injected.

    If curator_output is None or has no selected_signals, returns original
    signals unchanged (caller handles fallback).
    """
    if not curator_output or not isinstance(curator_output, dict):
        return signals

    selected = curator_output.get("selected_signals") or []
    if not isinstance(selected, list):
        return signals

    # Build lookup of curator's picks by (ticker, lane)
    picks: dict[tuple, dict] = {}
    for entry in selected:
        if not isinstance(entry, dict):
            continue
        t = entry.get("ticker", "")
        lane = entry.get("lane", "sub")
        if t:
            picks[(t.upper(), lane)] = entry

    if not picks:
        return []   # Curator explicitly picked nothing — emit nothing

    out = []
    for sig in signals:
        key = (sig.get("ticker", "").upper(), sig.get("lane", "sub"))
        pick = picks.get(key)
        if not pick:
            continue
        enriched = dict(sig)
        # LLM size override (clamped 0.5-1.5)
        try:
            mult = float(pick.get("size_multiplier", 1.0))
            mult = max(0.5, min(1.5, mult))
        except (TypeError, ValueError):
            mult = 1.0
        enriched["curator_size_multiplier"] = mult
        enriched["size_usd"] = round(sig.get("size_usd", 0) * mult, 2)
        enriched["curator_conviction"] = pick.get("conviction", "?")
        enriched["curator_rationale"]  = pick.get("rationale", "")
        enriched["curator_horizon"]    = pick.get("expected_horizon", "?")
        enriched["curator_key_risk"]   = pick.get("key_risk", "")
        out.append(enriched)

    # Preserve curator's order (they ranked by conviction)
    selected_order = {(e.get("ticker", "").upper(), e.get("lane", "sub")): i
                      for i, e in enumerate(selected) if isinstance(e, dict)}
    out.sort(key=lambda s: selected_order.get(
        (s.get("ticker", "").upper(), s.get("lane", "sub")),
        999,
    ))
    return out


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

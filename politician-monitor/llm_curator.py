"""
Capitol Trader Curator — LLM client (poll-based, fail-soft).

Wraps the `politician-monitor-curator` claude.ai routine. Called by
`monitor.py::run_scan()` after `collect_candidates()` (Form 4 + STOCK
Act PTRs filtered by whitelist + brackets) and before `emit_signals()`.

Architecture mirrors `reddit-monitor/llm_curator.py`:
  1. POST payload do Cloudflare Worker `politician-curator-proxy`
     → Worker forwards do routine trigger
     → Trigger zwraca receipt <1s, routine startuje async
  2. Routine produces JSON, self-commits do
     `politician-monitor/pending-curation.json` z [automerge] tagiem
  3. Poll git fetch + check for pending file (max 90s)
  4. Read + git rm + return parsed dict

Fail-soft contract:
  USE_POLITICIAN_CURATOR=false       → return None, monitor uses heuristic
  CLOUDFLARE_POLITICIAN_*_URL=""     → return None, monitor uses heuristic
  HTTP error                          → return None
  Poll timeout                        → return None
  JSON parse failure                  → return None
  Routine budget P2 exhausted         → return None

Monitor.py treats None as "no LLM input" — falls back to deterministic
selection (highest-weight + cluster-bonus). Pipeline NEVER breaks on
LLM failure.

Budget: low-volume — typically 0-2 calls/day (most scans have 0 new
disclosures since last poll). Shares P2_optional tier with reddit,
crypto, twitter curators (cap 4).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests


USE_CURATOR        = os.environ.get("USE_POLITICIAN_CURATOR", "true").lower() == "true"
WORKER_URL         = os.environ.get("CLOUDFLARE_POLITICIAN_CURATOR_WORKER_URL", "")
TRIGGER_TIMEOUT_S  = 30
POLL_INTERVAL_S    = 10
POLL_MAX_S         = 90
GIT_OP_TIMEOUT_S   = 30

MONITOR_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.abspath(os.path.join(MONITOR_DIR, ".."))
PENDING_PATH = os.path.join(MONITOR_DIR, "pending-curation.json")


def _git(args: list, timeout: int = GIT_OP_TIMEOUT_S):
    """Run git in REPO_ROOT. Returns (rc, stdout, stderr); quiet on failure."""
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
    rc, _, _ = _git(["fetch", "origin", branch])
    if rc != 0:
        return False
    _git(["pull", "--ff-only", "origin", branch])
    return True


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def curate(candidates: list, cluster_hints: list,
            account_context: dict) -> Optional[dict]:
    """
    Send candidates + cluster hints to Curator routine, poll for response,
    return parsed output. Returns None on any failure (fail-soft).

    Caller should treat None as "use heuristic fallback" (e.g. emit
    top-N by weight × score).

    `candidates` shape per curator-prompts.md INPUT spec — list of dicts
    with politician/ticker/side/bracket/dates etc.
    `cluster_hints` — list of cluster dicts with sector/tickers/count.
    `account_context` — equity/daily_pl_pct/open_positions/vix/regime.
    """
    if not USE_CURATOR:
        print("  Curator: USE_POLITICIAN_CURATOR=false, skipping (heuristic fallback)")
        return None
    if not WORKER_URL:
        print("  Curator: CLOUDFLARE_POLITICIAN_CURATOR_WORKER_URL not set, "
              "skipping (heuristic fallback)")
        return None
    if not candidates and not cluster_hints:
        print("  Curator: 0 candidates + 0 clusters → no point calling LLM")
        return None

    # Anthropic Routines daily budget gate (P2 optional tier).
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
        from routine_budget import check_and_record as _budget_check
        ok, b_reason, _b_state = _budget_check(
            "politician-curator", priority="P2_optional"
        )
        if not ok:
            print(f"  Curator: routine budget BLOCK — {b_reason} → heuristic fallback")
            return None
        print(f"  Curator: routine budget OK — {b_reason}")
    except Exception as e:
        print(f"  Curator: routine budget unavailable ({type(e).__name__}: {e}) — proceeding")

    branch = os.environ.get("GITHUB_REF_NAME") or _current_branch()
    payload = {
        "type":            "politician_curate",
        "as_of":           _utcnow(),
        "account_context": account_context,
        "candidates":      candidates,
        "cluster_hints":   cluster_hints,
        "target_branch":   branch,
    }

    _git(["config", "user.name",  "github-actions[bot]"])
    _git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    # Clear stale pending file
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
        print(f"  Curator trigger: HTTP {r.status_code} → heuristic fallback")
        if r.status_code == 429:
            print(f"    (Anthropic Routines daily limit hit.)")
        return None

    receipt_text = (r.text or "").strip()
    session_url = ""
    try:
        receipt = json.loads(receipt_text)
        if isinstance(receipt, dict):
            session_url = receipt.get("claude_code_session_url", "") or ""
    except json.JSONDecodeError:
        pass
    print(f"  Curator triggered ({len(candidates)} candidates + "
          f"{len(cluster_hints)} clusters, polling max {POLL_MAX_S}s)")
    if session_url:
        print(f"    debug session: {session_url}")

    # 2) Poll for committed file
    start = time.monotonic()
    while True:
        time.sleep(POLL_INTERVAL_S)
        elapsed = time.monotonic() - start
        if elapsed > POLL_MAX_S:
            print(f"  Curator: timeout after {elapsed:.0f}s → heuristic fallback")
            return None

        if not os.path.exists(PENDING_PATH):
            _git_pull(branch)

        if os.path.exists(PENDING_PATH):
            print(f"  Curator: response received after {elapsed:.0f}s")
            try:
                with open(PENDING_PATH) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"  Curator: pending file unreadable ({e}) → heuristic fallback")
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


def filter_signals_via_curator(signals: list, curator_output: Optional[dict]
                                ) -> list:
    """
    Apply curator's `selected_signals` to filter / re-prioritize the raw
    candidate list. Curator picks 0-3 tickers/ETFs; we return only those
    with `size_multiplier`, `curator_rationale`, `conviction`, `score`,
    `key_risk`, `expected_horizon` injected.

    If curator_output is None or has no selected_signals, returns []
    (caller falls back to heuristic — which is fine since most scans
    should produce zero emissions).
    """
    if not curator_output or not isinstance(curator_output, dict):
        return []

    selected = curator_output.get("selected_signals") or []
    if not isinstance(selected, list):
        return []

    # Curator's selection is the source of truth — build new signals
    # directly from it (not by filtering raw candidates). This lets
    # Curator emit ETF proxies (ITA from defense cluster) that may
    # not match any single candidate ticker.
    out = []
    for entry in selected:
        if not isinstance(entry, dict):
            continue

        ticker = (entry.get("ticker", "") or "").upper().strip()
        side = (entry.get("side", "BUY") or "BUY").upper().strip()
        if not ticker or side not in ("BUY", "SELL", "SELL_SHORT"):
            continue

        try:
            size_mult = float(entry.get("size_multiplier", 1.0))
            size_mult = max(0.5, min(1.5, size_mult))
        except (TypeError, ValueError):
            size_mult = 1.0

        try:
            size_usd = float(entry.get("size_usd", 0.0))
        except (TypeError, ValueError):
            size_usd = 0.0

        out.append({
            "ticker":              ticker,
            "side":                side,
            "size_usd":            round(size_usd, 2),
            "size_multiplier":     size_mult,
            "lane":                (entry.get("lane", "") or "").lower(),
            "curator_conviction":  entry.get("conviction", "?"),
            "curator_score":       entry.get("score", 0.0),
            "curator_rationale":   entry.get("rationale", ""),
            "curator_key_risk":    entry.get("key_risk", ""),
            "curator_horizon":     entry.get("expected_horizon", "?"),
        })

    # Cap at 3 signals (defense in depth — Curator should already cap)
    return out[:3]


__all__ = [
    "curate",
    "filter_signals_via_curator",
    "USE_CURATOR",
    "WORKER_URL",
    "POLL_MAX_S",
]

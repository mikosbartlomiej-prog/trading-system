"""v3.23.2 (2026-06-08) — Static search for AMD close source.

After v3.23.1 revealed the AMD market sell_to_close was placed via
Alpaca ``access_key`` with NO matching local ``safe_close`` event,
this module statically searches local logs/files for evidence of
which component submitted the close.

This is a READ-ONLY static search. It does NOT call any API. It does
NOT modify any file. It does NOT submit orders. If no strong evidence
is found, the classification is
``AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY`` —
the source remains unknown until GitHub Actions run logs or Alpaca
order-history API is consulted.

CONTRACT
--------
- READ-ONLY.
- Never speculates as fact. Unknown stays unknown.
- Returns a deterministic dict.
"""

from __future__ import annotations

import re
from pathlib import Path

# ─── Constants (target evidence we are looking for) ──────────────────────────

TARGET_SYMBOL          = "AMD"
TARGET_ORDER_ID        = "7f3ac850-49aa-4ccb-b075-c0ecb56c5871"
TARGET_TIMESTAMP_UTC   = "2026-06-05T21:35:45Z"
TARGET_TIMESTAMP_LOCAL = "2026-06-05T17:35:45-04:00"
TARGET_FILL_PRICE_USD  = 485.02

# ─── Classification enum ─────────────────────────────────────────────────────

AMD_CLOSE_SOURCE_IDENTIFIED = "AMD_CLOSE_SOURCE_IDENTIFIED"
AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY = (
    "AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY"
)

ALL_CLASSIFICATIONS: frozenset[str] = frozenset({
    AMD_CLOSE_SOURCE_IDENTIFIED,
    AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
})

# Invariants — test-asserted.
NEVER_PLACES_ORDERS         = True
NEVER_CALLS_LIVE_API        = True
NEVER_SPECULATES_AS_FACT    = True

# Match-strength markers.
STRONG = "STRONG"
WEAK   = "WEAK"

# Search-term patterns (case-insensitive). STRONG markers are order_id,
# exact-price-near-symbol, or exact-timestamp-near-symbol.
_STRONG_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(re.escape(TARGET_ORDER_ID), re.I),
    re.compile(r"\bAMD\b.{0,80}\b485\.02\b", re.I),
    re.compile(r"\b485\.02\b.{0,80}\bAMD\b", re.I),
    re.compile(r"\bAMD\b.{0,80}\b21:35:45\b"),
    re.compile(r"\b21:35:45\b.{0,80}\bAMD\b"),
    re.compile(r"\bAMD\b.{0,80}\b17:35:45\b"),
)
_WEAK_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bAMD\b.{0,40}sell_to_close", re.I),
    re.compile(r"sell_to_close.{0,40}\bAMD\b", re.I),
    re.compile(r"\bAMD\b.{0,40}market\s+sell", re.I),
    re.compile(r"\baccess_key\b.{0,80}\bAMD\b", re.I),
    re.compile(r"\bAMD\b.{0,80}\baccess_key\b", re.I),
)

# Directories to scan (skip ``.git``, ``.venv``, virtualenvs, etc.).
SCAN_DIRS: tuple[str, ...] = (
    "journal", "learning-loop", "scripts", "shared",
    "exit-monitor", "options-exit-monitor", ".github",
    "docs",
)


def classify_search_result(matches: list) -> str:
    """Return one of ALL_CLASSIFICATIONS based on match-strength.

    Any STRONG match → AMD_CLOSE_SOURCE_IDENTIFIED.
    Otherwise → AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY.
    """
    if not matches:
        return AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY
    for m in matches:
        if isinstance(m, dict) and m.get("match_strength") == STRONG:
            return AMD_CLOSE_SOURCE_IDENTIFIED
    return AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY


def _scan_file_for_matches(path: Path, rel: str) -> list[dict]:
    """Walk a single file looking for STRONG/WEAK patterns.

    Returns list of match dicts (may be empty).
    """
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        strong_hit = any(p.search(line) for p in _STRONG_PATTERNS)
        weak_hit = any(p.search(line) for p in _WEAK_PATTERNS) if not strong_hit else False
        if strong_hit:
            out.append({
                "file":            rel,
                "line_number":     line_no,
                "content_excerpt": line.strip()[:120],
                "match_strength":  STRONG,
            })
        elif weak_hit:
            out.append({
                "file":            rel,
                "line_number":     line_no,
                "content_excerpt": line.strip()[:120],
                "match_strength":  WEAK,
            })
    return out


def _is_self_reference(rel: str) -> bool:
    """Skip files that are themselves reports/modules ABOUT the incident.

    These mention the order_id but are not the close-submitter; counting
    them as evidence of source would be circular.
    """
    rel_lower = rel.lower()
    if rel_lower.startswith("learning-loop/position_reconciliation/"):
        return True
    if rel_lower.startswith("docs/"):
        return True
    if rel_lower.endswith("amd_close_source_search.py"):
        return True
    if "incident" in rel_lower and rel_lower.endswith(".md"):
        return True
    if rel_lower.endswith("position_reconciliation_latest.md"):
        return True
    return False


def search_amd_close(repo_root: Path) -> dict:
    """Static search across repo for evidence of AMD close source.

    Pure function (no network). Walks SCAN_DIRS and aggregates matches.
    Self-reference filtering is applied so v3.23.1 reconciliation
    reports do not count as evidence.
    """
    repo_root = Path(repo_root)
    matches: list[dict] = []

    for d in SCAN_DIRS:
        sd = repo_root / d
        if not sd.is_dir():
            continue
        for p in sd.rglob("*"):
            # Skip binaries / archives / __pycache__ / large auto-generated files.
            if not p.is_file():
                continue
            name = p.name
            if "__pycache__" in str(p) or name.endswith((".pyc", ".so", ".png",
                                                          ".jpg", ".jpeg",
                                                          ".pdf", ".gz",
                                                          ".tar", ".zip")):
                continue
            try:
                rel = p.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            if _is_self_reference(rel):
                continue
            matches.extend(_scan_file_for_matches(p, rel))

    classification = classify_search_result(matches)
    suspected_paths: list[str] = []
    confirmed_path: str | None = None
    for m in matches:
        if m.get("match_strength") == STRONG and confirmed_path is None:
            confirmed_path = m.get("file")
        elif m.get("match_strength") == WEAK:
            if m.get("file") not in suspected_paths:
                suspected_paths.append(m.get("file"))

    followup_required: list[str] = []
    if classification == AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY:
        followup_required = [
            "INVESTIGATE_AMD_CLOSE_SOURCE_IN_GITHUB_ACTIONS",
            "PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05",
        ]
    else:
        followup_required = [
            "VERIFY_CONFIRMED_PATH_EMITS_AUDIT_GOING_FORWARD",
        ]

    return {
        "target_symbol":         TARGET_SYMBOL,
        "target_order_id":       TARGET_ORDER_ID,
        "target_timestamp_utc":  TARGET_TIMESTAMP_UTC,
        "target_timestamp_local": TARGET_TIMESTAMP_LOCAL,
        "target_fill_price_usd": TARGET_FILL_PRICE_USD,
        "matches":               matches,
        "classification":        classification,
        "suspected_paths":       suspected_paths,
        "confirmed_path":        confirmed_path,
        "followup_required":     followup_required,
    }


__all__ = [
    "TARGET_SYMBOL", "TARGET_ORDER_ID",
    "TARGET_TIMESTAMP_UTC", "TARGET_TIMESTAMP_LOCAL",
    "TARGET_FILL_PRICE_USD",
    "AMD_CLOSE_SOURCE_IDENTIFIED",
    "AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY",
    "ALL_CLASSIFICATIONS",
    "NEVER_PLACES_ORDERS", "NEVER_CALLS_LIVE_API", "NEVER_SPECULATES_AS_FACT",
    "STRONG", "WEAK",
    "classify_search_result", "search_amd_close",
]

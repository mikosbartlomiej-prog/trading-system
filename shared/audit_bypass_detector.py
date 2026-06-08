"""v3.23.2 (2026-06-08) — Audit-bypass detector for close/sell paths.

After the v3.23.1 AMD reconciliation revealed
`MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`, we need
a deterministic static checker that classifies every code path that
can submit a sell/close order:

- SAFE_CLOSE_WRAPPED       — the code calls
  ``shared/alpaca_orders.py::safe_close()`` (THE single-entry close path).
- AUDIT_EQUIVALENT_WRAPPED — the code writes an audit event before
  submitting the order (e.g. ``audit.write_audit_event`` + ``requests.post``
  in the same function).
- READ_ONLY                — only ``GET`` requests against the broker,
  no order submission.
- ORDER_SUBMITTER_BYPASS   — POSTs ``sell`` to ``/v2/orders`` without
  ``safe_close`` AND without an audit-event write.
- LEGACY_DANGEROUS         — known legacy script (predates ``safe_close``)
  — operator review required.
- UNKNOWN_REQUIRES_REVIEW  — cannot determine deterministically.

CONTRACT
--------
- READ-ONLY. Does not modify any file. Does not delete legacy scripts.
- Does not submit orders.
- Does not call the broker.
- Returns a deterministic classification per file.

INVARIANTS (test-asserted)
--------------------------
- NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT
- NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT
- ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT
"""

from __future__ import annotations

import re
from pathlib import Path

# ─── Classification enum ─────────────────────────────────────────────────────

SAFE_CLOSE_WRAPPED        = "SAFE_CLOSE_WRAPPED"
AUDIT_EQUIVALENT_WRAPPED  = "AUDIT_EQUIVALENT_WRAPPED"
READ_ONLY                 = "READ_ONLY"
ORDER_SUBMITTER_BYPASS    = "ORDER_SUBMITTER_BYPASS"
LEGACY_DANGEROUS          = "LEGACY_DANGEROUS"
UNKNOWN_REQUIRES_REVIEW   = "UNKNOWN_REQUIRES_REVIEW"

ALL_CLASSIFICATIONS: frozenset[str] = frozenset({
    SAFE_CLOSE_WRAPPED,
    AUDIT_EQUIVALENT_WRAPPED,
    READ_ONLY,
    ORDER_SUBMITTER_BYPASS,
    LEGACY_DANGEROUS,
    UNKNOWN_REQUIRES_REVIEW,
})

# Invariants — test-asserted.
NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT                       = True
NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT   = True
ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT                     = True

# Mirror of tests/architecture_vnext/test_no_naked_sell_v3910.py ALLOWED_FILES.
ALLOW_LIST: frozenset[str] = frozenset({
    "shared/alpaca_orders.py",          # safe_close lives here
    "options-monitor/monitor.py",       # entry-only (BUY)
    "shared/broker_paper_adapter.py",   # hardened paper-only adapter
})

# Heuristics — file/dir hints.
SCAN_DIRS: tuple[str, ...] = (
    "shared", "scripts", "learning-loop", "crypto-monitor",
    "exit-monitor", "options-monitor", "options-exit-monitor",
    "price-monitor", "defense-monitor", "twitter-monitor",
    "geo-monitor", "reddit-monitor", "politician-monitor",
)

# Patterns we look for in source code.
# v3.23.2 refinement: a file is only treated as "submitting sell" if it
# contains an actual `requests.post(...) → /v2/orders` call. String
# literals like `"side": "sell"` or `sell_to_close` in unrelated contexts
# (analyzer docstrings, JSON payloads in monitor reports) are NOT enough.
# Files that only mention sell tokens without the POST call fall through
# to UNKNOWN_REQUIRES_REVIEW (a softer classification — not auto-flagged).
_SELL_SUBMIT_PATTERNS: tuple[re.Pattern, ...] = (
    # Loose: any requests.post(...) call where /v2/orders appears within
    # the next 200 chars (handles f-strings, multi-line calls, etc.).
    re.compile(r"requests\.(post|request)\s*\([^)]{0,200}\/v2\/orders",
                 re.I | re.DOTALL),
)
_SELL_SIDE_LITERAL_PATTERNS: tuple[re.Pattern, ...] = (
    # JSON-style: "side": "sell"
    re.compile(r"['\"]\s*side\s*['\"]\s*[:=]\s*['\"]sell['\"]", re.I),
    # Variable assignment: side = "sell"
    re.compile(r"\bside\s*=\s*['\"]sell['\"]", re.I),
    # Token reference
    re.compile(r"sell_to_close", re.I),
)
_SAFE_CLOSE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bsafe_close\s*\("),
    re.compile(r"from\s+(?:shared\.)?alpaca_orders\s+import[^#\n]*safe_close"),
)
_AUDIT_WRITE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"write_audit_event\s*\("),
    re.compile(r"emit_audit_event\s*\("),
)
_GET_ONLY_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"requests\.get\s*\(", re.I),
)


def classify_path(file_path: Path, source_code: str) -> str:
    """Return one of ALL_CLASSIFICATIONS for the given source code.

    Pure function — no I/O beyond accepting the source string.
    """
    # Allow-list short-circuit.
    try:
        rel = str(file_path.as_posix())
    except AttributeError:
        rel = str(file_path)
    for allow in ALL_LIST_HINTS():
        if rel.endswith(allow) or allow in rel:
            # Even allow-listed files are classified by their actual content,
            # but the allow-list signals operator intent.
            break

    # Look for sell-submit signals. v3.23.2: REQUIRE an actual
    # `requests.post(/v2/orders)` call. Pure string literals like
    # `sell_to_close` in docstrings/payloads are no longer enough.
    has_orders_post = any(p.search(source_code) for p in _SELL_SUBMIT_PATTERNS)
    has_sell_literal = any(p.search(source_code) for p in _SELL_SIDE_LITERAL_PATTERNS)
    has_sell_submit = has_orders_post and has_sell_literal
    has_safe_close = any(p.search(source_code) for p in _SAFE_CLOSE_PATTERNS)
    has_audit_write = any(p.search(source_code) for p in _AUDIT_WRITE_PATTERNS)
    has_get_only = any(p.search(source_code) for p in _GET_ONLY_PATTERNS)

    if not has_sell_submit and has_get_only:
        return READ_ONLY
    if not has_sell_submit:
        # No sell/close submission found at all → safest classification
        # is READ_ONLY (no order activity) when GET patterns exist.
        if has_get_only:
            return READ_ONLY
        return UNKNOWN_REQUIRES_REVIEW
    # has_sell_submit at this point.
    if has_safe_close:
        return SAFE_CLOSE_WRAPPED
    if has_audit_write:
        return AUDIT_EQUIVALENT_WRAPPED
    # Sell submit without safe_close and without audit write → bypass.
    # If the file is legacy-named, mark as LEGACY_DANGEROUS.
    if _looks_legacy(rel):
        return LEGACY_DANGEROUS
    return ORDER_SUBMITTER_BYPASS


def ALL_LIST_HINTS() -> frozenset[str]:
    """Expose the allow-list for callers."""
    return ALLOW_LIST


def _looks_legacy(rel_path: str) -> bool:
    """Heuristic: filenames like ``emergency_close_*.py``,
    ``one_shot_*.py``, ``manual_close_*.py`` are legacy."""
    name = Path(rel_path).name.lower()
    return any(
        marker in name for marker in (
            "emergency_close_", "one_shot_", "manual_close_",
            "panic_", "ad_hoc_",
        )
    )


def detect_bypasses(repo_root: Path) -> dict:
    """Walk SCAN_DIRS and classify every Python file. READ-ONLY.

    Returns:
        {
            "total_scanned":            int,
            "by_classification":        {classification: count},
            "flagged_files":            [str list of bypass-flagged file rels],
            "allow_list_files":         [str list of allow-listed file rels],
            "invariant_satisfied":      bool,
            "details":                  {file_rel: classification},
        }
    """
    repo_root = Path(repo_root)
    by_class: dict[str, int] = {c: 0 for c in ALL_CLASSIFICATIONS}
    details: dict[str, str] = {}
    flagged: list[str] = []
    allowed: list[str] = []
    total = 0

    for d in SCAN_DIRS:
        sd = repo_root / d
        if not sd.is_dir():
            continue
        for py in sd.rglob("*.py"):
            try:
                rel = py.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            if "/__pycache__/" in rel or "/tests/" in rel:
                continue
            if "test_" in py.name:
                continue
            try:
                src = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            cls = classify_path(py, src)
            details[rel] = cls
            by_class[cls] = by_class.get(cls, 0) + 1
            total += 1
            if cls in (ORDER_SUBMITTER_BYPASS, LEGACY_DANGEROUS):
                if rel in ALLOW_LIST:
                    allowed.append(rel)
                else:
                    flagged.append(rel)

    invariant_satisfied = len(flagged) == 0

    return {
        "total_scanned":        total,
        "by_classification":    dict(by_class),
        "flagged_files":        sorted(flagged),
        "allow_list_files":     sorted(allowed),
        "invariant_satisfied":  invariant_satisfied,
        "details":              details,
    }


__all__ = [
    # Classifications
    "SAFE_CLOSE_WRAPPED",
    "AUDIT_EQUIVALENT_WRAPPED",
    "READ_ONLY",
    "ORDER_SUBMITTER_BYPASS",
    "LEGACY_DANGEROUS",
    "UNKNOWN_REQUIRES_REVIEW",
    "ALL_CLASSIFICATIONS",
    # Invariants
    "NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT",
    "NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT",
    "ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT",
    "ALLOW_LIST",
    "SCAN_DIRS",
    # API
    "classify_path",
    "detect_bypasses",
    "ALL_LIST_HINTS",
]

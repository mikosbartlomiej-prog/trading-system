"""v3.27.0 (2026-06-09) — shadow outcome resolver.

Reads PENDING shadow records and, after the configured horizon,
computes a HYPOTHETICAL outcome from a fresh read-only market
snapshot. Writes outcomes to a sidecar JSONL file (NOT into the
original records — keeps the records file append-only and immutable).

CONTRACT
--------
- READ-ONLY for market access. Does NOT submit orders.
- Does NOT import ``shared/alpaca_orders.py``.
- Does NOT use realized P/L from the broker — every outcome is
  marked ``SHADOW_OUTCOME`` and is hypothetical.
- Resolves only records with ``evidence_quality=REAL_MARKET_DATA`` and
  ``outcome_tracking_status=PENDING``.
- Scaffold / halt-path records are skipped (their ``evidence_quality``
  is not ``REAL_MARKET_DATA``).
- Never overwrites original records destructively.

INVARIANTS (test-asserted)
--------------------------
- NEVER_SUBMITS_ORDERS = True
- NEVER_IMPORTS_ALPACA_ORDERS = True
- NEVER_USES_BROKER_REALIZED_PNL = True
- NEVER_RESOLVES_SCAFFOLD_RECORDS = True
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Invariants.
NEVER_SUBMITS_ORDERS               = True
NEVER_IMPORTS_ALPACA_ORDERS        = True
NEVER_USES_BROKER_REALIZED_PNL     = True
NEVER_RESOLVES_SCAFFOLD_RECORDS    = True

# Default horizon — 1 hour shadow outcome window.
DEFAULT_HORIZON_SECONDS = 3600

# Outcome status enum.
OUTCOME_PENDING                 = "PENDING"
OUTCOME_COMPLETED_HYPOTHETICAL  = "COMPLETED_HYPOTHETICAL"
OUTCOME_SKIPPED_NOT_REAL        = "SKIPPED_NOT_REAL"
OUTCOME_SKIPPED_TOO_EARLY       = "SKIPPED_TOO_EARLY"
OUTCOME_SKIPPED_NO_RESOLUTION_PRICE = "SKIPPED_NO_RESOLUTION_PRICE"
OUTCOME_SKIPPED_PROVIDER_ERROR  = "SKIPPED_PROVIDER_ERROR"

ALL_OUTCOME_STATUSES: frozenset[str] = frozenset({
    OUTCOME_PENDING, OUTCOME_COMPLETED_HYPOTHETICAL,
    OUTCOME_SKIPPED_NOT_REAL, OUTCOME_SKIPPED_TOO_EARLY,
    OUTCOME_SKIPPED_NO_RESOLUTION_PRICE,
    OUTCOME_SKIPPED_PROVIDER_ERROR,
})

EVIDENCE_DIR = Path("learning-loop") / "shadow_evidence"


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class OutcomeRecord:
    audit_trace_id: str
    symbol: str
    asset_class: str
    strategy: str
    side: str
    entry_shadow_price: float
    exit_shadow_price: float | None
    outcome_status: str
    outcome_resolved_at: str
    outcome_horizon_seconds: int
    hypothetical_return_pct: float | None
    hypothetical_pnl_preview: float | None
    outcome_data_quality: str
    source_record_timestamp: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "audit_trace_id": self.audit_trace_id,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "strategy": self.strategy,
            "side": self.side,
            "entry_shadow_price": self.entry_shadow_price,
            "exit_shadow_price": self.exit_shadow_price,
            "outcome_status": self.outcome_status,
            "outcome_resolved_at": self.outcome_resolved_at,
            "outcome_horizon_seconds": self.outcome_horizon_seconds,
            "hypothetical_return_pct": self.hypothetical_return_pct,
            "hypothetical_pnl_preview": self.hypothetical_pnl_preview,
            "outcome_data_quality": self.outcome_data_quality,
            "source_record_timestamp": self.source_record_timestamp,
            "outcome_kind": "SHADOW_OUTCOME",
            "is_broker_realized_pnl": False,
            "notes": list(self.notes),
            "version": "v3.27.0",
        }


# ─── Internal helpers ────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _iso_now(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.isoformat()


def _records_path(repo_root: Path, day: str) -> Path:
    return repo_root / EVIDENCE_DIR / f"records_{day}.jsonl"


def _outcomes_path(repo_root: Path, day: str) -> Path:
    return repo_root / EVIDENCE_DIR / f"outcomes_{day}.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _already_resolved_ids(outcomes_path: Path) -> set[str]:
    ids: set[str] = set()
    for o in _load_jsonl(outcomes_path):
        aid = o.get("audit_trace_id")
        if aid:
            ids.add(aid)
    return ids


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ─── Public API ──────────────────────────────────────────────────────────────

def resolve_records(
    records: Iterable[dict[str, Any]],
    *,
    fetch_snapshot_fn,
    now: datetime | None = None,
    horizon_seconds: int = DEFAULT_HORIZON_SECONDS,
    already_resolved: set[str] | None = None,
) -> list[OutcomeRecord]:
    """Resolve any eligible records.

    ``fetch_snapshot_fn(symbol, asset_class) -> MarketSnapshot-like``
    is injected so tests can pass a stub. The real caller passes
    ``shared/market_data_provider.py::fetch_snapshot``.

    Returns the list of outcome records (including SKIPPED outcomes
    so the caller can persist them). Records that are not yet
    eligible (`too early`) are NOT emitted — the caller will revisit
    them in the next run.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    already_resolved = already_resolved or set()
    outcomes: list[OutcomeRecord] = []
    for rec in records:
        aid = rec.get("audit_trace_id") or ""
        if not aid or aid in already_resolved:
            continue
        if (rec.get("evidence_quality") != "REAL_MARKET_DATA"):
            # Scaffold + halt records never resolve.
            continue
        if (rec.get("outcome_tracking_status")
                not in (OUTCOME_PENDING, None, "")):
            continue
        ts = _parse_iso(rec.get("timestamp") or "")
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if age < horizon_seconds:
            # Not yet eligible; skip silently.
            continue

        sizing = rec.get("sizing_preview") or {}
        entry_price = sizing.get("entry_shadow_price")
        if entry_price in (None, 0):
            entry_price = sizing.get("limit_price")
        if entry_price in (None, 0):
            outcomes.append(OutcomeRecord(
                audit_trace_id=aid,
                symbol=rec.get("symbol") or "",
                asset_class=rec.get("asset_class") or "us_equity",
                strategy=rec.get("strategy") or "?",
                side=rec.get("side") or "buy",
                entry_shadow_price=0.0,
                exit_shadow_price=None,
                outcome_status=OUTCOME_SKIPPED_NO_RESOLUTION_PRICE,
                outcome_resolved_at=_iso_now(now),
                outcome_horizon_seconds=horizon_seconds,
                hypothetical_return_pct=None,
                hypothetical_pnl_preview=None,
                outcome_data_quality="NO_ENTRY_PRICE_IN_SOURCE_RECORD",
                source_record_timestamp=rec.get("timestamp") or "",
            ))
            continue
        entry_price = float(entry_price)

        # Fetch a fresh snapshot.
        try:
            snap = fetch_snapshot_fn(
                rec.get("symbol") or "",
                rec.get("asset_class") or None,
            )
        except Exception as e:
            outcomes.append(OutcomeRecord(
                audit_trace_id=aid,
                symbol=rec.get("symbol") or "",
                asset_class=rec.get("asset_class") or "us_equity",
                strategy=rec.get("strategy") or "?",
                side=rec.get("side") or "buy",
                entry_shadow_price=entry_price,
                exit_shadow_price=None,
                outcome_status=OUTCOME_SKIPPED_PROVIDER_ERROR,
                outcome_resolved_at=_iso_now(now),
                outcome_horizon_seconds=horizon_seconds,
                hypothetical_return_pct=None,
                hypothetical_pnl_preview=None,
                outcome_data_quality=f"PROVIDER_ERROR: {type(e).__name__}",
                source_record_timestamp=rec.get("timestamp") or "",
            ))
            continue

        if hasattr(snap, "as_dict"):
            snap_d = snap.as_dict()
        else:
            snap_d = dict(snap)
        if snap_d.get("data_quality") != "REAL_MARKET_DATA":
            outcomes.append(OutcomeRecord(
                audit_trace_id=aid,
                symbol=rec.get("symbol") or "",
                asset_class=rec.get("asset_class") or "us_equity",
                strategy=rec.get("strategy") or "?",
                side=rec.get("side") or "buy",
                entry_shadow_price=entry_price,
                exit_shadow_price=None,
                outcome_status=OUTCOME_SKIPPED_NO_RESOLUTION_PRICE,
                outcome_resolved_at=_iso_now(now),
                outcome_horizon_seconds=horizon_seconds,
                hypothetical_return_pct=None,
                hypothetical_pnl_preview=None,
                outcome_data_quality=(snap_d.get("data_quality")
                                        or "UNKNOWN"),
                source_record_timestamp=rec.get("timestamp") or "",
            ))
            continue
        exit_price = snap_d.get("price")
        if exit_price in (None, 0):
            outcomes.append(OutcomeRecord(
                audit_trace_id=aid,
                symbol=rec.get("symbol") or "",
                asset_class=rec.get("asset_class") or "us_equity",
                strategy=rec.get("strategy") or "?",
                side=rec.get("side") or "buy",
                entry_shadow_price=entry_price,
                exit_shadow_price=None,
                outcome_status=OUTCOME_SKIPPED_NO_RESOLUTION_PRICE,
                outcome_resolved_at=_iso_now(now),
                outcome_horizon_seconds=horizon_seconds,
                hypothetical_return_pct=None,
                hypothetical_pnl_preview=None,
                outcome_data_quality="ZERO_OR_MISSING_EXIT_PRICE",
                source_record_timestamp=rec.get("timestamp") or "",
            ))
            continue
        exit_price = float(exit_price)
        # Hypothetical signed return.
        side = (rec.get("side") or "buy").lower()
        sign = 1.0 if side in ("buy", "buy_to_open") else -1.0
        ret_pct = sign * (exit_price - entry_price) / entry_price * 100.0
        proposed = float((sizing.get("proposed_usd") or 0.0))
        pnl_preview: float | None
        if proposed > 0:
            pnl_preview = round(
                sign * proposed * (exit_price - entry_price) / entry_price,
                4,
            )
        else:
            pnl_preview = None

        outcomes.append(OutcomeRecord(
            audit_trace_id=aid,
            symbol=rec.get("symbol") or "",
            asset_class=rec.get("asset_class") or "us_equity",
            strategy=rec.get("strategy") or "?",
            side=side,
            entry_shadow_price=entry_price,
            exit_shadow_price=exit_price,
            outcome_status=OUTCOME_COMPLETED_HYPOTHETICAL,
            outcome_resolved_at=_iso_now(now),
            outcome_horizon_seconds=horizon_seconds,
            hypothetical_return_pct=round(ret_pct, 4),
            hypothetical_pnl_preview=pnl_preview,
            outcome_data_quality="REAL_MARKET_DATA",
            source_record_timestamp=rec.get("timestamp") or "",
        ))
    return outcomes


def resolve_day(
    day: str,
    *,
    repo_root: Path,
    fetch_snapshot_fn,
    now: datetime | None = None,
    horizon_seconds: int = DEFAULT_HORIZON_SECONDS,
    max_records: int = 50,
) -> dict[str, Any]:
    """Resolve eligible PENDING records for a UTC day.

    Returns a summary dict (also includes the list of new outcomes
    written and the path of the outcomes file).
    """
    repo_root = Path(repo_root)
    records_path = _records_path(repo_root, day)
    outcomes_path = _outcomes_path(repo_root, day)
    records = _load_jsonl(records_path)
    if max_records and max_records > 0:
        records = records[:max_records]

    already = _already_resolved_ids(outcomes_path)
    outcomes = resolve_records(
        records, fetch_snapshot_fn=fetch_snapshot_fn,
        now=now, horizon_seconds=horizon_seconds,
        already_resolved=already,
    )

    completed = 0
    skipped = 0
    for o in outcomes:
        _append_jsonl(outcomes_path, o.as_dict())
        if o.outcome_status == OUTCOME_COMPLETED_HYPOTHETICAL:
            completed += 1
        else:
            skipped += 1

    # Bump completed_shadow_outcomes_count for the completed ones.
    if completed > 0:
        try:
            try:
                import shadow_evidence_counters as sec
            except ImportError:
                from shared import shadow_evidence_counters as sec
            c = sec.load_counters(repo_root)
            sec.increment(c, sec.METRIC_COMPLETED_SHADOW_OUTCOMES,
                           by=completed)
            sec.save_counters(c, repo_root=repo_root,
                               generated_at_iso=_iso_now(now))
        except Exception:
            pass  # fail-soft; outcomes still on disk

    return {
        "version":          "v3.27.0",
        "day":              day,
        "records_found":    len(records),
        "outcomes_emitted": len(outcomes),
        "completed":        completed,
        "skipped":          skipped,
        "outcomes_path":    (str(outcomes_path.relative_to(repo_root))
                              if repo_root in outcomes_path.parents
                              or outcomes_path == repo_root
                              else str(outcomes_path)),
    }


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.27.0",
        "default_horizon_seconds": DEFAULT_HORIZON_SECONDS,
        "outcome_statuses": sorted(ALL_OUTCOME_STATUSES),
        "invariants": {
            "NEVER_SUBMITS_ORDERS": NEVER_SUBMITS_ORDERS,
            "NEVER_IMPORTS_ALPACA_ORDERS": NEVER_IMPORTS_ALPACA_ORDERS,
            "NEVER_USES_BROKER_REALIZED_PNL":
                NEVER_USES_BROKER_REALIZED_PNL,
            "NEVER_RESOLVES_SCAFFOLD_RECORDS":
                NEVER_RESOLVES_SCAFFOLD_RECORDS,
        },
    }


__all__ = [
    # Invariants
    "NEVER_SUBMITS_ORDERS", "NEVER_IMPORTS_ALPACA_ORDERS",
    "NEVER_USES_BROKER_REALIZED_PNL",
    "NEVER_RESOLVES_SCAFFOLD_RECORDS",
    # Status enum
    "OUTCOME_PENDING", "OUTCOME_COMPLETED_HYPOTHETICAL",
    "OUTCOME_SKIPPED_NOT_REAL", "OUTCOME_SKIPPED_TOO_EARLY",
    "OUTCOME_SKIPPED_NO_RESOLUTION_PRICE",
    "OUTCOME_SKIPPED_PROVIDER_ERROR",
    "ALL_OUTCOME_STATUSES",
    # Constants
    "DEFAULT_HORIZON_SECONDS",
    # Data class
    "OutcomeRecord",
    # API
    "resolve_records", "resolve_day", "policy_summary",
]

#!/usr/bin/env python3
"""v3.30 ETAP 5 (2026-06-16) — Operator clearance PROPOSAL writer.

CONTRACT (do not loosen)
------------------------
This script is **read-mostly**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* clears safe_mode,
* clears the broker_repair_required quarantine,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``,
* places, cancels, or modifies orders,
* mutates risk thresholds.

It ONLY:

* validates operator-confirmation marker (v3.29 etap 1 contract),
* reads broker_repair_required canonical state,
* reads safe_mode_consistency_latest verdict,
* reads equity_gap_reconciliation_latest verdict,
* checks audit JSONL for fresh P13 / retry-storm events AFTER the
  marker timestamp,
* writes a PROPOSAL JSON to ``learning-loop/operator_markers/`` when
  ALL checks pass AND ``--operator-confirmed`` is supplied,
* appends an audit JSONL row describing the proposal write,
* refuses (exits non-zero, no write) when ANY check fails.

The proposal file is for OPERATOR REVIEW. It DOES NOT modify any
state file. A separate operator-driven step (manual editing of
``broker_repair_required_latest.json`` + a follow-up commit) is the
ONLY way to actually clear the quarantine. Safe_mode clearance is
NOT automated by this proposal either — the operator must take a
deliberate further action.

USAGE
-----
::

  python3 scripts/propose_clear_broker_repair_and_safe_mode.py \\
      --symbol AVAX/USD \\
      --operator-marker-path learning-loop/operator_markers/AVAX_USD_2026-06-16.json \\
      --dashboard-evidence-note "broker dust cleared; OCO 8h orphan cancelled" \\
      --dry-run false \\
      --operator-confirmed

Without ``--operator-confirmed`` (default) the script runs read-only
and prints what it WOULD propose without writing.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
- ``NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT``
- ``NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT = True
NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

# Leaf modules — no broker imports.
import symbol_normalization as sym_norm    # noqa: E402
import broker_repair_required as brr       # noqa: E402
import operator_repair_state as ors        # noqa: E402


# ── Output paths ──────────────────────────────────────────────────────────────

def _markers_dir() -> Path:
    env = os.environ.get("OPERATOR_MARKERS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "operator_markers"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _safe_mode_consistency_path() -> Path:
    env = os.environ.get("SAFE_MODE_CONSISTENCY_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"


def _equity_gap_path() -> Path:
    env = os.environ.get("EQUITY_GAP_LATEST_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Read helpers ─────────────────────────────────────────────────────────────

def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class ClearanceCheckResult:
    verdict: str  # CLEARANCE_PROPOSED / CLEARANCE_REFUSED
    refusal_reason: Optional[str]
    symbol_input: str
    symbol_canonical: str
    marker_ts_iso: Optional[str]
    fresh_p13_count: int
    fresh_403_count: int
    equity_gap_block: bool
    safe_mode_consistency_verdict: str
    safe_mode_consistency_blocker: Optional[str]
    broker_repair_present: bool
    evaluated_at_iso: str
    standing_markers: list[str] = field(default_factory=list)
    proposal_path: Optional[str] = None


def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        "NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT",
        "NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT",
    ]


# ── Fresh-incident scanner (post-marker) ─────────────────────────────────────

P13_DECISION_TYPES = {
    "P13_BRACKET_INTERLOCK_BLOCKED_CLOSE",
    "INCIDENT_P13_BRACKET_INTERLOCK",
    "SAFE_CLOSE_FAILED",
    "BROKER_CLOSE_FAILED",
}

ERROR_403_MARKERS = ("403", "insufficient", "held_for_orders")


def _count_fresh_incidents(symbol_canonical: str,
                           after_iso: str,
                           *,
                           lookback_days: int = 14) -> tuple[int, int]:
    """Count fresh P13 / retry-storm events strictly AFTER ``after_iso`` for
    the canonical symbol (or any of its aliases).

    Returns (p13_count, alpaca_403_count). Fail-soft: any I/O error
    counts the event as 0.
    """
    after_dt = _parse_iso(after_iso)
    if after_dt is None:
        return 0, 0
    aliases = sym_norm.aliases_for(symbol_canonical)
    sym_set = {a.upper() for a in aliases}
    sym_set.add(symbol_canonical.upper())

    p13 = 0
    alpaca_403 = 0

    audit_root = _audit_dir()
    if not audit_root.exists():
        return 0, 0

    for delta in range(0, max(1, int(lookback_days)) + 1):
        day = (_now().date()).fromordinal((_now().date()).toordinal() - delta).isoformat()
        path = audit_root / f"{day}.jsonl"
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = _parse_iso(str(row.get("ts_iso") or row.get("timestamp") or ""))
                    if ts is None or ts <= after_dt:
                        continue

                    # Match symbol field (or any aliased form).
                    sym_field = str(row.get("symbol") or "").upper()
                    affected = row.get("affected_symbols") or []
                    affected_upper = {str(s).upper() for s in affected if s}
                    sym_match = (
                        sym_field in sym_set
                        or bool(sym_set & affected_upper)
                    )
                    if not sym_match:
                        # Also check reason field for the canonical token (broker_repair_backfill rows).
                        reason_blob = str(row.get("reason") or "")
                        if not any(s in reason_blob.upper() for s in sym_set):
                            continue

                    dt = str(row.get("decision_type") or "")
                    if dt in P13_DECISION_TYPES:
                        p13 += 1
                    # Detect 403 / insufficient / held_for_orders error text.
                    err = (
                        str(row.get("last_error") or "")
                        + " " + str(row.get("error") or "")
                        + " " + str(row.get("reason") or "")
                    ).lower()
                    if any(m in err for m in ERROR_403_MARKERS):
                        alpaca_403 += 1
        except OSError:
            continue

    return p13, alpaca_403


# ── Core evaluation ──────────────────────────────────────────────────────────

def evaluate_clearance(symbol_input: str,
                       operator_marker_path: Path,
                       ) -> ClearanceCheckResult:
    """Pure read-only evaluation. Decides whether a clearance PROPOSAL
    is permissible. Never writes anything.
    """
    symbol_canonical = sym_norm.canonical_for(symbol_input)
    result = ClearanceCheckResult(
        verdict="CLEARANCE_REFUSED",
        refusal_reason=None,
        symbol_input=symbol_input,
        symbol_canonical=symbol_canonical,
        marker_ts_iso=None,
        fresh_p13_count=0,
        fresh_403_count=0,
        equity_gap_block=False,
        safe_mode_consistency_verdict="UNKNOWN",
        safe_mode_consistency_blocker=None,
        broker_repair_present=False,
        evaluated_at_iso=_now_iso(),
        standing_markers=_standing_markers(),
    )

    # 1. Operator marker must exist and have a valid timestamp.
    if not operator_marker_path.exists():
        result.refusal_reason = (
            f"operator marker not found at {operator_marker_path} — "
            "run scripts/record_operator_repair_confirmation.py first"
        )
        return result
    marker_raw = _read_json(operator_marker_path)
    if not marker_raw or not marker_raw.get("timestamp_iso"):
        result.refusal_reason = (
            f"operator marker {operator_marker_path} is unreadable or missing timestamp_iso"
        )
        return result
    if str(marker_raw.get("source", "")) != ors.MARKER_SOURCE:
        result.refusal_reason = (
            f"operator marker has source={marker_raw.get('source')!r}; "
            f"expected {ors.MARKER_SOURCE!r}"
        )
        return result
    marker_symbol_raw = str(marker_raw.get("symbol", ""))
    if sym_norm.canonical_for(marker_symbol_raw) != symbol_canonical:
        result.refusal_reason = (
            f"operator marker symbol={marker_symbol_raw!r} (canonical "
            f"{sym_norm.canonical_for(marker_symbol_raw)!r}) does not match "
            f"--symbol {symbol_input!r} (canonical {symbol_canonical!r})"
        )
        return result
    result.marker_ts_iso = str(marker_raw["timestamp_iso"])

    # 2. broker_repair_required must currently flag this canonical symbol.
    try:
        repair_present = brr.is_repair_required(symbol_canonical)
    except Exception as e:
        result.refusal_reason = f"failed to read broker_repair_required state: {e}"
        return result
    result.broker_repair_present = bool(repair_present)
    if not repair_present:
        result.refusal_reason = (
            f"broker_repair_required does not currently flag {symbol_canonical!r} — "
            "nothing to clear; refusing to write proposal"
        )
        return result

    # 3. safe_mode_consistency verdict must NOT show INCONSISTENT.
    smc = _read_json(_safe_mode_consistency_path()) or {}
    smc_verdict = str(smc.get("verdict", "UNKNOWN"))
    smc_blocker = smc.get("blocker")
    result.safe_mode_consistency_verdict = smc_verdict
    result.safe_mode_consistency_blocker = smc_blocker
    if smc_blocker:
        result.refusal_reason = (
            f"safe_mode_consistency blocker={smc_blocker!r} "
            f"(verdict={smc_verdict!r}) — must be resolved before clearance"
        )
        return result
    if smc_verdict.startswith("INCONSISTENT") or smc_verdict == "STALE_ACTIVE":
        result.refusal_reason = (
            f"safe_mode_consistency verdict={smc_verdict!r} — must be CONSISTENT "
            "before clearance proposal"
        )
        return result

    # 4. equity_gap_reconciliation must not have block_allocator=true.
    egap = _read_json(_equity_gap_path()) or {}
    if bool(egap.get("block_allocator", False)):
        result.equity_gap_block = True
        result.refusal_reason = (
            "equity_gap_reconciliation_latest reports block_allocator=true — "
            "equity reconciliation must be resolved first"
        )
        return result

    # 5. No fresh P13 / 403 events after the marker timestamp.
    p13, alpaca_403 = _count_fresh_incidents(symbol_canonical, result.marker_ts_iso)
    result.fresh_p13_count = p13
    result.fresh_403_count = alpaca_403
    if p13 > 0:
        result.refusal_reason = (
            f"{p13} fresh P13 / retry-storm audit event(s) for "
            f"{symbol_canonical!r} AFTER marker timestamp "
            f"{result.marker_ts_iso} — repair did not stick"
        )
        return result
    if alpaca_403 > 0:
        result.refusal_reason = (
            f"{alpaca_403} fresh broker-403/insufficient-balance event(s) for "
            f"{symbol_canonical!r} AFTER marker timestamp "
            f"{result.marker_ts_iso} — broker still rejects close path"
        )
        return result

    # ALL CLEAR.
    result.verdict = "CLEARANCE_PROPOSED"
    result.refusal_reason = None
    return result


# ── Proposal writer (operator-confirmed only) ────────────────────────────────

def _proposal_path(symbol_canonical: str) -> Path:
    safe_sym = symbol_canonical.replace("/", "_").replace(" ", "_")
    return _markers_dir() / f"clearance_proposal_{_today_iso_date()}_{safe_sym}.json"


def write_proposal(result: ClearanceCheckResult,
                   *,
                   marker_path: Path,
                   dashboard_evidence_note: str,
                   ) -> Path:
    """Write the clearance PROPOSAL JSON. Atomic write. NEVER mutates
    broker_repair_required, safe_mode_state, or runtime_state.

    Raises RuntimeError if the result is not CLEARANCE_PROPOSED.
    """
    if result.verdict != "CLEARANCE_PROPOSED":
        raise RuntimeError(
            f"refusing to write proposal: verdict={result.verdict} "
            f"refusal_reason={result.refusal_reason!r}"
        )

    path = _proposal_path(result.symbol_canonical)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version":          "v3.30",
        "proposal_type":           "OPERATOR_CLEARANCE_REVIEW",
        "symbol_input":            result.symbol_input,
        "symbol_canonical":        result.symbol_canonical,
        "operator_marker_path":    str(marker_path),
        "marker_ts_iso":           result.marker_ts_iso,
        "dashboard_evidence_note": dashboard_evidence_note,
        "fresh_p13_count":         result.fresh_p13_count,
        "fresh_403_count":         result.fresh_403_count,
        "equity_gap_block":        result.equity_gap_block,
        "safe_mode_consistency": {
            "verdict": result.safe_mode_consistency_verdict,
            "blocker": result.safe_mode_consistency_blocker,
        },
        "broker_repair_present":   result.broker_repair_present,
        "proposed_at_iso":         result.evaluated_at_iso,
        "does_not_execute_orders": True,
        "does_not_auto_clear_safe_mode": True,
        "does_not_auto_clear_broker_repair": True,
        "next_step_for_operator": (
            "Review this proposal. If accepted, the operator runs the "
            "broker_repair clearance manually via the documented "
            "operator_marker workflow. Safe_mode clearance is a "
            "separate deliberate operator action."
        ),
        "standing_markers":        result.standing_markers,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)

    # Append audit row — best-effort.
    try:
        ad = _audit_dir()
        ad.mkdir(parents=True, exist_ok=True)
        audit_path = ad / f"{_today_iso_date()}.jsonl"
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "decision_type":           "OPERATOR_CLEARANCE_PROPOSAL_WRITTEN",
                "actor":                   "propose_clear_broker_repair_and_safe_mode",
                "symbol":                  result.symbol_canonical,
                "proposal_path":           str(path),
                "marker_path":             str(marker_path),
                "ts_iso":                  _now_iso(),
                "does_not_execute_orders": True,
                "does_not_clear_safe_mode": True,
                "does_not_clear_broker_repair": True,
                "reversible":              True,
                "status":                  "placed",
            }, sort_keys=True, default=str) + "\n")
    except OSError:
        pass

    return path


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="propose_clear_broker_repair_and_safe_mode.py",
        description=(
            "Write a clearance PROPOSAL for an operator. Never calls the "
            "broker, never auto-clears safe_mode or broker_repair_required. "
            "Default is DRY-RUN; --operator-confirmed required to write."
        ),
    )
    p.add_argument("--symbol", required=True,
                   help="Symbol whose quarantine is proposed for clearance.")
    p.add_argument("--operator-marker-path", required=True,
                   help="Path to the operator-confirmation marker written by "
                        "record_operator_repair_confirmation.py.")
    p.add_argument("--dashboard-evidence-note", default="",
                   help="Free-text operator note describing the dashboard "
                        "evidence backing the proposal.")
    p.add_argument("--dry-run", default="true",
                   help="When 'true' (default) print only, no proposal write.")
    p.add_argument("--operator-confirmed", action="store_true",
                   help="REQUIRED to write the proposal file.")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    marker_path = Path(args.operator_marker_path)
    result = evaluate_clearance(args.symbol, marker_path)

    print(f"propose_clear: verdict={result.verdict}")
    print(f"  symbol_input={result.symbol_input!r}")
    print(f"  symbol_canonical={result.symbol_canonical!r}")
    print(f"  marker_ts_iso={result.marker_ts_iso!r}")
    print(f"  broker_repair_present={result.broker_repair_present}")
    print(f"  fresh_p13_count={result.fresh_p13_count}")
    print(f"  fresh_403_count={result.fresh_403_count}")
    print(f"  safe_mode_consistency={result.safe_mode_consistency_verdict}")
    print(f"  equity_gap_block={result.equity_gap_block}")
    if result.refusal_reason:
        print(f"  refusal_reason={result.refusal_reason}")

    dry_run = _str_to_bool(args.dry_run) or (not args.operator_confirmed)

    if result.verdict != "CLEARANCE_PROPOSED":
        # Refused — never write, regardless of --operator-confirmed.
        return 2

    if dry_run:
        print("  dry-run: would write proposal, but --operator-confirmed not "
              "supplied OR --dry-run=true")
        return 0

    proposal = write_proposal(
        result,
        marker_path=marker_path,
        dashboard_evidence_note=str(args.dashboard_evidence_note or ""),
    )
    print(f"  proposal_path: {proposal}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    "NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT",
    "NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
    "ClearanceCheckResult",
    "evaluate_clearance",
    "write_proposal",
    "main",
]

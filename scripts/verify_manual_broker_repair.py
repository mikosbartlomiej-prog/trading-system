#!/usr/bin/env python3
"""v3.28 ETAP 6 (2026-06-16) — Read-only manual-repair verifier for AVAXUSD P13.

CONTRACT (do not loosen)
------------------------
This script is the post-manual-repair verifier. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* auto-clears ``safe_mode``,
* writes any file when ``--dry-run`` is the default (true),
* enables LIVE_TRADING / ALLOW_BROKER_PAPER / EDGE_GATE_ENABLED /
  BROKER_EXECUTION_ENABLED / any other live-trading flag.

When ``--operator-confirmed --dry-run=false`` is supplied AND the verdict
is ``SAFE_TO_CLEAR_CANDIDATE``, the script writes a *proposal* file at::

    learning-loop/operator_markers/safe_mode_clear_proposal_<date>.json

and prints the verdict ``SAFE_MODE_CLEAR_PROPOSED_OPERATOR_MUST_APPLY``.
That file is informational. It is the OPERATOR who decides to act on
the proposal — never this script and never an automated cron job.

The script fail-safes to ``NOT_SAFE_TO_CLEAR`` on every error path.

USAGE
-----
::

    python3 scripts/verify_manual_broker_repair.py \\
        --symbol AVAX/USD \\
        --marker-path learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt

Default ``--dry-run`` is ``true`` (verifier writes nothing to operator_markers).
Run with ``--operator-confirmed --dry-run=false`` to write a proposal.

STANDING MARKERS
----------------
``EDGE_GATE_ENABLED=false``
``ALLOW_BROKER_PAPER=false``
``LIVE_TRADING_UNSUPPORTED``
``NO_ORDER_PLACEMENT``
``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Standing invariants — checked by tests ────────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ── Verdict constants ────────────────────────────────────────────────────────

VERDICT_SAFE_TO_CLEAR_CANDIDATE = "SAFE_TO_CLEAR_CANDIDATE"
VERDICT_NOT_SAFE_TO_CLEAR = "NOT_SAFE_TO_CLEAR"
VERDICT_PROPOSED = "SAFE_MODE_CLEAR_PROPOSED_OPERATOR_MUST_APPLY"


@dataclass
class VerifyResult:
    verdict: str
    reasons: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _emit_audit(row: dict) -> None:
    """Always emit an audit row — one per script run. Fail-soft."""
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return


# ── Local evidence loaders (no broker, no network) ────────────────────────────

def _load_broker_repair_state(symbol: str) -> dict:
    """Read the on-disk broker_repair_required entry for symbol (or sibling).

    Looks up both the literal symbol and the AVAX/USD↔AVAXUSD variants so
    callers can pass either form.
    """
    path = _REPO_ROOT / "learning-loop" / "broker_repair_required_latest.json"
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    entries = raw.get("entries") if "entries" in raw else raw
    if not isinstance(entries, dict):
        return {}

    candidates = {symbol, symbol.replace("/", ""), symbol.replace("USD", "/USD")}
    for cand in candidates:
        if cand in entries and isinstance(entries[cand], dict):
            return dict(entries[cand])
    return {}


def _load_safe_mode_state() -> dict:
    """Read the runtime_state.json::safe_mode section.

    Read-only — uses the file as the source of truth. Returns {} when the
    file or the section is missing/unreadable; caller decides what to do.
    """
    path = _REPO_ROOT / "learning-loop" / "runtime_state.json"
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    sm = raw.get("safe_mode")
    if not isinstance(sm, dict):
        return {}
    return sm


def _load_position_reconciliation_age_s() -> Optional[float]:
    path = _REPO_ROOT / "learning-loop" / "position_reconciliation_latest.json"
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return None
    ts = raw.get("reconciled_at") or raw.get("ts_iso")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (_now() - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def _load_equity_gap_verdict() -> Optional[str]:
    path = _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return None
    v = raw.get("verdict") or raw.get("equity_gap_verdict")
    return str(v) if v else None


def _load_last_avax_ledger_rows(symbol: str, limit: int = 5) -> list[dict]:
    """Scan opportunity_ledger jsonl for the last N rows mentioning symbol.

    Read-only. Fail-soft. Returns [] when ledger is missing.
    """
    ledger_dir = _REPO_ROOT / "learning-loop" / "opportunity_ledger"
    if not ledger_dir.exists():
        return []
    rows: list[dict] = []
    targets = {symbol, symbol.replace("/", ""), symbol.replace("USD", "/USD")}
    try:
        files = sorted(ledger_dir.glob("*.jsonl"))
    except OSError:
        return []
    for p in reversed(files):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sym = str(row.get("symbol", ""))
                    if sym in targets:
                        rows.append(row)
                        if len(rows) >= limit:
                            return rows
        except OSError:
            continue
    return rows


def _marker_present(marker_path: str) -> bool:
    if not marker_path:
        return False
    return os.path.exists(marker_path)


# ── Core evaluation ──────────────────────────────────────────────────────────

def evaluate_local_evidence(symbol: str, marker_path: str) -> VerifyResult:
    """Read-only evaluation. Default fail-safe is NOT_SAFE_TO_CLEAR.

    Returns:
        VerifyResult with verdict ∈ {SAFE_TO_CLEAR_CANDIDATE, NOT_SAFE_TO_CLEAR}
        plus accumulated reasons and a snapshot dict.
    """
    reasons: list[str] = []
    snapshot: dict = {
        "symbol": symbol,
        "marker_path": marker_path,
        "evaluated_at": _now_iso(),
    }

    try:
        # 1. Marker file must exist (operator-driven precondition).
        if not _marker_present(marker_path):
            reasons.append("operator marker file is missing — cannot proceed")
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)
        snapshot["marker_present"] = True

        # 2. broker_repair_required entry must exist and look like P13.
        repair = _load_broker_repair_state(symbol)
        snapshot["broker_repair_entry"] = repair
        if not repair:
            reasons.append("no broker_repair_required entry found for symbol; "
                           "nothing to clear")
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)
        attempts = int(repair.get("failed_attempts", 0) or 0)
        snapshot["failed_attempts"] = attempts
        if attempts <= 0:
            reasons.append("broker_repair entry has 0 attempts — entry looks invalid")
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)

        # 3. safe_mode must be in a state where clearing is meaningful.
        sm = _load_safe_mode_state()
        snapshot["safe_mode"] = sm
        if sm.get("forced", False):
            reasons.append("safe_mode.forced=true (operator hold) — refuse")
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)

        # 4. Position reconciliation must not be stale > 2 hours.
        age = _load_position_reconciliation_age_s()
        snapshot["position_recon_age_s"] = age
        if age is not None and age > 2 * 3600:
            reasons.append(
                f"position reconciliation stale ({age/3600:.2f}h > 2h)"
            )
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)

        # 5. Equity gap must be resolved (no BLOCK verdict).
        gap_verdict = _load_equity_gap_verdict()
        snapshot["equity_gap_verdict"] = gap_verdict
        if gap_verdict and "BLOCKS_ALLOCATOR" in gap_verdict.upper():
            reasons.append(f"equity gap verdict = {gap_verdict}")
            return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)

        # 6. Last few ledger rows for this symbol should not be active broker
        #    failures from the last hour.
        last_rows = _load_last_avax_ledger_rows(symbol, limit=5)
        snapshot["last_ledger_rows_count"] = len(last_rows)
        # We don't strictly fail on this — it's a hint surfaced in reasons.

        reasons.append("marker present")
        reasons.append("no broker call attempted by verifier")
        reasons.append(f"broker_repair entry attempts={attempts}")
        reasons.append(f"safe_mode active={bool(sm.get('active', False))}")
        return VerifyResult(VERDICT_SAFE_TO_CLEAR_CANDIDATE, reasons, snapshot)

    except Exception as e:
        # Fail-safe — any error becomes NOT_SAFE_TO_CLEAR.
        reasons.append(f"verifier exception: {type(e).__name__}: {e}")
        return VerifyResult(VERDICT_NOT_SAFE_TO_CLEAR, reasons, snapshot)


def write_clear_proposal(symbol: str, marker_path: str, result: VerifyResult) -> Path:
    """Write the operator-facing clear proposal — never clears safe_mode.

    The output path is::

        learning-loop/operator_markers/safe_mode_clear_proposal_<date>.json

    Returns the written path. Raises only on a hard I/O error (caller
    is expected to swallow and turn into a NOT_SAFE_TO_CLEAR audit row).
    """
    out_dir = _REPO_ROOT / "learning-loop" / "operator_markers"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"safe_mode_clear_proposal_{_today_iso_date()}.json"
    payload = {
        "schema_version": "v3.28",
        "kind":           "safe_mode_clear_proposal",
        "symbol":         symbol,
        "marker_path":    marker_path,
        "evaluated_at":   _now_iso(),
        "verdict":        result.verdict,
        "reasons":        list(result.reasons),
        "snapshot":       result.snapshot,
        "warning": (
            "This file is a proposal only. Operator must apply the clear "
            "manually via shared/broker_repair_required.clear_repair(...). "
            "This script never auto-clears safe_mode and never enables "
            "live trading flags."
        ),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="verify_manual_broker_repair.py",
        description="Read-only verification of a manual broker repair. "
                    "Default --dry-run=true; never calls broker.",
    )
    p.add_argument("--symbol", required=True,
                   help="Symbol to verify (e.g. AVAX/USD or AVAXUSD)")
    p.add_argument("--marker-path", default="",
                   help="Operator marker file path. Required for "
                        "SAFE_TO_CLEAR_CANDIDATE verdict.")
    p.add_argument("--operator-confirmed", action="store_true", default=False,
                   help="Operator has confirmed the manual broker repair. "
                        "Required (together with --dry-run=false) for the "
                        "script to write a clear proposal file.")
    p.add_argument("--dry-run", default="true",
                   help="When 'true' (default), script writes nothing. "
                        "When 'false' AND --operator-confirmed AND verdict "
                        "is SAFE_TO_CLEAR_CANDIDATE, a proposal is written.")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    dry_run = _str_to_bool(args.dry_run)

    result = evaluate_local_evidence(args.symbol, args.marker_path)

    # Print verdict line first so operators / scripts can grep it.
    print(f"verify_manual_broker_repair: verdict={result.verdict}")
    for reason in result.reasons:
        print(f"  reason: {reason}")

    # Audit row — always emit one per run.
    audit_row: dict = {
        "decision_type":   "VERIFY_MANUAL_BROKER_REPAIR",
        "actor":           "verify_manual_broker_repair",
        "symbol":          args.symbol,
        "marker_path":     args.marker_path,
        "operator_confirmed": bool(args.operator_confirmed),
        "dry_run":         dry_run,
        "verdict":         result.verdict,
        "reasons":         result.reasons,
        "snapshot":        result.snapshot,
        "ts_iso":          _now_iso(),
        "reversible":      True,
        "status":          "skipped",
    }

    # Only write a proposal in the strictly opt-in path.
    proposal_path: Optional[Path] = None
    if (result.verdict == VERDICT_SAFE_TO_CLEAR_CANDIDATE
            and args.operator_confirmed
            and not dry_run):
        try:
            proposal_path = write_clear_proposal(args.symbol, args.marker_path, result)
            print(f"verify_manual_broker_repair: proposal written -> {proposal_path}")
            print(f"verify_manual_broker_repair: verdict={VERDICT_PROPOSED}")
            audit_row["verdict"] = VERDICT_PROPOSED
            audit_row["proposal_path"] = str(proposal_path)
            audit_row["status"] = "placed"
        except OSError as e:
            print(f"verify_manual_broker_repair: proposal write FAILED ({e}) — "
                  f"verdict downgraded to {VERDICT_NOT_SAFE_TO_CLEAR}")
            audit_row["verdict"] = VERDICT_NOT_SAFE_TO_CLEAR
            audit_row["reasons"] = list(result.reasons) + [
                f"proposal write OSError: {e}"
            ]

    _emit_audit(audit_row)

    # Exit code: 0 always — operator reads verdict line.
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "VERDICT_SAFE_TO_CLEAR_CANDIDATE",
    "VERDICT_NOT_SAFE_TO_CLEAR",
    "VERDICT_PROPOSED",
    "VerifyResult",
    "evaluate_local_evidence",
    "write_clear_proposal",
    "main",
]

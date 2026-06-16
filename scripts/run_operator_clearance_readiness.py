#!/usr/bin/env python3
"""v3.31 ETAP 2 (2026-06-16) — Consolidated operator-clearance readiness wrapper.

CONTRACT (do not loosen)
------------------------
This script is **read-mostly**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* clears safe_mode,
* clears the broker_repair_required quarantine,
* fabricates operator markers,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``,
* places, cancels, or modifies orders,
* mutates risk thresholds.

It ONLY:

* enumerates the canonical broker_repair_required symbols on disk,
* validates the per-symbol operator-confirmation marker via
  :func:`shared.operator_repair_state.has_repair_confirmation`,
* validates that the marker timestamp is >= the last failure
  timestamp captured on the broker_repair_required entry,
* validates that NO fresh P13 audit event landed after the marker,
* validates that NO fresh retry-storm event landed after the marker,
* validates broker_repair_required entry exists for the canonical key,
* reads (does NOT compute) the safe_mode_consistency verdict,
* reads (does NOT compute) the equity_gap_reconciliation verdict,
* reads (does NOT compute) the system_activation_gate decision,
* writes a per-symbol + overall readiness summary to
  ``docs/OPERATOR_CLEARANCE_READINESS.md`` plus a JSON twin at
  ``learning-loop/operator_clearance_readiness_latest.json``,
* delegates per-symbol PROPOSAL writes (only when ``--apply`` and
  ``--operator-confirmed`` are both supplied AND verdict is
  ``READY_TO_PROPOSE_CLEARANCE``) to
  ``scripts/propose_clear_broker_repair_and_safe_mode.py`` via its
  internal Python API — never auto-applies, never auto-clears,
  never modifies state files beyond the dated readiness JSON +
  markdown.

USAGE
-----
::

  # Default: dry-run, write readiness summary only, no proposals.
  python3 scripts/run_operator_clearance_readiness.py

  # Write per-symbol clearance proposals for every READY symbol.
  python3 scripts/run_operator_clearance_readiness.py \\
      --apply --operator-confirmed \\
      --dashboard-evidence-note "manually verified on 2026-06-16"

Without ``--apply --operator-confirmed`` the script refuses to write
any proposal and only emits the readiness summary.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
- ``NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT``
- ``NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT``
- ``TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
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
TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER = True


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

# Leaf modules — no broker imports.
import operator_repair_state as ors                # noqa: E402
import broker_repair_required as brr               # noqa: E402
import symbol_normalization as sym_norm            # noqa: E402

# Per-symbol proposal writer (v3.30). Imported lazily inside the apply
# branch so the dry-run path doesn't pay the import cost.
try:
    import propose_clear_broker_repair_and_safe_mode as propose_mod  # noqa: E402
except Exception:  # pragma: no cover — import guard for older trees
    propose_mod = None  # type: ignore


# Per-symbol verdicts emitted by ``_evaluate_symbol``.
V_NOT_READY_NO_MARKER = "NOT_READY_NO_MARKER"
V_NOT_READY_FRESH_P13 = "NOT_READY_FRESH_P13_AFTER_MARKER"
V_NOT_READY_SAFE_MODE = "NOT_READY_SAFE_MODE_INCONSISTENT"
V_NOT_READY_EQUITY = "NOT_READY_EQUITY_GAP"
V_NOT_READY_NO_BROKER_REPAIR = "NOT_READY_BROKER_REPAIR_STILL_ACTIVE"
V_READY_TO_PROPOSE = "READY_TO_PROPOSE_CLEARANCE"
V_PROPOSAL_WRITTEN = "CLEARANCE_PROPOSAL_WRITTEN"
V_READY_MANUAL = "READY_FOR_OPERATOR_MANUAL_APPLY"

# Verdicts that are valid `overall_verdict` values when at least one
# symbol is ready and dry-run is in effect.
_DRY_RUN_READY_VERDICTS = {V_READY_TO_PROPOSE, V_READY_MANUAL}


# ── Path helpers ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


def _readiness_json_path() -> Path:
    env = os.environ.get("OPERATOR_CLEARANCE_READINESS_JSON")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "operator_clearance_readiness_latest.json"


def _readiness_md_path() -> Path:
    env = os.environ.get("OPERATOR_CLEARANCE_READINESS_MD")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs" / "OPERATOR_CLEARANCE_READINESS.md"


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


def _system_activation_path() -> Path:
    env = os.environ.get("SYSTEM_ACTIVATION_STATUS_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "system_activation_status_latest.json"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


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


# ── Standing-marker block ─────────────────────────────────────────────────────

def standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        "NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT",
        "NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT",
        "TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER",
    ]


# ── Result dataclasses ───────────────────────────────────────────────────────

@dataclass
class SymbolReadiness:
    symbol_canonical: str
    verdict: str
    refusal_reason: Optional[str] = None
    marker_present: bool = False
    marker_ts_iso: Optional[str] = None
    last_failure_ts_iso: Optional[str] = None
    fresh_p13_count: int = 0
    fresh_403_count: int = 0
    broker_repair_present: bool = False
    proposal_path: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OverallReadiness:
    evaluated_at_iso: str
    overall_verdict: str
    symbols: list[SymbolReadiness]
    safe_mode_consistency_verdict: str
    safe_mode_consistency_blocker: Optional[str]
    equity_gap_block_allocator: bool
    equity_gap_verdict: str
    system_activation_decision: str
    apply_requested: bool
    operator_confirmed: bool
    dry_run: bool
    standing_markers: list[str] = field(default_factory=standing_markers)

    def to_dict(self) -> dict:
        return {
            "schema_version":           "v3.31",
            "evaluated_at_iso":         self.evaluated_at_iso,
            "overall_verdict":          self.overall_verdict,
            "symbols": [s.to_dict() for s in self.symbols],
            "safe_mode_consistency": {
                "verdict": self.safe_mode_consistency_verdict,
                "blocker": self.safe_mode_consistency_blocker,
            },
            "equity_gap": {
                "block_allocator": self.equity_gap_block_allocator,
                "verdict":         self.equity_gap_verdict,
            },
            "system_activation_decision": self.system_activation_decision,
            "apply_requested":            self.apply_requested,
            "operator_confirmed":         self.operator_confirmed,
            "dry_run":                    self.dry_run,
            "does_not_execute_orders":    True,
            "does_not_auto_clear_safe_mode": True,
            "does_not_auto_clear_broker_repair": True,
            "standing_markers":           self.standing_markers,
        }


# ── Audit append (best-effort, never raises) ──────────────────────────────────

def _append_audit(event: dict) -> None:
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    except OSError:
        return


# ── Fresh-incident counter (re-uses propose_clear logic when available) ───────

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
    """Return (fresh_p13_count, fresh_403_count) strictly AFTER ``after_iso``
    for the canonical symbol or any of its aliases.

    Reads JSONL audit files. Fail-soft on any I/O error.
    """
    after_dt = _parse_iso(after_iso)
    if after_dt is None:
        return 0, 0
    aliases = sym_norm.aliases_for(symbol_canonical)
    sym_set = {str(a).upper() for a in aliases}
    sym_set.add(symbol_canonical.upper())

    p13 = 0
    err403 = 0

    audit_root = _audit_dir()
    if not audit_root.exists():
        return 0, 0

    today = _now().date()
    for delta in range(0, max(1, int(lookback_days)) + 1):
        day = today.fromordinal(today.toordinal() - delta).isoformat()
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
                    sym_field = str(row.get("symbol") or "").upper()
                    affected = row.get("affected_symbols") or []
                    affected_upper = {str(s).upper() for s in affected if s}
                    matched = (
                        sym_field in sym_set
                        or bool(sym_set & affected_upper)
                    )
                    if not matched:
                        reason_blob = (
                            str(row.get("reason") or "")
                            + " " + str(row.get("last_error") or "")
                        ).upper()
                        if not any(a in reason_blob for a in sym_set):
                            continue

                    dt = str(row.get("decision_type") or "")
                    if dt in P13_DECISION_TYPES:
                        p13 += 1
                    err_blob = (
                        str(row.get("last_error") or "")
                        + " " + str(row.get("error") or "")
                        + " " + str(row.get("reason") or "")
                    ).lower()
                    if any(m in err_blob for m in ERROR_403_MARKERS):
                        err403 += 1
        except OSError:
            continue

    return p13, err403


# ── Per-symbol evaluation ─────────────────────────────────────────────────────

def _evaluate_symbol(symbol_canonical: str,
                     *,
                     safe_mode_blocker: Optional[str],
                     equity_gap_block: bool) -> SymbolReadiness:
    """Pure read-only per-symbol verdict.

    Order of refusal (first match wins, fail-closed):

    1. broker_repair entry no longer present → nothing to clear.
    2. No operator marker → NOT_READY_NO_MARKER.
    3. Marker present but stale vs last_failure_ts → NOT_READY_FRESH_P13.
    4. safe_mode_consistency blocker → NOT_READY_SAFE_MODE.
    5. equity_gap blocker → NOT_READY_EQUITY.
    6. Fresh P13 / 403 events after marker → NOT_READY_FRESH_P13.
    7. else → READY_TO_PROPOSE_CLEARANCE.
    """
    out = SymbolReadiness(symbol_canonical=symbol_canonical, verdict=V_NOT_READY_NO_MARKER)

    # 1. broker_repair_required must currently flag the canonical symbol.
    try:
        state = brr.load_state()
    except Exception:
        state = {}
    entry = state.get(symbol_canonical)
    if entry is None:
        out.verdict = V_NOT_READY_NO_BROKER_REPAIR
        out.refusal_reason = (
            f"broker_repair_required does not currently flag "
            f"{symbol_canonical!r} — nothing to clear"
        )
        return out
    out.broker_repair_present = True
    out.last_failure_ts_iso = getattr(entry, "last_seen_iso", None) or None

    # 2. Operator marker presence.
    marker = ors.load_marker(symbol_canonical)
    if marker is None:
        out.verdict = V_NOT_READY_NO_MARKER
        out.refusal_reason = (
            f"no operator marker found for {symbol_canonical!r}; "
            f"run scripts/record_operator_repair_confirmation.py --symbol "
            f"{symbol_canonical} --operator-confirmed first"
        )
        return out
    out.marker_present = True
    out.marker_ts_iso = str(getattr(marker, "timestamp_iso", "")) or None

    # 3. Marker timestamp must be >= last failure timestamp (if any).
    if out.marker_ts_iso and out.last_failure_ts_iso:
        m_ts = _parse_iso(out.marker_ts_iso)
        f_ts = _parse_iso(out.last_failure_ts_iso)
        if m_ts is not None and f_ts is not None and m_ts < f_ts:
            out.verdict = V_NOT_READY_FRESH_P13
            out.refusal_reason = (
                f"marker timestamp {out.marker_ts_iso} predates last "
                f"failure {out.last_failure_ts_iso}; rerun the manual "
                "repair AFTER the last failure"
            )
            return out

    # 4. safe_mode_consistency blocker.
    if safe_mode_blocker:
        out.verdict = V_NOT_READY_SAFE_MODE
        out.refusal_reason = (
            f"safe_mode_consistency blocker={safe_mode_blocker!r} — "
            "must be resolved before clearance"
        )
        return out

    # 5. equity_gap blocker.
    if equity_gap_block:
        out.verdict = V_NOT_READY_EQUITY
        out.refusal_reason = (
            "equity_gap_reconciliation_latest reports block_allocator=true"
        )
        return out

    # 6. Fresh P13 / 403 events after marker timestamp.
    if out.marker_ts_iso:
        p13, err403 = _count_fresh_incidents(symbol_canonical, out.marker_ts_iso)
        out.fresh_p13_count = p13
        out.fresh_403_count = err403
        if p13 > 0 or err403 > 0:
            out.verdict = V_NOT_READY_FRESH_P13
            out.refusal_reason = (
                f"fresh incidents detected after marker timestamp: "
                f"p13={p13} 403/insufficient={err403}; repair did not stick"
            )
            return out

    # 7. All clear.
    out.verdict = V_READY_TO_PROPOSE
    return out


# ── Overall evaluation ───────────────────────────────────────────────────────

def evaluate_readiness(*,
                       apply_requested: bool,
                       operator_confirmed: bool,
                       dashboard_evidence_note: str = "",
                       ) -> OverallReadiness:
    """Read-only end-to-end evaluation across all canonical repair symbols.

    Even with ``apply_requested=True`` no clearance proposal is written
    unless ``operator_confirmed=True`` AND the per-symbol verdict is
    ``READY_TO_PROPOSE_CLEARANCE``. The script never auto-clears
    safe_mode or broker_repair_required.
    """
    # Enumerate canonical broker_repair_required keys.
    try:
        state = brr.load_state()
    except Exception:
        state = {}
    canonical_symbols = sorted(state.keys())

    # Read top-level inputs.
    smc = _read_json(_safe_mode_consistency_path()) or {}
    smc_verdict = str(smc.get("verdict", "UNKNOWN"))
    smc_blocker_raw = smc.get("blocker")
    smc_blocker: Optional[str] = None
    if smc_blocker_raw:
        smc_blocker = str(smc_blocker_raw)
    elif smc_verdict and (
        smc_verdict.startswith("INCONSISTENT")
        or smc_verdict == "STALE_ACTIVE"
    ):
        smc_blocker = smc_verdict

    egap = _read_json(_equity_gap_path()) or {}
    egap_block = bool(egap.get("block_allocator", False))
    egap_verdict = str(egap.get("verdict", "UNKNOWN"))

    sa = _read_json(_system_activation_path()) or {}
    sa_decision = str(sa.get("decision", "UNKNOWN"))

    # Per-symbol verdicts.
    syms: list[SymbolReadiness] = []
    for sym in canonical_symbols:
        syms.append(_evaluate_symbol(
            sym,
            safe_mode_blocker=smc_blocker,
            equity_gap_block=egap_block,
        ))

    # If there are no broker_repair entries at all, still emit a summary
    # with overall = READY_FOR_OPERATOR_MANUAL_APPLY (nothing to do).
    if not syms:
        overall = V_READY_MANUAL
    else:
        # Highest-severity verdict wins; first found in this order:
        priority = [
            V_NOT_READY_SAFE_MODE,
            V_NOT_READY_EQUITY,
            V_NOT_READY_FRESH_P13,
            V_NOT_READY_NO_MARKER,
            V_NOT_READY_NO_BROKER_REPAIR,
            V_READY_TO_PROPOSE,
        ]
        verdict_set = {s.verdict for s in syms}
        overall = V_READY_TO_PROPOSE
        for v in priority:
            if v in verdict_set:
                overall = v
                break

    # Apply path: write proposal per READY symbol if confirmed.
    dry_run = not (apply_requested and operator_confirmed)
    if not dry_run and overall == V_READY_TO_PROPOSE and propose_mod is not None:
        for s in syms:
            if s.verdict != V_READY_TO_PROPOSE:
                continue
            try:
                marker_path = ors._latest_marker_for(s.symbol_canonical)
                if marker_path is None or not marker_path.exists():
                    # Shouldn't happen — _evaluate_symbol already checked.
                    continue
                result = propose_mod.evaluate_clearance(
                    s.symbol_canonical, marker_path
                )
                if result.verdict != "CLEARANCE_PROPOSED":
                    # propose_mod ran its own stricter checks; honour them.
                    continue
                p_path = propose_mod.write_proposal(
                    result,
                    marker_path=marker_path,
                    dashboard_evidence_note=dashboard_evidence_note,
                )
                s.proposal_path = str(p_path)
                s.verdict = V_PROPOSAL_WRITTEN
            except Exception as e:  # pragma: no cover — defensive
                s.refusal_reason = (
                    f"propose_clear_broker_repair_and_safe_mode raised "
                    f"{type(e).__name__}: {e}"
                )
                # Leave verdict at READY_TO_PROPOSE so operator sees the gap.
        if all(s.verdict == V_PROPOSAL_WRITTEN for s in syms):
            overall = V_PROPOSAL_WRITTEN
        elif any(s.verdict == V_PROPOSAL_WRITTEN for s in syms):
            overall = V_PROPOSAL_WRITTEN

    out = OverallReadiness(
        evaluated_at_iso=_now_iso(),
        overall_verdict=overall,
        symbols=syms,
        safe_mode_consistency_verdict=smc_verdict,
        safe_mode_consistency_blocker=smc_blocker,
        equity_gap_block_allocator=egap_block,
        equity_gap_verdict=egap_verdict,
        system_activation_decision=sa_decision,
        apply_requested=apply_requested,
        operator_confirmed=operator_confirmed,
        dry_run=dry_run,
    )
    return out


# ── Output writers ───────────────────────────────────────────────────────────

def _write_json(result: OverallReadiness) -> Path:
    path = _readiness_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


def _write_markdown(result: OverallReadiness) -> Path:
    path = _readiness_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Operator clearance readiness")
    lines.append("")
    lines.append(f"- Evaluated at: `{result.evaluated_at_iso}`")
    lines.append(f"- Overall verdict: **`{result.overall_verdict}`**")
    lines.append(f"- Dry-run: `{result.dry_run}`")
    lines.append(f"- Apply requested: `{result.apply_requested}`")
    lines.append(f"- Operator confirmed: `{result.operator_confirmed}`")
    lines.append(
        f"- safe_mode_consistency verdict: `{result.safe_mode_consistency_verdict}`"
        f" (blocker={result.safe_mode_consistency_blocker!r})"
    )
    lines.append(
        f"- equity_gap_reconciliation: block_allocator="
        f"`{result.equity_gap_block_allocator}` verdict="
        f"`{result.equity_gap_verdict}`"
    )
    lines.append(
        f"- system_activation_gate decision: "
        f"`{result.system_activation_decision}`"
    )
    lines.append("")
    lines.append("## Per-symbol readiness")
    lines.append("")
    lines.append(
        "| Symbol | Verdict | Marker | Broker repair | Marker ts | "
        "Last failure ts | Fresh P13 | Fresh 403 | Proposal | Refusal |"
    )
    lines.append(
        "|--------|---------|--------|---------------|-----------|"
        "-----------------|-----------|-----------|----------|---------|"
    )
    for s in result.symbols:
        lines.append(
            f"| `{s.symbol_canonical}` | `{s.verdict}` "
            f"| `{s.marker_present}` | `{s.broker_repair_present}` "
            f"| `{s.marker_ts_iso}` | `{s.last_failure_ts_iso}` "
            f"| {s.fresh_p13_count} | {s.fresh_403_count} "
            f"| `{s.proposal_path}` | {s.refusal_reason or ''} |"
        )
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in result.standing_markers:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append(
        "_This wrapper NEVER calls the broker, NEVER imports broker plumbing,"
        " NEVER clears safe_mode, NEVER clears broker_repair_required,"
        " NEVER flips live flags, NEVER fabricates markers. Templates under"
        " `docs/operator_repair_templates/` and"
        " `learning-loop/operator_markers/templates/` do NOT count as"
        " markers._"
    )

    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_operator_clearance_readiness.py",
        description=(
            "Consolidated operator-clearance readiness check across all "
            "broker_repair_required symbols. Default DRY-RUN; writes only "
            "the readiness summary. Use --apply --operator-confirmed to "
            "delegate per-symbol PROPOSAL writes — even then nothing is "
            "auto-cleared."
        ),
    )
    p.add_argument("--apply", action="store_true",
                   help="Request per-symbol proposal writes. Refused "
                        "without --operator-confirmed.")
    p.add_argument("--operator-confirmed", action="store_true",
                   help="Required alongside --apply to actually write "
                        "per-symbol proposals.")
    p.add_argument("--dry-run", default="true",
                   help="'true' (default) forces dry-run regardless of "
                        "--apply/--operator-confirmed. 'false' lets the "
                        "other two flags decide.")
    p.add_argument("--dashboard-evidence-note", default="",
                   help="Free-text operator note attached to proposals "
                        "when --apply --operator-confirmed is supplied.")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    forced_dry = _str_to_bool(args.dry_run)
    apply_requested = bool(args.apply) and not forced_dry
    operator_confirmed = bool(args.operator_confirmed) and not forced_dry

    # apply requested but operator NOT confirmed → still write summary,
    # but refuse to write any proposal.
    refused_apply = bool(args.apply) and not bool(args.operator_confirmed)

    result = evaluate_readiness(
        apply_requested=apply_requested,
        operator_confirmed=operator_confirmed,
        dashboard_evidence_note=str(args.dashboard_evidence_note or ""),
    )

    json_path = _write_json(result)
    md_path = _write_markdown(result)

    _append_audit({
        "decision_type":   "OPERATOR_CLEARANCE_READINESS_EVALUATED",
        "actor":           "run_operator_clearance_readiness",
        "overall_verdict": result.overall_verdict,
        "n_symbols":       len(result.symbols),
        "apply_requested": apply_requested,
        "operator_confirmed": operator_confirmed,
        "dry_run":         result.dry_run,
        "json_path":       str(json_path),
        "md_path":         str(md_path),
        "ts_iso":          _now_iso(),
        "does_not_execute_orders": True,
        "does_not_clear_safe_mode": True,
        "does_not_clear_broker_repair": True,
        "reversible":      True,
        "status":          "placed",
    })

    print(f"overall_verdict={result.overall_verdict}")
    print(f"  symbols_checked={len(result.symbols)}")
    print(f"  dry_run={result.dry_run}")
    print(f"  apply_requested={result.apply_requested}")
    print(f"  operator_confirmed={result.operator_confirmed}")
    print(f"  json={json_path}")
    print(f"  md={md_path}")
    for m in standing_markers():
        print(f"  standing_marker={m}")
    if refused_apply:
        print("  refused_apply: --apply requires --operator-confirmed too")
    return 0


if __name__ == "__main__":
    sys.exit(main())

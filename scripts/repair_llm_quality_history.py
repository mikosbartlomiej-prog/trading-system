#!/usr/bin/env python3
"""v3.30.1 (2026-06-09) — LLM quality history self-healing repair.

Reconciles ``learning-loop/llm_advisory/quality_history.jsonl`` with the
latest ``quality_review_latest.json`` snapshot WITHOUT ever marking a
stale, mock, placeholder, or source-mismatched run as
``accepted_for_unlock_counting=true``.

Append-only. Never deletes a history row. Never rewrites old rows.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER calls ``submit_order`` / ``place_order`` / ``safe_close``.
- NEVER mutates readiness counters / shadow evidence counters.
- NEVER places orders.
- NEVER marks a stale / mock / placeholder / source-mismatched row as
  ``accepted_for_unlock_counting=true``.
- Refuses (exit 1) if any of the 7 broker-execution / live env flags
  is truthy.

This module is intentionally standalone — it does NOT import the
v3.30.1 broker-orders module (and never will).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Status enum ────────────────────────────────────────────────────────────

QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT          = (
    "QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT")
QUALITY_HISTORY_ALREADY_CONSISTENT                 = (
    "QUALITY_HISTORY_ALREADY_CONSISTENT")
QUALITY_HISTORY_REPAIR_BLOCKED_SOURCE_MISMATCH     = (
    "QUALITY_HISTORY_REPAIR_BLOCKED_SOURCE_MISMATCH")
QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED       = (
    "QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED")
QUALITY_HISTORY_REPAIRED_ACCEPTABLE_CONFIRMED      = (
    "QUALITY_HISTORY_REPAIRED_ACCEPTABLE_CONFIRMED")

ALL_REPAIR_STATUSES = frozenset({
    QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT,
    QUALITY_HISTORY_ALREADY_CONSISTENT,
    QUALITY_HISTORY_REPAIR_BLOCKED_SOURCE_MISMATCH,
    QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED,
    QUALITY_HISTORY_REPAIRED_ACCEPTABLE_CONFIRMED,
})

# Substrings (case-insensitive) that identify mock/test/placeholder
# run_ids. None of these are ever allowed to count toward unlock.
_MOCK_PATTERNS = (
    "mock",
    "test",
    "placeholder",
    "-mock-",
    "-test-",
    "fake",
    "sample",
)

_STANDING_MARKERS = [
    "NO_MANUAL_REPO_VARIABLE_REQUIRED_FOR_CALIBRATION",
    "STALE_MOCK_QUALITY_NEVER_COUNTS_AS_ACCEPTABLE",
    "CALIBRATION_BOUNDED_FREE_ONLY_GEMINI",
    "PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED",
    "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
    "CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY",
    "NO_ORDER_PLACEMENT",
    "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
    "LIVE_TRADING_UNSUPPORTED",
    "DETERMINISTIC_GATES_REMAIN_FINAL",
]


# ─── Helpers ────────────────────────────────────────────────────────────────

def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_or_live_truthy() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _safe_read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_history(history_path: Path) -> list[dict]:
    if not history_path.exists():
        return []
    out: list[dict] = []
    try:
        for line in history_path.read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


def _is_mock_pattern(run_id: str) -> bool:
    if not run_id:
        return False
    rid = run_id.lower()
    return any(pat in rid for pat in _MOCK_PATTERNS)


def _is_stale_snapshot(qrep: dict) -> bool:
    """Anti-mock guards. Mirrors the contract enforced by
    ``broker_paper_canary_unlock._quality_row_passes_anti_mock``.

    Returns True (stale) when ANY of:
      - rows_with_provider_used <= 0
      - secret_leak_hits > 0
      - unsafe_phrase_hits > 0
      - rows_seen <= 0
      - every row had empty risks AND empty next-actions AND zero
        confidence (schema-shaped but empty payload).
    """
    if not qrep or not isinstance(qrep, dict):
        return True
    if int(qrep.get("rows_with_provider_used", 0) or 0) <= 0:
        return True
    if int(qrep.get("secret_leak_hits", 0) or 0) > 0:
        return True
    if int(qrep.get("unsafe_phrase_hits", 0) or 0) > 0:
        return True
    rows_seen = int(qrep.get("rows_seen", 0) or 0)
    if rows_seen <= 0:
        return True
    if (int(qrep.get("empty_risks_count", 0) or 0) == rows_seen
            and int(qrep.get(
                "empty_next_actions_count", 0) or 0) == rows_seen
            and int(qrep.get(
                "zero_confidence_count", 0) or 0) == rows_seen):
        return True
    return False


def _source_mismatch(latest: dict) -> tuple[bool, str]:
    """Top-level ``quality_status`` must match embedded
    ``quality_report.status`` when both are present.
    """
    qrep = latest.get("quality_report") or {}
    status_top = latest.get("quality_status")
    status_rep = qrep.get("status")
    if status_top is None or status_rep is None:
        return False, "no embedded report.status — nothing to mismatch"
    if status_top != status_rep:
        return True, (
            f"quality_review_latest mismatch: "
            f"top={status_top} vs report={status_rep}")
    return False, "no mismatch"


def _entry_from_latest(latest: dict, *,
                          accepted: bool,
                          ) -> dict:
    qrep = latest.get("quality_report") or {}
    return {
        "appended_at_iso":          datetime.now(
            timezone.utc).isoformat(),
        "run_id":                   latest.get("run_id"),
        "quality_status":           latest.get("quality_status"),
        "rows_seen":                int(qrep.get(
            "rows_seen", 0) or 0),
        "rows_with_provider_used":  int(qrep.get(
            "rows_with_provider_used", 0) or 0),
        "empty_risks_count":        int(qrep.get(
            "empty_risks_count", 0) or 0),
        "empty_next_actions_count": int(qrep.get(
            "empty_next_actions_count", 0) or 0),
        "zero_confidence_count":    int(qrep.get(
            "zero_confidence_count", 0) or 0),
        "secret_leak_hits":         int(qrep.get(
            "secret_leak_hits", 0) or 0),
        "unsafe_phrase_hits":       int(qrep.get(
            "unsafe_phrase_hits", 0) or 0),
        "selected_provider":        latest.get(
            "selected_provider"),
        "selected_model":           latest.get("selected_model"),
        "free_only":                bool(latest.get(
            "free_only", True)),
        "accepted_for_unlock_counting": bool(accepted),
        "repair_origin":            "v3.30.1_history_self_heal",
    }


def _append_history_row(history_path: Path, entry: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _build_payload(*,
                      repair_status: str,
                      latest_run_id: str | None,
                      rationale: list[str],
                      anti_mock_passed: bool,
                      source_mismatch: bool,
                      stale: bool,
                      mock_pattern: bool,
                      accepted: bool,
                      ) -> dict:
    return {
        "version":                  "v3.30.1",
        "generated_at_iso":         datetime.now(
            timezone.utc).isoformat(),
        "latest_run_id":            latest_run_id,
        "repair_status":            repair_status,
        "rationale":                list(rationale),
        "anti_mock_passed":         bool(anti_mock_passed),
        "source_mismatch":          bool(source_mismatch),
        "stale":                    bool(stale),
        "mock_pattern":             bool(mock_pattern),
        "accepted_for_unlock_counting": bool(accepted),
        "safety": {
            "broker_paper_canary_still_blocked":  True,
            "live_trading_unsupported":           True,
            "no_order_placement_in_v3301":        True,
            "edge_gate_enabled":                  False,
            "allow_broker_paper":                 False,
            "broker_execution_enabled":           False,
            "schedule_enabled":                   False,
            "llm_pre_order_veto_honored":         False,
            "deterministic_gates_remain_final":   True,
        },
        "standing_markers":         list(_STANDING_MARKERS),
    }


def _write_artifacts(payload: dict) -> None:
    json_path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                  / "quality_history_repair_latest.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    doc_path = REPO_ROOT / "docs" / "LLM_QUALITY_HISTORY_REPAIR_STATUS.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# LLM Quality History Repair Status (v3.30.1)\n",
        f"- **Repair status:** `{payload.get('repair_status')}`",
        f"- **Latest run_id:** `{payload.get('latest_run_id')}`",
        f"- **Anti-mock passed:** "
        f"{str(payload.get('anti_mock_passed')).lower()}",
        f"- **Source mismatch:** "
        f"{str(payload.get('source_mismatch')).lower()}",
        f"- **Stale snapshot:** "
        f"{str(payload.get('stale')).lower()}",
        f"- **Mock-pattern run_id:** "
        f"{str(payload.get('mock_pattern')).lower()}",
        f"- **Accepted for unlock counting:** "
        f"{str(payload.get('accepted_for_unlock_counting')).lower()}",
        "",
        "## Rationale\n",
    ]
    for r in payload.get("rationale") or []:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## Safety invariants\n")
    for k, v in sorted((payload.get("safety") or {}).items()):
        lines.append(f"- `{k}`: **{str(v).lower()}**")
    lines.append("")
    lines.append("## Standing markers\n")
    for m in payload.get("standing_markers") or []:
        lines.append(f"- `{m}`")
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Core reconciliation ────────────────────────────────────────────────────

def reconcile(*,
                 latest_path: Path | None = None,
                 history_path: Path | None = None,
                 write_artifacts: bool = False,
                 ) -> dict:
    """Pure function: read inputs, decide repair status, optionally
    append a history row + write artefacts. Never raises.
    """
    latest_path = latest_path or (
        REPO_ROOT / "learning-loop" / "llm_advisory"
        / "quality_review_latest.json")
    history_path = history_path or (
        REPO_ROOT / "learning-loop" / "llm_advisory"
        / "quality_history.jsonl")

    latest = _safe_read_json(latest_path)
    if not latest:
        payload = _build_payload(
            repair_status=QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT,
            latest_run_id=None,
            rationale=["quality_review_latest.json missing or empty"],
            anti_mock_passed=False,
            source_mismatch=False,
            stale=False,
            mock_pattern=False,
            accepted=False,
        )
        if write_artifacts:
            try:
                _write_artifacts(payload)
            except Exception:
                pass
        return payload

    latest_run_id = latest.get("run_id") or None
    if not latest_run_id:
        payload = _build_payload(
            repair_status=QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT,
            latest_run_id=None,
            rationale=[
                "quality_review_latest.json has no run_id"],
            anti_mock_passed=False,
            source_mismatch=False,
            stale=False,
            mock_pattern=False,
            accepted=False,
        )
        if write_artifacts:
            try:
                _write_artifacts(payload)
            except Exception:
                pass
        return payload

    qrep = latest.get("quality_report") or {}
    quality_status_top = latest.get("quality_status")
    stale = _is_stale_snapshot(qrep)
    mock_pattern = _is_mock_pattern(latest_run_id)
    mismatch, mismatch_reason = _source_mismatch(latest)
    anti_mock_passed = (not stale) and (not mock_pattern) and (
        not mismatch)

    history = _read_history(history_path)
    existing_entry = None
    for h in history:
        if h.get("run_id") == latest_run_id:
            existing_entry = h
            break

    # ── Already-consistent path ────────────────────────────────────────
    if existing_entry is not None:
        # Already present in history. Determine whether it is in a
        # consistent state (anti-mock pass + accepted) or whether the
        # current run has been correctly recorded as rejected.
        entry_accepted = bool(existing_entry.get(
            "accepted_for_unlock_counting", False))
        # Consistent = (anti_mock_passed iff entry_accepted) AND
        #              top status matches history status.
        history_status = existing_entry.get("quality_status")
        statuses_match = (
            history_status is None
            or quality_status_top is None
            or history_status == quality_status_top)
        consistent = (
            statuses_match
            and (anti_mock_passed == entry_accepted))
        if consistent:
            payload = _build_payload(
                repair_status=QUALITY_HISTORY_ALREADY_CONSISTENT,
                latest_run_id=latest_run_id,
                rationale=[
                    f"run_id={latest_run_id} already in history; "
                    f"anti_mock_passed={anti_mock_passed}; "
                    f"accepted_for_unlock_counting="
                    f"{entry_accepted}"],
                anti_mock_passed=anti_mock_passed,
                source_mismatch=mismatch,
                stale=stale,
                mock_pattern=mock_pattern,
                accepted=entry_accepted,
            )
            if write_artifacts:
                try:
                    _write_artifacts(payload)
                except Exception:
                    pass
            return payload

    # ── Repair path: append-only ───────────────────────────────────────
    # Source mismatch wins first.
    if mismatch:
        rationale = [
            f"source mismatch detected: {mismatch_reason}",
            "appending rejected history row "
            "(accepted_for_unlock_counting=false)",
        ]
        if existing_entry is None:
            entry = _entry_from_latest(latest, accepted=False)
            try:
                _append_history_row(history_path, entry)
            except Exception:
                rationale.append("append failed (non-fatal)")
        payload = _build_payload(
            repair_status=(
                QUALITY_HISTORY_REPAIR_BLOCKED_SOURCE_MISMATCH),
            latest_run_id=latest_run_id,
            rationale=rationale,
            anti_mock_passed=False,
            source_mismatch=True,
            stale=stale,
            mock_pattern=mock_pattern,
            accepted=False,
        )
        if write_artifacts:
            try:
                _write_artifacts(payload)
            except Exception:
                pass
        return payload

    # Stale or mock-pattern → always rejected.
    if stale or mock_pattern:
        rationale = []
        if mock_pattern:
            rationale.append(
                f"run_id={latest_run_id} matches mock/test/"
                f"placeholder pattern")
        if stale:
            rationale.append(
                "anti-mock guards failed on quality_report (stale "
                "snapshot)")
        rationale.append(
            "appending rejected history row "
            "(accepted_for_unlock_counting=false)")
        if existing_entry is None:
            entry = _entry_from_latest(latest, accepted=False)
            try:
                _append_history_row(history_path, entry)
            except Exception:
                rationale.append("append failed (non-fatal)")
        payload = _build_payload(
            repair_status=(
                QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED),
            latest_run_id=latest_run_id,
            rationale=rationale,
            anti_mock_passed=False,
            source_mismatch=False,
            stale=stale,
            mock_pattern=mock_pattern,
            accepted=False,
        )
        if write_artifacts:
            try:
                _write_artifacts(payload)
            except Exception:
                pass
        return payload

    # Clean acceptable path — only when quality_status is ACCEPTABLE.
    if quality_status_top == "LLM_ADVISORY_QUALITY_ACCEPTABLE":
        rationale = [
            f"run_id={latest_run_id} cleared all anti-mock guards",
            "appending accepted history row "
            "(accepted_for_unlock_counting=true)",
        ]
        if existing_entry is None:
            entry = _entry_from_latest(latest, accepted=True)
            try:
                _append_history_row(history_path, entry)
            except Exception:
                rationale.append("append failed (non-fatal)")
        payload = _build_payload(
            repair_status=(
                QUALITY_HISTORY_REPAIRED_ACCEPTABLE_CONFIRMED),
            latest_run_id=latest_run_id,
            rationale=rationale,
            anti_mock_passed=True,
            source_mismatch=False,
            stale=False,
            mock_pattern=False,
            accepted=True,
        )
        if write_artifacts:
            try:
                _write_artifacts(payload)
            except Exception:
                pass
        return payload

    # Non-ACCEPTABLE top status (e.g. INSUFFICIENT_SAMPLE,
    # GENERIC_PLACEHOLDER) — append as rejected.
    rationale = [
        f"quality_status={quality_status_top} is not ACCEPTABLE",
        "appending rejected history row "
        "(accepted_for_unlock_counting=false)",
    ]
    if existing_entry is None:
        entry = _entry_from_latest(latest, accepted=False)
        try:
            _append_history_row(history_path, entry)
        except Exception:
            rationale.append("append failed (non-fatal)")
    payload = _build_payload(
        repair_status=(
            QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED),
        latest_run_id=latest_run_id,
        rationale=rationale,
        anti_mock_passed=False,
        source_mismatch=False,
        stale=stale,
        mock_pattern=mock_pattern,
        accepted=False,
    )
    if write_artifacts:
        try:
            _write_artifacts(payload)
        except Exception:
            pass
    return payload


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM quality history self-healing repair (v3.30.1).")
    parser.add_argument("--write-artifacts", action="store_true",
                          default=False,
                          help="Write learning-loop/llm_advisory/"
                                "quality_history_repair_latest.json + "
                                "docs/LLM_QUALITY_HISTORY_REPAIR_STATUS.md")
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_or_live_truthy()
    if refuse is not None:
        print(json.dumps(
            {
                "status": refuse,
                "version": "v3.30.1",
                "broker_paper_canary_still_blocked": True,
                "live_trading_unsupported": True,
                "no_order_placement_in_v3301": True,
            },
            sort_keys=True))
        return 1

    payload = reconcile(write_artifacts=args.write_artifacts)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

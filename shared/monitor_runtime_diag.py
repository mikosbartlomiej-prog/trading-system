"""v3.24 (2026-06-15) — ETAP 9 — Monitor runtime diagnostics.

WHY
---
Seven of eight wired monitors (price/options/defense/twitter/reddit/geo/
politician) emit confidence-augmented signals through
``shared.signal_emitter.emit_signal_opportunity`` but the audit on
2026-06-15 showed that for days at a time only crypto-monitor is
actually firing a SignalEvent during a cron tick. We cannot tell from
the opportunity ledger alone WHY a monitor went silent — did the scan
not run? Was the input feed empty? Did every symbol fail the signal
test? Did the emit helper itself raise?

This module is the answer. It is a tiny, append-only JSONL diagnostic
writer that each monitor calls at well-defined points in its run loop.
Reading back the daily diagnostic file produces a deterministic
"what happened on each cron tick" report.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders`` or any broker module.
- NEVER makes network calls.
- NEVER raises — every failure is silently swallowed.
- Pure local I/O against ``learning-loop/monitor_runtime_diag/``.

FREE OPERATION
--------------
Zero paid services. Zero LLM calls. Pure local JSONL append.

USAGE
-----
    from monitor_runtime_diag import record_diag, DIAG_RAN, DIAG_NO_SIGNAL

    record_diag("crypto-monitor", DIAG_RAN, detail={"coins": 11})
    ...
    record_diag("crypto-monitor", DIAG_NO_SIGNAL, detail={"scanned": 11})
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ─── Diagnostic token set ────────────────────────────────────────────────────


DIAG_RAN              = "RAN"
DIAG_INPUT_EMPTY      = "INPUT_EMPTY"
DIAG_NO_SIGNAL        = "NO_SIGNAL"
DIAG_SIGNAL_DETECTED  = "SIGNAL_DETECTED"
DIAG_EMIT_ATTEMPTED   = "EMIT_ATTEMPTED"
DIAG_EMIT_SUCCESS     = "EMIT_SUCCESS"
DIAG_EMIT_FAILED      = "EMIT_FAILED"


# Frozen so callers cannot mutate it at runtime — the v3.24 contract
# treats the token set as a closed enum so the reporter can rely on a
# fixed schema.
DIAG_TOKENS: frozenset[str] = frozenset({
    DIAG_RAN,
    DIAG_INPUT_EMPTY,
    DIAG_NO_SIGNAL,
    DIAG_SIGNAL_DETECTED,
    DIAG_EMIT_ATTEMPTED,
    DIAG_EMIT_SUCCESS,
    DIAG_EMIT_FAILED,
})


# Test hook so tests can swap the output directory without monkey-patching
# the whole module. Production callers leave this unset.
_DIAG_DIR_OVERRIDE: Path | None = None


def _diag_dir() -> Path:
    """Resolve the output directory for diagnostic JSONL files.

    Honours the env var ``MONITOR_RUNTIME_DIAG_DIR`` (used by tests),
    then ``_DIAG_DIR_OVERRIDE`` (used by tests too), then falls back to
    ``learning-loop/monitor_runtime_diag/`` at the repo root.
    """
    if _DIAG_DIR_OVERRIDE is not None:
        return Path(_DIAG_DIR_OVERRIDE)
    env_override = os.environ.get("MONITOR_RUNTIME_DIAG_DIR")
    if env_override:
        return Path(env_override)
    # Resolve repo root from this file's location.
    # shared/monitor_runtime_diag.py → repo_root = parent of shared/
    here = Path(__file__).resolve()
    return here.parent.parent / "learning-loop" / "monitor_runtime_diag"


def _set_diag_dir_for_tests(p: Any) -> None:
    """Test helper. Not part of the public API."""
    global _DIAG_DIR_OVERRIDE
    _DIAG_DIR_OVERRIDE = Path(p) if p is not None else None


def _today_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl"


def record_diag(
    monitor_name: str,
    token: str,
    detail: dict | None = None,
) -> bool:
    """Append a single-line JSON record to today's diag file.

    Fail-soft. Returns True iff the write succeeded. Any error returns
    False and never propagates.

    Parameters
    ----------
    monitor_name : str
        Canonical monitor name (e.g. ``"crypto-monitor"``).
    token : str
        One of the DIAG_* constants above. Unknown tokens are silently
        coerced to ``"UNKNOWN"`` so a typo in caller code never breaks
        the writer.
    detail : dict | None
        Optional diagnostic detail (e.g. counts of items scanned,
        rejection reasons, error class names). Must be JSON-serialisable;
        non-serialisable values are coerced to ``str()``.
    """
    try:
        tok = str(token) if token else "UNKNOWN"
        if tok not in DIAG_TOKENS:
            tok = "UNKNOWN"

        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monitor":   str(monitor_name or "unknown"),
            "token":     tok,
            "detail":    _coerce_jsonable(detail or {}),
        }

        out_dir = _diag_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

        out_file = out_dir / _today_filename()
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:
        # Diagnostic writer must NEVER break the monitor.
        return False


def _coerce_jsonable(obj: Any) -> Any:
    """Best-effort coercion so json.dumps never raises."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        if isinstance(obj, dict):
            return {str(k): _coerce_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_coerce_jsonable(x) for x in obj]
        return str(obj)


__all__ = [
    "DIAG_RAN",
    "DIAG_INPUT_EMPTY",
    "DIAG_NO_SIGNAL",
    "DIAG_SIGNAL_DETECTED",
    "DIAG_EMIT_ATTEMPTED",
    "DIAG_EMIT_SUCCESS",
    "DIAG_EMIT_FAILED",
    "DIAG_TOKENS",
    "record_diag",
]

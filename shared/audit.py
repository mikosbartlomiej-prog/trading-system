"""
Unified JSONL audit layer for autonomous decisions.

Two on-disk locations (matches spec §8):
  - journal/autonomy/YYYY-MM-DD.jsonl       — trading decisions
  - learning-loop/code-autonomy/history/YYYY-MM-DD.jsonl  — code decisions
  - learning-loop/code-autonomy/history/YYYY-MM-DD.md     — human summary

Write is append-only. Daily rollover (one file per UTC date). No locking
needed — each call appends a single line, atomic on POSIX for <PIPE_BUF
which our records always are.

Public API:
  write_audit_event(decision, kind="trading") -> path
  write_code_audit_event(decision, summary_md=None) -> tuple[path_jsonl, path_md]
  read_today(kind="trading") -> list[dict]
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

try:
    from autonomy import Decision
except ImportError:  # pragma: no cover
    from shared.autonomy import Decision  # type: ignore


_REPO_ROOT = Path(__file__).resolve().parent.parent

# Path roots — overridable by env for tests.
def _trading_dir() -> Path:
    return Path(os.environ.get("AUDIT_TRADING_DIR")
                or _REPO_ROOT / "journal" / "autonomy")


def _code_dir() -> Path:
    return Path(os.environ.get("AUDIT_CODE_DIR")
                or _REPO_ROOT / "learning-loop" / "code-autonomy" / "history")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, line: str) -> None:
    _ensure_dir(path.parent)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


# ─── Public API ───────────────────────────────────────────────────────────────

def write_audit_event(decision: Decision | dict,
                      kind: Literal["trading", "code"] = "trading") -> Path:
    """
    Append one Decision (or its dict form) to today's JSONL file.

    Returns the path written. Idempotent only by accident — the audit is
    APPEND-ONLY, so callers should make_decision once per actual decision.
    """
    if isinstance(decision, Decision):
        record = decision.to_dict()
    else:
        record = dict(decision)
    base = _code_dir() if kind == "code" else _trading_dir()
    date = _today_iso()
    path = base / f"{date}.jsonl"
    _append_jsonl(path, json.dumps(record, default=str, sort_keys=True))
    return path


def write_code_audit_event(decision: Decision | dict,
                            summary_md: str | None = None) -> tuple[Path, Path | None]:
    """
    Convenience for code autonomy events. Always writes JSONL; optionally
    appends a Markdown bullet to the daily human summary.
    """
    jsonl_path = write_audit_event(decision, kind="code")
    md_path: Path | None = None
    if summary_md:
        base = _code_dir()
        date = _today_iso()
        md_path = base / f"{date}.md"
        _ensure_dir(md_path.parent)
        with open(md_path, "a", encoding="utf-8") as f:
            if md_path.stat().st_size == 0:
                f.write(f"# Code-autonomy audit — {date}\n\n")
            f.write(f"- `{datetime.now(timezone.utc).strftime('%H:%M:%S')}` {summary_md.strip()}\n")
    return jsonl_path, md_path


def read_today(kind: Literal["trading", "code"] = "trading") -> list[dict]:
    """Return today's audit records (empty list if no file)."""
    base = _code_dir() if kind == "code" else _trading_dir()
    path = base / f"{_today_iso()}.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def read_range(days: int, kind: Literal["trading", "code"] = "trading") -> list[dict]:
    """Return last `days` days of audit records (oldest first)."""
    from datetime import date, timedelta
    base = _code_dir() if kind == "code" else _trading_dir()
    out: list[dict] = []
    today = date.today()
    for delta in range(days - 1, -1, -1):
        d = today - timedelta(days=delta)
        path = base / f"{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return out

#!/usr/bin/env python3
"""v3.13.1 (2026-05-30) — Send single end-of-day digest email summarising
all DIGEST-classified notifications from `learning-loop/notify_digest/<date>.jsonl`.

USAGE
-----
python3 scripts/send_daily_digest.py                    # today UTC
python3 scripts/send_daily_digest.py --date 2026-05-30  # specific date
python3 scripts/send_daily_digest.py --no-send          # preview to stdout only
python3 scripts/send_daily_digest.py --clear            # delete digest after send

NOTES
-----
- DIGEST emails are non-critical (per shared/notify.py::NotificationPolicy).
- This script bundles a whole day into ONE email so the inbox stays tidy.
- Critical emails are NEVER in the digest — they were sent immediately.
- If the digest file is empty/missing, exit 0 silently (no spam).
- Designed to run from a workflow at 21:00 UTC daily (after analyzer).

NO PAID DEPS. Reads local JSONL, sends via existing Gmail SMTP path
(`shared/notify.py::send_email` with NOTIFY_FORCE_SEND override so the
digest summary itself isn't suppressed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_digest(date_iso: str) -> list[dict]:
    digest_dir_env = os.environ.get("NOTIFY_DIGEST_DIR")
    if digest_dir_env:
        digest_dir = Path(digest_dir_env)
    else:
        digest_dir = _REPO_ROOT / "learning-loop" / "notify_digest"
    path = digest_dir / f"{date_iso}.jsonl"
    if not path.exists():
        return []
    rows = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception as e:
        print(f"  read error: {e}")
    return rows


def _render(date_iso: str, rows: list[dict]) -> tuple[str, str]:
    """Build (subject, body) for the digest email."""
    if not rows:
        return ("", "")

    # Bucket by subject prefix (first [TAG] in each subject)
    by_tag = defaultdict(list)
    for r in rows:
        sub = r.get("subject", "")
        # Extract first [tag]
        if sub.startswith("["):
            end = sub.find("]")
            tag = sub[:end + 1] if end > 0 else "[?]"
        else:
            tag = "[other]"
        by_tag[tag].append(r)

    total = len(rows)
    subject = f"[DAILY DIGEST] {date_iso} — {total} non-critical events"

    lines = []
    lines.append(f"Trading-system daily digest for {date_iso}")
    lines.append(f"Total batched events: {total}")
    lines.append("")
    lines.append("Critical events were sent as separate emails earlier; this")
    lines.append("digest collects only non-critical / informational items so")
    lines.append("your inbox stays clean.")
    lines.append("")
    lines.append("Breakdown by tag:")
    for tag, items in sorted(by_tag.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {tag:30s}  ×{len(items)}")
    lines.append("")
    lines.append("─" * 70)
    lines.append("Detail (latest 50 events, newest first):")
    lines.append("")
    for r in list(reversed(rows))[:50]:
        ts = r.get("timestamp", "")[:19]
        sub = r.get("subject", "")[:90]
        lines.append(f"  {ts}  {sub}")
        preview = (r.get("body_preview") or "").split("\n")[0][:120]
        if preview:
            lines.append(f"      └─ {preview}")
    if len(rows) > 50:
        lines.append("")
        lines.append(f"  ... and {len(rows) - 50} earlier event(s) — see")
        lines.append(f"  learning-loop/notify_digest/{date_iso}.jsonl for full log")
    lines.append("")
    lines.append("─" * 70)
    lines.append("To see live state any time: python3 scripts/session_report.py --no-write")
    lines.append("To disable this digest: set NOTIFY_MODE=off or skip the cron")
    lines.append("To get every event live: set NOTIFY_MODE=verbose (NOT recommended)")
    return subject, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily digest of non-critical emails")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--no-send", action="store_true",
                          help="Print to stdout, don't send email")
    parser.add_argument("--clear", action="store_true",
                          help="Delete digest file after successful send")
    args = parser.parse_args()

    date_iso = args.date or datetime.now(timezone.utc).date().isoformat()
    rows = _load_digest(date_iso)
    if not rows:
        print(f"  no digest entries for {date_iso} — nothing to send")
        return 0

    subject, body = _render(date_iso, rows)

    if args.no_send:
        print("─" * 70)
        print(f"SUBJECT: {subject}")
        print("─" * 70)
        print(body)
        return 0

    # Force this digest summary to BE sent, even though the prefix
    # "[DAILY DIGEST]" is not in CRITICAL_MARKERS.
    os.environ["NOTIFY_FORCE_SEND"] = "[DAILY DIGEST]"
    # Re-import to pick up env (or just use direct SMTP)
    from notify import send_email
    ok = send_email(subject, body)
    if not ok:
        print(f"  digest send FAILED")
        return 1
    print(f"  digest sent: {subject}")

    if args.clear:
        digest_dir_env = os.environ.get("NOTIFY_DIGEST_DIR")
        if digest_dir_env:
            path = Path(digest_dir_env) / f"{date_iso}.jsonl"
        else:
            path = _REPO_ROOT / "learning-loop" / "notify_digest" / f"{date_iso}.jsonl"
        try:
            path.unlink()
            print(f"  digest file cleared: {path.name}")
        except Exception as e:
            print(f"  clear failed (non-fatal): {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

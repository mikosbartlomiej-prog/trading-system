#!/usr/bin/env python3
"""v3.27.3 (2026-06-09) — incident digest aggregator.

Reads the local notification digest + flood-guard audit JSONLs for a
given date (defaults to today UTC) and emits ONE summary email with the
unique fingerprints, counts, and previews.

If Gmail credentials are missing, the digest is printed to stdout and
the script exits 0 — the digest is operational visibility, never a
hard prerequisite for trading.

HARD SAFETY
-----------
- NEVER submits orders.
- NEVER imports the broker-orders module.
- NEVER reads or writes secret values.
- NEVER deletes the digest or audit JSONLs (read-only on disk).
- NEVER sends more than ONE email per invocation regardless of input
  size — this script EXISTS to collapse hundreds of duplicates into
  one digest.
- Refuses (exit 1) if any of
  ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING`` /
  ``LIVE_ENABLED`` / ``GO_LIVE`` / ``LIVE_TRADING_ENABLED``
  is truthy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _digest_dir() -> Path:
    override = os.environ.get("NOTIFY_DIGEST_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "notify_digest"


def _digest_path(date_iso: str) -> Path:
    return _digest_dir() / f"{date_iso}.jsonl"


def _audit_path(date_iso: str) -> Path:
    return _digest_dir() / f"notification_decisions_{date_iso}.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
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


def aggregate(date_iso: str) -> dict[str, Any]:
    """Pure aggregator: returns the dict used to render the digest."""
    digest_entries = _read_jsonl(_digest_path(date_iso))
    audit_entries  = _read_jsonl(_audit_path(date_iso))

    # Audit gives us fingerprints + verdicts. Group by fingerprint.
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "fingerprint":          None,
            "first_seen":           None,
            "last_seen":            None,
            "total_count":          0,
            "send_count":           0,
            "digest_count":         0,
            "verdicts":             Counter(),
            "latest_subject":       None,
            "latest_body_preview":  None,
            "latest_reason":        None,
        }
    )
    for e in audit_entries:
        fp = e.get("fingerprint") or "unknown"
        g = grouped[fp]
        g["fingerprint"] = fp
        ts = e.get("timestamp_iso")
        if ts:
            if g["first_seen"] is None or ts < g["first_seen"]:
                g["first_seen"] = ts
            if g["last_seen"] is None or ts > g["last_seen"]:
                g["last_seen"] = ts
                g["latest_subject"]      = e.get("subject_preview")
                g["latest_body_preview"] = e.get("body_preview")
                g["latest_reason"]       = e.get("reason")
        g["total_count"] += 1
        verdict = e.get("verdict") or "unknown"
        g["verdicts"][verdict] += 1
        if verdict.startswith("FLOOD_SEND"):
            g["send_count"] += 1
        elif verdict in (
            "FLOOD_DIGEST", "FLOOD_BLOCK_HOURLY_CAP",
            "FLOOD_BLOCK_DAILY_CAP",
        ):
            g["digest_count"] += 1

    immediate_total = sum(g["send_count"] for g in grouped.values())
    digest_total    = sum(g["digest_count"] for g in grouped.values())
    summary = {
        "date":                  date_iso,
        "groups":                list(grouped.values()),
        "unique_fingerprints":   len(grouped),
        "immediate_sent_count":  immediate_total,
        "digested_count":        digest_total,
        "raw_digest_entries":    len(digest_entries),
    }
    # Sort groups by total count desc for the rendered output.
    summary["groups"].sort(
        key=lambda g: g["total_count"], reverse=True)
    # Stringify Counter for clean JSON.
    for g in summary["groups"]:
        g["verdicts"] = dict(g["verdicts"])
    return summary


def render_subject(summary: dict[str, Any]) -> str:
    return (
        f"[INCIDENT-DIGEST] {summary['date']} — "
        f"{summary['unique_fingerprints']} unique, "
        f"{summary['immediate_sent_count']} immediate, "
        f"{summary['digested_count']} digested"
    )


def render_body(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Incident digest for {summary['date']} (UTC)")
    lines.append("")
    lines.append(
        f"Unique fingerprints: {summary['unique_fingerprints']}")
    lines.append(
        f"Immediate sends:     {summary['immediate_sent_count']}")
    lines.append(
        f"Digested duplicates: {summary['digested_count']}")
    lines.append(
        f"Raw digest entries:  {summary['raw_digest_entries']}")
    lines.append("")
    if not summary["groups"]:
        lines.append("No notification activity recorded for this date.")
        lines.append("")
        lines.append(
            "Standing markers: BROKER_PAPER_CANARY_STILL_BLOCKED, "
            "LIVE_TRADING_UNSUPPORTED.")
        return "\n".join(lines)
    lines.append("=== Top fingerprints ===")
    for g in summary["groups"][:20]:
        lines.append("")
        lines.append(f"- fingerprint: {g['fingerprint']}")
        lines.append(f"  first_seen:  {g['first_seen']}")
        lines.append(f"  last_seen:   {g['last_seen']}")
        lines.append(f"  total:       {g['total_count']}")
        lines.append(f"  immediate:   {g['send_count']}")
        lines.append(f"  digested:    {g['digest_count']}")
        verdict_str = ", ".join(
            f"{k}={v}" for k, v in (g['verdicts'] or {}).items())
        lines.append(f"  verdicts:    {verdict_str}")
        if g.get("latest_subject"):
            lines.append(
                f"  latest_subject: {g['latest_subject'][:200]}")
        if g.get("latest_body_preview"):
            lines.append(
                f"  latest_body:    {g['latest_body_preview'][:300]}")
        if g.get("latest_reason"):
            lines.append(f"  latest_reason:  {g['latest_reason']}")
    lines.append("")
    lines.append(
        "Standing markers: BROKER_PAPER_CANARY_STILL_BLOCKED, "
        "LIVE_TRADING_UNSUPPORTED.")
    return "\n".join(lines)


def send_one_email(subject: str, body: str) -> bool:
    """Call ``shared/notify.py::send_email`` for ONE digest email."""
    try:
        import notify as _n  # type: ignore
    except ImportError:
        try:
            from shared import notify as _n  # type: ignore
        except ImportError:
            return False
    try:
        return bool(_n.send_email(subject=subject, body=body))
    except Exception as e:
        print(f"  [incident-digest] send_email failed: {e}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate the day's notification activity into "
                     "ONE digest email.",
    )
    parser.add_argument(
        "--date", default=None,
        help="ISO date (YYYY-MM-DD) of the digest to aggregate; "
              "defaults to today UTC.",
    )
    parser.add_argument(
        "--only-if-events", action="store_true",
        help="No-op exit (status 0) when there is nothing to send.",
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Render the digest to stdout but do NOT send.",
    )
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    date_iso = args.date or datetime.now(
        timezone.utc).date().isoformat()
    summary = aggregate(date_iso)

    if args.only_if_events and summary["unique_fingerprints"] == 0:
        print(json.dumps({
            "status":  "NOTHING_TO_DIGEST",
            "date":    date_iso,
            "version": "v3.27.3",
        }, sort_keys=True))
        return 0

    subject = render_subject(summary)
    body    = render_body(summary)

    if args.print_only:
        print(subject)
        print(body)
        print(json.dumps({
            "status":  "PRINTED",
            "date":    date_iso,
            "version": "v3.27.3",
        }, sort_keys=True))
        return 0

    sent = send_one_email(subject, body)
    print(json.dumps({
        "status":          "DIGEST_DISPATCHED" if sent
                            else "DIGEST_PRINTED_NO_GMAIL",
        "date":            date_iso,
        "version":         "v3.27.3",
        "subject":         subject,
        "fingerprint_count": summary["unique_fingerprints"],
        "immediate_sends":  summary["immediate_sent_count"],
        "digested_count":   summary["digested_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

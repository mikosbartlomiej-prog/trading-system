"""v3.27.3 (2026-06-09) — notification flood guard.

Problem
-------
``shared/notify.py``'s ``_CRITICAL_MARKERS`` ships ``[INCIDENT-CRITICAL]``
through the SMTP fast-path. During an incident loop (e.g. the
``scripts/incident_pattern_detector.py`` cron firing every 5 min while
the underlying condition persists) the same critical incident is
re-detected on every tick, generating hundreds of duplicate emails
within an hour. The truly actionable first alert gets buried in the
noise.

Solution
--------
Pure-function flood guard that:

- fingerprints critical alerts on ``(normalized_subject, body_marker)``,
- always lets the FIRST unique fingerprint through,
- routes duplicates within a configurable cooldown to a digest file,
- enforces per-hour and per-day caps for safety,
- preserves every decision in an append-only JSONL audit,
- NEVER silently drops a critical event — even a "block" verdict still
  appends the event to the digest so the operator can see it later.

This module has ZERO knowledge of SMTP, broker, or trading state. It is
a pure routing function over (subject, body, now) → verdict. The caller
(``shared/notify.py``) applies the verdict.

HARD SAFETY
-----------
- NEVER submits orders.
- NEVER imports the broker-orders module.
- NEVER stores secret values (subject + body previews are truncated).
- NEVER deletes existing audit or digest files (append-only on disk).
- NEVER suppresses a critical event without appending it to digest.
- ``[KILL-SWITCH*]`` and ``[FAIL*]`` markers ALWAYS pass-through to send
  regardless of flood-guard state.
- Even with the guard disabled (``NOTIFY_FLOOD_GUARD_ENABLED=false``),
  the audit JSONL is still written so flood post-mortems remain possible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Verdict enum ───────────────────────────────────────────────────────────

# The caller (``send_email``) applies these:
#   FLOOD_SEND_FIRST       — first occurrence, deliver immediately
#   FLOOD_SEND_ESCALATION  — operator override OR explicit always-send marker
#   FLOOD_DIGEST           — duplicate within cooldown, route to digest
#   FLOOD_BLOCK_HOURLY_CAP — hourly cap exceeded, route to digest + audit
#   FLOOD_BLOCK_DAILY_CAP  — daily cap exceeded, route to digest + audit
#   FLOOD_BYPASS_DISABLED  — flood-guard disabled; caller proceeds with
#                            its own routing decision (audit still written)

FLOOD_SEND_FIRST          = "FLOOD_SEND_FIRST"
FLOOD_SEND_ESCALATION     = "FLOOD_SEND_ESCALATION"
FLOOD_DIGEST              = "FLOOD_DIGEST"
FLOOD_BLOCK_HOURLY_CAP    = "FLOOD_BLOCK_HOURLY_CAP"
FLOOD_BLOCK_DAILY_CAP     = "FLOOD_BLOCK_DAILY_CAP"
FLOOD_BYPASS_DISABLED     = "FLOOD_BYPASS_DISABLED"

ALL_FLOOD_VERDICTS: frozenset[str] = frozenset({
    FLOOD_SEND_FIRST,
    FLOOD_SEND_ESCALATION,
    FLOOD_DIGEST,
    FLOOD_BLOCK_HOURLY_CAP,
    FLOOD_BLOCK_DAILY_CAP,
    FLOOD_BYPASS_DISABLED,
})

# Verdicts that result in actually sending an email.
SENDING_VERDICTS: frozenset[str] = frozenset({
    FLOOD_SEND_FIRST,
    FLOOD_SEND_ESCALATION,
})

# Verdicts that the caller should treat as "digest" (success-but-not-sent).
DIGEST_VERDICTS: frozenset[str] = frozenset({
    FLOOD_DIGEST,
    FLOOD_BLOCK_HOURLY_CAP,
    FLOOD_BLOCK_DAILY_CAP,
})

# ─── Always-send markers ─────────────────────────────────────────────────────

# Operator must SEE these regardless of flood state. The defaults:
# kill-switch activations + workflow fail markers.
_DEFAULT_ALWAYS_SEND_MARKERS: tuple[str, ...] = (
    "[KILL-SWITCH",
    "[FAIL",
)

# Operator can extend via env: NOTIFY_ALWAYS_SEND_MARKERS=[X],[Y]
def _env_marker_list(name: str,
                       default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    items = tuple(x.strip() for x in raw.split(",") if x.strip())
    return items or default


def always_send_markers() -> tuple[str, ...]:
    return _env_marker_list(
        "NOTIFY_ALWAYS_SEND_MARKERS",
        _DEFAULT_ALWAYS_SEND_MARKERS,
    )


# Markers that operator wants to ALWAYS digest (never immediate).
# Empty by default — operator opt-in.
def always_digest_markers() -> tuple[str, ...]:
    return _env_marker_list(
        "NOTIFY_ALWAYS_DIGEST_MARKERS",
        (),
    )


# Markers that the flood guard actively monitors. The first prefix
# present in ``subject`` selects the cooldown bucket.
_FLOOD_GUARDED_PREFIXES: tuple[str, ...] = (
    "[INCIDENT-CRITICAL]",
)


# ─── Threshold knobs (env-tunable) ───────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def flood_guard_enabled() -> bool:
    return _env_bool("NOTIFY_FLOOD_GUARD_ENABLED", True)


def incident_critical_first_immediate() -> bool:
    return _env_bool("INCIDENT_CRITICAL_IMMEDIATE_FIRST", True)


def incident_critical_cooldown_minutes() -> int:
    return _env_int("INCIDENT_CRITICAL_COOLDOWN_MINUTES", 60)


def incident_critical_max_per_hour() -> int:
    return _env_int("INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR", 3)


def incident_critical_max_per_day() -> int:
    return _env_int("INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY", 10)


# ─── On-disk locations ──────────────────────────────────────────────────────

def _state_dir() -> Path:
    override = os.environ.get("NOTIFY_FLOOD_STATE_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "notify_state"


def _digest_dir() -> Path:
    override = os.environ.get("NOTIFY_DIGEST_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "notify_digest"


def _state_path() -> Path:
    return _state_dir() / "notification_flood_state.json"


def _audit_path(date_iso: str | None = None) -> Path:
    d = date_iso or datetime.now(timezone.utc).date().isoformat()
    return _digest_dir() / f"notification_decisions_{d}.jsonl"


# ─── Pure helpers (subject normalisation + fingerprinting) ───────────────────

# Strip volatile bits from the subject so equivalent incidents collapse
# into the same fingerprint: timestamps, counts, paths, hashes.
_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS(+TZ)
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:[+\-]\d{2}:?\d{2}|Z)?)?\b"),
     "<DATE>"),
    # "N pattern hit(s)" / "5 events"
    (re.compile(r"\b\d+\s+(?:pattern|event|finding|hit|signal)s?\b",
                  re.IGNORECASE),
     "<COUNT>"),
    # Long hex / hash blobs (commit SHAs, UUIDs)
    (re.compile(r"\b[0-9a-f]{8,40}\b"), "<HASH>"),
    # File paths
    (re.compile(r"/[\w./-]+\.(?:py|md|json|jsonl|yml|yaml|txt|csv|log)"),
     "<PATH>"),
    # Excessive whitespace
    (re.compile(r"\s+"), " "),
)


def normalize_subject(subject: str) -> str:
    """Strip volatile suffixes (dates, counts, hashes, paths) so the
    same incident type collapses to one fingerprint.

    Examples:
        "[INCIDENT-CRITICAL] 3 pattern hit(s) — 2026-06-09"
        → "[incident-critical] <count> — <date>"
        "[INCIDENT-CRITICAL] 1 pattern hit(s) — 2026-06-10"
        → "[incident-critical] <count> — <date>"   (identical)
    """
    if not subject:
        return ""
    s = subject.strip().lower()
    for pat, repl in _VOLATILE_PATTERNS:
        s = pat.sub(repl, s)
    return s.strip()


# Body markers that distinguish ONE underlying incident from another.
# Order matters: the FIRST matching pattern wins (so a body with multiple
# patterns fingerprints to its primary one).
_BODY_INCIDENT_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bP\d{2,}\b"),                  # P01..P99 codes
    re.compile(r"\b(?:CRITICAL|WARN)\b\s+\w+",   # CRITICAL <token>
                 re.IGNORECASE),
)


def _extract_body_markers(body: str) -> str:
    """Pull stable marker tokens out of the body. The tokens are
    deduped + sorted so equivalent bodies yield identical fingerprints.
    """
    if not body:
        return ""
    matches: set[str] = set()
    for pat in _BODY_INCIDENT_MARKERS:
        for m in pat.findall(body):
            matches.add(m.upper().strip())
    return "|".join(sorted(matches))


def incident_fingerprint(subject: str, body: str) -> str:
    """Pure deterministic fingerprint over (normalized subject, body
    markers). Two events with the same fingerprint represent the same
    underlying incident even if subject text or counts differ slightly.
    """
    norm = normalize_subject(subject)
    markers = _extract_body_markers(body)
    raw = f"{norm}\n{markers}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ─── State load / save ──────────────────────────────────────────────────────

@dataclass
class FloodState:
    """Per-fingerprint state plus rolling counters."""

    # Fingerprint → most-recent send timestamp (ISO) and event count
    fingerprints: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Date string → number of immediate sends today
    immediate_per_day: dict[str, int]         = field(default_factory=dict)
    # ISO hour string → number of immediate sends in that hour
    immediate_per_hour: dict[str, int]        = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fingerprints":       self.fingerprints,
            "immediate_per_day":  self.immediate_per_day,
            "immediate_per_hour": self.immediate_per_hour,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "FloodState":
        if not raw or not isinstance(raw, dict):
            return cls()
        return cls(
            fingerprints       =dict(raw.get("fingerprints") or {}),
            immediate_per_day  =dict(raw.get("immediate_per_day") or {}),
            immediate_per_hour =dict(raw.get("immediate_per_hour") or {}),
        )


def load_flood_state(path: Path | None = None) -> FloodState:
    p = path or _state_path()
    if not p.exists():
        return FloodState()
    try:
        return FloodState.from_dict(
            json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return FloodState()


def save_flood_state(state: FloodState,
                       path: Path | None = None) -> None:
    p = path or _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ─── Audit append (never overwrites) ────────────────────────────────────────

def _safe_preview(text: str, n: int = 240) -> str:
    """Truncated preview that does NOT leak secrets — strips any
    16+ char run that looks like an API key."""
    if not text:
        return ""
    # Crude secret-shape stripper: 16+ uppercase/digit runs (Alpaca-key
    # shape) get redacted.
    cleaned = re.sub(r"[A-Z0-9]{16,}", "<REDACTED>", text)
    cleaned = cleaned.replace("\n", " ")
    return cleaned[:n]


def record_notification_decision(
    *,
    subject: str,
    body: str,
    fingerprint: str,
    verdict: str,
    reason: str,
    now: datetime,
    audit_path: Path | None = None,
) -> Path:
    """Append-only JSONL record of every flood-guard decision."""
    p = audit_path or _audit_path(now.date().isoformat())
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp_iso":   now.astimezone(timezone.utc).isoformat(),
        "fingerprint":     fingerprint,
        "verdict":         verdict,
        "reason":          reason,
        "subject_preview": _safe_preview(subject, 200),
        "body_preview":    _safe_preview(body, 400),
    }
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return p


# ─── Core decision function ─────────────────────────────────────────────────

def _is_always_send(subject: str) -> bool:
    s = subject or ""
    for marker in always_send_markers():
        if marker in s:
            return True
    return False


def _is_always_digest(subject: str) -> bool:
    s = subject or ""
    for marker in always_digest_markers():
        if marker in s:
            return True
    return False


def _is_flood_guarded(subject: str) -> bool:
    s = subject or ""
    for prefix in _FLOOD_GUARDED_PREFIXES:
        if prefix in s:
            return True
    return False


def _bucket_hour(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def _bucket_day(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


def _prune_stale(state: FloodState, now: datetime) -> None:
    """Drop fingerprint / hour / day entries older than 36 h so the
    state file does not grow unbounded.
    """
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=36)
    for k, v in list(state.fingerprints.items()):
        last = v.get("last_send_iso") or v.get("last_seen_iso")
        if not last:
            continue
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff:
            del state.fingerprints[k]
    today = _bucket_day(now)
    for k in list(state.immediate_per_day):
        if k != today:
            del state.immediate_per_day[k]
    this_hour = _bucket_hour(now)
    for k in list(state.immediate_per_hour):
        if k != this_hour:
            del state.immediate_per_hour[k]


def should_send_immediate(
    subject: str,
    body: str,
    *,
    now: datetime | None = None,
    state: FloodState | None = None,
) -> tuple[str, str, str]:
    """Pure decision: returns (verdict, fingerprint, reason).

    The caller is responsible for:
    - persisting the (possibly mutated) state,
    - appending to the audit JSONL,
    - performing the actual SMTP send (or digest append).
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = state if state is not None else load_flood_state()
    fp = incident_fingerprint(subject, body)

    # Operator-forced markers always pass-through with SEND_ESCALATION.
    if _is_always_send(subject):
        return (FLOOD_SEND_ESCALATION, fp,
                "always-send marker matched")

    # Operator-forced digest markers always route to digest.
    if _is_always_digest(subject):
        return (FLOOD_DIGEST, fp, "always-digest marker matched")

    # Flood-guard disabled → caller proceeds with its own routing.
    if not flood_guard_enabled():
        return (FLOOD_BYPASS_DISABLED, fp, "flood-guard disabled by env")

    # Only flood-guarded prefixes are gated. Anything else passes through
    # with SEND_ESCALATION so the caller's existing policy still applies.
    if not _is_flood_guarded(subject):
        return (FLOOD_SEND_ESCALATION, fp,
                "subject not in flood-guarded prefix list")

    _prune_stale(state, now)

    # Hourly / daily caps (apply BEFORE first-seen check so a burst
    # cannot abuse "first seen" labelling).
    hour_key  = _bucket_hour(now)
    day_key   = _bucket_day(now)
    per_hour  = int(state.immediate_per_hour.get(hour_key, 0))
    per_day   = int(state.immediate_per_day.get(day_key, 0))
    if per_day >= incident_critical_max_per_day():
        return (FLOOD_BLOCK_DAILY_CAP, fp,
                f"daily cap reached ({per_day} >= "
                f"{incident_critical_max_per_day()})")
    if per_hour >= incident_critical_max_per_hour():
        return (FLOOD_BLOCK_HOURLY_CAP, fp,
                f"hourly cap reached ({per_hour} >= "
                f"{incident_critical_max_per_hour()})")

    # Cooldown check by fingerprint.
    fp_state = state.fingerprints.get(fp) or {}
    last_iso = fp_state.get("last_send_iso")
    if last_iso:
        try:
            last_dt = datetime.fromisoformat(
                last_iso.replace("Z", "+00:00"))
        except Exception:
            last_dt = None
        if last_dt is not None:
            cooldown = timedelta(
                minutes=incident_critical_cooldown_minutes())
            if (now - last_dt) < cooldown:
                return (FLOOD_DIGEST, fp,
                        f"within cooldown ({last_iso})")

    # First occurrence (or cooldown elapsed) → send.
    if incident_critical_first_immediate() or last_iso is None:
        return (FLOOD_SEND_FIRST, fp,
                "first occurrence or cooldown elapsed")
    return (FLOOD_DIGEST, fp, "first-immediate disabled")


def apply_verdict(
    *,
    state: FloodState,
    verdict: str,
    fingerprint: str,
    now: datetime,
) -> None:
    """Mutate state to reflect a verdict that resulted in a SEND.

    Pure book-keeping: no I/O. Caller persists ``state`` afterwards.
    """
    now_iso = now.astimezone(timezone.utc).isoformat()
    fp_state = state.fingerprints.get(fingerprint) or {}
    fp_state["last_seen_iso"] = now_iso
    fp_state["seen_count"] = int(fp_state.get("seen_count", 0)) + 1
    if verdict in SENDING_VERDICTS:
        fp_state["last_send_iso"] = now_iso
        fp_state["send_count"] = int(fp_state.get("send_count", 0)) + 1
        state.immediate_per_hour[_bucket_hour(now)] = (
            int(state.immediate_per_hour.get(_bucket_hour(now), 0)) + 1)
        state.immediate_per_day[_bucket_day(now)] = (
            int(state.immediate_per_day.get(_bucket_day(now), 0)) + 1)
    state.fingerprints[fingerprint] = fp_state


# ─── End-to-end convenience ─────────────────────────────────────────────────

def evaluate_and_record(
    subject: str,
    body: str,
    *,
    now: datetime | None = None,
    state_path: Path | None = None,
    audit_path: Path | None = None,
) -> tuple[str, str, str]:
    """Run the full pipeline (load → decide → persist → audit) and
    return ``(verdict, fingerprint, reason)``. This is the public
    convenience used by ``shared/notify.py::send_email``.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = load_flood_state(state_path)
    verdict, fp, reason = should_send_immediate(
        subject, body, now=now, state=state)
    if verdict in SENDING_VERDICTS or verdict in DIGEST_VERDICTS:
        apply_verdict(state=state, verdict=verdict,
                       fingerprint=fp, now=now)
        save_flood_state(state, state_path)
    record_notification_decision(
        subject=subject, body=body,
        fingerprint=fp, verdict=verdict, reason=reason,
        now=now, audit_path=audit_path)
    return verdict, fp, reason


__all__ = [
    # Verdict enum
    "FLOOD_SEND_FIRST", "FLOOD_SEND_ESCALATION",
    "FLOOD_DIGEST", "FLOOD_BLOCK_HOURLY_CAP",
    "FLOOD_BLOCK_DAILY_CAP", "FLOOD_BYPASS_DISABLED",
    "ALL_FLOOD_VERDICTS", "SENDING_VERDICTS", "DIGEST_VERDICTS",
    # Env-tunable knobs
    "flood_guard_enabled",
    "incident_critical_first_immediate",
    "incident_critical_cooldown_minutes",
    "incident_critical_max_per_hour",
    "incident_critical_max_per_day",
    "always_send_markers", "always_digest_markers",
    # Pure helpers
    "normalize_subject", "incident_fingerprint",
    "_safe_preview",
    # State + audit
    "FloodState", "load_flood_state", "save_flood_state",
    "record_notification_decision",
    # Decision function
    "should_send_immediate", "apply_verdict",
    # Convenience
    "evaluate_and_record",
]

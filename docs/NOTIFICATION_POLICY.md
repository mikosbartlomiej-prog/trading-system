# Notification Policy (v3.27.3 — 2026-06-09)

This document captures the layered notification policy applied by
[shared/notify.py](../shared/notify.py).

## Why this exists

Before v3.27.3, an incident loop on `scripts/incident_pattern_detector.py`
(cron `*/5`, re-firing every 5 minutes while the underlying condition
persisted) could emit hundreds of identical `[INCIDENT-CRITICAL]` emails
inside one hour. The first alert was buried by the noise; the operator's
inbox became unusable.

v3.27.3 layers a deterministic **flood guard** in front of the SMTP
path so the first unique critical incident still reaches the operator
immediately, while duplicates within a configurable cooldown are routed
to a digest. Every decision is recorded in an append-only audit JSONL —
no critical event is ever silently dropped.

## How a subject is routed (in order)

[shared/notify.py::send_email](../shared/notify.py) consults three
layers, in order:

1. **`NOTIFY_MODE`** (`off` / `minimal` / `verbose`, default `minimal`):
   `off` suppresses everything; `verbose` sends everything through to
   the next layer; `minimal` applies the v3.13 critical/digest/suppress
   classifier.
2. **v3.13.x classifier** (`_classify_subject`): subjects matching
   `_CRITICAL_MARKERS` (`[INCIDENT-CRITICAL]`, `[KILL-SWITCH*`,
   `[FAIL*`, etc.) are flagged `send`; subjects matching
   `_DIGEST_MARKERS` (`[BUY]`, `[EXIT]`, `[PEAK-WARN]`, …) are
   routed to the digest; cron-zero-summary subjects are suppressed.
3. **v3.27.3 flood guard**
   ([shared/notification_flood_guard.py](../shared/notification_flood_guard.py)):
   runs only after layers 1+2 have already decided `send`. It fingerprints
   the subject + body markers, lets the first unique fingerprint through,
   routes duplicates within a configurable cooldown to the digest, and
   enforces per-hour and per-day caps as a safety backstop.

## v3.27.3 flood-guard verdicts

| Verdict | Caller action |
|---|---|
| `FLOOD_SEND_FIRST` | First occurrence of a fingerprint OR cooldown elapsed — proceed to SMTP. |
| `FLOOD_SEND_ESCALATION` | Subject matched an always-send marker (`[KILL-SWITCH*`, `[FAIL*`, operator override) OR was not a flood-guarded prefix — proceed to SMTP. |
| `FLOOD_DIGEST` | Duplicate fingerprint within cooldown — route to digest JSONL. |
| `FLOOD_BLOCK_HOURLY_CAP` | Hourly cap exceeded — route to digest JSONL. |
| `FLOOD_BLOCK_DAILY_CAP` | Daily cap exceeded — route to digest JSONL. |
| `FLOOD_BYPASS_DISABLED` | `NOTIFY_FLOOD_GUARD_ENABLED=false` — proceed to SMTP (caller behaviour unchanged). |

**Every verdict is appended to**
`learning-loop/notify_digest/notification_decisions_YYYY-MM-DD.jsonl`
**— including `FLOOD_BYPASS_DISABLED`.** This guarantees a complete
post-mortem trail even when the guard is disabled.

## Fingerprinting

The flood guard is intentionally **conservative** about what counts as
"the same incident":

- `normalize_subject(subject)` strips dates (`<DATE>`), counts
  (`<COUNT>`), hashes (`<HASH>`), and file paths (`<PATH>`).
- `_extract_body_markers(body)` pulls stable tokens such as `P02`,
  `P11`, `CRITICAL <name>`, sorts them deduplicated, and joins with
  `|`.
- The fingerprint is `sha256(normalized_subject + "\n" + body_markers)`
  truncated to 16 hex chars.

Two `[INCIDENT-CRITICAL]` events with the same `P02` body marker
collapse to the same fingerprint even if the subject's hit-count or
date string differs.

## Environment knobs

| Variable | Default | Effect |
|---|---|---|
| `NOTIFY_FLOOD_GUARD_ENABLED` | `true` | Master switch. `false` bypasses the guard but still writes the audit JSONL. |
| `INCIDENT_CRITICAL_IMMEDIATE_FIRST` | `true` | First occurrence of a fingerprint sends immediately. |
| `INCIDENT_CRITICAL_COOLDOWN_MINUTES` | `60` | Duplicates within this window are digested. |
| `INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR` | `3` | Hourly cap on `FLOOD_SEND_FIRST` deliveries. |
| `INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY` | `10` | Daily cap on `FLOOD_SEND_FIRST` deliveries. |
| `NOTIFY_ALWAYS_SEND_MARKERS` | `[KILL-SWITCH,[FAIL` | Comma-separated subject substrings that bypass the cooldown + caps. |
| `NOTIFY_ALWAYS_DIGEST_MARKERS` | (empty) | Comma-separated subject substrings that always digest. |
| `NOTIFY_FLOOD_STATE_DIR` | `learning-loop/notify_state/` | Override the state directory (used by tests). |
| `NOTIFY_DIGEST_DIR` | `learning-loop/notify_digest/` | Override the digest directory (used by tests). |

## Always-send markers (cannot be flood-throttled)

By default, the following bypass the flood guard:

- `[KILL-SWITCH*` — operator-armed kill switches must reach the
  inbox immediately.
- `[FAIL*` — workflow failure alerts must reach the inbox
  immediately.

Operator can extend (not narrow) the list via `NOTIFY_ALWAYS_SEND_MARKERS`.

## On-disk artefacts

```
learning-loop/notify_state/notification_flood_state.json
    rolling fingerprint → last-send + send-count map +
    immediate_per_hour + immediate_per_day counters; pruned to 36 h.

learning-loop/notify_digest/YYYY-MM-DD.jsonl
    standard v3.13 digest file (one row per digested email).

learning-loop/notify_digest/notification_decisions_YYYY-MM-DD.jsonl
    append-only audit of every flood-guard decision — fingerprint,
    verdict, reason, subject + body previews.
```

Neither the state file nor the digest files are committed to the
repository as part of v3.27.3. They are operational artefacts written
by the running monitors; the `.gitignore` umbrella for
`learning-loop/runtime_state.json` etc. applies.

## Daily digest dispatch

`scripts/send_incident_digest.py` aggregates the day's audit JSONL +
digest JSONL into ONE summary email:

```
Subject: [INCIDENT-DIGEST] 2026-06-09 — N unique, M immediate, K digested

Body:
  - per-fingerprint group with first_seen / last_seen / total / immediate
    / digested counts + verdict tally + latest subject / body preview.
```

Run modes:

```bash
# Send the digest for today (default):
python3 scripts/send_incident_digest.py

# Quiet exit when there is nothing to send:
python3 scripts/send_incident_digest.py --only-if-events

# Render to stdout without sending:
python3 scripts/send_incident_digest.py --print-only

# Aggregate a specific date:
python3 scripts/send_incident_digest.py --date 2026-06-09
```

Safety:

- Sends **at most ONE email per invocation** regardless of input size.
- Refuses (exit 1) if any of
  `ALLOW_BROKER_PAPER` / `EDGE_GATE_ENABLED` /
  `BROKER_EXECUTION_ENABLED` / `LIVE_TRADING` / `LIVE_ENABLED` /
  `GO_LIVE` / `LIVE_TRADING_ENABLED` is truthy.
- NEVER imports the broker-orders module
  (asserted by `tests/test_incident_digest_script_v3273.py::TestNoBrokerImports`).

## How to tune for an operator persona

| Persona | Recommended overrides |
|---|---|
| Default (autonomous paper system) | none (the defaults: 1 send + cooldown 60 min, max 3/hr + 10/day, kill-switch + fail unsuppressed). |
| Operator wants only one incident-critical per day | `INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY=1`. |
| Operator is debugging the guard | `NOTIFY_FLOOD_GUARD_ENABLED=false` — full audit still recorded; SMTP runs every call. |
| Operator wants stricter cooldown | `INCIDENT_CRITICAL_COOLDOWN_MINUTES=180` (3 h). |
| Operator wants a custom critical bypass | `NOTIFY_ALWAYS_SEND_MARKERS=[KILL-SWITCH,[FAIL,[OPERATOR-ALERT]`. |

## Hard safety invariants

- The flood guard NEVER submits orders.
- The flood guard NEVER imports the broker-orders module
  (asserted by `tests/test_notification_flood_guard_v3273.py::TestNoBrokerImports`).
- The flood guard NEVER deletes existing audit or digest files —
  audit rows are append-only on disk.
- The flood guard NEVER silently drops a critical event — even capped
  events are appended to the digest JSONL so the operator can see
  them in `scripts/send_incident_digest.py`.
- `[KILL-SWITCH*]` and `[FAIL*]` markers bypass cooldowns + caps.
- Subject and body previews stored in the audit JSONL are redacted
  for any 16+ char uppercase-alphanumeric token (Alpaca-key shape) —
  asserted by `test_secrets_redacted_in_preview`.
- Standing markers `BROKER_PAPER_CANARY_STILL_BLOCKED` and
  `LIVE_TRADING_UNSUPPORTED` are emitted in the rendered digest body.
- `BROKER_PAPER_CANARY_STILL_BLOCKED`. `LIVE_TRADING_UNSUPPORTED`.

## Test coverage

- `tests/test_notification_flood_guard_v3273.py` — 17 tests
  (normalize/fingerprint, cooldown, hourly + daily caps, always-send,
  disable bypass, audit always written, secrets redacted, no broker
  imports).
- `tests/test_notify_policy_incident_digest_v3273.py` — 10 tests
  (`send_email` end-to-end routing, KILL-SWITCH bypass during cap,
  NOTIFY_MODE interactions, audit file growth).
- `tests/test_incident_digest_script_v3273.py` — 8 tests
  (empty aggregate, fingerprint grouping, at-most-one-email,
  --print-only never sends, broker-flag refusal, no broker imports,
  preview truncation).
- `tests/test_notify_policy_v3131.py` — legacy v3.13.x baseline; the
  helper `_reload_notify` was updated to isolate flood-guard state
  per call so the legacy tests do not collide with on-repo state.

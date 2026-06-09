"""
Shared email notification module — used by all monitors.
Sends email via Gmail SMTP when a signal is detected or order executed.
"""

from __future__ import annotations  # v3.11.3: PEP 604 (X | None) parseable on Py 3.9 (local) + 3.11 (CI).

import os
import smtplib
import traceback
from email.message import EmailMessage
from datetime import datetime, timezone

GMAIL_USER         = os.environ.get("GMAIL_USER", "").strip()
# Strip ALL whitespace variants — copy-paste from Google's UI often inserts \xa0 (non-breaking space)
GMAIL_APP_PASSWORD = (
    os.environ.get("GMAIL_APP_PASSWORD", "")
    .replace('\xa0', '')   # non-breaking space
    .replace(' ', '')  # narrow no-break space (U+202F)
    .replace(' ', '')      # regular space — Google App Passwords work without spaces
    .strip()
)
NOTIFY_TO          = os.environ.get("NOTIFY_EMAIL", GMAIL_USER).strip()


def _clean(text: str) -> str:
    """Strip ALL non-ASCII characters so SMTP never chokes."""
    return (
        text
        .replace('\xa0', ',')    # non-breaking space (locale thousands sep) -> comma
        .replace(' ', ',')  # narrow no-break space -> comma
        .replace('–', '-')  # en dash -> hyphen
        .replace('—', '-')  # em dash -> hyphen
        .encode('ascii', 'ignore')
        .decode('ascii')
    )


def _usd(amount: float) -> str:
    """Format dollar amount safely — avoids locale-sensitive thousands separator."""
    # Manually insert commas to bypass locale \xa0 issue on European Ubuntu
    try:
        s = f"{int(amount):,}"   # Python built-in comma grouping (locale-independent)
        return f"${s}".replace('\xa0', ',')
    except Exception:
        return f"${amount:.0f}"


# ─── v3.13.1 (2026-05-30) — Notification policy / inbox-noise filter ─────────
#
# Problem: monitors send dozens of emails per session (per-signal BUY/EXIT,
# cron summaries "[Monitor] N signals, M sent", individual PDT transitions,
# allocator PLAN nightly, etc.). Inbox becomes unreadable; CRITICAL alerts
# get buried.
#
# Solution: single chokepoint `send_email` consults `NotificationPolicy`
# which classifies subjects into 3 buckets:
#
#   "send"     → real email delivered (CRITICAL or actionable)
#   "digest"   → appended to learning-loop/notify_digest/<date>.jsonl
#                (read by scripts/session_report.py and optional
#                 scripts/send_daily_digest.py)
#   "suppress" → only logged to stdout, never delivered
#
# Mode controlled by env `NOTIFY_MODE` (default `minimal`):
#   off      — never send any email
#   minimal  — send CRITICAL only, digest INFO, suppress NOISE  (DEFAULT)
#   verbose  — send everything (legacy v3.12 behavior)
#
# Operator may override per-subject via NOTIFY_FORCE_SEND / NOTIFY_FORCE_SUPPRESS
# (comma-separated subject substrings).

import json
import re
from pathlib import Path

NOTIFY_MODE = os.environ.get("NOTIFY_MODE", "minimal").lower().strip()
if NOTIFY_MODE not in ("off", "minimal", "verbose"):
    NOTIFY_MODE = "minimal"

_FORCE_SEND     = [s.strip() for s in os.environ.get("NOTIFY_FORCE_SEND", "").split(",") if s.strip()]
_FORCE_SUPPRESS = [s.strip() for s in os.environ.get("NOTIFY_FORCE_SUPPRESS", "").split(",") if s.strip()]

# Subjects that ALWAYS get delivered immediately (operator must look NOW).
_CRITICAL_MARKERS = (
    "[INCIDENT-CRITICAL]",
    "[SAFE_MODE_ENTERED]",
    "[INTRADAY-DEFEND]",
    "[INTRADAY-RED-AFTER-GREEN]",
    "[PROFIT-LOCK]",
    "[ROUTINE-BUDGET-LOW]",
    "[op-correction]",
    "[POL-FILING]",        # operator must read PDF
    "[ERROR]",
    "[allocator REVALIDATE]",  # orders were dropped — operator should know
    "[CONFIDENCE-BLOCK]",  # confidence gate BLOCKed something unusual
    "[PDT-LOCKED]",        # PDT lockout — significant
    "[KILL-SWITCH",        # any kill-switch activation
    "[FAIL",               # workflow failures
)

# Subjects routed to DIGEST (batched, not immediate). Operator can read
# the digest in session_report or via scripts/send_daily_digest.py.
_DIGEST_MARKERS = (
    "[BUY]",                 # individual signal
    "[SELL]",
    "[SELL_SHORT]",
    "[EXIT]",                # individual exit
    "[EXECUTED]",            # individual options exec
    "[OPTIONS REJECTED]",
    "[QUEUED]",
    "[DEFERRED]",
    "[NOT-SENT]",
    "[INTRADAY-WARN]",       # warn-level, not action
    "[PEAK-WARN]",
    "[INCIDENT-WARN]",       # warn-level patterns
    "[PDT-OK]",
    "[PDT-CAUTION]",
    "[PDT-RESTRICTED]",
    "[SAFE_MODE_EXITED]",    # cleanup, just info
    "[allocator PLAN]",      # nightly plan, just info
    "[learning-loop AUTO-PR]",  # operator reviews on GitHub
    "[CONFIDENCE-ALERT]",    # ALERT_ONLY zone
)

# Cron-summary pattern: "[Defense Monitor] 0 signal(s), 0 sent"
_CRON_SUMMARY_RE = re.compile(r"^\[[\w\s-]+(?:Monitor|monitor)\]\s+\d+\s+signal", re.IGNORECASE)


def _classify_subject(subject: str) -> str:
    """Return one of: "send" / "digest" / "suppress".

    Pure function; deterministic; can be unit-tested without SMTP.
    """
    s = subject or ""

    # Operator overrides win first
    for marker in _FORCE_SUPPRESS:
        if marker in s:
            return "suppress"
    for marker in _FORCE_SEND:
        if marker in s:
            return "send"

    # Global mode shortcuts
    if NOTIFY_MODE == "off":
        return "suppress"
    if NOTIFY_MODE == "verbose":
        return "send"

    # MINIMAL mode logic:

    # 1) Critical = always send
    for marker in _CRITICAL_MARKERS:
        if marker in s:
            return "send"

    # 2) Allocator EXEC: only send if failures present
    if "[allocator EXEC]" in s:
        # subjects are like "[allocator EXEC] 0 placed, 0 skipped, 6 failed"
        m = re.search(r"(\d+)\s+failed", s)
        if m and int(m.group(1)) > 0:
            return "send"
        return "digest"

    # 3) Cron summaries — suppress when zero signals, digest otherwise
    cs = _CRON_SUMMARY_RE.match(s)
    if cs:
        # Has signals number — check if it's zero
        m = re.search(r"\]\s+(\d+)\s+signal", s)
        if m and int(m.group(1)) == 0:
            return "suppress"
        return "digest"

    # 4) Known digest markers
    for marker in _DIGEST_MARKERS:
        if marker in s:
            return "digest"

    # 5) Unknown subjects — send (safer to surface than swallow)
    return "send"


def _append_to_digest(subject: str, body: str) -> None:
    """Append non-critical email to local digest file.

    Format: one JSONL row per suppressed/digested email. Read by
    scripts/session_report.py and scripts/send_daily_digest.py.

    Fail-soft: any I/O error → fall back to stdout only.
    """
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        ts    = datetime.now(timezone.utc).isoformat()
        # Allow override via env (used by tests for isolation)
        digest_dir_env = os.environ.get("NOTIFY_DIGEST_DIR")
        if digest_dir_env:
            digest_dir = Path(digest_dir_env)
        else:
            digest_dir = Path(__file__).resolve().parent.parent / "learning-loop" / "notify_digest"
        digest_dir.mkdir(parents=True, exist_ok=True)
        path = digest_dir / f"{today}.jsonl"
        entry = {"timestamp": ts, "subject": subject, "body_preview": (body or "")[:500]}
        with path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # Never let digest failure block the workflow
        print(f"  [notify-digest] append failed (non-fatal): {e}")


def _consult_flood_guard(subject: str, body: str) -> tuple[str, str, str] | None:
    """v3.27.3 — apply ``shared/notification_flood_guard`` ahead of the
    SMTP fast-path. Returns ``(verdict, fingerprint, reason)`` or ``None``
    if the flood-guard module is unavailable (import error → fail-soft
    preserves v3.13 behaviour).
    """
    try:
        import notification_flood_guard as _g  # type: ignore
    except ImportError:
        try:
            from shared import notification_flood_guard as _g  # type: ignore
        except ImportError:
            return None
    try:
        return _g.evaluate_and_record(subject, body)
    except Exception as e:
        # Never let the flood-guard break the SMTP path; surface and
        # fall through to the legacy classifier.
        print(f"  [notify-flood-guard] error (non-fatal): {e}")
        return None


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """
    Send email via Gmail SMTP, gated by NotificationPolicy + v3.27.3
    flood guard.

    Returns True on successful delivery OR successful digest append.
    Returns False only on hard failure (SMTP error after classifier said "send").
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("  Email: missing GMAIL_USER or GMAIL_APP_PASSWORD - skipping")
        return False

    # ── v3.13.1: consult policy BEFORE building SMTP message ──
    verdict = _classify_subject(subject)

    if verdict == "suppress":
        print(f"  [notify-policy] SUPPRESS: {subject[:80]}")
        return False  # not delivered (intentional)

    if verdict == "digest":
        print(f"  [notify-policy] DIGEST: {subject[:80]}")
        _append_to_digest(subject, body)
        return True   # successfully digested

    # ── v3.27.3: consult flood-guard before the SMTP fast-path ──
    # The guard only gates flood-guarded prefixes (default:
    # `[INCIDENT-CRITICAL]`). Everything else returns
    # ``FLOOD_SEND_ESCALATION`` and falls through to SMTP unchanged.
    guard_result = _consult_flood_guard(subject, body)
    if guard_result is not None:
        fg_verdict, fg_fp, fg_reason = guard_result
        try:
            import notification_flood_guard as _g  # type: ignore
        except ImportError:
            from shared import notification_flood_guard as _g  # type: ignore
        if fg_verdict in _g.DIGEST_VERDICTS:
            print(
                f"  [notify-flood-guard] {fg_verdict} fp={fg_fp} "
                f"reason={fg_reason}: {subject[:80]}")
            # Always append to the standard digest so the operator
            # never loses sight of the event — even capped ones.
            _append_to_digest(subject, body)
            return True
        # SENDING verdicts (FLOOD_SEND_FIRST / FLOOD_SEND_ESCALATION /
        # FLOOD_BYPASS_DISABLED) fall through to SMTP.

    # verdict == "send" → original SMTP path
    try:
        subject = _clean(subject)
        body    = _clean(body)

        print(f"  [email] subject repr: {repr(subject[:60])}")
        print(f"  [email] body len: {len(body)}, first 80: {repr(body[:80])}")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = NOTIFY_TO
        print(f"  [email] headers set OK, calling set_content...")
        msg.set_content(body, charset="utf-8")
        print(f"  [email] content set, connecting to smtp.gmail.com:465...")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)

        print(f"  Email sent: {subject}")
        return True

    except Exception as e:
        print(f"  Email error: {e}")
        traceback.print_exc()
        return False


def notify_signal(signal: dict, alert_sent: bool, reason: str = "") -> bool:
    """Notification about a detected trading signal.

    Options proposals (signal['option_type'] set) get a richer subject and
    body that doubles as an autonomous-audit notification. Per the
    autonomy contract (docs/AUTONOMY_CONTRACT.md) there is no operator
    approval step — every signal ends APPROVE or REJECT.
    """
    if signal.get("option_type"):
        return _notify_options_proposal(signal, alert_sent)

    symbol   = signal.get("symbol", "?")
    action   = signal.get("action", "?")
    strategy = signal.get("strategy", "?")
    size_usd = signal.get("size_usd", 0)
    # Display entry price if monitor provided it. Do NOT fall back to
    # `score` (relevance/momentum score) — that produced misleading
    # bodies like "Price: $2.00" for defense signals where score=2 is
    # unrelated to ticker price. Defense/Twitter signals leave price
    # blank; order placement uses fresh quote at execute time.
    price    = signal.get("price")
    if price is None and signal.get("entry_price") is not None:
        price = signal["entry_price"]
    headline = signal.get("headline", signal.get("keywords", ""))
    source   = signal.get("source", "")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    arrow  = "BUY" if action.upper().startswith("BUY") else "SELL"
    if alert_sent:
        status = "Alert sent to Alpaca"
    elif reason:
        status = f"Alert NOT sent ({reason})"
    else:
        status = "Alert NOT sent (error)"

    # Subject prefix communicates outcome at-a-glance:
    #   BUY/SELL  — actually placed at Alpaca
    #   QUEUED    — market closed (pre/after/weekend/holiday); signal valid, retry later
    #   DEFERRED  — per-instrument window blocked (e.g. paused symbol like MSTR/SMCI,
    #               or trade-window says no); same outcome as QUEUED but emphasizes
    #               that the cause is per-instrument policy not pure market hours
    #   NOT-SENT  — hard failure (risk-officer REJECT, API error, etc.)
    market_closed_reasons = ("pre_market", "after_hours", "weekend", "holiday", "closed")
    if alert_sent:
        prefix = arrow
    elif reason and any(r in reason for r in market_closed_reasons):
        prefix = "QUEUED"
    elif reason and ("paused" in reason or "trade-window" in reason or "blocked" in reason):
        prefix = "DEFERRED"
    elif reason:
        prefix = "NOT-SENT"
    else:
        prefix = arrow                     # legacy callers without reason
    subject = f"[{prefix}] [{strategy}] {action} {symbol} - {_usd(size_usd)}"

    body = (
        f"Trading Signal Detected\n"
        f"{'='*40}\n"
        f"Time:     {now}\n"
        f"Symbol:   {symbol}\n"
        f"Action:   {action}\n"
        f"Strategy: {strategy}\n"
        f"Size:     {_usd(size_usd)}\n"
        + (f"Price:    ${price:.2f}\n" if isinstance(price, (int, float)) else "")
        + (f"Score:    {signal.get('score', '')}\n" if signal.get('score') else "")
        + (f"Source:   {source}\n" if source else "")
        + (f"Headline: {str(headline)[:120]}\n" if headline else "")
        + f"\nStatus: {status}\n"
        f"{'='*40}\n"
        f"Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview"
    )

    return send_email(subject, body)


def _notify_options_proposal(signal: dict, alert_sent: bool) -> bool:
    symbol     = signal.get("symbol", "?")
    action     = signal.get("action", "?")
    opt_type   = signal.get("option_type", "?").upper()
    spot       = signal.get("spot", 0)
    strike_t   = signal.get("strike_target", 0)
    strike_min = signal.get("strike_min", 0)
    strike_max = signal.get("strike_max", 0)
    expiry_min = signal.get("expiry_min", "")
    expiry_max = signal.get("expiry_max", "")
    iv_max     = signal.get("iv_max_pct", 0)
    size_usd   = signal.get("size_usd", 0)
    max_ctr    = signal.get("max_contracts", 1)
    rsi        = signal.get("rsi", 0)
    tp_mult    = signal.get("tp_premium_mult", 1.8)
    sl_mult    = signal.get("sl_premium_mult", 0.5)
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # AUTONOMY: this email is an audit notification, NOT an approval
    # request. The options-monitor auto-decides APPROVE/REJECT per
    # docs/AUTONOMY_CONTRACT.md. If a proposal email arrives the system
    # has already EITHER placed the order ([EXECUTED] subject) OR rejected
    # it for a deterministic reason (this subject).
    routine_status = "delivered to routine" if alert_sent else "routine delivery FAILED"
    subject = f"[OPTIONS REJECTED] {opt_type} {symbol} ~${strike_t} ({expiry_min}..{expiry_max})"

    body = (
        f"Options Proposal - AUTONOMOUSLY REJECTED (audit)\n"
        f"{'='*48}\n"
        f"Time:        {now}\n"
        f"Symbol:      {symbol}\n"
        f"Type:        {opt_type}\n"
        f"Action:      {action}\n"
        f"Spot:        ${spot}\n"
        f"Strike:      ~${strike_t}  (range ${strike_min} - ${strike_max})\n"
        f"Expiry:      {expiry_min}  to  {expiry_max}\n"
        f"IV cap:      <= {iv_max}%\n"
        f"Budget:      {_usd(size_usd)}  (max {max_ctr} contract(s))\n"
        f"TP:          +{int((tp_mult - 1) * 100)}% premium\n"
        f"SL:          -{int((1 - sl_mult) * 100)}% premium\n"
        f"RSI signal:  {rsi}\n"
        f"\n"
        f"Decision: REJECT (autonomous). Most common reasons:\n"
        f"  - OPTIONS_ENABLED=false in this environment\n"
        f"  - liquidity gate failed (spread/OI/volume)\n"
        f"  - portfolio_risk premium-at-risk cap hit\n"
        f"  - max open options reached\n"
        f"Audit trail: journal/autonomy/YYYY-MM-DD.jsonl\n"
        f"\n"
        f"Routine: {routine_status}.\n"
        f"{'='*48}\n"
    )
    return send_email(subject, body)


def notify_exit(symbol: str, action: str, reason: str, pl_pct: float = None) -> bool:
    """Notification when exit monitor closes a position."""
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pl_str = f" | P&L: {pl_pct:+.1f}%" if pl_pct is not None else ""

    subject = f"[EXIT] {symbol} - {reason}{pl_str}"
    body = (
        f"Exit Monitor - Position Closed\n"
        f"{'='*40}\n"
        f"Time:   {now}\n"
        f"Symbol: {symbol}\n"
        f"Action: {action}\n"
        f"Reason: {reason}\n"
        + (f"P&L:    {pl_pct:+.1f}%\n" if pl_pct is not None else "")
        + f"{'='*40}\n"
        f"Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview"
    )

    return send_email(subject, body)


def notify_order_executed(symbol: str, side: str, qty: float, price: float,
                           size_usd: float, sl: float, tp: float,
                           strategy: str, order_id: str) -> bool:
    """Notification after a bracket order is placed."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rr  = round((tp - price) / (price - sl), 2) if sl and tp and price and (price - sl) != 0 else "?"

    subject = f"[EXECUTED] {symbol} {side} @ ${price:.2f}"
    body = (
        f"Trade Executed\n"
        f"{'='*40}\n"
        f"Time:     {now}\n"
        f"Symbol:   {symbol}\n"
        f"Side:     {side}\n"
        f"Price:    ${price:.2f}\n"
        f"Qty:      {qty}\n"
        f"Size:     {_usd(size_usd)}\n"
        f"SL:       ${sl:.2f}\n"
        f"TP:       ${tp:.2f}\n"
        f"R:R:      {rr}\n"
        f"Strategy: {strategy}\n"
        f"Order ID: {order_id}\n"
        f"{'='*40}\n"
        f"Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview"
    )

    return send_email(subject, body)


def notify_summary(monitor: str, signals_found: int, alerts_sent: int) -> bool:
    """
    Short run summary — only sends when signals were found (no spam on empty runs).
    """
    if signals_found == 0:
        return False

    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[{monitor}] {signals_found} signal(s), {alerts_sent} sent"
    body = (
        f"Monitor Run Summary\n"
        f"{'='*40}\n"
        f"Monitor:       {monitor}\n"
        f"Time:          {now}\n"
        f"Signals found: {signals_found}\n"
        f"Alerts sent:   {alerts_sent}\n"
        f"{'='*40}\n"
        f"Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview"
    )

    return send_email(subject, body)


def notify_pr_open(pr_url: str, title: str, lane: str, risk: str) -> bool:
    """
    Email the operator when the daily learning-loop opens a Lane 2 auto-PR
    with a new heuristic for adapter.py. The PR is not pilne — but the
    operator should know it's queued.
    """
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[learning-loop AUTO-PR] {title[:60]}"
    body = (
        f"Learning-loop Lane 2 — auto-PR opened\n"
        f"{'='*60}\n"
        f"Time:    {now}\n"
        f"Lane:    {lane}\n"
        f"Risk:    {risk}\n"
        f"Title:   {title}\n"
        f"PR URL:  {pr_url}\n"
        f"{'='*60}\n\n"
        f"What this is:\n"
        f"  The daily learning-loop LLM (Senior PM persona) proposed a new\n"
        f"  heuristic for learning-loop/adapter.py. The proposal passed the\n"
        f"  Lane 2 validation gate (target file in whitelist, code parses,\n"
        f"  test_adapter.py stays green) and a PR has been opened.\n\n"
        f"What you should do:\n"
        f"  1. Open the PR.\n"
        f"  2. Review the appended function and its test (both append-only\n"
        f"     to the existing files — no edits to existing code).\n"
        f"  3. If the proposal includes a `wire_into_adapt_strategy` hint,\n"
        f"     add a small follow-up commit that wires the call point.\n"
        f"  4. Merge when satisfied. CI must be green (it should be —\n"
        f"     local tests passed before the PR was created).\n\n"
        f"Safety net:\n"
        f"  - The PR is append-only by construction. Existing heuristics\n"
        f"    are untouched.\n"
        f"  - If you don't merge, nothing changes — daily-learning will\n"
        f"    keep using the deterministic adapter unchanged.\n"
        f"  - The branch name pattern is `learning-loop/auto-YYYY-MM-DD-*`\n"
        f"    so you can filter / batch-review later.\n"
    )

    return send_email(subject, body)


def notify_allocation_plan(plan: dict) -> bool:
    """
    Email summary after AccountAwareAllocator generates a daily plan.
    Always sends (no signal threshold) so operator always sees what
    is queued for the morning executor.

    Subject:
      [allocator PLAN] regime=X invested_after=YY% N orders (auto_execute=Z)
    """
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    regime  = plan.get("market_regime", "?")
    invested_before = plan.get("invested_ratio_before", 0)
    invested_after  = plan.get("invested_ratio_after_target", 0)
    orders  = plan.get("rebalance_orders") or []
    risk    = plan.get("risk_checks") or {}
    n_act   = risk.get("n_orders", 0)
    n_hold  = risk.get("n_hold", 0)
    auto_x  = (plan.get("config") or {}).get("auto_execute", False)
    equity  = plan.get("account_equity", 0)
    cash    = plan.get("cash", 0)

    subject = (
        f"[allocator PLAN] {regime} "
        f"invested {invested_before:.0%} -> {invested_after:.0%} "
        f"({n_act} orders, auto={'ON' if auto_x else 'OFF'})"
    )

    lines = []
    lines.append(f"Daily allocation plan ({plan.get('date', '?')})")
    lines.append("=" * 60)
    lines.append(f"Generated:        {now}")
    lines.append(f"Equity:           {_usd(equity)}")
    lines.append(f"Cash:             {_usd(cash)}")
    lines.append(f"Regime:           {regime} (source={plan.get('regime_source','?')})")
    lines.append(f"Invested before:  {invested_before:.2%}")
    lines.append(f"Invested target:  {invested_after:.2%}")
    lines.append(f"Defensive mode:   {plan.get('defensive_mode_active', False)}")
    lines.append(f"Kill switch:      {plan.get('kill_switch_armed', False)}")
    lines.append(f"Auto-execute:     {'ON' if auto_x else 'OFF (plan-only)'}")
    lines.append("")
    lines.append(f"Allocation reason: {plan.get('allocation_reason','?')}")
    lines.append("")
    lines.append(f"Target weights ({len(plan.get('target_weights') or {})}):")
    for sym, w in (plan.get("target_weights") or {}).items():
        usd = w * equity
        lines.append(f"  {sym:<10} {w:>6.2%}   ({_usd(usd)})")
    lines.append("")
    lines.append(f"Rebalance orders ({n_act} actionable + {n_hold} hold):")
    for o in orders:
        action = o.get("action", "?")
        sym = o.get("symbol", "?")
        delta = o.get("delta", 0)
        reason = o.get("reason", "")
        lines.append(f"  [{action:<6}] {sym:<10} delta={delta:+9.2f}  {reason}")
    lines.append("")

    failed = risk.get("failed") or []
    if failed:
        lines.append("Risk checks failed:")
        for f in failed:
            lines.append(f"  - {f}")
        lines.append("")

    lines.append("Status:")
    if auto_x:
        lines.append("  AUTO-EXECUTE active. Morning executor (13:35 UTC) will fire orders")
        lines.append("  through deterministic risk gates (risk_officer + portfolio_risk +")
        lines.append("  intraday_governor + instrument_windows + buying_power).")
        lines.append("  No manual action required. Watch inbox for [allocator EXEC] report.")
    else:
        # 2026-05-14: This branch is now informational only — system is meant
        # to run with auto_execute_rebalance=true. If you're seeing this in
        # production, it means a deployment regression has occurred — fix the
        # config; no operator action expected.
        lines.append("  AUTO-EXECUTE is currently DISABLED (regression detected).")
        lines.append(f"  Plan saved at: learning-loop/allocations/{plan.get('date','?')}.json")
        lines.append("  Re-enable by setting capital_deployment.auto_execute_rebalance=true.")
    lines.append("")
    lines.append("Trace log: learning-loop/allocations/" + str(plan.get("date", "?")) + ".log")
    lines.append("Dashboard: https://app.alpaca.markets/paper/dashboard/overview")

    return send_email(subject, "\n".join(lines))


def notify_allocation_execution(plan_date: str, results: list[dict]) -> bool:
    """
    Email summary after morning executor places orders. Always sends.

    Subject:
      [allocator EXEC] N placed, M skipped, K failed
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n_placed  = sum(1 for r in results if r.get("status") == "placed")
    n_skipped = sum(1 for r in results if r.get("status") == "skipped")
    n_failed  = sum(1 for r in results if r.get("status") == "failed")

    subject = f"[allocator EXEC] {n_placed} placed, {n_skipped} skipped, {n_failed} failed"

    lines = []
    lines.append(f"Allocation execution report ({plan_date})")
    lines.append("=" * 60)
    lines.append(f"Executed at:  {now}")
    lines.append(f"Placed:       {n_placed}")
    lines.append(f"Skipped:      {n_skipped}")
    lines.append(f"Failed:       {n_failed}")
    lines.append("")
    lines.append("Per-order results:")
    for r in results:
        sym    = r.get("symbol", "?")
        action = r.get("action", "?")
        status = r.get("status", "?")
        reason = r.get("reason", "")
        oid    = r.get("alpaca_order_id", "")
        line   = f"  [{status:<7}] {action:<6} {sym:<10}  {reason}"
        if oid:
            line += f"  id={oid}"
        lines.append(line)
    lines.append("")
    lines.append("Dashboard: https://app.alpaca.markets/paper/dashboard/overview")
    lines.append(f"Plan source: learning-loop/allocations/{plan_date}.json")

    return send_email(subject, "\n".join(lines))


def notify_peak_retrace(peak: dict, level: str = "WARN") -> bool:
    """
    Email alert when intraday daily P&L has retraced significantly from peak.
    `peak` is the shared.peak_tracker dict (see peak_tracker.update_peak).
    `level` is "WARN" (30-50% retrace) or "PROFIT_LOCK" (50%+).

    Caller is responsible for dedup (use peak_tracker.alert_already_sent_today).
    """
    if not peak:
        return False
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pk_usd      = float(peak.get("peak_pl_usd", 0))
    cur_usd     = float(peak.get("current_pl_usd", 0))
    pk_at       = (peak.get("peak_at") or "?")[:16].replace("T", " ")
    retrace_pct = float(peak.get("retrace_from_peak", 0))

    if level == "PROFIT_LOCK":
        subject = f"[PROFIT-LOCK] Intraday P&L retraced {retrace_pct:.0%} from peak ${pk_usd:+,.0f}"
        urgency = "PROFIT-LOCK CASCADE ARMED — aggressive winner harvesting active"
    else:
        subject = f"[PEAK-WARN] Intraday P&L retraced {retrace_pct:.0%} from peak ${pk_usd:+,.0f}"
        urgency = "WARNING — retrace approaching profit-lock threshold (50%)"

    lines = [
        "Intraday P&L peak alert",
        "=" * 60,
        f"Time:              {now}",
        f"Level:             {level}",
        f"Status:            {urgency}",
        "",
        f"Peak P&L:          ${pk_usd:+,.2f}",
        f"Peak at:           {pk_at}",
        f"Peak equity:       ${float(peak.get('peak_equity',0)):,.2f}",
        "",
        f"Current P&L:       ${cur_usd:+,.2f}",
        f"Current equity:    ${float(peak.get('current_equity',0)):,.2f}",
        f"Retrace from peak: {retrace_pct:.1%}",
        "",
    ]

    if level == "PROFIT_LOCK":
        lines += [
            "What happens now:",
            "  exit-monitor + options-exit-monitor will aggressively close",
            "  winning positions at PEAK * 0.70 instead of waiting for static TP.",
            "  Goal: lock 70% of unrealized gains before further retrace.",
            "",
            "Why this fired:",
            "  Yesterday (2026-05-12) +$3,173 peak retraced to -$184 over",
            "  4.5 hours with zero protective action. This alert is the fix.",
        ]
    else:
        lines += [
            "What to monitor:",
            "  If retrace crosses 50% from peak, PROFIT-LOCK cascade arms",
            "  and exit-monitor switches to aggressive harvest mode.",
            "",
            "Manual override:",
            "  Set learning-loop/state.json::daily_peak.profit_lock_disabled=true",
            "  if you intentionally want to ride the position through retrace.",
        ]

    lines += [
        "",
        f"Dashboard: https://app.alpaca.markets/paper/dashboard/overview",
    ]

    return send_email(subject, "\n".join(lines))


def notify_intraday_state(snapshot: dict | object, level: str) -> bool:
    """
    Email audit when IntradayProfitGovernor enters one of the protected
    states (GIVEBACK_WARN, PROFIT_LOCK, DEFEND_DAY, RED_DAY_AFTER_GREEN).

    `snapshot` is an IntradaySnapshot dataclass OR its dict form. `level`
    is one of those state names. Subject is prefixed `[INTRADAY-PROTECTION]`.

    Body lists peak, current, giveback, max-gross target, what actions
    just fired, and the affected symbols (if reduced/closed positions
    were passed via `top_giveback_symbols`).

    Dedup is the caller's responsibility (mark_alert_sent in governor).
    """
    if hasattr(snapshot, "to_dict"):
        snap = snapshot.to_dict()
    else:
        snap = dict(snapshot or {})
    if not snap:
        return False

    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    peak_usd = float(snap.get("intraday_peak_pnl", 0))
    cur_usd  = float(snap.get("current_intraday_pnl", 0))
    peak_eq  = float(snap.get("intraday_peak_equity", 0))
    cur_eq   = float(snap.get("current_equity", 0))
    retrace  = float(snap.get("giveback_pct_of_peak", 0))
    peak_at  = (snap.get("peak_at") or "?")[:16].replace("T", " ")
    floor    = float(snap.get("profit_floor_usd", 0))
    max_gx   = float(snap.get("max_gross_target", 1.50))
    affected = snap.get("top_giveback_symbols") or []
    action   = snap.get("last_action") or "-"

    headers = {
        "GIVEBACK_WARN":       ("[INTRADAY-WARN]",        "WARN — retrace > 25% of intraday peak"),
        "PROFIT_LOCK":         ("[INTRADAY-PROFIT-LOCK]", "PROFIT-LOCK ARMED — winners harvested, options closed first"),
        "DEFEND_DAY":          ("[INTRADAY-DEFEND]",      "DEFEND-DAY — exposure cut to 50%, weak positions flattened, new entries blocked"),
        "RED_DAY_AFTER_GREEN": ("[INTRADAY-RED-AFTER-GREEN]", "RED AFTER GREEN — intraday flat-mode, entries blocked until next session"),
    }
    prefix, urgency = headers.get(level, ("[INTRADAY]", level))
    subject = f"{prefix} peak ${peak_usd:+,.0f} → current ${cur_usd:+,.0f} ({retrace:.0%} giveback)"

    lines = [
        "Intraday profit governor state change",
        "=" * 60,
        f"Time:                {now}",
        f"State:               {level}",
        f"Action:              {urgency}",
        f"Action codename:     {action}",
        "",
        f"Peak P&L:            ${peak_usd:+,.2f}",
        f"Peak equity:         ${peak_eq:,.2f}",
        f"Peak at:             {peak_at}",
        "",
        f"Current P&L:         ${cur_usd:+,.2f}",
        f"Current equity:      ${cur_eq:,.2f}",
        f"Giveback from peak:  {retrace:.1%}",
        f"Profit floor:        " + (f"${floor:,.2f}" if floor > 0 else "(not armed)"),
        f"Max gross target:    {max_gx:.2f}× equity",
        "",
    ]

    if level == "RED_DAY_AFTER_GREEN":
        lines += [
            "What just happened (deterministic):",
            "  exit-monitor will close all options momentum positions and",
            "  any non-hedge intraday positions. alpaca_orders.py will reject",
            "  every new entry until the next session.",
            "",
            "Why this fired:",
            "  A day that peaked at +$5,000 or more cannot be allowed to end",
            "  flat-or-negative without protective action. The +5000 → -2000",
            "  scenario from prior sessions ends here.",
        ]
    elif level == "DEFEND_DAY":
        lines += [
            "What just happened:",
            "  Gross exposure clamped to 0.50×. New entries are blocked.",
            "  Weak intraday positions and options flagged for flattening.",
            "  Hedges (TLT / GLD) are allowed to remain open.",
        ]
    elif level == "PROFIT_LOCK":
        lines += [
            "What just happened:",
            "  Winners ≥+8% (and ALL options) are flagged for direct close.",
            "  Gross exposure clamped to 1.00× equity. Below-threshold new",
            "  entries blocked; only signals with score ≥ 0.65 punch through.",
        ]
    else:
        lines += [
            "What to watch:",
            "  Trailing stops tightened. No automated exits yet — but if",
            "  retrace crosses 35% the system advances to PROFIT_LOCK.",
        ]

    if affected:
        lines += ["", "Top giveback contributors:"]
        lines += [f"  - {s}" for s in affected[:8]]

    lines += [
        "",
        "Dashboard: https://app.alpaca.markets/paper/dashboard/overview",
        "Audit log: journal/autonomy/ (one JSONL line per FSM transition)",
    ]

    return send_email(subject, "\n".join(lines))


def notify_pdt_state(snapshot: dict, transition: str = "ENTER") -> bool:
    """
    Email audit when the PDT guard transitions between modes (OK →
    CAUTION → RESTRICTED → LOCKED). Dedup is caller's responsibility.

    `snapshot` is a PDTSnapshot.to_dict() result. `transition` is "ENTER"
    when entering the new state, "EXIT" when leaving (mode improved).

    Subject prefix maps to severity:
      OK         → [PDT-OK]          (informational only)
      CAUTION    → [PDT-CAUTION]     (1-2 day-trades used)
      RESTRICTED → [PDT-RESTRICTED]  (one DT away from DTMC)
      LOCKED     → [PDT-LOCKED]      (BP=0 or DTMC active)
    """
    if not snapshot:
        return False

    mode      = snapshot.get("mode", "UNKNOWN")
    dt_used   = int(snapshot.get("daytrade_count", 0))
    dt_limit  = int(snapshot.get("dt_limit", 3))
    dt_remain = int(snapshot.get("dt_remaining", 0))
    bp        = float(snapshot.get("buying_power", 0))
    equity    = float(snapshot.get("equity", 0))
    bp_pct    = float(snapshot.get("bp_pct_equity", 0))
    reason    = snapshot.get("reason", "")
    ts        = (snapshot.get("classified_at") or "")[:16].replace("T", " ")

    prefix_map = {
        "OK":         ("[PDT-OK]",         "PDT mode improved to OK"),
        "CAUTION":    ("[PDT-CAUTION]",    f"PDT CAUTION — daytrade {dt_used}/{dt_limit} used"),
        "RESTRICTED": ("[PDT-RESTRICTED]", f"PDT RESTRICTED — one DT from DTMC ({dt_used}/{dt_limit})"),
        "LOCKED":     ("[PDT-LOCKED]",     f"PDT LOCKED — BP=$0 or DTMC active"),
    }
    prefix, summary = prefix_map.get(mode, ("[PDT]", f"PDT mode={mode}"))
    subject = f"{prefix} {summary}"

    lines = [
        f"PDT-guard {transition} {mode}",
        "=" * 60,
        f"Time:               {ts}",
        f"Mode:               {mode}",
        f"Reason:             {reason}",
        "",
        f"Daytrade count:     {dt_used}/{dt_limit} used (remaining {dt_remain})",
        f"Buying power:       ${bp:,.0f} ({bp_pct:.1f}% of equity)",
        f"Equity:             ${equity:,.0f}",
        "",
    ]

    if mode == "LOCKED":
        lines += [
            "Behaviour:",
            "  - All new BUY/SELL_SHORT orders BLOCKED (broker would reject).",
            "  - Non-emergency intraday closes BLOCKED.",
            "  - Emergency closes (CLOSE_EMERGENCY / PROFIT_LOCK / SL hit /",
            "    governor force-close) HONOURED — positions can always die.",
            "",
            "Recovery path:",
            "  - Wait for 5-business-day rolling window to expire (PDT count drops).",
            "  - OR close existing positions to free buying_power.",
        ]
    elif mode == "RESTRICTED":
        lines += [
            "Behaviour:",
            "  - New BUYs ALLOWED but the position MUST be held overnight",
            "    (closing same day would trip DTMC).",
            "  - Non-emergency intraday closes DEFERRED to next session.",
            "  - Emergency closes HONOURED.",
        ]
    elif mode == "CAUTION":
        lines += [
            "Behaviour:",
            "  - All orders ALLOWED (warning level only).",
            "  - System favours overnight holds at this level.",
        ]
    else:
        lines += [
            "Behaviour:",
            "  - Normal operations. No PDT-driven order restrictions.",
        ]

    lines += [
        "",
        f"Dashboard: https://app.alpaca.markets/paper/dashboard/overview",
        f"Audit log: journal/autonomy/ (one JSONL line per blocked/deferred order)",
    ]

    return send_email(subject, "\n".join(lines))


def notify_routine_budget_low(state: dict, threshold: int = 3) -> bool:
    """
    Email warning when remaining routine call budget drops below
    `threshold` (default 3). Caller (typically learning-loop analyzer
    end-of-run) decides when to fire. Dedup is caller's responsibility.

    `state` is the dict returned by routine_budget.get_state():
      {total_used, daily_limit, remaining_total, by_tier, remaining_by_tier, ...}
    """
    if not state:
        return False

    used      = int(state.get("total_used", 0))
    limit     = int(state.get("daily_limit", 15))
    remaining = int(state.get("remaining_total", 0))
    by_tier   = state.get("by_tier", {}) or {}
    remain_t  = state.get("remaining_by_tier", {}) or {}

    if remaining > threshold:
        return False  # Not low enough to alert.

    subject = f"[ROUTINE-BUDGET-LOW] {remaining} of {limit} calls remaining today"

    lines = [
        "Anthropic Routines daily budget warning",
        "=" * 60,
        f"Total used today:    {used}/{limit}",
        f"Remaining (incl buffer): {remaining}",
        "",
        "By tier:",
    ]
    for tname in ("P0_essential", "P1_important", "P2_optional"):
        used_t = int(by_tier.get(tname, 0))
        rem_t  = int(remain_t.get(tname, 0))
        lines.append(f"  {tname:18s} used={used_t}  remaining={rem_t}")

    lines += [
        "",
        "Behaviour going forward (deterministic):",
        "  - P0 (daily-learning) is reserved — calls go through up to cap.",
        "  - P2 (Reddit/Crypto Curators) start refusing with 'budget BLOCK'.",
        "  - Monitor still emits heuristic signals; only LLM enrichment skipped.",
        "",
        "Reset: automatic at next UTC midnight.",
    ]

    return send_email(subject, "\n".join(lines))

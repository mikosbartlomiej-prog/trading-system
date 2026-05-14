"""
Shared email notification module — used by all monitors.
Sends email via Gmail SMTP when a signal is detected or order executed.
"""

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


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """
    Send email via Gmail SMTP.
    Returns True on success.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("  Email: missing GMAIL_USER or GMAIL_APP_PASSWORD - skipping")
        return False

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

    lines.append("Next step:")
    if auto_x:
        lines.append("  Morning executor will place orders shortly after 13:35 UTC.")
        lines.append("  Watch inbox for [allocator EXEC] follow-up.")
    else:
        lines.append("  Auto-execute is OFF. Review plan in repo:")
        lines.append(f"  learning-loop/allocations/{plan.get('date','?')}.json")
        lines.append("  To enable: set capital_deployment.auto_execute_rebalance=true")
        lines.append("  in config/capital_deployment.json and commit.")
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

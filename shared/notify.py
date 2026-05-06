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


def notify_signal(signal: dict, alert_sent: bool) -> bool:
    """Notification about a detected trading signal."""
    symbol   = signal.get("symbol", "?")
    action   = signal.get("action", "?")
    strategy = signal.get("strategy", "?")
    size_usd = signal.get("size_usd", 0)
    price    = signal.get("price", signal.get("score", "?"))
    headline = signal.get("headline", signal.get("keywords", ""))
    source   = signal.get("source", "")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    arrow  = "BUY" if action.upper().startswith("BUY") else "SELL"
    status = "Alert sent to Alpaca" if alert_sent else "Alert NOT sent (error)"

    subject = f"[{arrow}] [{strategy}] {action} {symbol} - {_usd(size_usd)}"

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

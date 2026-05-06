"""
Shared email notification module — uzywany przez wszystkie monitory.
Wysyla email przez Gmail SMTP gdy wykryto sygnal lub wykonano zlecenie.
"""

import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone

GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_TO          = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


def _clean(text: str) -> str:
    """Strip all non-ASCII so SMTP and stdout never choke on emoji/dashes/nbsp."""
    return (
        text
        .replace('\xa0', ' ')    # non-breaking space -> regular space
        .replace(' ', ' ')  # narrow no-break space -> regular space
        .replace('—', '-')  # em dash -> hyphen
        .replace('–', '-')  # en dash -> hyphen
        .encode('ascii', 'ignore')
        .decode('ascii')
    )


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """
    Wysyla email przez Gmail SMTP.
    Zwraca True jesli sukces.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("  Email: brak GMAIL_USER lub GMAIL_APP_PASSWORD - pomijam")
        return False

    try:
        subject = _clean(subject)
        body    = _clean(body)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = NOTIFY_TO
        msg.set_content(body, charset="utf-8")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)

        print(f"  Email wyslany: {subject}")
        return True

    except Exception as e:
        print(f"  Email blad: {e}")
        return False


def notify_signal(signal: dict, alert_sent: bool) -> bool:
    """
    Powiadomienie o wykrytym sygnale tradingowym.
    """
    symbol   = signal.get("symbol", "?")
    action   = signal.get("action", "?")
    strategy = signal.get("strategy", "?")
    size_usd = signal.get("size_usd", 0)
    price    = signal.get("price", signal.get("score", "?"))
    headline = signal.get("headline", signal.get("keywords", ""))
    source   = signal.get("source", "")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    arrow  = "BUY" if action in ("BUY", "BUY_TO_OPEN") else "SELL"
    status = "Alert sent to Alpaca" if alert_sent else "Alert NOT sent (error)"

    subject = f"[{arrow}] [{strategy}] {action} {symbol} - ${size_usd:,.0f}".replace('\xa0', ',')

    body = (
        f"Trading Signal Detected\n"
        f"{'='*40}\n"
        f"Time:     {now}\n"
        f"Symbol:   {symbol}\n"
        f"Action:   {action}\n"
        f"Strategy: {strategy}\n"
        f"Size:     ${size_usd:,.0f}\n"
        + (f"Price:    ${price}\n" if isinstance(price, (int, float)) else "")
        + (f"Score:    {signal.get('score', '')}\n" if signal.get('score') else "")
        + (f"Source:   {source}\n" if source else "")
        + (f"Headline: {str(headline)[:120]}\n" if headline else "")
        + f"\nStatus: {status}\n"
        f"{'='*40}\n"
        f"Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview"
    )

    return send_email(subject, body)


def notify_exit(symbol: str, action: str, reason: str, pl_pct: float = None) -> bool:
    """
    Powiadomienie o zamknieciu pozycji przez exit monitor.
    """
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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


def notify_summary(monitor: str, signals_found: int, alerts_sent: int) -> bool:
    """
    Krotkie podsumowanie po kazdym runie monitora.
    Wysylaj tylko gdy sa sygnaly.
    """
    if signals_found == 0:
        return False

    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[{monitor}] {signals_found} sygnal(ow), {alerts_sent} wyslanych"
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

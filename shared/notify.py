"""
Shared email notification module — używany przez wszystkie monitory.
Wysyła email przez Gmail SMTP gdy wykryto sygnał lub wykonano zlecenie.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_TO          = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)  # domyślnie do siebie


def _clean(text: str) -> str:
    """Replace non-breaking spaces and other chars that break ASCII SMTP encoding.
    Root cause: Python's :, formatter uses \\xa0 as thousands separator on some locales."""
    return text.replace('\xa0', ' ')


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """
    Wysyła email przez Gmail SMTP.
    Zwraca True jeśli sukces.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("  Email: brak GMAIL_USER lub GMAIL_APP_PASSWORD — pomijam")
        return False

    try:
        subject = _clean(subject)
        body    = _clean(body)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = NOTIFY_TO

        if html:
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)

        print(f"  Email wysłany: {subject}")
        return True

    except Exception as e:
        print(f"  Email błąd: {e}")
        return False


def notify_signal(signal: dict, alert_sent: bool) -> bool:
    """
    Powiadomienie o wykrytym sygnale tradingowym.
    signal: dict z polami symbol, action, strategy, size_usd, score, headline itd.
    """
    symbol   = signal.get("symbol", "?")
    action   = signal.get("action", "?")
    strategy = signal.get("strategy", "?")
    size_usd = signal.get("size_usd", 0)
    price    = signal.get("price", signal.get("score", "?"))
    headline = signal.get("headline", signal.get("keywords", ""))
    source   = signal.get("source", "")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    emoji = "🟢" if action in ("BUY", "BUY_TO_OPEN") else "🔴"
    status = "✅ Alert wysłany do Alpaca" if alert_sent else "⚠️ Alert NIE wysłany (błąd)"

    subject = f"{emoji} [{strategy}] {action} {symbol} — ${size_usd:,}"

    body = f"""
Trading Signal Detected
{'='*40}
Time:     {now}
Symbol:   {symbol}
Action:   {action}
Strategy: {strategy}
Size:     ${size_usd:,}
{'Price:    $' + str(price) if isinstance(price, (int, float)) else ''}
{'Score:    ' + str(signal.get('score', '')) if signal.get('score') else ''}
{'Source:   ' + source if source else ''}
{'Headline: ' + str(headline)[:120] if headline else ''}

Status: {status}
{'='*40}
Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview
""".strip()

    return send_email(subject, body)


def notify_exit(symbol: str, action: str, reason: str, pl_pct: float = None) -> bool:
    """
    Powiadomienie o zamknięciu pozycji przez exit monitor.
    """
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    emoji = "🔴" if "CLOSE" in action else "📊"
    pl_str = f" | P&L: {pl_pct:+.1f}%" if pl_pct is not None else ""

    subject = f"{emoji} EXIT {symbol} — {reason}{pl_str}"
    body = f"""
Exit Monitor — Position Closed
{'='*40}
Time:   {now}
Symbol: {symbol}
Action: {action}
Reason: {reason}
{'P&L:    ' + f'{pl_pct:+.1f}%' if pl_pct is not None else ''}
{'='*40}
Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview
""".strip()

    return send_email(subject, body)


def notify_summary(monitor: str, signals_found: int, alerts_sent: int) -> bool:
    """
    Krótkie podsumowanie po każdym runie monitora.
    Wysyłaj tylko gdy są sygnały (nie przy każdym pustym runie).
    """
    if signals_found == 0:
        return False  # nie spamuj gdy brak sygnałów

    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    emoji = "📊"
    subject = f"{emoji} [{monitor}] {signals_found} sygnał(ów), {alerts_sent} wysłanych"
    body = f"""
Monitor Run Summary
{'='*40}
Monitor:       {monitor}
Time:          {now}
Signals found: {signals_found}
Alerts sent:   {alerts_sent}
{'='*40}
Alpaca Paper: https://app.alpaca.markets/paper/dashboard/overview
""".strip()

    return send_email(subject, body)

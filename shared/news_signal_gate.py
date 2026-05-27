"""shared/news_signal_gate.py — single helper for news/social monitor wiring.

v3.10.1 (2026-05-27): Phase C wiring helper extracted from defense-monitor.
DRY: each news monitor calls one function instead of copy-pasting 40 lines.

USAGE (in monitor.py, replacing inline signal check):

    from news_signal_gate import gate_news_signal, _shared_caches

    cache, cool = _shared_caches(strategy="defense-news")
    verdict = gate_news_signal(
        symbol=signal["symbol"],
        side=signal["action"],
        signal_strength=signal["score"] / 100.0,
        headline=signal["headline"],
        source=signal.get("source"),
        published_at=signal.get("published_at"),
        strategy="defense-news",
        market_data=None,  # most news monitors don't pre-fetch bars
        event_cache=cache, cooldown=cool,
    )
    if verdict.verdict.value == "BLOCK":
        continue
    if verdict.verdict.value == "ALERT_ONLY":
        notify_signal(signal, alert_sent=True)
        continue
    if verdict.verdict.value == "DOWNSIZE":
        signal["size_usd"] = round(signal["size_usd"] * verdict.size_multiplier)
    # ALLOW or DOWNSIZE → proceed to execute

Returns RiskDecision (verdict, reason, size_multiplier, decision_id).
"""

from __future__ import annotations

from typing import Optional

# Module-level singletons (per monitor process — persist across signals in same run)
_CACHES: dict[str, tuple] = {}


def _shared_caches(strategy: str):
    """One EventCache + CooldownTracker per strategy name, reused across signals."""
    if strategy not in _CACHES:
        try:
            from signal_confirmation import EventCache, CooldownTracker
        except ImportError:
            from shared.signal_confirmation import EventCache, CooldownTracker  # type: ignore
        _CACHES[strategy] = (EventCache(), CooldownTracker())
    return _CACHES[strategy]


def gate_news_signal(
    *,
    symbol: str,
    side: str,
    signal_strength: float,
    headline: str = "",
    source: str = "",
    published_at: Optional[str] = None,
    strategy: str = "news",
    market_data: Optional[dict] = None,
    event_cache=None,
    cooldown=None,
    cooldown_hours: float = 4.0,
    max_article_age_hours: float = 6.0,
):
    """One-call wrapper for news/social signal classification.

    Auto-instantiates EventCache + CooldownTracker if not provided (shared
    per-strategy via _shared_caches). Returns RiskDecision.

    On any failure: fail-soft → ALLOW (so monitor proceeds with original
    size). Per intraday-first directive: gate failures must NEVER paralyze
    the system; downstream risk_officer + safe_close still gate the order.
    """
    try:
        from signal_confirmation import classify_news_signal_intraday
        from risk_classification import allow as _allow
    except ImportError:
        from shared.signal_confirmation import classify_news_signal_intraday  # type: ignore
        from shared.risk_classification import allow as _allow  # type: ignore

    if event_cache is None or cooldown is None:
        event_cache, cooldown = _shared_caches(strategy)

    event = {
        "symbol":       symbol,
        "published_at": published_at,
        "headline":     headline,
        "source":       source,
        "strategy":     strategy,
    }

    try:
        return classify_news_signal_intraday(
            event=event, side=side, market_data=market_data,
            event_cache=event_cache, cooldown=cooldown,
            signal_strength=signal_strength,
            cooldown_hours=cooldown_hours,
            max_article_age_hours=max_article_age_hours,
        )
    except Exception as e:
        # Fail-soft: gate error must not block signal flow
        return _allow(
            f"signal-gate error ({type(e).__name__}: {e}); proceeding without confirmation",
            gate="news_signal_gate_failsoft",
        )


def mark_signal_acted(symbol: str, strategy: str = "news") -> None:
    """Call after non-BLOCK verdict to stamp cooldown for next signal."""
    try:
        _, cool = _shared_caches(strategy)
        cool.mark(symbol, strategy)
    except Exception:
        pass

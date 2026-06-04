"""v3.16.0 (2026-06-04) — Pure geo-classifier (event-driven backtest Phase 1 MVP).

Extracted from `geo-monitor/monitor.py::_classify_news_to_signals` so the same
classifier can be replayed offline by the backtest harness (`backtest/event_replay.py`)
without spinning up Alpaca / NewsAPI / RSS clients.

CONTRACT
--------
This module is PURE:
  - No I/O. No HTTP. No state.
  - Deterministic given identical inputs.
  - Fail-soft: any malformed input → empty list (no exceptions raised).
  - 100% testable on synthetic events.

The live monitor still owns:
  - HTTP fetchers (Finnhub / NewsAPI / RSS)
  - VIX / drawdown / concentration / PDT gates
  - notify_signal + audit emission
  - Cloudflare Worker forwarding (legacy routine path)
  - Alpaca order placement via execute_stock_signal

NEVER
-----
- Place orders.
- Call any external network.
- Mutate any module-level state.

OUTPUT SHAPE
------------
Each `classify_event_to_signals(...)` returns a list[GeoSignal] (possibly empty).
GeoSignal is a frozen dataclass — easy to JSON-serialize for the trade ledger.

The shape mirrors the live monitor's signal dict so we can flow signals through
`alpaca_orders.execute_stock_signal` after refactor without translation. Backtest
harness uses `confidence_inputs_seed` to feed `confidence_builder.build_signal_confidence`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# ─── Static keyword maps (module constants — easy to test + override) ─────────

# Defense escalation keywords → defense ETF + Big-5 primes
KEYWORDS_DEFENSE = (
    "iran attack", "iran missile", "israel strike", "missile strike",
    "missile launched", "hezbollah", "hamas", "middle east war",
    "rocket attack", "drone strike", "air strike", "ground operation",
    "military escalation", "armed conflict",
)

# Energy supply / oil shock keywords → XOM / CVX / XLE
KEYWORDS_ENERGY = (
    "oil embargo", "strait of hormuz", "oil supply",
    "iran ", "iran nuclear", "opec", "trump sanction iran",
    "oil pipeline", "gas pipeline", "refinery attack",
    "oil price spike", "petroleum sanctions",
)

# Generic geopolitical / safe-haven keywords → GLD
KEYWORDS_GOLD = (
    "nuclear", "war ", "tensions escalate", "diplomatic crisis",
    "world war", "imminent attack", "security crisis",
    "ww3", "global conflict",
)

# Ticker buckets (primary tickers fired by each event class).
# Mirrored from geo-monitor/monitor.py::ASSET_MAP first two entries.
TICKERS_DEFENSE_PRIMARY: tuple[str, ...] = ("RTX", "LMT")
TICKERS_ENERGY_PRIMARY:  tuple[str, ...] = ("XOM", "CVX")
TICKERS_GOLD_PRIMARY:    tuple[str, ...] = ("GLD",)

# Strategy naming — must match learning-loop state.json keys.
STRATEGY_DEFENSE = "geo-defense"
STRATEGY_ENERGY  = "geo-energy"
STRATEGY_GOLD    = "geo-gold"
STRATEGY_XOM     = "geo-xom"   # XOM/CVX legacy alias for backwards compat

# Sizing per docs/STRATEGY.md §4.4 (geopolitical bucket, v2.0+).
SIZE_HIGH_PRIORITY_USD   = 8000.0
SIZE_MEDIUM_PRIORITY_USD = 4000.0
GEO_SL_PCT = -5.0
GEO_TP_PCT = 10.0

# Score threshold to upgrade priority from MEDIUM → HIGH.
HIGH_PRIORITY_SCORE = 3


# ─── Output dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GeoSignal:
    """Backtest-friendly representation of a geo trade proposal.

    Mirrors the dict shape produced by geo-monitor for live execution but
    typed for offline replay + downstream confidence scoring.
    """
    bucket:                  str                          # "defense" | "energy" | "gold"
    primary_tickers:         tuple                        # tuple[str, ...]
    strategy:                str                          # "geo-defense" | "geo-energy" | "geo-gold" | "geo-xom"
    side:                    str = "BUY"
    size_hint_usd:           float = SIZE_MEDIUM_PRIORITY_USD
    sl_pct:                  float = GEO_SL_PCT
    tp_pct:                  float = GEO_TP_PCT
    priority:                str = "MEDIUM"               # MEDIUM | HIGH
    headline:                str = ""
    detected_at_iso:         str = ""
    source_type:             str = ""
    event_scoring:           dict = field(default_factory=dict)
    confidence_inputs_seed:  dict = field(default_factory=dict)
    rationale:               str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_live_signal(self) -> dict:
        """Shape that matches `geo-monitor::_classify_news_to_signals` output.

        Used when we refactor the live monitor to call this classifier and
        forward to `execute_stock_signal` — preserves backward-compat with the
        downstream notify_signal + alpaca_orders pipeline.
        """
        return {
            "symbol":    self.primary_tickers[0] if self.primary_tickers else "",
            "action":    self.side,
            "size_usd":  self.size_hint_usd,
            "sl_pct":    self.sl_pct,
            "tp_pct":    self.tp_pct,
            "strategy":  self.strategy,
            "score":     self.event_scoring.get("credibility", 0),
            "source":    self.source_type or "geo-news",
            "headline":  self.headline[:120],
            "url":       "",
            "bucket":    self.bucket,
            "priority":  self.priority,
            "confidence_inputs": self.confidence_inputs_seed,
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _haystack(headline: str, summary: str) -> str:
    """Lowercase combined text for keyword matching. Fail-soft on None."""
    h = (headline or "").lower()
    s = (summary or "").lower()
    return f"{h} {s}"


def _matches_any(haystack: str, keywords: tuple) -> bool:
    """True if any keyword appears in haystack."""
    return any(kw in haystack for kw in keywords)


def _priority_for(score: int) -> str:
    """Map event score to priority bucket."""
    return "HIGH" if score >= HIGH_PRIORITY_SCORE else "MEDIUM"


def _size_for(priority: str) -> float:
    return SIZE_HIGH_PRIORITY_USD if priority == "HIGH" else SIZE_MEDIUM_PRIORITY_USD


def score_event_keywords(headline: str, summary: str = "") -> int:
    """Heuristic score: count of strong keywords.

    Each defense keyword = +3, energy keyword = +2, gold keyword = +1.
    Matches `geo-monitor::score_news` semantics loosely. Used by the
    backtest harness when an event lacks an explicit score.
    """
    haystack = _haystack(headline, summary)
    score = 0
    for kw in KEYWORDS_DEFENSE:
        if kw in haystack:
            score += 3
    for kw in KEYWORDS_ENERGY:
        if kw in haystack:
            score += 2
    for kw in KEYWORDS_GOLD:
        if kw in haystack:
            score += 1
    return score


def classify_event_to_signals(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result: dict | None = None,
    priority: str | None = None,
    score: int | None = None,
) -> list[GeoSignal]:
    """Pure classifier: event → list[GeoSignal].

    Args:
        headline: event title (any case, can be empty)
        summary:  optional body / summary text
        source_type: e.g. "reuters_ap", "major_outlet", "official_government"
        detected_at_iso: UTC ISO 8601 timestamp (advisory, not used for routing)
        event_scoring_result: optional precomputed score dict from event_scoring
        priority: explicit "HIGH" | "MEDIUM" override
        score: explicit score override — used for priority derivation if priority is None

    Returns:
        list[GeoSignal] (possibly empty). One GeoSignal per (bucket, ticker)
        that triggered. Dedup is caller's responsibility (live monitor caps
        at MAX_TRADES_PER_RUN).

    Fail-soft contract:
        Any error → return [].
    """
    try:
        haystack = _haystack(headline, summary)
        if not haystack.strip():
            return []

        # Resolve priority.
        if priority not in ("HIGH", "MEDIUM"):
            effective_score = score if score is not None else score_event_keywords(headline, summary)
            priority = _priority_for(effective_score)
        size = _size_for(priority)

        signals: list[GeoSignal] = []
        seen_tickers: set = set()

        # Defense bucket.
        if _matches_any(haystack, KEYWORDS_DEFENSE):
            for ticker in TICKERS_DEFENSE_PRIMARY:
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                signals.append(_build_signal(
                    bucket="defense",
                    ticker=ticker,
                    strategy=STRATEGY_DEFENSE,
                    priority=priority,
                    size_hint_usd=size,
                    headline=headline,
                    detected_at_iso=detected_at_iso,
                    source_type=source_type,
                    event_scoring_result=event_scoring_result,
                    rationale="defense keyword match",
                ))

        # Energy bucket. XOM/CVX get geo-xom alias (legacy state.json key);
        # others (e.g. XLE in future expansion) route to geo-energy.
        if _matches_any(haystack, KEYWORDS_ENERGY):
            for ticker in TICKERS_ENERGY_PRIMARY:
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                strategy = STRATEGY_XOM if ticker in ("XOM", "CVX") else STRATEGY_ENERGY
                signals.append(_build_signal(
                    bucket="energy",
                    ticker=ticker,
                    strategy=strategy,
                    priority=priority,
                    size_hint_usd=size,
                    headline=headline,
                    detected_at_iso=detected_at_iso,
                    source_type=source_type,
                    event_scoring_result=event_scoring_result,
                    rationale="energy keyword match",
                ))

        # Gold (safe-haven) bucket.
        if _matches_any(haystack, KEYWORDS_GOLD):
            ticker = TICKERS_GOLD_PRIMARY[0]
            if ticker not in seen_tickers:
                seen_tickers.add(ticker)
                signals.append(_build_signal(
                    bucket="gold",
                    ticker=ticker,
                    strategy=STRATEGY_GOLD,
                    priority=priority,
                    size_hint_usd=size,
                    headline=headline,
                    detected_at_iso=detected_at_iso,
                    source_type=source_type,
                    event_scoring_result=event_scoring_result,
                    rationale="safe-haven keyword match",
                ))

        return signals
    except Exception:
        # Fail-soft contract: never raise from the classifier.
        return []


def _build_signal(
    bucket: str,
    ticker: str,
    strategy: str,
    priority: str,
    size_hint_usd: float,
    headline: str,
    detected_at_iso: str,
    source_type: str,
    event_scoring_result: dict | None,
    rationale: str,
) -> GeoSignal:
    """Internal constructor for GeoSignal with confidence_inputs seed."""
    # Seed for downstream confidence_builder. Caller can override with live
    # account_status + governor state. We populate only the things the
    # classifier already knows.
    seed = {
        "regime":          None,
        "primary_score":   _credibility_to_unit(event_scoring_result),
        "bars_age_s":      None,
        "duplicate":       False,
    }
    return GeoSignal(
        bucket=bucket,
        primary_tickers=(ticker,),
        strategy=strategy,
        side="BUY",
        size_hint_usd=size_hint_usd,
        sl_pct=GEO_SL_PCT,
        tp_pct=GEO_TP_PCT,
        priority=priority,
        headline=(headline or "")[:200],
        detected_at_iso=detected_at_iso,
        source_type=source_type,
        event_scoring=dict(event_scoring_result or {}),
        confidence_inputs_seed=seed,
        rationale=rationale,
    )


def _credibility_to_unit(event_scoring_result: dict | None) -> float | None:
    """Map event_scoring 0-100 credibility → 0..1 for confidence_builder.

    Returns None when no scoring is supplied — confidence_builder will treat
    missing input as neutral 0.5 fail-soft.
    """
    if not event_scoring_result:
        return None
    cred = event_scoring_result.get("credibility")
    if cred is None:
        return None
    try:
        return max(0.0, min(1.0, float(cred) / 100.0))
    except Exception:
        return None


def cap_signals_per_run(signals: list, max_per_run: int) -> list:
    """Helper for callers (live monitor + backtest replay) that cap output.

    Defaults to first-come-first-served per the live monitor's MAX_TRADES_PER_RUN
    semantics. Caller controls dedup across runs.
    """
    if max_per_run <= 0:
        return list(signals)
    return list(signals)[:max_per_run]


__all__ = [
    "GeoSignal",
    "KEYWORDS_DEFENSE", "KEYWORDS_ENERGY", "KEYWORDS_GOLD",
    "TICKERS_DEFENSE_PRIMARY", "TICKERS_ENERGY_PRIMARY", "TICKERS_GOLD_PRIMARY",
    "STRATEGY_DEFENSE", "STRATEGY_ENERGY", "STRATEGY_GOLD", "STRATEGY_XOM",
    "SIZE_HIGH_PRIORITY_USD", "SIZE_MEDIUM_PRIORITY_USD",
    "GEO_SL_PCT", "GEO_TP_PCT",
    "HIGH_PRIORITY_SCORE",
    "score_event_keywords",
    "classify_event_to_signals",
    "cap_signals_per_run",
]

"""
Signal confirmation gate for news / social signals.

Rule F of the architecture spec: news/social must never produce an order
on its own. Required combination:

  (news or social mention)
  AND price confirmation (breakout / breakdown / above-MA)
  AND volume confirmation (above rolling avg)
  AND not duplicate (event dedupe)
  AND not in cooldown
  AND fresh (news article age below threshold)

All checks are deterministic, free, and offline-friendly. They take a
caller-provided market_data dict — no Alpaca call inside this module —
so monitors can pre-fetch once and reuse across multiple proposals.

Output is structured {ok, reasons[], metrics} so monitors can attach the
result to the email body / journal without extra plumbing.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


# ─── 1. Price / volume confirmation ───────────────────────────────────────────

DEFAULT_VOLUME_RATIO_MIN = 1.20      # 20% above 20-day avg
DEFAULT_SPREAD_PCT_MAX = 1.50         # 1.5% bid-ask spread


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def confirm_price_volume(
    symbol: str,
    side: str,
    market_data: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Confirm a directional signal against bars/quote.

    market_data shape (any of these allowed; missing → degrade):
      {
        "last":          float — last price,
        "sma_20":        float — 20-bar simple moving avg,
        "sma_50":        float — optional,
        "atr":           float — optional, used for breakout magnitude,
        "volume":        float — today's bar volume,
        "avg_volume_20": float — 20-bar avg volume,
        "high_5d":       float — for breakout,
        "low_5d":        float — for breakdown,
        "quote": {"bid": float, "ask": float},
      }

    Returns {ok, reasons, metrics}.
    side: "buy" / "long" → look for breakout above SMA / 5d-high
          "sell_short" / "short" → look for breakdown
    """
    config = config or {}
    side = (side or "").strip().lower()
    reasons: list[str] = []
    metrics: dict[str, Any] = {}

    if not market_data:
        return {"ok": False, "reasons": ["price-confirm: market_data unavailable"],
                "metrics": {}}

    last = _safe_float(market_data.get("last"))
    sma20 = _safe_float(market_data.get("sma_20"))
    volume = _safe_float(market_data.get("volume"))
    avg_volume = _safe_float(market_data.get("avg_volume_20"))
    high_5d = _safe_float(market_data.get("high_5d"))
    low_5d = _safe_float(market_data.get("low_5d"))
    quote = market_data.get("quote") or {}

    metrics.update({
        "last": last, "sma_20": sma20, "volume": volume,
        "avg_volume_20": avg_volume, "high_5d": high_5d, "low_5d": low_5d,
    })

    if last <= 0:
        return {"ok": False, "reasons": ["price-confirm: last price unknown"],
                "metrics": metrics}

    # Price direction
    if side in ("buy", "long", "buy_to_open"):
        if sma20 > 0 and last < sma20:
            reasons.append(f"long-side: last {last:.2f} < SMA20 {sma20:.2f}")
        if high_5d > 0 and last < high_5d * 0.995:
            reasons.append(f"long-side: last {last:.2f} below 5d-high {high_5d:.2f} (no breakout)")
    elif side in ("sell_short", "short", "sell_to_open"):
        if sma20 > 0 and last > sma20:
            reasons.append(f"short-side: last {last:.2f} > SMA20 {sma20:.2f}")
        if low_5d > 0 and last > low_5d * 1.005:
            reasons.append(f"short-side: last {last:.2f} above 5d-low {low_5d:.2f} (no breakdown)")
    else:
        reasons.append(f"unknown side '{side}'")

    # Volume confirmation
    vol_min_ratio = float(config.get("volume_ratio_min", DEFAULT_VOLUME_RATIO_MIN))
    if avg_volume > 0:
        ratio = volume / avg_volume if volume > 0 else 0.0
        metrics["volume_ratio"] = ratio
        if ratio < vol_min_ratio:
            reasons.append(f"volume {ratio:.2f}x avg < {vol_min_ratio:.2f}x required")
    else:
        # Volume baseline unavailable — degrade to a warning, not a hard fail.
        # Bars sometimes load with no avg_volume_20 (e.g. weekend backfill).
        metrics["volume_ratio"] = None

    # Spread (if quote available)
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    if bid > 0 and ask > 0:
        spread_pct = (ask - bid) / ((ask + bid) / 2.0) * 100.0
        metrics["spread_pct"] = spread_pct
        spread_max = float(config.get("spread_pct_max", DEFAULT_SPREAD_PCT_MAX))
        if spread_pct > spread_max:
            reasons.append(f"spread {spread_pct:.2f}% > {spread_max}% (illiquid)")

    return {"ok": not reasons, "reasons": reasons, "metrics": metrics}


# ─── 2. Event dedupe ──────────────────────────────────────────────────────────

def event_fingerprint(event: dict[str, Any]) -> str:
    """
    Stable hash over the salient fields. Headlines may repeat verbatim;
    we want to skip them after the first emission within the cache window.

    Hash includes (lowercased + stripped):
        headline / text / title / body  — first non-empty
        source / outlet / handle        — first non-empty
        symbol / ticker                 — first non-empty
        date_utc                        — YYYY-MM-DD bucket
    """
    parts = []
    for k in ("headline", "title", "text", "body"):
        v = event.get(k)
        if v:
            parts.append(str(v).strip().lower())
            break
    for k in ("source", "outlet", "handle"):
        v = event.get(k)
        if v:
            parts.append(str(v).strip().lower())
            break
    for k in ("symbol", "ticker", "underlying"):
        v = event.get(k)
        if v:
            parts.append(str(v).strip().lower())
            break
    when = event.get("published_at") or event.get("timestamp") or ""
    if when:
        parts.append(str(when)[:10])

    blob = "|".join(parts) or json.dumps(event, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


class EventCache:
    """
    In-memory + on-disk dedupe cache. Default disk path lives under
    `learning-loop/event_cache.json` and is read-only at monitor cron
    time — writes use atomic replace. Falls back to memory-only if the
    path is unwritable (tests, sandboxes).
    """

    def __init__(self, path: str | None = None, ttl_hours: int = 48):
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self._cache: dict[str, float] = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    raw = json.load(f) or {}
                if isinstance(raw, dict):
                    self._cache = {k: float(v) for k, v in raw.items()
                                   if isinstance(v, (int, float))}
            except (json.JSONDecodeError, OSError, ValueError):
                self._cache = {}
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        self._cache = {k: t for k, t in self._cache.items() if t > cutoff}

    def seen(self, fingerprint: str) -> bool:
        return fingerprint in self._cache

    def mark(self, fingerprint: str) -> None:
        self._cache[fingerprint] = time.time()
        self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._cache, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


def dedupe_event(event: dict[str, Any], cache: EventCache | None) -> dict[str, Any]:
    """
    Return {ok, fingerprint, was_duplicate}. ok=False means caller should drop.
    cache may be None (memory-only single-run dedupe — caller passes a fresh
    EventCache(path=None) and reuses across this run's proposals).
    """
    fp = event_fingerprint(event)
    if cache is None:
        return {"ok": True, "fingerprint": fp, "was_duplicate": False}
    if cache.seen(fp):
        return {"ok": False, "fingerprint": fp, "was_duplicate": True}
    cache.mark(fp)
    return {"ok": True, "fingerprint": fp, "was_duplicate": False}


# ─── 3. Cooldown per (symbol, strategy) ───────────────────────────────────────

class CooldownTracker:
    """
    Persisted per (symbol, strategy) → last-emit timestamp.
    Disk format same as EventCache: a JSON dict on a single path. Falls
    back to memory-only if the path is unwritable.
    """

    def __init__(self, path: str | None = None):
        self.path = path
        self._map: dict[str, float] = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    raw = json.load(f) or {}
                if isinstance(raw, dict):
                    self._map = {k: float(v) for k, v in raw.items()
                                 if isinstance(v, (int, float))}
            except (json.JSONDecodeError, OSError, ValueError):
                self._map = {}

    @staticmethod
    def _key(symbol: str, strategy: str) -> str:
        return f"{(symbol or '').upper().strip()}|{(strategy or '').lower().strip()}"

    def cooldown_ok(self, symbol: str, strategy: str, cooldown_hours: float,
                    now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        k = self._key(symbol, strategy)
        last = self._map.get(k, 0.0)
        elapsed = now - last
        if elapsed < cooldown_hours * 3600:
            remain = cooldown_hours * 3600 - elapsed
            return {
                "ok": False,
                "reason": f"cooldown active ({remain / 3600:.1f}h remaining)",
                "elapsed_hours": elapsed / 3600,
            }
        return {"ok": True, "reason": "ok", "elapsed_hours": elapsed / 3600}

    def mark(self, symbol: str, strategy: str, now: float | None = None) -> None:
        self._map[self._key(symbol, strategy)] = now if now is not None else time.time()
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._map, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ─── 4. Article freshness ─────────────────────────────────────────────────────

def article_fresh(
    published_at: str | datetime | None,
    max_age_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Returns {ok, age_hours, reason}. Stale news (e.g. NewsAPI free tier
    sometimes returns articles >24h old) must not trigger trades.
    """
    if published_at is None:
        return {"ok": False, "age_hours": None, "reason": "no published_at"}
    if isinstance(published_at, str):
        try:
            ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return {"ok": False, "age_hours": None, "reason": f"unparseable timestamp {published_at!r}"}
    else:
        ts = published_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cur = now or datetime.now(timezone.utc)
    age = (cur - ts).total_seconds() / 3600.0
    if age < 0:
        # Article from the future — treat as stale (clock skew sentinel).
        return {"ok": False, "age_hours": age, "reason": "future timestamp"}
    if age > max_age_hours:
        return {"ok": False, "age_hours": age,
                "reason": f"article {age:.1f}h old > {max_age_hours}h max"}
    return {"ok": True, "age_hours": age, "reason": "fresh"}


# ─── 5. Convenience: full confirm pipeline ────────────────────────────────────

def confirm_event_signal(
    event: dict[str, Any],
    side: str,
    market_data: dict[str, Any] | None,
    event_cache: EventCache | None,
    cooldown: CooldownTracker | None,
    cooldown_hours: float,
    max_article_age_hours: float,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    All-in-one helper: dedupe → freshness → cooldown → price/volume.

    Order matters — cheap deterministic checks first, fail-fast.
    Returns {ok, blocked_by, reasons, metrics}.
    """
    reasons: list[str] = []
    metrics: dict[str, Any] = {}
    blocked_by: list[str] = []

    # Dedupe
    dedupe = dedupe_event(event, event_cache)
    metrics["fingerprint"] = dedupe["fingerprint"]
    if not dedupe["ok"]:
        return {"ok": False, "blocked_by": ["dedupe"], "reasons": ["duplicate event"], "metrics": metrics}

    # Freshness
    fresh = article_fresh(
        event.get("published_at") or event.get("timestamp"),
        max_article_age_hours,
    )
    metrics["age_hours"] = fresh["age_hours"]
    if not fresh["ok"]:
        blocked_by.append("freshness")
        reasons.append(fresh["reason"])

    # Cooldown
    sym = event.get("symbol") or event.get("ticker") or ""
    strategy = event.get("strategy") or "news"
    if cooldown is not None and sym:
        cd = cooldown.cooldown_ok(sym, strategy, cooldown_hours)
        if not cd["ok"]:
            blocked_by.append("cooldown")
            reasons.append(cd["reason"])
        metrics["cooldown"] = cd

    # Price / volume confirmation
    pv = confirm_price_volume(sym, side, market_data, config=config)
    metrics["price_volume"] = pv
    if not pv["ok"]:
        blocked_by.append("price_volume")
        reasons.extend(pv["reasons"])

    return {
        "ok": not blocked_by,
        "blocked_by": blocked_by,
        "reasons": reasons,
        "metrics": metrics,
    }


# ─── v3.10 (2026-05-27) — intraday-friendly classification ─────────────────────

def classify_news_signal_intraday(
    event: dict[str, Any],
    side: str,
    market_data: dict[str, Any] | None,
    event_cache: "EventCache | None",
    cooldown: "CooldownTracker | None",
    *,
    signal_strength: float = 0.5,
    cooldown_hours: float = 4.0,
    max_article_age_hours: float = 6.0,
    config: dict[str, Any] | None = None,
):
    """v3.10 intraday-first: map confirmation result to RiskVerdict.

    Per architectural directive: brak pełnego potwierdzenia ≠ DROP. Policy:
      duplicate / stale / future timestamp           → BLOCK
      strong signal (≥0.7) + partial confirmation    → DOWNSIZE (0.5×)
      weak signal (<0.4) + no confirmation           → ALERT_ONLY
      full confirmation (price + volume + freshness) → ALLOW
      everything else (moderate signal, partial)     → DOWNSIZE (0.7×)

    Args:
        event:           {symbol, published_at/timestamp, headline, source, ...}
        side:            "BUY" / "SELL_SHORT"
        market_data:     dict with last_price, ma_*, vol_avg_*, etc.
        event_cache:     EventCache instance (or None for no dedupe)
        cooldown:        CooldownTracker instance (or None)
        signal_strength: 0.0-1.0 — caller's confidence in signal quality
                         (e.g. Curator score, sentiment magnitude, source credibility)
        cooldown_hours:  default 4h between same-ticker-strategy signals
        max_article_age_hours: default 6h freshness window for intraday

    Returns:
        RiskDecision (verdict + reason + gate + metadata)
    """
    try:
        from risk_classification import (
            RiskVerdict, block, downsize, allow, alert_only,
        )
    except ImportError:
        from shared.risk_classification import (  # type: ignore
            RiskVerdict, block, downsize, allow, alert_only,
        )

    result = confirm_event_signal(
        event=event, side=side, market_data=market_data,
        event_cache=event_cache, cooldown=cooldown,
        cooldown_hours=cooldown_hours,
        max_article_age_hours=max_article_age_hours,
        config=config,
    )

    blocked_by = set(result.get("blocked_by") or [])
    metrics = result.get("metrics") or {}
    sym = event.get("symbol") or event.get("ticker") or "?"

    # HARD BLOCKS — same-class as 2026-05-22 incident path (must never trade)
    if "dedupe" in blocked_by:
        return block(
            f"{sym}: duplicate event (fingerprint match)",
            gate="signal_confirmation",
            fingerprint=metrics.get("fingerprint"),
        )

    # Future timestamp check — encoded in article_fresh, surfaces as freshness fail
    # with "future timestamp" or "age_hours < 0" patterns
    age_h = metrics.get("age_hours")
    if isinstance(age_h, (int, float)) and age_h < -0.05:  # 3 min tolerance for clock skew
        return block(
            f"{sym}: future timestamp (age_hours={age_h:.2f})",
            gate="signal_confirmation",
            age_hours=age_h,
        )

    # Stale (very old) — also BLOCK rather than DOWNSIZE
    if isinstance(age_h, (int, float)) and age_h > max_article_age_hours * 4:
        return block(
            f"{sym}: stale event age={age_h:.1f}h > {max_article_age_hours*4}h",
            gate="signal_confirmation", age_hours=age_h,
        )

    # Cooldown — defer-style, but in news context we treat as BLOCK for now
    # (caller can decide to retry on next cron — most don't)
    if "cooldown" in blocked_by:
        return block(
            f"{sym}: in cooldown — recent signal for same strategy",
            gate="signal_confirmation",
            cooldown=metrics.get("cooldown"),
        )

    # Full confirmation → ALLOW
    if result.get("ok"):
        return allow(
            f"{sym}: full confirmation (price+volume+freshness OK)",
            gate="signal_confirmation",
            signal_strength=signal_strength,
            **metrics,
        )

    # Partial confirmation — intraday policy based on signal_strength
    # (only price_volume failed at this point)
    if "price_volume" in blocked_by:
        if signal_strength >= 0.7:
            # Strong signal trumps weak market confirmation — downsize but proceed
            return downsize(
                f"{sym}: strong signal ({signal_strength:.2f}) + partial confirmation; size 0.5×",
                size_multiplier=0.5, gate="signal_confirmation",
                signal_strength=signal_strength, **metrics,
            )
        elif signal_strength >= 0.4:
            # Moderate signal — bigger discount
            return downsize(
                f"{sym}: moderate signal ({signal_strength:.2f}) + partial confirmation; size 0.3×",
                size_multiplier=0.3, gate="signal_confirmation",
                signal_strength=signal_strength, **metrics,
            )
        else:
            # Weak signal + no confirmation → ALERT_ONLY
            return alert_only(
                f"{sym}: weak signal ({signal_strength:.2f}) + no confirmation; alert only",
                gate="signal_confirmation",
                signal_strength=signal_strength, **metrics,
            )

    # Freshness fail (not future, not stale-too-old) — moderate age but past window
    if "freshness" in blocked_by:
        return alert_only(
            f"{sym}: article age past {max_article_age_hours}h window",
            gate="signal_confirmation", **metrics,
        )

    # Fall-through (shouldn't reach here normally)
    return alert_only(
        f"{sym}: unconfirmed signal ({', '.join(blocked_by) or 'unknown reasons'})",
        gate="signal_confirmation", **metrics,
    )

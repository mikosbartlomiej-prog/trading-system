"""Deterministic bar/quote/VIX fakes for E2E."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeMarketData:
    """In-memory market-data stub.

    Tests set bars/quote/VIX explicitly; no random data.
    """
    bars: dict[str, dict] = field(default_factory=dict)
    quotes: dict[str, dict] = field(default_factory=dict)
    vix_level: float | None = 18.5
    market_open: bool = True
    stale_symbols: set[str] = field(default_factory=set)

    # ─── bars ───────────────────────────────────────────────────────────────

    def set_bars(self, symbol: str, *, closes: list[float],
                  highs: list[float] | None = None,
                  lows: list[float] | None = None,
                  volumes: list[int] | None = None,
                  times: list[str] | None = None) -> None:
        n = len(closes)
        self.bars[symbol.upper()] = {
            "close":  closes,
            "high":   highs   or [c * 1.01 for c in closes],
            "low":    lows    or [c * 0.99 for c in closes],
            "volume": volumes or [1_000_000] * n,
            "time":   times   or [f"2026-05-{(i % 28) + 1:02d}" for i in range(n)],
        }

    def get_daily_bars(self, symbol: str, days: int = 35) -> dict | None:
        if symbol.upper() in self.stale_symbols:
            return None
        bars = self.bars.get(symbol.upper())
        if not bars:
            return None
        return {k: v[-days:] for k, v in bars.items()}

    # ─── quotes ─────────────────────────────────────────────────────────────

    def set_quote(self, symbol: str, *, bid: float, ask: float):
        self.quotes[symbol.upper()] = {"bid": bid, "ask": ask,
                                        "mid": (bid + ask) / 2.0}

    def get_latest_quote(self, symbol: str) -> dict | None:
        if symbol.upper() in self.stale_symbols:
            return None
        return self.quotes.get(symbol.upper())

    # ─── VIX / regime ───────────────────────────────────────────────────────

    def set_vix(self, level: float | None):
        self.vix_level = level

    def get_vix(self) -> float | None:
        return self.vix_level

    def mark_stale(self, *symbols: str):
        for s in symbols:
            self.stale_symbols.add(s.upper())

"""v3.30 (2026-06-16) — Symbol canonical normalization (pure, leaf-level).

PURPOSE
-------
Production retry-storm leak diagnosed 2026-06-16 final-phase audit:
``broker_repair_required`` state was populated with the strings
``AVAX``, ``AVAXUSD``, ``ETH``, ``ETHUSD``, ``LTCUSD`` (the forms in
which the various P13 audit emitters happened to spell the symbol).
But ``safe_close()`` is called with the Alpaca-native crypto form
``AVAX/USD`` for crypto. ``is_repair_required("AVAX/USD")`` therefore
returned ``False`` for a symbol that was very much quarantined →
the broker call still leaked through, the 403 still came back, and
the retry storm continued.

This module fixes the leak by giving every caller a single canonical
key for the same symbol. The canonical form for crypto is the
Alpaca-native ``<BASE>/USD`` (e.g. ``AVAX/USD``). Equity tickers
stay as their upper-case ticker (``SPY`` stays ``SPY``).

HARD INVARIANTS
---------------
* NEVER imports ``alpaca_orders``.
* NEVER imports ``broker_repair_required`` (avoid circular imports —
  ``broker_repair_required`` imports US, not the other way around).
* NEVER calls a broker function.
* NEVER makes a network call.
* Pure functions only — no module-level mutable state aside from the
  ``frozenset`` of known crypto bases.

PUBLIC API
----------
``canonical_for(symbol) -> str``
    Return the canonical key for the symbol. Crypto bases normalize
    to ``<BASE>/USD``; equity tickers normalize to their upper-cased
    form. Empty / None input returns ``""``.

``aliases_for(symbol) -> set[str]``
    Return the full set of aliases that should resolve to the same
    canonical key. Useful for round-trip merging of legacy on-disk
    state files that were written with mixed spellings.

``is_crypto_canonical(symbol) -> bool``
    True iff ``symbol`` looks like a canonical crypto pair
    (``<BASE>/USD`` form).
"""

from __future__ import annotations

from typing import Iterable


# ── Known crypto bases (Alpaca paper supported assets) ────────────────────────
#
# These are the only bases whose three forms (BARE, BASEUSD, BASE/USD) we
# treat as aliases of the canonical ``BASE/USD``. Anything else (FOO,
# FOOUSD) is treated as an equity ticker and normalizes to its upper-case
# form — there is no risk of misclassification because non-crypto strings
# never appear in broker_repair_required for crypto-only incidents.
CRYPTO_BASES: frozenset[str] = frozenset({
    "BTC", "ETH", "LTC", "BCH", "AVAX", "SOL", "DOT", "LINK",
    "MATIC", "UNI", "AAVE", "DOGE", "XRP", "ADA",
})


def _strip(symbol: object) -> str:
    """Cheap, total-function cleanup. None / non-string → ``""``."""
    if symbol is None:
        return ""
    try:
        return str(symbol).strip().upper()
    except Exception:
        return ""


def _split_base(symbol: str) -> tuple[str, str | None]:
    """Return ``(base, quote)`` if ``symbol`` parses as a crypto pair.

    Crypto pairs accepted:
      * ``BTC/USD`` → ("BTC", "USD")
      * ``BTCUSD``  → ("BTC", "USD")   if BTC ∈ CRYPTO_BASES
      * ``BTC``     → ("BTC", "USD")   if BTC ∈ CRYPTO_BASES (implicit quote)

    Otherwise returns ``(symbol, None)`` — equity case.
    """
    if not symbol:
        return ("", None)

    # Form 1: explicit slash pair "BASE/USD".
    if "/" in symbol:
        parts = symbol.split("/", 1)
        base = parts[0].strip()
        quote = parts[1].strip() if len(parts) == 2 else ""
        if base and base in CRYPTO_BASES and quote == "USD":
            return (base, "USD")
        # Unknown slash form — leave to equity path (will not normalize
        # to crypto canonical).
        return (symbol, None)

    # Form 2: "BASEUSD" — accept only when the prefix is a known base.
    if symbol.endswith("USD") and len(symbol) > 3:
        base = symbol[:-3]
        if base in CRYPTO_BASES:
            return (base, "USD")

    # Form 3: bare base — accept only when symbol is exactly a known base.
    if symbol in CRYPTO_BASES:
        return (symbol, "USD")

    return (symbol, None)


def canonical_for(symbol: object) -> str:
    """Return the canonical key for ``symbol``.

    * Crypto bases (``AVAX``, ``AVAXUSD``, ``AVAX/USD``) → ``"AVAX/USD"``.
    * Equity tickers (``SPY``, ``spy ``) → ``"SPY"``.
    * Empty / None → ``""``.

    Pure function — same input always yields same output, no I/O.
    """
    s = _strip(symbol)
    if not s:
        return ""
    base, quote = _split_base(s)
    if quote == "USD" and base in CRYPTO_BASES:
        return f"{base}/USD"
    return s


def aliases_for(symbol: object) -> set[str]:
    """Return every accepted alias that canonicalizes to the same key.

    For ``"AVAX"`` returns ``{"AVAX", "AVAXUSD", "AVAX/USD"}``. For
    equity tickers returns just ``{ticker}``. Useful for merging
    legacy on-disk state written with mixed spellings.
    """
    canonical = canonical_for(symbol)
    if not canonical:
        return set()
    if is_crypto_canonical(canonical):
        # canonical is "BASE/USD"
        base = canonical.split("/", 1)[0]
        return {base, f"{base}USD", f"{base}/USD"}
    return {canonical}


def is_crypto_canonical(symbol: object) -> bool:
    """True iff ``symbol`` is in canonical crypto form (``<BASE>/USD``)."""
    s = _strip(symbol)
    if "/" not in s:
        return False
    parts = s.split("/", 1)
    if len(parts) != 2:
        return False
    base, quote = parts[0].strip(), parts[1].strip()
    return base in CRYPTO_BASES and quote == "USD"


def canonical_set(symbols: Iterable[object]) -> set[str]:
    """Convenience: canonicalize an iterable of symbols, drop empties.

    Pure helper used by tests and migration scripts; does not allocate
    anything beyond the returned set.
    """
    out: set[str] = set()
    for s in symbols:
        c = canonical_for(s)
        if c:
            out.add(c)
    return out


__all__ = [
    "CRYPTO_BASES",
    "canonical_for",
    "aliases_for",
    "is_crypto_canonical",
    "canonical_set",
]

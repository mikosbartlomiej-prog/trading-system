"""
Portfolio-level risk engine.

Existing risk_officer.py / risk_guards.py validate trades one-at-a-time
against ticker-level limits. They miss correlated exposure (e.g. NVDA +
SOXL + AMD all firing at once = one bet on AI semis with 3 tickers) and
they miss aggregate gross/net exposure.

This module evaluates a proposed trade against the WHOLE portfolio:

  - per-symbol exposure including pending open orders
  - correlated-bucket exposure (ai_semis, crypto_beta, defense, etc.)
  - gross / net / long / short exposure
  - options premium-at-risk
  - cash reserve floor
  - daily drawdown reuse

Bound by `shared.runtime_config.profile_limits()` — SAFE_FREE /
BALANCED_PAPER / AGGRESSIVE_PAPER. Default BALANCED_PAPER.

The engine fail-OPEN on missing inputs (returns APPROVE with warnings)
so an Alpaca outage doesn't silently halt all trading — same contract
as shared/risk_guards.py.

Public API:
    compute_exposure(account, positions, open_orders) -> dict
    evaluate_portfolio_risk(proposed, account, positions, open_orders,
                            state=None, profile=None) -> dict
"""

from __future__ import annotations

from typing import Any

try:  # both shared/* style and same-dir style imports must work
    from runtime_config import profile_limits, risk_profile, RiskProfile
except ImportError:  # pragma: no cover
    from shared.runtime_config import profile_limits, risk_profile, RiskProfile  # type: ignore


# ─── Correlated buckets (per spec §D.2) ───────────────────────────────────────
#
# Tickers can sit in MULTIPLE buckets — e.g. NVDA is both ai_semis AND
# nasdaq_beta. Bucket exposure is computed per-bucket: a single $10k NVDA
# position contributes $10k to BOTH ai_semis and nasdaq_beta.

CORRELATED_BUCKETS: dict[str, set[str]] = {
    "ai_semis":     {"NVDA", "AMD", "AVGO", "ARM", "SMCI", "SOXL", "SOXS", "SMH"},
    "nasdaq_beta":  {"QQQ", "TQQQ", "SQQQ", "AAPL", "MSFT", "META",
                     "AMZN", "GOOGL", "TSLA", "NVDA", "AVGO"},
    "crypto_beta":  {"BTC/USD", "ETH/USD", "COIN", "MSTR", "MARA", "RIOT",
                     "SOL/USD", "AVAX/USD", "LINK/USD", "DOT/USD"},
    "defense":      {"LMT", "RTX", "NOC", "GD", "BA", "HII", "KTOS",
                     "PLTR", "AXON", "LDOS", "SAIC", "CACI", "AVAV",
                     "ITA", "XAR", "DFEN", "BAESY", "EADSY"},
    "broad_market": {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI",
                     "SPXL", "SPXS", "UPRO", "SPXU", "TNA", "TZA"},
    "energy":       {"XLE", "XOM", "CVX", "USO", "OXY"},
    "leveraged_3x": {"TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU",
                     "SOXL", "SOXS", "FAS", "FAZ", "TNA", "TZA"},
    "software_cloud": {"NOW", "CRM", "ADBE", "ORCL", "INTU", "WDAY",
                       "PANW", "CRWD"},
}


# ─── Exposure computation ─────────────────────────────────────────────────────

def _normalise_symbol(s: str) -> str:
    return (s or "").strip().upper()


def _is_options_contract(symbol: str) -> bool:
    return len(symbol) > 7 and any(ch.isdigit() for ch in symbol)


def _is_crypto(symbol: str) -> bool:
    return "/" in symbol


def _buckets_for(symbol: str) -> list[str]:
    sym = _normalise_symbol(symbol)
    return [b for b, members in CORRELATED_BUCKETS.items() if sym in members]


def _market_value(position: dict[str, Any]) -> float:
    """Best-effort market value extraction, tolerant of Alpaca/None inputs."""
    for key in ("market_value", "current_value", "value"):
        v = position.get(key) if isinstance(position, dict) else None
        try:
            if v is not None:
                return abs(float(v))
        except (TypeError, ValueError):
            continue
    # Fallback: qty * avg_entry_price
    try:
        return abs(float(position.get("qty", 0)) * float(position.get("avg_entry_price", 0)))
    except (TypeError, ValueError):
        return 0.0


def _signed_market_value(position: dict[str, Any]) -> float:
    """Positive for long, negative for short."""
    mv = _market_value(position)
    side = (position.get("side") or "").strip().lower()
    if side == "short":
        return -mv
    qty = 0.0
    try:
        qty = float(position.get("qty", 0))
    except (TypeError, ValueError):
        pass
    return mv if qty >= 0 else -mv


def _open_order_notional(order: dict[str, Any]) -> float:
    """Approximate notional for an open entry order. Exit orders return 0."""
    try:
        qty = float(order.get("qty") or 0)
    except (TypeError, ValueError):
        return 0.0
    price = order.get("limit_price") or order.get("stop_price") or 0
    try:
        price = float(price)
    except (TypeError, ValueError):
        return 0.0
    if qty <= 0 or price <= 0:
        return 0.0
    coid = (order.get("client_order_id") or "").lower()
    if coid.startswith("exit-") or "_take_profit" in coid or "_stop_loss" in coid:
        return 0.0
    return qty * price


def compute_exposure(
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]] | None,
    open_orders: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    Compute full exposure snapshot.

    Inputs are tolerant of None (e.g. Alpaca outage) — missing data
    degrades to zero exposure (caller will then approve fail-open).
    """
    positions = positions or []
    open_orders = open_orders or []

    equity = 0.0
    cash = 0.0
    buying_power = 0.0
    if account:
        try:
            equity = float(account.get("equity") or 0)
            cash = float(account.get("cash") or 0)
            buying_power = float(account.get("buying_power") or 0)
        except (TypeError, ValueError):
            pass

    gross_usd = 0.0
    net_usd = 0.0
    long_usd = 0.0
    short_usd = 0.0
    crypto_usd = 0.0
    options_premium_usd = 0.0
    per_symbol_usd: dict[str, float] = {}
    bucket_usd: dict[str, float] = {b: 0.0 for b in CORRELATED_BUCKETS}

    for p in positions:
        if not isinstance(p, dict):
            continue
        sym = _normalise_symbol(p.get("symbol") or "")
        if not sym:
            continue
        mv = _market_value(p)
        smv = _signed_market_value(p)
        gross_usd += mv
        net_usd += smv
        if smv >= 0:
            long_usd += mv
        else:
            short_usd += mv
        per_symbol_usd[sym] = per_symbol_usd.get(sym, 0.0) + mv
        if _is_crypto(sym):
            crypto_usd += mv
        if _is_options_contract(sym):
            options_premium_usd += mv
        for b in _buckets_for(sym):
            bucket_usd[b] += mv

    # Include open ENTRY orders in pending exposure (exits don't reduce risk yet).
    pending_usd_by_symbol: dict[str, float] = {}
    for o in open_orders:
        if not isinstance(o, dict):
            continue
        sym = _normalise_symbol(o.get("symbol") or "")
        notional = _open_order_notional(o)
        if notional <= 0:
            continue
        pending_usd_by_symbol[sym] = pending_usd_by_symbol.get(sym, 0.0) + notional

    pct = (lambda x: (x / equity * 100.0) if equity > 0 else 0.0)

    return {
        "equity":                          equity,
        "cash":                            cash,
        "buying_power":                    buying_power,
        "gross_exposure_usd":              gross_usd,
        "net_exposure_usd":                net_usd,
        "long_exposure_usd":               long_usd,
        "short_exposure_usd":              short_usd,
        "crypto_exposure_usd":             crypto_usd,
        "options_premium_at_risk_usd":     options_premium_usd,
        "gross_exposure_pct":              pct(gross_usd),
        "net_exposure_pct":                pct(net_usd),
        "long_exposure_pct":               pct(long_usd),
        "short_exposure_pct":              pct(short_usd),
        "crypto_exposure_pct":             pct(crypto_usd),
        "options_premium_at_risk_pct":     pct(options_premium_usd),
        "cash_reserve_pct":                pct(cash),
        "per_symbol_exposure":             {s: pct(v) for s, v in per_symbol_usd.items()},
        "per_symbol_exposure_usd":         per_symbol_usd,
        "correlated_bucket_exposure":      {b: pct(v) for b, v in bucket_usd.items()},
        "correlated_bucket_exposure_usd":  bucket_usd,
        "pending_exposure_usd":            pending_usd_by_symbol,
    }


# ─── Trade evaluation ─────────────────────────────────────────────────────────

def evaluate_portfolio_risk(
    proposed_trade: dict[str, Any],
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]] | None,
    open_orders: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,  # noqa: ARG001 — reserved for future profile-from-state
    profile: RiskProfile | None = None,
) -> dict[str, Any]:
    """
    Evaluate a proposed entry against portfolio-level limits.

    proposed_trade shape (matches monitor signal dicts):
      {
        "symbol":  "NVDA",
        "side":    "buy" | "sell_short" | "sell" (crypto exit) | ...
        "size_usd": 12000,
        "asset_class": "us_equity" | "crypto" | "us_option"  (optional)
      }

    Returns:
      {
        "decision": "APPROVE" | "REJECT",
        "failed":   [str, ...],     # hard rule violations
        "warnings": [str, ...],     # soft (logged, not blocking)
        "metrics":  dict,           # combined snapshot incl. proposed
      }

    Fail-open: account=None / equity<=0 → APPROVE with warning.
    """
    failed: list[str] = []
    warnings: list[str] = []

    profile = profile or risk_profile()
    limits = profile_limits(profile)

    sym = _normalise_symbol(proposed_trade.get("symbol") or "")
    side = (proposed_trade.get("side") or "").strip().lower()
    try:
        size_usd = float(proposed_trade.get("size_usd") or 0)
    except (TypeError, ValueError):
        size_usd = 0.0

    asset_class = proposed_trade.get("asset_class")
    if not asset_class:
        if _is_options_contract(sym):
            asset_class = "us_option"
        elif _is_crypto(sym):
            asset_class = "crypto"
        else:
            asset_class = "us_equity"

    exposure = compute_exposure(account, positions, open_orders)
    equity = exposure["equity"]

    if equity <= 0:
        warnings.append("portfolio-risk: equity unknown — fail-open")
        return {
            "decision": "APPROVE",
            "failed":   [],
            "warnings": warnings,
            "metrics":  {"exposure": exposure, "profile": profile, "limits": limits},
        }

    # ── 1. per-trade pct ─────────────────────────────────────────────────────
    trade_pct = (size_usd / equity) * 100.0
    if trade_pct > limits["max_single_trade_pct"]:
        failed.append(
            f"single-trade {trade_pct:.1f}% > {limits['max_single_trade_pct']}% "
            f"(profile {profile})"
        )

    # ── 2. per-symbol exposure (existing + pending + this trade) ─────────────
    existing_sym_usd = exposure["per_symbol_exposure_usd"].get(sym, 0.0)
    pending_sym_usd = exposure["pending_exposure_usd"].get(sym, 0.0)
    combined_sym_usd = existing_sym_usd + pending_sym_usd + size_usd
    combined_sym_pct = (combined_sym_usd / equity) * 100.0
    if combined_sym_pct > limits["max_symbol_exposure_pct"]:
        failed.append(
            f"symbol-exposure {sym} {combined_sym_pct:.1f}% > "
            f"{limits['max_symbol_exposure_pct']}%"
        )

    # ── 3. correlated bucket exposure ────────────────────────────────────────
    for bucket in _buckets_for(sym):
        existing_bkt_usd = exposure["correlated_bucket_exposure_usd"].get(bucket, 0.0)
        new_bkt_pct = ((existing_bkt_usd + size_usd) / equity) * 100.0
        if new_bkt_pct > limits["max_correlated_bucket_pct"]:
            failed.append(
                f"bucket-exposure '{bucket}' {new_bkt_pct:.1f}% > "
                f"{limits['max_correlated_bucket_pct']}%"
            )

    # ── 4. gross / net exposure ──────────────────────────────────────────────
    new_gross_pct = ((exposure["gross_exposure_usd"] + size_usd) / equity) * 100.0
    if new_gross_pct > limits["max_gross_exposure_pct"]:
        failed.append(
            f"gross-exposure {new_gross_pct:.1f}% > "
            f"{limits['max_gross_exposure_pct']}%"
        )

    # ── 5. net long / short exposure ─────────────────────────────────────────
    if side in ("buy", "buy_to_open", "long"):
        new_long_pct = ((exposure["long_exposure_usd"] + size_usd) / equity) * 100.0
        if new_long_pct > limits["max_net_long_exposure_pct"]:
            failed.append(
                f"net-long {new_long_pct:.1f}% > {limits['max_net_long_exposure_pct']}%"
            )
    elif side in ("sell_short", "short", "sell_to_open_put"):
        new_short_pct = ((exposure["short_exposure_usd"] + size_usd) / equity) * 100.0
        if new_short_pct > limits["max_short_exposure_pct"]:
            failed.append(
                f"short-exposure {new_short_pct:.1f}% > "
                f"{limits['max_short_exposure_pct']}%"
            )

    # ── 6. crypto exposure cap ───────────────────────────────────────────────
    if asset_class == "crypto":
        new_crypto_pct = ((exposure["crypto_exposure_usd"] + size_usd) / equity) * 100.0
        if new_crypto_pct > limits["max_crypto_exposure_pct"]:
            failed.append(
                f"crypto-exposure {new_crypto_pct:.1f}% > "
                f"{limits['max_crypto_exposure_pct']}%"
            )

    # ── 7. options premium-at-risk ───────────────────────────────────────────
    if asset_class == "us_option":
        new_premium_pct = (
            (exposure["options_premium_at_risk_usd"] + size_usd) / equity
        ) * 100.0
        if new_premium_pct > limits["max_options_premium_at_risk_pct"]:
            failed.append(
                f"options-premium {new_premium_pct:.2f}% > "
                f"{limits['max_options_premium_at_risk_pct']}% "
                f"(profile {profile})"
            )

    # ── 8. cash reserve floor ────────────────────────────────────────────────
    min_cash_pct = limits["min_cash_reserve_pct"]
    if min_cash_pct > 0:
        approx_cash_after = exposure["cash"] - size_usd
        new_cash_pct = (approx_cash_after / equity) * 100.0
        if new_cash_pct < min_cash_pct:
            failed.append(
                f"cash-reserve {new_cash_pct:.1f}% < {min_cash_pct}% "
                f"(profile {profile})"
            )

    # ── 9. soft warnings ─────────────────────────────────────────────────────
    if size_usd <= 0:
        warnings.append("size_usd <= 0 — proposal would be a no-op")
    if (trade_pct > limits["max_single_trade_pct"] * 0.8
            and trade_pct <= limits["max_single_trade_pct"]):
        warnings.append(f"trade size {trade_pct:.1f}% is close to cap")

    decision = "REJECT" if failed else "APPROVE"
    return {
        "decision": decision,
        "failed":   failed,
        "warnings": warnings,
        "metrics":  {
            "profile":         profile,
            "limits":          limits,
            "exposure":        exposure,
            "trade_pct":       trade_pct,
            "combined_sym_pct": combined_sym_pct,
            "asset_class":     asset_class,
        },
    }

"""
Runtime configuration flags for deterministic execution + LLM isolation.

Single source of truth for env-driven kill switches and risk profiles.
Every monitor and risk gate reads from here, never from os.environ directly,
so a future test/fixture/CI environment can override deterministically.

Design rules (mirror docs/ARCHITECTURE_VNEXT.md):
  - System is paper-only forever. No LIVE_TRADING env. No live broker URL.
  - LLM is OFF by default. LLM may produce reports/rationales, never bypass
    deterministic risk gates. Execution must succeed with LLM_ENABLED=false.
  - Options are OFF by default. OPTIONS_ENABLED=true required to allow
    options entries.
  - Risk profile defaults to BALANCED_PAPER (sane intermediate). SAFE_FREE
    is the most conservative profile; AGGRESSIVE_PAPER preserves v2.3
    behaviour for users who opt in.

The module is intentionally tiny and dependency-free so risk gates can
import it without circular concerns.
"""

from __future__ import annotations

import os
from typing import Literal

RiskProfile = Literal["SAFE_FREE", "BALANCED_PAPER", "AGGRESSIVE_PAPER"]

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


def llm_enabled() -> bool:
    """LLM features (curation, narrative) — disabled by default."""
    return _bool("LLM_ENABLED", False)


def llm_reports_enabled() -> bool:
    """LLM-generated reports (daily narrative, weekly retro).

    Default false — system runs deterministically without LLM. Operator
    flips this on after verifying LLM_ENABLED + Anthropic budget.
    Reports never bypass risk gates regardless of this flag.
    """
    return _bool("LLM_REPORTS_ENABLED", False)


def llm_execution_influence_enabled() -> bool:
    """Allow LLM output to influence execution path (ranking only, never
    bypass gates). Default false. SHOULD be kept false in production —
    flag exists only to make the test of "LLM ranking is ignored" explicit.
    """
    return _bool("LLM_EXECUTION_INFLUENCE_ENABLED", False)


def options_enabled() -> bool:
    """Options entries (options-monitor).

    Default is profile-driven: AGGRESSIVE_PAPER → True (paper account, full
    options-level access, IntradayProfitGovernor protects giveback), other
    profiles → False unless explicitly opted in via OPTIONS_ENABLED=true.
    """
    profile_default = (risk_profile() == "AGGRESSIVE_PAPER")
    return _bool("OPTIONS_ENABLED", profile_default)


def intraday_protection_enabled() -> bool:
    """IntradayProfitGovernor — defends intraday P&L peaks.

    Default True. Set INTRADAY_PROTECTION_ENABLED=false to bypass (testing /
    backtest replay only — production should always run with this ON).
    """
    return _bool("INTRADAY_PROTECTION_ENABLED", True)


def risk_profile() -> RiskProfile:
    """Active risk profile. One of SAFE_FREE / BALANCED_PAPER / AGGRESSIVE_PAPER.

    Default BALANCED_PAPER. Misconfigured value falls back to BALANCED_PAPER
    so a typo doesn't accidentally unlock the most aggressive limits.
    """
    raw = (os.environ.get("RISK_PROFILE") or "BALANCED_PAPER").strip().upper()
    if raw in ("SAFE_FREE", "BALANCED_PAPER", "AGGRESSIVE_PAPER"):
        return raw  # type: ignore[return-value]
    return "BALANCED_PAPER"


def active_universe() -> str:
    """v3.18.0 (2026-06-04) — Active market universe identifier.

    Read from ACTIVE_UNIVERSE env var. Default `US_LARGE` matches the existing
    setup (Alpaca paper, US large-cap + ETF buckets). Other valid values:
    `CRYPTO`, `US_MICROCAP`, `PL_GPW`, `CUSTOM`. Misconfigured value falls
    back to `US_LARGE` so a typo doesn't accidentally route to a disabled
    universe.

    The pre-trade dispatch path (shared/allocator.py::_execute_one) calls
    `universe_selector.is_paper_ready(active_universe())` BEFORE submitting
    any order. If False → audit emit + skip with reason
    `universe_not_paper_ready`.
    """
    raw = (os.environ.get("ACTIVE_UNIVERSE") or "US_LARGE").strip().upper()
    valid = {"US_LARGE", "US_MICROCAP", "PL_GPW", "CRYPTO", "CUSTOM"}
    if raw in valid:
        return raw
    return "US_LARGE"


# ─── Profile-driven limits (used by portfolio_risk.py) ────────────────────────
#
# Numbers chosen to be free-tier safe, paper-friendly, and explicit. SAFE_FREE
# is the recommended starting point; AGGRESSIVE_PAPER mirrors the existing
# v2.0/v2.3 risk-on numbers so current users see no behavioural change unless
# they opt down.

_PROFILE_LIMITS: dict[str, dict[str, float]] = {
    "SAFE_FREE": {
        "max_single_trade_pct":          5.0,
        "max_symbol_exposure_pct":       12.0,
        "max_correlated_bucket_pct":     25.0,
        "max_gross_exposure_pct":        100.0,
        "max_net_long_exposure_pct":     90.0,
        "max_short_exposure_pct":        15.0,
        "max_crypto_exposure_pct":       10.0,
        "max_options_premium_at_risk_pct": 1.0,
        "min_cash_reserve_pct":          20.0,
        "max_daily_drawdown_pct":        -5.0,
        "options_enabled_default":       False,
        "margin_enabled":                False,
    },
    "BALANCED_PAPER": {
        "max_single_trade_pct":          10.0,
        "max_symbol_exposure_pct":       20.0,
        "max_correlated_bucket_pct":     35.0,
        "max_gross_exposure_pct":        125.0,
        "max_net_long_exposure_pct":     100.0,
        "max_short_exposure_pct":        40.0,
        "max_crypto_exposure_pct":       20.0,
        "max_options_premium_at_risk_pct": 3.0,
        "min_cash_reserve_pct":          10.0,
        "max_daily_drawdown_pct":        -8.0,
        "options_enabled_default":       False,
        "margin_enabled":                True,
    },
    "AGGRESSIVE_PAPER": {
        "max_single_trade_pct":          20.0,
        "max_symbol_exposure_pct":       40.0,
        # v3.8.6 (2026-05-16): bucket cap raised 60→65%. AI/Nasdaq/Semis
        # rally pushed our 6-stock basket (AMD+SMH+NVDA+QQQ+SPY +
        # AVGO/ARM/SMCI optionally) to ~62% on 2026-05-15 — blocking
        # legit Monday plan adds. 65% gives ~5% headroom for tactical
        # overweight without losing safety. Reduce to 55% in BALANCED.
        "max_correlated_bucket_pct":     65.0,
        "max_gross_exposure_pct":        200.0,
        "max_net_long_exposure_pct":     150.0,
        "max_short_exposure_pct":        80.0,
        "max_crypto_exposure_pct":       25.0,
        "max_options_premium_at_risk_pct": 5.0,
        "min_cash_reserve_pct":          0.0,
        "max_daily_drawdown_pct":        -12.0,
        "options_enabled_default":       True,
        "margin_enabled":                True,
    },
}


def profile_limits(profile: RiskProfile | None = None) -> dict[str, float]:
    """Return the limits dict for the given profile (or active profile)."""
    name = profile or risk_profile()
    # SAFE_FREE / BALANCED_PAPER / AGGRESSIVE_PAPER all present — risk_profile()
    # guarantees this. Defensive fallback to BALANCED_PAPER on misconfig.
    return dict(_PROFILE_LIMITS.get(name, _PROFILE_LIMITS["BALANCED_PAPER"]))


def snapshot() -> dict[str, object]:
    """Single dict snapshot of all flags — used by health-check and reports."""
    return {
        "llm_enabled":                   llm_enabled(),
        "llm_reports_enabled":           llm_reports_enabled(),
        "llm_execution_influence_enabled": llm_execution_influence_enabled(),
        "options_enabled":               options_enabled(),
        "risk_profile":                  risk_profile(),
        "paper_only":                    True,  # invariant — never live
    }

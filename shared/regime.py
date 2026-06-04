"""
shared/regime.py — Event Switch market regime state machine.

Four regimes:
  RISK_ON          — aggressive long, AI/semis + crypto bias
  INFLATION_SHOCK  — energy/metals rotation, limited tech exposure
  RISK_OFF         — defensive, hedges only (GLD/TLT), put-side bias
  NEUTRAL          — selective, top momentum only, half size

Detection modes (set in aggressive_profile.json::regime.detection_mode):
  hybrid (default) — read manual override from learning-loop/state.json
                     ::global_overrides.regime_override; if None/null,
                     auto-detect via rules
  auto             — rules only (ignore manual override)
  manual           — manual only (auto returns "NEUTRAL")

Auto-detect rules (config-driven, see aggressive_profile.regime.auto_rules):
  VIX >= 50                                         → RISK_OFF (panic)
  SPY 5d <= -4%                                     → RISK_OFF (breakdown)
  energy_5d > +3% AND SPY 5d <= -2%                 → INFLATION_SHOCK
  VIX < 25 AND SPY 5d >= +1.5%                      → RISK_ON
  else                                              → NEUTRAL

Each regime carries:
  - options_side_bias (long/short/null)
  - allowed_buckets   (which watchlist buckets entries are allowed from)
  - size_multiplier   (0.5-1.0)
  - max_alt_positions (crypto Tier 2 cap)

Monitors call `detect_regime()` once per run, then `is_bucket_allowed()`
per ticker. Bucket allowlist gives the FSM teeth: in RISK_OFF, AI tickers
won't enter even if their technical signal fires.

Manual override usage:
  json.load(open('learning-loop/state.json'))['global_overrides']['regime_override']
  = "RISK_OFF"   # forces all monitors to this regime
  = null         # falls back to auto-detect
"""

from __future__ import annotations  # v3.11.3: PEP 604 (X | None) parseable on Py 3.9 (local) + 3.11 (CI).

import json
import os

_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_PATH = os.path.join(_REPO_ROOT, "learning-loop", "state.json")

REGIMES = ("RISK_ON", "INFLATION_SHOCK", "RISK_OFF", "NEUTRAL")
DEFAULT_REGIME = "NEUTRAL"


def _read_manual_override() -> str | None:
    """Read regime_override from learning-loop/state.json::global_overrides."""
    try:
        with open(_STATE_PATH) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    val = (s.get("global_overrides") or {}).get("regime_override")
    if val in REGIMES:
        return val
    return None


def _auto_detect(market_signals: dict, rules: dict) -> str:
    """
    Apply rules in priority order. `market_signals` must contain:
      vix:            float (today's VIX)
      spy_5d_pct:     float (5-day % return of SPY)
      energy_5d_pct:  float or None (5-day % return of XLE; optional)
      btc_24h_pct:    float or None (BTC 24h % change; optional)

    Returns one of REGIMES.
    """
    vix = market_signals.get("vix")
    spy_5d = market_signals.get("spy_5d_pct")
    energy_5d = market_signals.get("energy_5d_pct")

    if vix is not None and vix >= rules.get("vix_full_panic_threshold", 50):
        return "RISK_OFF"
    if spy_5d is not None and spy_5d <= rules.get("spy_5d_risk_off_threshold", -4.0):
        return "RISK_OFF"
    if (energy_5d is not None and spy_5d is not None
            and energy_5d > rules.get("energy_5d_inflation_signal_pct", 3.0)
            and spy_5d <= rules.get("spy_5d_inflation_threshold", -2.0)):
        return "INFLATION_SHOCK"
    if (vix is not None and vix < 25
            and spy_5d is not None and spy_5d >= rules.get("spy_5d_risk_on_threshold", 1.5)):
        return "RISK_ON"
    return "NEUTRAL"


def detect_regime(market_signals: dict | None = None) -> dict:
    """
    Main entry point. Returns:
      {
        "regime":              one of REGIMES,
        "source":              "manual" | "auto" | "fallback",
        "manual_override":     str or None,
        "inferred":            str (always present — what auto would say),
        "options_side_bias":   "long" | "short" | None,
        "allowed_buckets":     list[str],
        "size_multiplier":     float,
        "max_alt_positions":   int,
        "reason":              human-readable explanation,
      }

    `market_signals` defaults to empty dict (no auto-detect — falls back to NEUTRAL).
    Callers (monitors) typically pass {vix, spy_5d_pct, energy_5d_pct, btc_24h_pct}
    derived from compute_reaction_metrics + crypto-monitor BTC fetch.
    """
    # Local import to avoid circular (profile.py reads no other shared modules)
    try:
        from profile import load_profile
    except ImportError:
        try:
            from shared.profile import load_profile
        except ImportError:
            def load_profile(): return {}

    prof = load_profile()
    detection_mode = (prof.get("regime") or {}).get("detection_mode", "hybrid")
    rules = (prof.get("regime") or {}).get("auto_rules") or {}
    buckets_per_regime = prof.get("buckets_per_regime") or {}

    manual = _read_manual_override()
    inferred = _auto_detect(market_signals or {}, rules)

    if detection_mode == "manual":
        regime = manual or DEFAULT_REGIME
        source = "manual" if manual else "fallback"
    elif detection_mode == "auto":
        regime = inferred
        source = "auto"
    else:  # hybrid
        if manual:
            regime = manual
            source = "manual"
        else:
            regime = inferred
            source = "auto"

    cfg = buckets_per_regime.get(regime) or {}
    return {
        "regime":              regime,
        "source":              source,
        "manual_override":     manual,
        "inferred":            inferred,
        "options_side_bias":   cfg.get("options_side_bias"),
        "allowed_buckets":     cfg.get("allowed_buckets") or [],
        "size_multiplier":     float(cfg.get("size_multiplier", 1.0)),
        "max_alt_positions":   int(cfg.get("max_alt_positions", 3)),
        "reason":              _describe_decision(regime, source, market_signals or {}),
    }


def is_bucket_allowed(bucket_name: str, regime_info: dict) -> bool:
    """True if entries from this watchlist bucket are allowed in current regime."""
    return bucket_name in (regime_info.get("allowed_buckets") or [])


def is_ticker_allowed(ticker: str, regime_info: dict) -> tuple[bool, str]:
    """
    True if this ticker is in any of the allowed buckets for current regime.
    Returns (allowed, bucket_name_or_reason).
    """
    try:
        from profile import bucket_for_ticker
    except ImportError:
        try:
            from shared.profile import bucket_for_ticker
        except ImportError:
            def bucket_for_ticker(_t): return None

    bucket = bucket_for_ticker(ticker)
    if not bucket:
        return False, f"{ticker} not in any watchlist bucket"
    if bucket in (regime_info.get("allowed_buckets") or []):
        return True, bucket
    return False, f"{bucket} not allowed in regime {regime_info['regime']}"


def _describe_decision(regime: str, source: str, sig: dict) -> str:
    """Human-readable explanation for rationale logs."""
    parts = [f"regime={regime} ({source})"]
    if sig:
        parts.append(f"VIX={sig.get('vix','?')}, SPY 5d={sig.get('spy_5d_pct','?')}%"
                     + (f", energy 5d={sig.get('energy_5d_pct')}%" if sig.get('energy_5d_pct') is not None else "")
                     + (f", BTC 24h={sig.get('btc_24h_pct')}%" if sig.get('btc_24h_pct') is not None else ""))
    return " | ".join(parts)


# ─── v3.18.0 ETAP 7 — per-strategy regime fit ────────────────────────────────
#
# Each strategy declares the regimes it FITS, the regimes it is BLOCKED in,
# and the score it would receive in any other regime. The data is hard-coded
# (not via config) because: (a) it's source-of-truth-doc-level, (b) any change
# is a strategy redesign requiring a code-review PR, (c) we don't want a
# misconfigured config to silently un-block a strategy.
#
# fit_score scale:
#   1.0   = preferred — strategy is in its native regime
#   0.7   = acceptable — strategy is regime-agnostic
#   0.5   = sub-optimal but allowed — keep sizing modest
#   0.0   = strategy is BLOCKED in this regime (is_blocked=True)

# Regimes considered. Strategies use these as keys in their preferred/blocked
# sets; any regime NOT in either set gets sub_optimal_score.
_REGIMES = ("RISK_ON", "RISK_OFF", "NEUTRAL", "INFLATION_SHOCK")

# Strategy → (preferred set, blocked set, agnostic flag)
# Mirrors config/aggressive_profile.json::buckets_per_regime, but expressed
# from the strategy's perspective (not the bucket's).
_STRATEGY_REGIME_MATRIX: dict = {
    # Equity momentum
    "momentum-long": {
        "preferred": ("RISK_ON", "NEUTRAL"),
        "blocked":   ("RISK_OFF", "INFLATION_SHOCK"),
        "rationale": "Long stocks need risk appetite; blocked in panic + inflation rotation",
    },
    "overbought-short": {
        "preferred": ("RISK_OFF", "INFLATION_SHOCK"),
        "blocked":   ("RISK_ON",),
        "rationale": "Short setups need fade-the-rip backdrop; shorts in uptrend = disaster",
    },
    # Crypto — 24/7 different cycle; regime-agnostic
    "crypto-momentum": {
        "preferred": (),
        "blocked":   (),
        "agnostic":  True,
        "rationale": "Crypto cycles independent of equity regime",
    },
    "crypto-oversold-bounce": {
        "preferred": (),
        "blocked":   (),
        "agnostic":  True,
        "rationale": "Crypto mean-reversion runs on its own clock",
    },
    "crypto-breakdown": {
        "preferred": (),
        "blocked":   (),
        "agnostic":  True,
        "rationale": "Crypto-only setup; equity regime not informative",
    },
    # Geo / event
    "geo-defense": {
        "preferred": ("INFLATION_SHOCK", "RISK_OFF"),
        "blocked":   ("RISK_ON",),
        "rationale": "Defense names rally on geopolitical stress; muted in pure RISK_ON",
    },
    "geo-energy": {
        "preferred": ("INFLATION_SHOCK", "RISK_OFF"),
        "blocked":   (),  # not blocked in RISK_ON but sub-optimal
        "rationale": "Energy fits inflation shock + risk-off; allowed elsewhere with caution",
    },
    "geo-gold": {
        "preferred": ("INFLATION_SHOCK", "RISK_OFF"),
        "blocked":   (),
        "rationale": "Gold is the classic crisis hedge; works in inflation + RO regimes",
    },
    "geo-xom": {
        "preferred": ("INFLATION_SHOCK", "RISK_OFF"),
        "blocked":   (),
        "rationale": "Single-name energy proxy; same regime fit as geo-energy",
    },
    # Options
    "options-momentum": {
        "preferred": ("RISK_ON",),
        "blocked":   ("RISK_OFF",),
        "rationale": "Long calls need bullish drift; puts handled by separate strategy",
    },
    # Allocator-level
    "allocator-rebalance": {
        "preferred": (),
        "blocked":   (),
        "agnostic":  True,
        "rationale": "Allocator handles regime internally; mechanical rebalance is regime-neutral",
    },
}


def per_strategy_regime_fit(strategy: str, current_regime: str) -> dict:
    """Return per-strategy regime fit score + flags.

    Returns:
      {
        "fit_score":         float in [0..1],   # confidence adjustment input
        "preferred_regimes": tuple,              # e.g. ("RISK_ON", "NEUTRAL")
        "blocked_regimes":   tuple,              # e.g. ("RISK_OFF",)
        "is_blocked":        bool,
        "rationale":         str,
      }

    Unknown strategy → returns neutral fit (0.5) with empty preferred/blocked
    and a "strategy_unknown" rationale. Unknown regime → fit defaults to 0.5
    (cannot determine).

    Fail-soft: any internal error → returns neutral fit, never raises.
    """
    s = (strategy or "").strip()
    r = (current_regime or "").strip().upper()
    cfg = _STRATEGY_REGIME_MATRIX.get(s)

    if cfg is None:
        return {
            "fit_score":         0.5,
            "preferred_regimes": (),
            "blocked_regimes":   (),
            "is_blocked":        False,
            "rationale":         f"strategy_unknown: {s!r} not in regime matrix",
        }

    preferred = tuple(cfg.get("preferred") or ())
    blocked   = tuple(cfg.get("blocked") or ())
    agnostic  = bool(cfg.get("agnostic"))
    rationale = cfg.get("rationale", "")

    # Unknown regime → neutral fit (cannot validate)
    if r not in _REGIMES:
        return {
            "fit_score":         0.5,
            "preferred_regimes": preferred,
            "blocked_regimes":   blocked,
            "is_blocked":        False,
            "rationale":         f"{rationale} | regime={r!r} unknown — neutral fit",
        }

    # Regime-agnostic strategies: fixed 0.7 for ALL regimes (acceptable, not preferred)
    if agnostic:
        return {
            "fit_score":         0.7,
            "preferred_regimes": preferred,
            "blocked_regimes":   blocked,
            "is_blocked":        False,
            "rationale":         f"{rationale} | regime-agnostic",
        }

    # Blocked → fit_score 0.0, is_blocked=True
    if r in blocked:
        return {
            "fit_score":         0.0,
            "preferred_regimes": preferred,
            "blocked_regimes":   blocked,
            "is_blocked":        True,
            "rationale":         f"{rationale} | BLOCKED in {r}",
        }

    # Preferred → 1.0
    if r in preferred:
        return {
            "fit_score":         1.0,
            "preferred_regimes": preferred,
            "blocked_regimes":   blocked,
            "is_blocked":        False,
            "rationale":         f"{rationale} | preferred in {r}",
        }

    # Sub-optimal (not preferred, not blocked) → 0.5
    return {
        "fit_score":         0.5,
        "preferred_regimes": preferred,
        "blocked_regimes":   blocked,
        "is_blocked":        False,
        "rationale":         f"{rationale} | sub-optimal in {r}",
    }


__all__ = [
    "REGIMES",
    "DEFAULT_REGIME",
    "detect_regime",
    "is_bucket_allowed",
    "is_ticker_allowed",
    "per_strategy_regime_fit",
]

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

"""
shared/profile.py — Aggressive Momentum + Event Switch config loader.

Single entry point to read configuration files. Caches results per-process
so monitors don't re-read JSON on every signal check.

USAGE:
  from profile import load_profile, load_watchlists, profile_value
  prof = load_profile()
  max_single = prof["capital"]["max_single_position_pct_equity"]
  ai_tickers = load_watchlists()["ai_nasdaq_semis"]["tickers"]

Falls back to empty dicts on missing files / parse errors so monitors
can safely run with hardcoded defaults if config is corrupted.
"""

import json
import os

_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROFILE    = os.path.join(_REPO_ROOT, "config", "aggressive_profile.json")
_WATCHLISTS = os.path.join(_REPO_ROOT, "config", "watchlists.json")

_cache: dict = {"profile": None, "watchlists": None}


def _safe_load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  profile loader: {os.path.basename(path)} unavailable ({e}); using empty fallback")
        return {}


def load_profile() -> dict:
    """Return aggressive_profile.json (cached)."""
    if _cache["profile"] is None:
        _cache["profile"] = _safe_load(_PROFILE)
    return _cache["profile"]


def load_watchlists() -> dict:
    """Return watchlists.json (cached)."""
    if _cache["watchlists"] is None:
        _cache["watchlists"] = _safe_load(_WATCHLISTS)
    return _cache["watchlists"]


def profile_value(path: str, default=None):
    """
    Read nested profile value by dot-path:
      profile_value("capital.max_single_position_pct_equity", 0.20)
      profile_value("regime.detection_mode", "hybrid")
    Returns `default` if any segment missing.
    """
    prof = load_profile()
    cur = prof
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return default
        cur = cur[seg]
    return cur


def bucket_for_ticker(ticker: str) -> str | None:
    """Return name of watchlist bucket containing this ticker, or None."""
    wls = load_watchlists()
    for bucket_name, cfg in wls.items():
        if not isinstance(cfg, dict):
            continue
        if ticker in (cfg.get("tickers") or []):
            return bucket_name
    return None


def allowed_buckets_for_regime(regime: str) -> list[str]:
    """List of bucket names approved for entries in given regime."""
    prof = load_profile()
    cfg = (prof.get("buckets_per_regime") or {}).get(regime) or {}
    return cfg.get("allowed_buckets") or []


def regime_size_multiplier(regime: str) -> float:
    """Regime-level size multiplier (0.5 in RISK_OFF, 0.7 NEUTRAL, etc.)."""
    prof = load_profile()
    cfg = (prof.get("buckets_per_regime") or {}).get(regime) or {}
    try:
        return float(cfg.get("size_multiplier", 1.0))
    except (TypeError, ValueError):
        return 1.0


def reset_cache():
    """Force reload of all configs. Tests call this between scenarios."""
    _cache["profile"] = None
    _cache["watchlists"] = None

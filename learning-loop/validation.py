"""
Learning-loop adaptation validator — anti-overfitting layer.

Sits between the deterministic adapter / LLM override application and the
state.json write. Rejects aggressive parameter changes that aren't backed
by enough trades. The point is to keep state.json semi-stable: a 1-trade
flutter shouldn't flip a strategy off, and a 3-day winning streak shouldn't
double size.

Rules implemented (spec §G.1):

  - No size increase if trades_7d < MIN_SAMPLE_INCREASE (default 20).
  - No strategy disable from small sample unless `hard_safety=True`
    (e.g. 5+ consecutive losses — the adapter sets this flag).
  - No side_bias change for options if options_trades_7d < MIN_SAMPLE_BIAS.
  - No ticker disable below MIN_SAMPLE_TICKER trades.
  - State changes only once per day — caller is expected to check
    `state.last_validated_at`.

The validator never silently rewrites a new_state — it produces a report
of accepted/rejected changes, and the caller (analyzer.py) decides what
to keep. Rationale strings are written into the per-strategy `notes`
field so future runs can see WHY a proposed change was dropped.
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Any

MIN_SAMPLE_INCREASE = 20    # require 20 trades in 7d before increasing size
MIN_SAMPLE_DISABLE = 10     # require 10 trades before disable (non-safety)
MIN_SAMPLE_BIAS_OPTIONS = 20
MIN_SAMPLE_TICKER = 5

# How much a single daily run is allowed to move size_multiplier without
# extra justification. Even with N >= MIN_SAMPLE_INCREASE, a single day
# can only halve or double — keeps the loop from over-reacting to one
# big winner.
MAX_DAILY_SIZE_MULT_STEP_UP = 1.50
MAX_DAILY_SIZE_MULT_STEP_DOWN = 0.50  # i.e. can cut to half-size in one day


def _trades_7d_for(today_stats: dict[str, Any], strategy: str) -> int:
    """Best-effort trade-count lookup from today_stats. Tolerant of schema drift."""
    per_strat = today_stats.get("per_strategy") or today_stats.get("strategies") or {}
    cfg = per_strat.get(strategy) or {}
    for k in ("trades_7d", "trades_count_7d", "n_trades_7d"):
        v = cfg.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    # Fall back to today's trades only — pessimistic for sample-size.
    for k in ("trades_today", "trades_count", "n_trades"):
        v = cfg.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _is_already_validated_today(old_state: dict[str, Any]) -> bool:
    raw = old_state.get("last_validated_at") or ""
    if not raw or not isinstance(raw, str):
        return False
    try:
        return date.fromisoformat(raw[:10]) == datetime.now(timezone.utc).date()
    except ValueError:
        return False


def validate_adaptation(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    today_stats: dict[str, Any],
    *,
    allow_double_run: bool = False,
) -> dict[str, Any]:
    """
    Compare per-strategy fields between old_state and new_state. Drop
    changes that violate sample-size rules.

    Returns:
      {
        "validated_state": dict,        # merged: old + accepted changes only
        "accepted":  [str, ...],        # human-readable change log
        "rejected":  [{ strategy, field, old, new, reason }, ...],
        "second_run": bool,             # True if blocked by once-per-day rule
      }
    """
    accepted: list[str] = []
    rejected: list[dict[str, Any]] = []

    # Second-daily-run protection
    second_run = _is_already_validated_today(old_state)
    if second_run and not allow_double_run:
        return {
            "validated_state": dict(old_state),
            "accepted": [],
            "rejected": [{"strategy": "*", "field": "*", "old": None, "new": None,
                          "reason": "already validated today (second-run blocked)"}],
            "second_run": True,
        }

    # Deep-clone new_state so we can reset rejected fields back to old values.
    import json as _json
    out = _json.loads(_json.dumps(new_state))

    old_strats = (old_state.get("strategies") or {})
    new_strats = (out.get("strategies") or {})

    for strat_name, new_cfg in new_strats.items():
        old_cfg = old_strats.get(strat_name) or {}
        if not isinstance(new_cfg, dict):
            continue
        n_trades = _trades_7d_for(today_stats, strat_name)

        # size_multiplier guard
        if "size_multiplier" in new_cfg:
            old_v = float(old_cfg.get("size_multiplier", 1.0))
            new_v = float(new_cfg["size_multiplier"])
            if abs(new_v - old_v) > 1e-3:
                going_up = new_v > old_v
                # Daily step bound — never more than ×1.5 up or to half down.
                if going_up and new_v / max(old_v, 1e-6) > MAX_DAILY_SIZE_MULT_STEP_UP:
                    rejected.append({
                        "strategy": strat_name, "field": "size_multiplier",
                        "old": old_v, "new": new_v,
                        "reason": f"step-up {new_v / max(old_v, 1e-6):.2f}x > "
                                  f"{MAX_DAILY_SIZE_MULT_STEP_UP}x daily max",
                    })
                    out["strategies"][strat_name]["size_multiplier"] = old_v
                elif (not going_up
                      and new_v / max(old_v, 1e-6) < MAX_DAILY_SIZE_MULT_STEP_DOWN):
                    rejected.append({
                        "strategy": strat_name, "field": "size_multiplier",
                        "old": old_v, "new": new_v,
                        "reason": f"step-down {new_v / max(old_v, 1e-6):.2f}x < "
                                  f"{MAX_DAILY_SIZE_MULT_STEP_DOWN}x daily min",
                    })
                    out["strategies"][strat_name]["size_multiplier"] = old_v
                elif going_up and n_trades < MIN_SAMPLE_INCREASE:
                    rejected.append({
                        "strategy": strat_name, "field": "size_multiplier",
                        "old": old_v, "new": new_v,
                        "reason": f"size increase blocked — trades_7d={n_trades} "
                                  f"< {MIN_SAMPLE_INCREASE}",
                    })
                    out["strategies"][strat_name]["size_multiplier"] = old_v
                else:
                    accepted.append(
                        f"{strat_name}.size_multiplier {old_v} -> {new_v} "
                        f"(n={n_trades})"
                    )

        # enabled guard (disable requires sample OR hard_safety flag)
        if "enabled" in new_cfg:
            old_v = bool(old_cfg.get("enabled", True))
            new_v = bool(new_cfg["enabled"])
            if old_v != new_v:
                hard_safety = bool(new_cfg.get("hard_safety") or new_cfg.get("safety_disable"))
                if new_v is False and not hard_safety and n_trades < MIN_SAMPLE_DISABLE:
                    rejected.append({
                        "strategy": strat_name, "field": "enabled",
                        "old": old_v, "new": new_v,
                        "reason": f"disable blocked — trades_7d={n_trades} "
                                  f"< {MIN_SAMPLE_DISABLE} and not hard_safety",
                    })
                    out["strategies"][strat_name]["enabled"] = old_v
                else:
                    accepted.append(
                        f"{strat_name}.enabled {old_v} -> {new_v} "
                        f"(n={n_trades}, hard_safety={hard_safety})"
                    )

        # side_bias for options
        if "side_bias" in new_cfg:
            old_v = old_cfg.get("side_bias")
            new_v = new_cfg["side_bias"]
            if old_v != new_v:
                if "options" in strat_name.lower() and n_trades < MIN_SAMPLE_BIAS_OPTIONS:
                    rejected.append({
                        "strategy": strat_name, "field": "side_bias",
                        "old": old_v, "new": new_v,
                        "reason": f"options side_bias change blocked — "
                                  f"trades_7d={n_trades} < {MIN_SAMPLE_BIAS_OPTIONS}",
                    })
                    out["strategies"][strat_name]["side_bias"] = old_v
                else:
                    accepted.append(f"{strat_name}.side_bias {old_v} -> {new_v}")

        # paused_until — always allowed; it's a date, not a parameter.
        if "paused_until" in new_cfg and new_cfg["paused_until"] != old_cfg.get("paused_until"):
            accepted.append(
                f"{strat_name}.paused_until {old_cfg.get('paused_until')} -> {new_cfg['paused_until']}"
            )

    # Stamp validation timestamp on the state ONLY if validation actually ran.
    out["last_validated_at"] = datetime.now(timezone.utc).isoformat()
    return {
        "validated_state": out,
        "accepted": accepted,
        "rejected": rejected,
        "second_run": False,
    }

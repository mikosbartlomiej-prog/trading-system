from __future__ import annotations  # v3.11.3 part 2: PEP 604 on Py 3.9.

"""
Adapter — pure function (old_state, today_stats) -> new_state.

Heuristics encoded as small testable functions. No I/O — analyzer.py
owns reading/writing files.
"""

import re
from copy import deepcopy
from datetime import datetime, timezone


# ─── Bounds & thresholds ─────────────────────────────────────────────────────

MIN_SAMPLE_TRADES   = 10        # don't adapt until lifetime >= this many trades
MIN_7D_TRADES       = 5         # don't adapt 7d window until 5+ trades

MIN_SIZE_MULT       = 0.30
MAX_SIZE_MULT       = 2.00

# Win-rate triggers (over 7d window)
WR_COOL_THRESHOLD   = 0.35      # below this -> size *= 0.8
WR_WARM_THRESHOLD   = 0.60      # above this -> size *= 1.10

# P&L triggers (% of equity over 7d)
PL_COOL_PCT         = -2.0      # below this -> size *= 0.7
PL_WARM_PCT         =  3.0      # above this -> size *= 1.05

# Disable triggers
CONSECUTIVE_LOSS_LIMIT       = 5       # 5 in a row -> pause
LIFETIME_ROI_DISABLE_PCT     = -10.0   # lifetime ROI worse than this -> pause

# Pause duration in days (auto re-enable check after this)
PAUSE_DAYS = 3


# ─── Helper: apply multiplicative size change with bounds ────────────────────

def _adjust_size(current: float, factor: float) -> float:
    new = current * factor
    return max(MIN_SIZE_MULT, min(MAX_SIZE_MULT, new))


# ─── Per-strategy adaptation ─────────────────────────────────────────────────

def adapt_strategy(name: str, old: dict, stats: dict, equity: float) -> dict:
    """
    Compute new strategy state given:
      old:     prior state dict (or {} / partial dict if first run /
               manual edit). Missing keys get default values.
      stats:   today's contribution + 7d totals + lifetime totals
      equity:  current account equity (for P&L %)

    Returns a new dict with size_multiplier, enabled, side_bias, rationale,
    and rolled-up stats.
    """
    defaults = {
        "trades_lifetime":    0,
        "trades_7d":          0,
        "win_rate_lifetime":  0.0,
        "win_rate_7d":        0.0,
        "pnl_usd_lifetime":   0.0,
        "pnl_usd_7d":         0.0,
        "size_multiplier":    1.0,
        "enabled":            True,
        "side_bias":          None,
        "consecutive_losses": 0,
        "rationale":          "default",
        "paused_until":       None,
    }
    # Start from defaults, overlay any old keys present (defensive: handles
    # partial state.json after manual edit or first run).
    new = deepcopy(defaults)
    if old:
        for k, v in old.items():
            new[k] = v

    # Roll in the latest stats (analyzer computes these)
    new["trades_lifetime"]   = stats.get("trades_lifetime", new["trades_lifetime"])
    new["trades_7d"]         = stats.get("trades_7d", 0)
    new["win_rate_lifetime"] = stats.get("win_rate_lifetime", 0.0)
    new["win_rate_7d"]       = stats.get("win_rate_7d", 0.0)
    new["pnl_usd_lifetime"]  = stats.get("pnl_usd_lifetime", 0.0)
    new["pnl_usd_7d"]        = stats.get("pnl_usd_7d", 0.0)
    new["consecutive_losses"] = stats.get("consecutive_losses", 0)

    today_iso = datetime.now(timezone.utc).date().isoformat()

    # Auto-resume from pause if expired
    if new.get("paused_until"):
        if today_iso >= new["paused_until"]:
            new["enabled"] = True
            new["paused_until"] = None
            new["rationale"] = f"auto-resumed from pause on {today_iso}"
            # v3.9.0 (2026-05-21): stamp enabled_at on transitions
            # False → True so silent_strategy_warnings can grant a 5-day
            # grace period (LLM proposal 2026-05-17). Without this,
            # newly-re-enabled strategies (geo-* in v3.8.7, options-momentum
            # post-pause) immediately receive SILENT warning even though
            # they need a few days to accumulate trades.
            new["enabled_at"] = today_iso
    # Detect enable flip from prior state — when LLM/manual override sets
    # enabled True externally, also stamp enabled_at.
    elif new.get("enabled") and not old.get("enabled", True):
        new["enabled_at"] = today_iso

    # If currently paused, don't adapt size
    if not new["enabled"]:
        return new

    # Insufficient sample
    if new["trades_lifetime"] < MIN_SAMPLE_TRADES:
        new["rationale"] = (
            f"hold (lifetime trades {new['trades_lifetime']} < {MIN_SAMPLE_TRADES}; "
            f"need more sample before adapting)"
        )
        return new

    old_mult = new["size_multiplier"]
    reasons  = []

    # Lifetime ROI disable
    starting = stats.get("starting_equity", equity if equity > 0 else 100000)
    lifetime_roi = (new["pnl_usd_lifetime"] / starting * 100) if starting > 0 else 0.0
    if lifetime_roi < LIFETIME_ROI_DISABLE_PCT:
        new["enabled"] = False
        new["paused_until"] = (datetime.now(timezone.utc).date()).isoformat()
        new["rationale"] = (
            f"DISABLED — lifetime ROI {lifetime_roi:.1f}% < {LIFETIME_ROI_DISABLE_PCT}%; "
            f"auto-disabled by adapter (next daily-learning will keep it off "
            f"unless paused_until is cleared in state.json; no operator action expected)"
        )
        return new

    # Consecutive losses pause — v3.10: mark hard_safety so validator allows
    # this intraday-safe adaptation even when 7d sample size is low.
    if new["consecutive_losses"] >= CONSECUTIVE_LOSS_LIMIT:
        from datetime import timedelta
        until = (datetime.now(timezone.utc).date() + timedelta(days=PAUSE_DAYS)).isoformat()
        new["enabled"] = False
        new["paused_until"] = until
        new["hard_safety"] = True  # v3.10: bypass MIN_SAMPLE_DISABLE in validator
        new["rationale"] = (
            f"PAUSED until {until} — {new['consecutive_losses']} consecutive losses; "
            f"auto-resume after {PAUSE_DAYS} days (hard_safety=true, validator bypassed)"
        )
        return new

    # Sample for 7d adjustments
    if new["trades_7d"] >= MIN_7D_TRADES:
        # Win rate thresholds
        if new["win_rate_7d"] < WR_COOL_THRESHOLD:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 0.8)
            reasons.append(f"7d win-rate {new['win_rate_7d']*100:.0f}% < {WR_COOL_THRESHOLD*100:.0f}% -> -20%")
        elif new["win_rate_7d"] > WR_WARM_THRESHOLD:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 1.10)
            reasons.append(f"7d win-rate {new['win_rate_7d']*100:.0f}% > {WR_WARM_THRESHOLD*100:.0f}% -> +10%")

        # P&L thresholds
        pl_pct = (new["pnl_usd_7d"] / equity * 100) if equity > 0 else 0
        if pl_pct < PL_COOL_PCT:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 0.7)
            reasons.append(f"7d P&L {pl_pct:+.1f}% < {PL_COOL_PCT}% -> -30%")
        elif pl_pct > PL_WARM_PCT:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 1.05)
            reasons.append(f"7d P&L {pl_pct:+.1f}% > {PL_WARM_PCT}% -> +5%")

    # Side-bias for options (if user opt-in via "options-momentum" name)
    # Heuristic: if strategy-options has separate long_pnl vs short_pnl tracked
    long_pnl  = stats.get("pnl_long_7d", 0)
    short_pnl = stats.get("pnl_short_7d", 0)
    if name.startswith("options") and stats.get("trades_7d", 0) >= MIN_7D_TRADES:
        if long_pnl < 0 and short_pnl > abs(long_pnl):
            new["side_bias"] = "short"
            reasons.append(f"options long P&L ${long_pnl:.0f}, short ${short_pnl:.0f} -> bias=short (PUT-only)")
        elif short_pnl < 0 and long_pnl > abs(short_pnl):
            new["side_bias"] = "long"
            reasons.append(f"options short P&L ${short_pnl:.0f}, long ${long_pnl:.0f} -> bias=long (CALL-only)")

    if abs(new["size_multiplier"] - old_mult) > 0.001 or reasons:
        new["rationale"] = " | ".join(reasons) if reasons else "no change"
    else:
        new["rationale"] = "no change (within thresholds)"

    return new


# ─── Top-level orchestration ─────────────────────────────────────────────────

def _apply_tp_feedback(state: dict, today_stats: dict) -> list[str]:
    """
    LLM proposal 2026-05-09: TP feedback loop.

    When a strategy's static TP target is missing too often (hit_rate
    < 0.20 over 5+ placements), the target is too aggressive vs realised
    price movement. Record a `suggested_tp_multiplier` of 1.4 (down
    from default 1.8) in state['strategies'][s]; options-exit-monitor
    reads this on next tick and uses tighter TP.

    Returns list of rationale lines (one per strategy where TP was
    tightened).
    """
    if not state or not isinstance(state.get("strategies"), dict):
        return []
    tp_hr = today_stats.get("tp_hit_rate") or {}
    if not isinstance(tp_hr, dict):
        return []

    out: list[str] = []
    for strat, stats in tp_hr.items():
        if not isinstance(stats, dict):
            continue
        placed = stats.get("tp_placed", 0)
        hit = stats.get("tp_hit_rate", 0.0)
        if placed < 5 or hit >= 0.20:
            continue
        if strat not in state["strategies"]:
            continue
        cur = state["strategies"][strat].get("suggested_tp_multiplier", 1.8)
        if cur == 1.4:
            continue                       # already tightened
        state["strategies"][strat]["suggested_tp_multiplier"] = 1.4
        out.append(
            f"{strat}: suggested_tp_multiplier {cur:.1f} -> 1.4 "
            f"(hit_rate {hit:.0%} on {placed} placements — TP too far)"
        )
    return out


def _flag_silent_strategies(state: dict, today_stats: dict,
                              min_days: int = 10) -> list[str]:
    """
    LLM proposal 2026-05-10: flag strategies that are `enabled=True` but
    have produced zero trades for `min_days` days. They sit in state.json
    consuming attention budget in LLM payload but contribute nothing.

    We DON'T auto-disable — that's a policy decision the LLM/operator
    should make. We just emit a rationale flag so they're visible.

    Returns list of rationale lines (one per silent strategy).
    """
    if not state or not isinstance(state.get("strategies"), dict):
        return []
    days_tracked = state.get("days_tracked", 0) or 0
    if days_tracked < min_days:
        return []                          # not enough history yet

    # v3.8.6 (2026-05-16): exclude allocator-level tags from SILENT check.
    # alloc-exit, alloc-reduce, allocator-rebalance, op-correction are
    # NOT strategies — they're allocator's order tagging for operational
    # flows. Their "0 trades lifetime" is meaningless because trades are
    # attributed to the underlying signal strategy, not the allocator tag.
    # v3.9.8 (2026-05-23): added alloc-reduce (was being flagged daily;
    # same allocator-tag category as alloc-exit per shared/allocator.py).
    ALLOCATOR_LEVEL_TAGS = {
        "alloc-exit", "alloc-reduce", "allocator-rebalance",
        "op-correction", "operational-correction",
        "emergency-close", "unknown",
    }

    # v3.9.0 (2026-05-21, LLM proposal 2026-05-17): grant 5-day grace
    # period after re-enable. Strategy that was disabled and just came
    # back online doesn't have any history yet — flagging it SILENT
    # immediately is noise. After GRACE_DAYS the warning fires normally.
    GRACE_DAYS = 5
    today_iso = datetime.now(timezone.utc).date().isoformat()

    by_strat = today_stats.get("by_strategy") or {}
    out: list[str] = []
    for name, cfg in state["strategies"].items():
        if not cfg.get("enabled", True):
            continue                       # disabled is fine
        if name in ALLOCATOR_LEVEL_TAGS:
            continue                       # not a strategy — allocator tag

        # Grace period check — recently re-enabled strategies skip SILENT.
        enabled_at = cfg.get("enabled_at")
        if enabled_at:
            try:
                from datetime import date as _date
                ea = _date.fromisoformat(enabled_at)
                td = _date.fromisoformat(today_iso)
                days_since_enable = (td - ea).days
                if days_since_enable < GRACE_DAYS:
                    continue               # grace window active
            except (ValueError, TypeError):
                pass                        # malformed → no grace, fire normally

        stats = by_strat.get(name) or {}
        if stats.get("trades_lifetime", 0) > 0:
            continue                       # has trades at some point
        if stats.get("trades_7d", 0) > 0:
            continue                       # active this week

        # v3.11.1 (2026-05-29) — REFINED zombie-prune policy.
        # PROBLEM with v3.11 (shipped 2026-05-27): forced auto-disable on
        # "0 trades lifetime" disabled 6 strategies on 2026-05-28
        # (crypto-momentum + 4 geo-* + options-momentum) during BTC/ETH
        # RSI 20.5/19.5 — best buying opportunity. LLM Senior PM had to
        # OVERRIDE every day. Per LLM analysis: cause was PIPELINE FAILURE
        # (monitor routing broken, Anthropic quota), NOT lack of edge.
        #
        # NEW POLICY — distinguish two cases:
        # (a) Strategy fired orders but all rejected/lost → legit auto-prune
        #     Condition: orders_placed_lifetime >= 5 AND trades_lifetime == 0
        # (b) Strategy fired ZERO orders → pipeline failure, NOT prune
        #     Condition: orders_placed_lifetime < 5
        #     → log flag "PIPELINE_FAILURE_SUSPECTED", DON'T auto-disable
        #
        # If we can't get orders_placed_lifetime from stats, FAIL SAFE (no prune).
        AUTO_PRUNE_DAYS = 21
        MIN_PLACED_FOR_PRUNE = 5  # need ≥5 placement attempts to prove no edge
        LLM_OVERRIDE_LOCK_DAYS = 14  # v3.11.3 part 2 (2026-05-30) — see below
        if days_tracked >= AUTO_PRUNE_DAYS:
            override = bool(cfg.get("hard_safety_override"))
            if override:
                out.append(
                    f"{name}: SILENT {days_tracked}d but hard_safety_override=true → keep enabled"
                )
                continue

            # v3.11.3 part 2 (2026-05-30) — LLM-OVERRIDE LOCK.
            # From LLM proposal 2026-05-29: an explicit LLM override
            # (Senior PM re-enables a strategy) was being CANCELED by the
            # very next deterministic adapter run, which re-prunes the
            # same strategy → LLM has to re-enable next night → cycle
            # repeats 5+ days (observed for crypto-momentum). Honor the
            # LLM's judgment for LLM_OVERRIDE_LOCK_DAYS days so it has
            # time to gather evidence. Stamp set by
            # `analyzer.apply_llm_overrides` via `safe_apply_overrides`.
            last_llm_at = cfg.get("last_llm_override_at")
            if last_llm_at:
                try:
                    from datetime import date as _date
                    _today = _date.fromisoformat(today_iso)
                    days_since_llm = (_today - _date.fromisoformat(last_llm_at)).days
                    if days_since_llm < LLM_OVERRIDE_LOCK_DAYS:
                        out.append(
                            f"{name}: SILENT {days_tracked}d but LLM override "
                            f"{last_llm_at} active ({days_since_llm}d ago "
                            f"< {LLM_OVERRIDE_LOCK_DAYS}d lock) → keep enabled"
                        )
                        # v3.22.1 — escalate to operator action queue when
                        # LLM is unavailable AND this strategy is in a long
                        # silence that the lock cannot be revised away from.
                        try:
                            import sys, os
                            sys.path.insert(
                                0,
                                os.path.join(
                                    os.path.dirname(__file__), "..", "shared"
                                ),
                            )
                            from llm_availability import (  # noqa: E402
                                escalate_silent_strategy_lock,
                            )
                            escalate_silent_strategy_lock(
                                strategy=name,
                                silent_days=int(days_tracked),
                                last_override_iso=last_llm_at,
                            )
                        except Exception:
                            pass  # fail-soft — escalation must not break adapter
                        continue
                except (ValueError, TypeError):
                    pass  # malformed date → fall through

            # Check whether strategy ever ATTEMPTED to trade
            # (fill_rate.<strategy>.placed counts placement attempts)
            fill_rate = today_stats.get("fill_rate") or {}
            strategy_fill = fill_rate.get(name) or {}
            placed_lifetime = int(strategy_fill.get("placed_lifetime")
                                    or strategy_fill.get("placed", 0))
            # Fallback: any orders observed
            if placed_lifetime == 0:
                # Pipeline failure case — DON'T auto-disable, flag instead
                out.append(
                    f"{name}: PIPELINE_FAILURE_SUSPECTED — SILENT {days_tracked}d, "
                    f"0 trades AND 0 placement attempts. NOT auto-pruned (v3.11.1). "
                    f"Likely cause: monitor routing broken, API quota, or strategy never fires. "
                    f"Operator check: monitor-health for this strategy's monitor."
                )
                continue

            if placed_lifetime >= MIN_PLACED_FOR_PRUNE:
                # Legit case: placed many orders, none became trades → no edge
                cfg["enabled"] = False
                cfg["paused_until"] = None
                cfg["hard_safety"] = True
                cfg["auto_pruned_at"] = today_iso
                cfg["rationale"] = (
                    f"AUTO-PRUNED: SILENT {days_tracked}d, {placed_lifetime} placement "
                    f"attempts, 0 trades. v3.11.1 refined zombie-prune (legit no-edge)."
                )
                out.append(
                    f"{name}: AUTO-PRUNED (SILENT {days_tracked}d, "
                    f"{placed_lifetime} placed / 0 trades) — enabled=False. "
                    f"To revive: hard_safety_override=true OR clear auto_pruned_at."
                )
            else:
                # In-between: some attempts but not enough sample
                out.append(
                    f"{name}: SILENT {days_tracked}d with {placed_lifetime} placement "
                    f"attempts — insufficient sample for prune (need ≥{MIN_PLACED_FOR_PRUNE}). "
                    f"v3.11.1 keeps enabled."
                )
        else:
            out.append(
                f"{name}: SILENT — enabled but 0 trades lifetime "
                f"({days_tracked} days tracked, will evaluate at {AUTO_PRUNE_DAYS}d)"
            )
    return out


_UUID_KEY_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-')


def _is_uuid_key(name: str) -> bool:
    """Detect Alpaca bracket order ID artifacts in strategy keys."""
    return bool(name) and bool(_UUID_KEY_RE.match(name))


def _prune_uuid_keys(state: dict) -> tuple[int, list[str]]:
    """
    Remove UUID-format strategy keys from state['strategies'].

    LLM proposal 2026-05-09 + 2026-05-10 weekly retro: state.json contains
    7 legacy UUID keys (fdeebe90-, 62bd8628-, etc.) from old single-leg
    attribution bug — these never correspond to real strategies and emit
    noise as '0 trades / 0% WR / $0' in per-strategy reports.

    Returns (count_pruned, list_of_pruned_names).
    """
    if not state or not isinstance(state.get("strategies"), dict):
        return 0, []
    strats = state["strategies"]
    pruned = [n for n in list(strats.keys()) if _is_uuid_key(n)]
    for n in pruned:
        del strats[n]
    return len(pruned), pruned


def _reset_options_bias_if_no_data(state: dict, today_stats: dict) -> bool:
    """
    Auto-clear `global_overrides.options_side_bias` when there's no
    options-momentum activity to support it.

    LLM proposal 2026-05-09: options_side_bias propagates across days
    even after the LLM has moved on. If `options-momentum.trades_7d < 3`,
    we have insufficient evidence for any directional bias — reset to
    None to prevent stale overrides influencing future entries.

    Returns True if a reset was applied.
    """
    if not state or not isinstance(state.get("global_overrides"), dict):
        return False
    current_bias = state["global_overrides"].get("options_side_bias")
    if current_bias is None:
        return False                      # already clear
    om_stats = today_stats.get("by_strategy", {}).get("options-momentum", {})
    trades_7d = om_stats.get("trades_7d", 0)
    if trades_7d < 3:
        state["global_overrides"]["options_side_bias"] = None
        return True
    return False


def adapt(state: dict, today_stats: dict) -> tuple[dict, list[str]]:
    """
    Top-level adapter.

    Inputs:
      state:        current learning-loop/state.json contents (or {} if first run)
      today_stats:  computed by analyzer.py — must include
                    {
                      "as_of": iso date,
                      "equity": float,
                      "starting_equity": float,
                      "by_strategy": {name: stats_dict, ...},
                      "by_asset_class": {...},
                      "by_source": {...},
                    }

    Returns:
      (new_state, rationale_lines) where rationale_lines is a list of
      one-liners describing each change made.
    """
    rationale: list[str] = []
    new_state = deepcopy(state) if state else {
        "version": "1.0",
        "days_tracked": 0,
        "cumulative": {"total_trades": 0, "total_pnl_usd": 0.0, "starting_equity": None},
        "strategies": {},
        "asset_classes": {},
        "sources": {},
        "next_actions": [],
        "global_overrides": {
            "options_side_bias": None,
            "max_open_options": None,
            "max_concurrent_per_strategy": {},
        },
    }

    today_iso = today_stats.get("as_of") or datetime.now(timezone.utc).date().isoformat()
    new_state["last_updated"] = datetime.now(timezone.utc).isoformat()
    new_state["days_tracked"] = (state.get("days_tracked", 0) if state else 0) + 1

    # ── Pre-pass cleanups (LLM proposals 2026-05-09 + 2026-05-10) ─────────────
    # Filter UUID-format strategy keys from previous single-leg attribution
    # bug (Alpaca bracket order IDs leaked as strategy names).
    pruned_count, pruned_names = _prune_uuid_keys(new_state)
    if pruned_count:
        rationale.append(
            f"{today_iso} · pruned {pruned_count} UUID artifact strategy keys "
            f"({', '.join(pruned_names[:3])}{'...' if pruned_count > 3 else ''})"
        )
    # Auto-clear options_side_bias when no supporting trade data.
    if _reset_options_bias_if_no_data(new_state, today_stats):
        rationale.append(
            f"{today_iso} · options_side_bias reset to null "
            f"(zero supporting data in 7d window — proposal 2026-05-09)"
        )
    # PR #10 (2026-05-26, fixed v3.9.9 2026-05-27): macro fallback.
    # Decoupled from _reset_options_bias_if_no_data gate (v3.9.9 fix): the
    # reset returns False when bias is already None, which made this dead
    # code in the original wire-in. Now runs independently whenever
    # current bias is None AND trade sample is thin (< 3 trades 7d).
    # SPY RSI ≥72 → short (PUT-favored), ≤35 → long (CALL-favored).
    _current_bias = new_state.get("global_overrides", {}).get("options_side_bias")
    _om_trades_7d = (
        today_stats.get("by_strategy", {})
                   .get("options-momentum", {})
                   .get("trades_7d", 0)
    )
    if _current_bias is None and _om_trades_7d < 3:
        macro_bias, macro_reason = heuristic_options_bias_from_spy_rsi(today_stats)
        if macro_bias is not None:
            new_state["global_overrides"]["options_side_bias"] = macro_bias
            rationale.append(
                f"{today_iso} · options_side_bias={macro_bias} via macro fallback — {macro_reason}"
            )
    # TP feedback loop (LLM proposal 2026-05-09): tighten suggested_tp_
    # multiplier when realised hit rate is poor.
    for line in _apply_tp_feedback(new_state, today_stats):
        rationale.append(f"{today_iso} · TP feedback: {line}")
    # Silent-strategy flag (LLM proposal 2026-05-10): surface zombies.
    for line in _flag_silent_strategies(new_state, today_stats, min_days=10):
        rationale.append(f"{today_iso} · {line}")
    new_state["cumulative"]   = {
        "total_trades":     today_stats.get("cumulative_trades",   0),
        "total_pnl_usd":    today_stats.get("cumulative_pnl_usd",  0.0),
        "starting_equity":  today_stats.get("starting_equity") or
                             (state.get("cumulative", {}).get("starting_equity") if state else None),
    }

    # Per-strategy adapt
    next_actions: list[str] = []
    for strat_name, strat_stats in today_stats.get("by_strategy", {}).items():
        old = (state.get("strategies", {}) if state else {}).get(strat_name, {})
        new = adapt_strategy(strat_name, old, strat_stats, today_stats.get("equity", 0))

        # Lane 2 PR #8 (2026-05-21) — Crypto oversold bounce boost.
        # Applied AFTER per-strategy adapt so it can override the
        # baseline multiplier. Bounded by clamp inside adapt_strategy
        # rules (0.30-2.00). Fires only when both ETH ≤30 AND BTC ≤45.
        if strat_name == "crypto-momentum" and new.get("enabled"):
            fired, boost_mult, boost_reason = heuristic_crypto_oversold_boost(today_stats)
            if fired and new.get("size_multiplier", 1.0) < boost_mult:
                new["size_multiplier"] = boost_mult
                existing_rat = new.get("rationale", "") or ""
                new["rationale"] = (
                    f"{existing_rat} | {boost_reason}" if existing_rat else boost_reason
                )

            # Lane 2 PR #9 (2026-05-23) — Deep oversold amplifier.
            # Fires AFTER PR #8 base boost. ETH ≤25 (vs ≤30) = deep
            # capitulation territory, historically larger bounce. Overrides
            # upward to 1.5× (vs 1.3× from base). Same clamp (≤2.00) +
            # never downgrades existing multiplier.
            fired2, deep_mult, deep_reason = heuristic_crypto_deep_oversold_boost(today_stats)
            if fired2 and new.get("size_multiplier", 1.0) < deep_mult:
                new["size_multiplier"] = deep_mult
                existing_rat = new.get("rationale", "") or ""
                new["rationale"] = (
                    f"{existing_rat} | {deep_reason}" if existing_rat else deep_reason
                )

        # Detect changes vs old for rationale + next_actions
        old_mult = old.get("size_multiplier", 1.0)
        new_mult = new["size_multiplier"]
        if abs(new_mult - old_mult) > 0.001:
            line = f"{strat_name}: size_multiplier {old_mult:.2f} -> {new_mult:.2f}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)
        if old.get("enabled", True) != new.get("enabled", True):
            line = f"{strat_name}: enabled {old.get('enabled', True)} -> {new['enabled']}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)
        if old.get("side_bias") != new.get("side_bias"):
            line = f"{strat_name}: side_bias {old.get('side_bias')} -> {new['side_bias']}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)

        new_state["strategies"][strat_name] = new

    new_state["asset_classes"] = today_stats.get("by_asset_class", {})
    new_state["sources"]       = today_stats.get("by_source", {})
    new_state["next_actions"]  = next_actions

    # ── Fill-rate heuristics (LLM proposals 2026-05-09 #4 + #5 + #7) ─────────
    # Run AFTER per-strategy adaptation so we can both alert (warning) and
    # cut size (action) in one pass. Each heuristic is pure; rationale lines
    # become part of the daily log.
    fill_data = today_stats.get("fill_rate") or {}

    # Alerts (no state change, just visibility) — proposal #7
    for alert in heuristic_fill_rate_alert(fill_data):
        rationale.append(
            f"{today_iso} · fill-rate alert [{alert['strategy']}]: {alert['alert']}"
        )

    # Chronic options-momentum signal (proposal #5)
    chronic, why = heuristic_options_chronic_fill(fill_data)
    if chronic:
        rationale.append(f"{today_iso} · chronic-fill [options-momentum]: {why}")

    # Size-cut for options-momentum on high cancel rate (proposal #4)
    opts = fill_data.get("options-momentum", {})
    cut, factor, cut_reason = heuristic_fill_rate_size_cut(
        opts.get("canceled", 0), opts.get("placed", 0),
    )
    if cut and "options-momentum" in new_state.get("strategies", {}):
        cur = new_state["strategies"]["options-momentum"].get("size_multiplier", 1.0)
        capped = max(MIN_SIZE_MULT, min(MAX_SIZE_MULT, cur * factor))
        if abs(capped - cur) > 0.001:
            new_state["strategies"]["options-momentum"]["size_multiplier"] = round(capped, 2)
            line = f"options-momentum: size_multiplier {cur:.2f} -> {capped:.2f} (fill-rate guard)"
            rationale.append(f"{today_iso} · {line} · {cut_reason}")
            next_actions.append(line)

    # Stale-exit-emergency detector (Lane 2 PR #3, 2026-05-09): surface
    # the QQQ260518P00714000-style failure in daily rationale so operator
    # gets a visible nudge to clean up stuck orders.
    stale_fired, stale_why = heuristic_stale_exit_emergency(fill_data)
    if stale_fired:
        rationale.append(f"{today_iso} · {stale_why}")

    # SPY-overbought regime gate for options-momentum (Lane 2 PR #4, 2026-05-14):
    # When SPY RSI > 75 we extend the options-momentum pause regardless of
    # paused_until expiry. This codifies the LLM Senior PM's 2026-05-13
    # rationale: -$3,120 loss occurred in identical RSI 82+ regime;
    # auto-resume in that environment would repeat the mistake.
    block_om, om_why = heuristic_spy_overbought_options_block(today_stats)
    if block_om and "options-momentum" in new_state.get("strategies", {}):
        om = new_state["strategies"]["options-momentum"]
        # Pin paused_until to tomorrow's date so adapt re-evaluates next run.
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        until = (_dt.now(_tz.utc).date() + _td(days=1)).isoformat()
        changed = False
        if om.get("enabled") is not False:
            om["enabled"] = False; changed = True
        if om.get("paused_until") != until:
            om["paused_until"] = until; changed = True
        if changed:
            rationale.append(f"{today_iso} · options-momentum: SPY-overbought gate · {om_why}")
            next_actions.append(f"options-momentum: paused_until -> {until} (SPY-overbought gate)")

    if not rationale:
        rationale.append(f"{today_iso} · no parameter changes (all strategies within thresholds)")

    # v3.11 (2026-05-27) — final gates before state.json write.
    try:
        from edge_validator import enforce_edge_gate_on_state, enforce_regime_gate
        # Phase E: regime-conditional enable (auto-pause strategy if regime
        # incompatible; auto-resume when regime changes back)
        current_regime = (today_stats.get("regime") or
                          (today_stats.get("regime_data") or {}).get("regime") or "")
        if current_regime:
            new_state, regime_log = enforce_regime_gate(new_state, current_regime)
            for line in regime_log:
                rationale.append(f"{today_iso} · {line}")
        # Phase A: backtest-gated enable (forces enabled=False without verified
        # edge: WR ≥ 50%, PF ≥ 1.3, MDD < 20%, n ≥ 10 in realistic backtest)
        new_state, edge_log = enforce_edge_gate_on_state(new_state)
        for line in edge_log:
            rationale.append(f"{today_iso} · {line}")
    except Exception as e:
        # Fail-soft: gate failure must NEVER prevent state write
        rationale.append(f"{today_iso} · edge_validator unavailable ({type(e).__name__}: {e}) — skipped")

    return new_state, rationale


# ─── Lane2 auto-added — Detect options-momentum fill rate below 50% over 5+ orders and alert to widen limits ────────────

def heuristic_options_limit_too_tight(fill_stats: dict) -> tuple:
    """Flag when options-momentum limits are systematically too tight."""
    opts = fill_stats.get("options-momentum", {})
    placed = opts.get("placed", 0)
    fill_rate = opts.get("fill_rate", 1.0)
    if placed >= 5 and fill_rate < 0.5:
        return True, (
            f"options-momentum fill_rate {fill_rate:.0%} over {placed} orders"
            " — limits too tight, widen to ask+1% or mid+3%"
        )
    return False, ""


# ─── Lane 3 → manual-implemented — fill-rate heuristics (LLM proposals 2026-05-09) ───

def heuristic_fill_rate_size_cut(canceled: int, placed: int,
                                   cancel_threshold: float = 0.50) -> tuple:
    """
    Recommend a size_multiplier scaling factor when cancel rate is high.

    Implementation of LLM proposal 2026-05-09 #4: chronic high cancel
    rate suggests we're placing 'phantom' orders that never fill,
    wasting allocated capital. Scaling size_multiplier down forces
    less notional to be deployed until execution improves.

    Returns (should_cut, factor, reason):
      factor in [0.40, 0.75] when should_cut True
      factor 1.0 when no action (sample too small or fill_rate OK)
    Requires >= 3 placed for a signal.

    Caller wires into adapt() AFTER the per-strategy loop:
        cap, factor, why = heuristic_fill_rate_size_cut(...)
        if cap and 'options-momentum' in new_state['strategies']:
            sm = new_state['strategies']['options-momentum']['size_multiplier']
            new_state['strategies']['options-momentum']['size_multiplier'] = (
                max(MIN_SIZE_MULT, min(MAX_SIZE_MULT, sm * factor))
            )
    """
    if placed < 3:
        return False, 1.0, f"sample too small ({placed} placed)"
    cancel_rate = canceled / placed
    if cancel_rate >= cancel_threshold:
        factor = max(0.40, min(0.75, 1.0 - cancel_rate))
        return True, factor, (
            f"cancel_rate={cancel_rate:.0%} >= {cancel_threshold:.0%} "
            f"({canceled}/{placed} canceled) -> cap multiplier *{factor}"
        )
    return False, 1.0, f"fill_rate OK (cancel_rate={cancel_rate:.0%})"


def heuristic_fill_rate_alert(fill_rate_data: dict,
                                threshold: float = 0.50,
                                min_placed: int = 3) -> list:
    """
    Identify all strategies with persistent low fill rates.

    Implementation of LLM proposal 2026-05-09 #7 (alert function).
    Pure function — takes a `today_stats['fill_rate']` dict, returns a
    sorted list of alert dicts (worst-first). Zero side effects;
    caller (analyzer or weekly_retro) decides whether to emit warnings
    to rationale.md or trigger size cuts via heuristic_fill_rate_size_cut.

    Each alert dict:
      {strategy, fill_rate, placed, filled, canceled, alert (str)}
    """
    alerts = []
    for strategy, data in (fill_rate_data or {}).items():
        if not isinstance(data, dict):
            continue
        placed = data.get("placed", 0)
        # v3.11.3 part 2 (2026-05-30) — prefer fill_rate_closed (excludes
        # open-GTC orders) so "limits too tight" alert isn't a false
        # positive for GTC setups that simply sit waiting for the market.
        # Fall back to legacy fill_rate for old data. From LLM proposal
        # 2026-05-29.
        rate = data.get("fill_rate_closed")
        if rate is None:
            rate = data.get("fill_rate", 1.0)
        canceled = data.get("canceled", 0)
        # If all orders are still open (closed_total = 0), do NOT alert —
        # we have no closed-rate signal yet.
        closed_total = (
            data.get("filled", 0) + canceled
            + data.get("expired", 0) + data.get("rejected", 0)
        )
        if placed >= min_placed and closed_total >= 1 and rate < threshold:
            open_pending = data.get("open_pending", data.get("other", 0))
            alerts.append({
                "strategy":  strategy,
                "fill_rate": rate,
                "placed":    placed,
                "filled":    data.get("filled", 0),
                "canceled":  canceled,
                "open_pending": open_pending,
                "alert": (
                    f"fill rate {rate:.0%} below {threshold:.0%} on closed orders "
                    f"({canceled} canceled / {placed - open_pending} closed, "
                    f"{open_pending} open-GTC ignored) — limits too tight or quote stale"
                ),
            })
    return sorted(alerts, key=lambda x: x["fill_rate"])  # worst first


def heuristic_options_chronic_fill(fill_rate_data: dict,
                                     min_consecutive_sessions: int = 2) -> tuple:
    """
    Flag chronic (multi-session) options-momentum fill deficit.

    Implementation of LLM proposal 2026-05-09 #5: distinct from the
    single-day `heuristic_options_limit_too_tight` because chronic
    multi-day deficit means our cost model is wrong, not just a quiet
    market. Without persistent state we can only detect it within the
    24h window, but we tag the alert so weekly_retro can stitch
    multiple days together.

    Returns (alert, reason). Note: cannot determine "consecutive
    sessions" from a single-day stats dict — caller can extend with
    state.json `chronic_fill_deficit_streak` field if desired.
    """
    opts = (fill_rate_data or {}).get("options-momentum", {})
    placed = opts.get("placed", 0)
    rate = opts.get("fill_rate", 1.0)
    if placed >= 5 and rate < 0.50:
        return True, (
            f"options-momentum fill_rate {rate:.0%} on {placed} placed "
            f"— suggests chronic limit-pricing miscalibration (consider "
            f"pricing at midpoint+5% instead of close*1.05)"
        )
    return False, ""


# ─── SPY-overbought regime gate for options-momentum (Lane 2 PR #4, 2026-05-14) ─
def heuristic_spy_overbought_options_block(today_stats: dict) -> tuple[bool, str]:
    """
    Block options-momentum re-enable when SPY RSI > 75 (overbought regime).

    Codifies the 2026-05-13 daily-learning Senior PM rationale: $3,120
    loss happened in SPY RSI 82+ regime; auto-resume under same conditions
    would repeat the mistake. Heuristic is read from today_stats which is
    populated by compute_rsi_snapshot().

    Returns (block, reason). Caller (apply_heuristics) extends pause when
    block is True.
    """
    spy_rsi = (today_stats or {}).get("rsi_snapshot", {}).get("SPY", {}).get("today")
    if spy_rsi is not None and spy_rsi > 75:
        return True, f"SPY RSI {spy_rsi:.1f} > 75 — overbought regime, options-momentum pause extended"
    return False, ""


# ─── Stale-exit-emergency detector (Lane 2 PR #3, 2026-05-09) ────────────────
def heuristic_stale_exit_emergency(fill_stats: dict) -> tuple[bool, str]:
    """
    Flag when exit-emergency orders are placed but never fill or cancel.

    Realised problem 2026-05-13/14: QQQ260518P00714000 had 4 attempted
    closes that all returned errors (paper API buying-power bug), the
    standing LIMIT @$5.80 sat unfilled, and no auto-cancellation fired.
    Detector: if `exit-emergency.placed >= 2` and both `filled == 0` AND
    `canceled == 0`, surface in rationale so operator runs the
    cancel-stale-emergency-orders workflow.
    """
    fe = (fill_stats or {}).get("exit-emergency", {})
    placed = fe.get("placed", 0)
    filled = fe.get("filled", 0)
    canceled = fe.get("canceled", 0)
    if placed >= 2 and filled == 0 and canceled == 0:
        return True, (
            f"exit-emergency: {placed} placed / 0 filled / 0 canceled "
            "— stale LIMIT orders suspected; run cancel-stale-emergency-orders workflow"
        )
    return False, ""


# ─── Lane2 auto-added — Crypto oversold bounce boost — ETH RSI ≤ 30 + BTC RSI ≤ 45 ────────────
def heuristic_crypto_oversold_boost(today_stats: dict) -> tuple:
    """Boost crypto-momentum size_multiplier when ETH deeply oversold and BTC approaching oversold.

    Args:
        today_stats: full today_stats dict (rsi_snapshot is top-level key).
    Returns:
        (fired: bool, multiplier: float, reason: str)
    """
    rsi = today_stats.get("rsi_snapshot", {})
    eth_rsi = rsi.get("ETH/USD", {}).get("today", 50.0)
    btc_rsi = rsi.get("BTC/USD", {}).get("today", 50.0)
    if eth_rsi <= 30.0 and btc_rsi <= 45.0:
        return True, 1.3, "ETH RSI {:.1f} <=30 + BTC RSI {:.1f} <=45: oversold bounce setup".format(eth_rsi, btc_rsi)
    return False, 1.0, ""


# ─── Lane2 auto-added — Deep oversold crypto amplifier: ETH ≤ 25 → boost crypto-momentum to 1.5x (vs 1.3x at ≤ 30) ────────────
def heuristic_crypto_deep_oversold_boost(today_stats: dict) -> tuple:
    """Amplify crypto-momentum size_multiplier to 1.5x when ETH RSI <= 25 (deep capitulation).
    Complements heuristic_crypto_oversold_boost (<=30 -> 1.3x); this overrides upward for deeper signal.
    Wire AFTER heuristic_crypto_oversold_boost in adapt_strategy so the deeper threshold wins.
    """
    rsi = today_stats.get("rsi_snapshot", {})
    eth_rsi = rsi.get("ETH/USD", {}).get("today", 50)
    btc_rsi = rsi.get("BTC/USD", {}).get("today", 50)
    if eth_rsi <= 25 and btc_rsi <= 45:
        return True, 1.5, f"ETH RSI {eth_rsi:.1f} <= 25 (deep capitulation) + BTC RSI {btc_rsi:.1f} <= 45"
    return False, 1.0, ""


# ─── Lane2 auto-added — Set options_side_bias from SPY RSI when trade sample is thin ────────────
def heuristic_options_bias_from_spy_rsi(today_stats):
    """Derive options side_bias from SPY RSI when trade data is thin.

    Returns (bias, reason) where bias is 'short', 'long', or None.
    Prevents adapter from losing directional conviction after holiday/silent periods
    when trade-based data resets to zero but macro signal is clear.
    """
    rsi_snapshot = today_stats.get("rsi_snapshot", {})
    spy_info = rsi_snapshot.get("SPY", {})
    spy_rsi = spy_info.get("today")
    if spy_rsi is None:
        return None, "no SPY RSI data available"
    if spy_rsi >= 72:
        return "short", "SPY RSI={} >= 72 -- extended market; PUT-side statistically favored".format(spy_rsi)
    if spy_rsi <= 35:
        return "long", "SPY RSI={} <= 35 -- oversold market; CALL-side statistically favored".format(spy_rsi)
    return None, "SPY RSI={} -- neutral zone; no directional override".format(spy_rsi)

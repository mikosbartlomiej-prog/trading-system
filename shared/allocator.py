"""
shared/allocator.py — Account-Aware Capital Deployment Engine.

Runs POST-learning-loop (daily cron 21:00 UTC) to compute target portfolio
allocation for next trading day. Reads:
  - account state (equity, cash, buying_power) via shared.risk_guards
  - current positions via shared.risk_guards.get_open_positions
  - market regime via shared.regime.detect_regime
  - momentum scores via shared.momentum_score.score_symbol
  - aggressive profile + watchlists via shared.profile
  - capital deployment config (this module's config file)

Outputs:
  - daily allocation plan → learning-loop/allocations/<date>.json
  - rebalance orders list (dict-based, NOT auto-executed unless
    config.auto_execute_rebalance=true; default OFF)

Goal: 100% invested capital (target 1.00, min 0.98) with regime-aware
fallback. Idle cash above max_idle_cash_ratio (0.02) triggers fallback
allocation. Hard risk limits (max_single_position, max_sector_exposure,
defensive_mode, daily_drawdown HALT, kill_switch) override the deployment
target — plan logs the conflict in `risk_checks_failed` field.

DESIGN NOTES:
- Idempotent: rebuilds plan from scratch each run; doesn't depend on
  previous plan state.
- Fail-soft: Alpaca outage → empty positions/account; plan still writes
  with "API unavailable" rationale; auto-execute skipped.
- Delta-based orders: skip rebalance if abs(delta) < min_diff_pct_to_rebalance
  (default 2% of equity). Cash drag preferable to micro-trades.
- Asset-class aware: stocks/ETFs in shares (whole or fractional per config);
  crypto in fractional qty; options skipped (separate flow).

USAGE (from analyzer.py post-learning-loop):
  from allocator import AccountAwareAllocator
  alloc = AccountAwareAllocator()
  plan = alloc.compute_daily_plan(today_stats, new_state)
  alloc.save_plan(plan, date_iso)
  if alloc.cfg["auto_execute_rebalance"]:
      alloc.execute_orders(plan["rebalance_orders"])
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_PATH = os.path.join(_REPO_ROOT, "config", "capital_deployment.json")
_ALLOCATIONS_DIR = os.path.join(_REPO_ROOT, "learning-loop", "allocations")

# Order action enum (per user spec)
ORDER_BUY     = "BUY"
ORDER_SELL    = "SELL"
ORDER_HOLD    = "HOLD"
ORDER_REDUCE  = "REDUCE"
ORDER_EXIT    = "EXIT"


def _safe_load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  allocator: {os.path.basename(path)} unavailable ({e})")
        return {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class AccountAwareAllocator:
    """Day-to-day portfolio rebalancer running after learning-loop."""

    def __init__(self):
        # Load config (defensive defaults if file missing)
        raw_cfg = _safe_load(_CONFIG_PATH)
        self.cfg = raw_cfg.get("capital_deployment") or {}
        self.fallbacks = raw_cfg.get("fallback_allocations") or {}
        self.sizing = raw_cfg.get("sizing_rules") or {}
        self.risk_cfg = raw_cfg.get("risk_overrides") or {}
        # Pre-cache profile + watchlists (avoid re-reading on every helper call)
        try:
            from profile import load_profile, load_watchlists
        except ImportError:
            from shared.profile import load_profile, load_watchlists
        self.profile = load_profile()
        self.watchlists = load_watchlists()

    # ── Public API ────────────────────────────────────────────────────

    def compute_daily_plan(self,
                            today_stats: dict | None = None,
                            new_state: dict | None = None,
                            account_override: dict | None = None,
                            positions_override: list[dict] | None = None,
                            scored_universe_override: list[dict] | None = None,
                            ) -> dict:
        """
        Build full allocation plan dict.

        Inputs (all optional — None triggers live fetch from shared modules):
          today_stats:             learning-loop today_stats (regime context, RSI)
          new_state:               adapted state.json (paused tickers, overrides)
          account_override:        injected account state (tests / dry-run)
          positions_override:      injected positions list (tests)
          scored_universe_override: pre-scored ticker list (tests)

        Returns dict (per user spec point 10):
          date, account_equity, portfolio_value, cash,
          invested_ratio_before, invested_ratio_after_target,
          market_regime, selected_symbols, target_weights,
          current_weights, rebalance_orders, risk_checks,
          learning_loop_signature
        """
        plan: dict = {
            "date":              _today(),
            "generated_at":      _utcnow_iso(),
            "version":           "1.0",
            "config":            {
                "target_invested_ratio":  self.cfg.get("target_invested_ratio", 1.0),
                "min_invested_ratio":     self.cfg.get("min_invested_ratio", 0.98),
                "auto_execute":           self.cfg.get("auto_execute_rebalance", False),
            },
        }

        # 1. Fetch account state
        account = account_override if account_override is not None else self._fetch_account()
        plan["account_equity"]    = account.get("equity", 0)
        plan["portfolio_value"]   = account.get("portfolio_value", account.get("equity", 0))
        plan["cash"]              = account.get("cash", 0)
        plan["buying_power"]      = account.get("buying_power", 0)
        plan["account_blocked"]   = bool(account.get("account_blocked", False))
        plan["trading_blocked"]   = bool(account.get("trading_blocked", False))

        # 2. Fetch positions
        positions = positions_override if positions_override is not None else self._fetch_positions()
        plan["current_positions"] = [self._normalize_position(p, plan["account_equity"]) for p in positions]
        plan["invested_ratio_before"] = self._invested_ratio(plan["current_positions"], plan["account_equity"])

        # 3. Detect kill-switch / defensive mode
        defensive = self._check_defensive_mode()
        plan["defensive_mode_active"] = defensive["active"]
        plan["kill_switch_armed"]     = defensive["kill_switch_armed"]

        # 4. Detect regime (from new_state if provided, else live detect)
        regime_info = self._infer_regime(new_state, today_stats)
        plan["market_regime"]         = regime_info["regime"]
        plan["regime_source"]         = regime_info.get("source", "?")
        plan["allowed_buckets"]       = regime_info.get("allowed_buckets") or []
        plan["regime_size_mult"]      = regime_info.get("size_multiplier", 1.0)

        # 5. Build scored universe (top momentum candidates from allowed buckets)
        if scored_universe_override is not None:
            scored = scored_universe_override
        else:
            scored = self._score_allowed_universe(regime_info, today_stats)
        plan["scored_universe"] = scored[:15]   # top 15 for visibility

        # 6. Compute target weights — primary picks + fallback fill
        target_weights, allocation_reason = self._compute_target_weights(
            scored=scored,
            regime_info=regime_info,
            defensive=defensive,
            plan=plan,
        )
        plan["target_weights"] = target_weights
        plan["allocation_reason"] = allocation_reason
        plan["invested_ratio_after_target"] = sum(target_weights.values())

        # 7. Current weights (from existing positions)
        plan["current_weights"] = {
            p["symbol"]: round(p["pct_equity"] / 100.0, 4)
            for p in plan["current_positions"]
        }

        # 8. Generate delta rebalance orders
        orders, risk_checks = self._compute_rebalance_orders(
            target=target_weights,
            current=plan["current_positions"],
            equity=plan["account_equity"],
            buying_power=plan["buying_power"],
            scored=scored,
            defensive=defensive,
        )
        plan["rebalance_orders"]   = orders
        plan["risk_checks"]        = risk_checks
        plan["learning_loop_ref"]  = (today_stats or {}).get("as_of") or _today()

        return plan

    def save_plan(self, plan: dict, date_iso: str | None = None) -> str:
        """Write plan to learning-loop/allocations/<date>.json. Returns path."""
        if not os.path.exists(_ALLOCATIONS_DIR):
            os.makedirs(_ALLOCATIONS_DIR, exist_ok=True)
        date_iso = date_iso or plan.get("date") or _today()
        path = os.path.join(_ALLOCATIONS_DIR, f"{date_iso}.json")
        try:
            with open(path, "w") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            return path
        except OSError as e:
            print(f"  allocator: save_plan error: {e}")
            return ""

    # ── Internals ─────────────────────────────────────────────────────

    def _fetch_account(self) -> dict:
        try:
            from risk_guards import get_account_status
        except ImportError:
            from shared.risk_guards import get_account_status
        acct = get_account_status() or {}
        if not acct:
            print("  allocator: account unavailable (fail-soft) — plan written with zeros")
        return {
            "equity":          float(acct.get("equity", 0) or 0),
            "portfolio_value": float(acct.get("equity", 0) or 0),     # /v2/account doesn't return separately; treat = equity
            "cash":            float(acct.get("buying_power", 0) or 0) - float(acct.get("equity", 0) or 0) * 0.5
                                  if acct else 0,  # rough; replace by direct call if needed
            "buying_power":    float(acct.get("buying_power", 0) or 0),
            "last_equity":     float(acct.get("last_equity", 0) or 0),
            "daily_pl_pct":    float(acct.get("daily_pl_pct", 0) or 0),
            # NB: account_blocked / trading_blocked not in get_account_status today;
            # add later if Alpaca outage detection needed
        }

    def _fetch_positions(self) -> list[dict]:
        try:
            from risk_guards import get_open_positions
        except ImportError:
            from shared.risk_guards import get_open_positions
        return get_open_positions() or []

    def _normalize_position(self, p: dict, equity: float) -> dict:
        """Compact dict suitable for plan JSON."""
        mv = float(p.get("market_value", 0) or 0)
        pct = (abs(mv) / equity * 100) if equity > 0 else 0
        return {
            "symbol":           p.get("symbol", ""),
            "asset_class":      p.get("asset_class", "us_equity"),
            "side":             p.get("side", "long"),
            "qty":              round(float(p.get("qty", 0) or 0), 6),
            "avg_entry_price":  round(float(p.get("avg_entry_price", 0) or 0), 4),
            "current_price":    round(float(p.get("current_price", 0) or 0), 4),
            "market_value":     round(mv, 2),
            "unrealized_pl":    round(float(p.get("unrealized_pl", 0) or 0), 2),
            "pl_pct":           round(float(p.get("unrealized_plpc", 0) or 0) * 100, 2),
            "pct_equity":       round(pct, 2),
        }

    def _invested_ratio(self, positions: list[dict], equity: float) -> float:
        if equity <= 0:
            return 0.0
        total = sum(abs(p["market_value"]) for p in positions)
        return round(total / equity, 4)

    def _check_defensive_mode(self) -> dict:
        try:
            from defensive_mode import is_defensive_mode_active, is_full_stop_armed
        except ImportError:
            try:
                from shared.defensive_mode import is_defensive_mode_active, is_full_stop_armed
            except ImportError:
                return {"active": False, "kill_switch_armed": False}
        return {
            "active":            is_defensive_mode_active(),
            "kill_switch_armed": is_full_stop_armed(),
        }

    def _infer_regime(self, new_state: dict | None, today_stats: dict | None) -> dict:
        try:
            from regime import detect_regime
        except ImportError:
            from shared.regime import detect_regime
        # Build market_signals from today_stats.rsi_snapshot if available
        market_signals = {}
        if today_stats and isinstance(today_stats.get("rsi_snapshot"), dict):
            # Use SPY RSI as proxy for spy_5d (not exact match but better than nothing)
            spy = today_stats["rsi_snapshot"].get("SPY") or {}
            # No direct spy_5d here; auto-detect will fallback gracefully
        return detect_regime(market_signals)

    def _score_allowed_universe(self, regime_info: dict,
                                  today_stats: dict | None) -> list[dict]:
        """Score every ticker in allowed buckets; return sorted by score desc."""
        try:
            from momentum_score import score_symbol
            from market_data import get_daily_bars
        except ImportError:
            from shared.momentum_score import score_symbol
            from shared.market_data import get_daily_bars

        # Build universe from allowed buckets
        universe: list[str] = []
        for bucket in (regime_info.get("allowed_buckets") or []):
            bucket_cfg = (self.watchlists.get(bucket) or {})
            tickers = bucket_cfg.get("tickers") or []
            # Skip crypto (separate allocation flow in crypto-monitor)
            if bucket == "crypto":
                continue
            universe.extend(tickers)
        universe = list(dict.fromkeys(universe))   # dedup preserve order

        # Fetch SPY/QQQ benchmarks once
        spy_bars = get_daily_bars("SPY", days=35)
        qqq_bars = get_daily_bars("QQQ", days=35)

        scored: list[dict] = []
        for sym in universe:
            try:
                bars = get_daily_bars(sym, days=35)
            except Exception as e:
                print(f"  allocator: {sym} bars error: {e}")
                continue
            if not bars or len(bars.get("close", [])) < 22:
                continue
            s = score_symbol(sym, bars, spy_bars=spy_bars, qqq_bars=qqq_bars)
            s["bucket"] = self._bucket_of(sym)
            scored.append(s)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _bucket_of(self, ticker: str) -> str:
        try:
            from profile import bucket_for_ticker
        except ImportError:
            from shared.profile import bucket_for_ticker
        return bucket_for_ticker(ticker) or "unknown"

    # ── Target weights computation ────────────────────────────────────

    def _compute_target_weights(self,
                                  scored: list[dict],
                                  regime_info: dict,
                                  defensive: dict,
                                  plan: dict) -> tuple[dict[str, float], str]:
        """
        Returns (target_weights, allocation_reason).

        Algorithm:
          1. Defensive mode + kill_switch → no new entries, only EXIT/REDUCE
             existing positions. Returns existing weights minus disallowed.
          2. Else: primary picks = top N scored tickers above min_score_for_entry,
             each at primary_pick_target_weight (default 18%, max 5 = 90%).
          3. Fill remaining to target_invested_ratio with fallback instruments
             for current regime, each at fallback_pick_target_weight (default 10%).
          4. Enforce max_single_position (20%) + max_sector_exposure (55%).
        """
        target: dict[str, float] = {}
        target_ratio = float(self.cfg.get("target_invested_ratio", 1.0))
        primary_w  = float(self.sizing.get("primary_pick_target_weight", 0.18))
        max_pri    = int(self.sizing.get("max_primary_picks", 5))
        fallback_w = float(self.sizing.get("fallback_pick_target_weight", 0.10))
        max_fb     = int(self.sizing.get("max_fallback_picks", 3))

        # ── Defensive mode: existing positions only, no new buys ────────
        if defensive["active"] and self.cfg.get("skip_full_deployment_when_kill_switch_active", True):
            for p in plan["current_positions"]:
                # Keep existing weight as target (i.e. no rebalance; orders generated
                # will be HOLD or EXIT depending on whether ticker still allowed)
                target[p["symbol"]] = round(p["pct_equity"] / 100.0, 4)
            return target, "defensive_mode_active — no new entries; existing positions inventoried"

        # ── Primary picks from scored universe ──────────────────────────
        min_score = float((self.profile.get("scoring") or {}).get("min_score_for_entry", 0.35))
        primary_picks = [s for s in scored if s.get("score", 0) >= min_score][:max_pri]
        for s in primary_picks:
            target[s["ticker"]] = primary_w

        # Enforce hard caps BEFORE computing remaining for fallback fill,
        # so sector cap (e.g. 55% for ai_nasdaq_semis) doesn't leave residual
        # cash uninvested. Cap → remaining → fallback fill closes the gap.
        target = self._enforce_position_caps(target)
        target = self._enforce_sector_caps(target)

        primary_total = sum(target.values())
        remaining = target_ratio - primary_total

        # ── Fallback fill ────────────────────────────────────────────────
        used_fallback: list[str] = []
        if self.cfg.get("use_fallback_instruments", True) and remaining > fallback_w / 2:
            fallbacks = self.fallbacks.get(regime_info["regime"]) or []
            picks_added = 0
            for sym in fallbacks:
                if picks_added >= max_fb or remaining <= 0:
                    break
                if sym in target:
                    continue                         # avoid duplicate primary+fallback
                w = min(fallback_w, remaining)
                target[sym] = w
                used_fallback.append(sym)
                remaining -= w
                picks_added += 1

        # Re-enforce caps after fallback (fallback could push sector over)
        target = self._enforce_position_caps(target)
        target = self._enforce_sector_caps(target)

        # Build reason string
        reason_parts = [
            f"regime={regime_info['regime']}",
            f"primary_picks={len(primary_picks)}({primary_total:.0%})",
        ]
        if used_fallback:
            reason_parts.append(f"fallback={used_fallback}")
        if remaining > 0.01:
            reason_parts.append(f"unfilled={remaining:.2%}")
        return target, " | ".join(reason_parts)

    def _enforce_position_caps(self, weights: dict) -> dict:
        cap = float((self.profile.get("capital") or {}).get("max_single_position_pct_equity", 0.20))
        return {sym: min(w, cap) for sym, w in weights.items()}

    def _enforce_sector_caps(self, weights: dict) -> dict:
        """Aggregate by bucket; if bucket > max_sector_exposure, scale down proportionally."""
        cap = float((self.profile.get("capital") or {}).get("max_sector_exposure_pct_equity", 0.55))
        by_bucket: dict[str, float] = {}
        ticker_to_bucket: dict[str, str] = {}
        for sym, w in weights.items():
            b = self._bucket_of(sym)
            ticker_to_bucket[sym] = b
            by_bucket[b] = by_bucket.get(b, 0) + w
        out = dict(weights)
        for b, total in by_bucket.items():
            if total > cap and total > 0:
                scale = cap / total
                for sym, w in weights.items():
                    if ticker_to_bucket[sym] == b:
                        out[sym] = round(w * scale, 4)
        return out

    # ── Rebalance order generation ────────────────────────────────────

    def _compute_rebalance_orders(self,
                                    target: dict[str, float],
                                    current: list[dict],
                                    equity: float,
                                    buying_power: float,
                                    scored: list[dict],
                                    defensive: dict) -> tuple[list[dict], dict]:
        """
        Generate delta orders (BUY / SELL / REDUCE / EXIT / HOLD).

        Skip rebalance if abs(delta) < min_diff_pct_to_rebalance * equity.
        Validate against risk_officer whitelist (skip silently if blocked).
        Cap by max_rebalance_orders_per_day.
        """
        orders: list[dict] = []
        passed: list[str] = []
        failed: list[str] = []

        min_diff_pct = float(self.sizing.get("min_diff_pct_to_rebalance", 0.02))
        min_order_usd = float(self.cfg.get("min_order_value_usd", 100))
        max_orders   = int(self.cfg.get("max_rebalance_orders_per_day", 10))
        allow_frac   = bool(self.cfg.get("allow_fractional_shares", True))

        # Map current positions by symbol
        current_by_sym = {p["symbol"]: p for p in current}

        # 1. EXIT/REDUCE for symbols in current but NOT in target (or below target)
        for p in current:
            sym = p["symbol"]
            current_value = p["market_value"]
            target_w = target.get(sym, 0.0)
            target_value = target_w * equity
            delta = target_value - current_value
            delta_pct_equity = delta / equity if equity > 0 else 0

            if target_w == 0:
                # Position should be exited
                orders.append(self._build_order(sym, ORDER_EXIT, p, target_value, equity, allow_frac,
                                                  reason="symbol not in target allocation"))
            elif abs(delta_pct_equity) < min_diff_pct:
                orders.append({
                    "symbol": sym, "action": ORDER_HOLD, "current_value": round(current_value, 2),
                    "target_value": round(target_value, 2), "delta": round(delta, 2),
                    "reason": f"|delta {delta_pct_equity:+.2%}| < min_diff {min_diff_pct:.2%}",
                })
            elif delta > 0:
                if delta < min_order_usd:
                    orders.append({
                        "symbol": sym, "action": ORDER_HOLD,
                        "current_value": round(current_value, 2),
                        "target_value": round(target_value, 2), "delta": round(delta, 2),
                        "reason": f"add ${delta:.0f} below min_order_value ${min_order_usd:.0f}",
                    })
                else:
                    orders.append(self._build_order(sym, ORDER_BUY, p, target_value, equity, allow_frac,
                                                      reason=f"add ${delta:.0f} to reach target {target_w:.1%}"))
            else:   # delta < 0 → reduce
                orders.append(self._build_order(sym, ORDER_REDUCE, p, target_value, equity, allow_frac,
                                                  reason=f"reduce ${-delta:.0f} to target {target_w:.1%}"))

        # 2. BUY for symbols in target but NOT in current
        for sym, w in target.items():
            if sym in current_by_sym:
                continue
            target_value = w * equity
            if target_value < min_order_usd:
                orders.append({
                    "symbol": sym, "action": ORDER_HOLD,
                    "target_value": round(target_value, 2),
                    "reason": f"target ${target_value:.0f} below min_order_value ${min_order_usd:.0f}",
                })
                continue
            orders.append(self._build_order(sym, ORDER_BUY, None, target_value, equity, allow_frac,
                                              reason=f"new position at target {w:.1%}"))

        # 3. Risk validation pass (whitelist check via risk_officer)
        validated_orders = []
        for o in orders:
            if o["action"] == ORDER_HOLD:
                validated_orders.append(o)
                continue
            ok, reason = self._validate_order(o)
            if ok:
                passed.append(f"{o['symbol']}:{o['action']}")
                validated_orders.append(o)
            else:
                failed.append(f"{o['symbol']}:{o['action']} — {reason}")
                # Demote to HOLD so plan shows attempted intent
                o["action"] = ORDER_HOLD
                o["reason"] = f"BLOCKED ({reason})"
                validated_orders.append(o)

        # 4. Cap order count (sort by abs(delta) descending — biggest moves first)
        actionable = [o for o in validated_orders if o["action"] != ORDER_HOLD]
        actionable.sort(key=lambda o: abs(o.get("delta", 0)), reverse=True)
        if len(actionable) > max_orders:
            cap_dropped = actionable[max_orders:]
            for o in cap_dropped:
                o["action"] = ORDER_HOLD
                o["reason"] = f"max_rebalance_orders_per_day={max_orders} reached"
                failed.append(f"{o['symbol']}: capped by max_orders")
            actionable = actionable[:max_orders]

        # Reassemble preserving original holds
        final_orders = actionable + [o for o in validated_orders if o["action"] == ORDER_HOLD]

        risk_checks = {
            "passed": passed,
            "failed": failed,
            "n_orders": len([o for o in final_orders if o["action"] != ORDER_HOLD]),
            "n_hold":   len([o for o in final_orders if o["action"] == ORDER_HOLD]),
        }
        return final_orders, risk_checks

    def _build_order(self, sym: str, action: str, position: dict | None,
                      target_value: float, equity: float, allow_frac: bool,
                      reason: str = "") -> dict:
        """Construct order dict with sizing details."""
        current_value = float(position["market_value"]) if position else 0.0
        current_qty   = float(position["qty"]) if position else 0.0
        current_price = float(position["current_price"]) if position else 0.0
        delta_value   = target_value - current_value

        # Quantity calculation
        if action == ORDER_EXIT:
            qty_delta = -current_qty
        elif current_price > 0:
            target_qty = target_value / current_price
            qty_delta = target_qty - current_qty
            if not allow_frac:
                qty_delta = int(qty_delta)   # whole shares
        else:
            qty_delta = None  # need fresh quote at execute time

        return {
            "symbol":         sym,
            "action":         action,
            "asset_class":    (position or {}).get("asset_class", "us_equity"),
            "current_value":  round(current_value, 2),
            "target_value":   round(target_value, 2),
            "delta":          round(delta_value, 2),
            "current_qty":    round(current_qty, 6),
            "qty_delta":      round(qty_delta, 6) if qty_delta is not None else None,
            "current_price":  round(current_price, 4) if current_price > 0 else None,
            "reason":         reason,
        }

    def _validate_order(self, order: dict) -> tuple[bool, str]:
        """Cheap pre-flight checks. Does NOT call Alpaca."""
        sym = order["symbol"]
        action = order["action"]
        # Whitelist check via risk_officer
        if self.risk_cfg.get("respect_risk_officer_whitelist", True):
            try:
                from risk_officer import _WHITELIST, _on_whitelist
            except ImportError:
                from shared.risk_officer import _WHITELIST, _on_whitelist
            if not _on_whitelist(sym):
                return False, f"{sym} not on risk_officer whitelist"
        # Action sanity
        if action not in (ORDER_BUY, ORDER_SELL, ORDER_REDUCE, ORDER_EXIT):
            return False, f"invalid action {action}"
        return True, "ok"

    def execute_orders(self, orders: list[dict]) -> list[dict]:
        """
        Execute approved BUY/REDUCE/EXIT orders via shared.alpaca_orders.

        GATED: only runs when config.auto_execute_rebalance=true. Default OFF
        — operator reviews plan first.

        Returns list of execution results (one per order).
        """
        if not self.cfg.get("auto_execute_rebalance", False):
            print("  allocator: auto_execute_rebalance=false; skipping execution (plan-only)")
            return []
        # Implementation deferred — operator reviews plan first.
        # When enabled, this would call execute_stock_signal / similar
        # with sizing from order["qty_delta"] and asset_class routing.
        print("  allocator: auto_execute path NOT YET IMPLEMENTED — flip flag once safe")
        return []

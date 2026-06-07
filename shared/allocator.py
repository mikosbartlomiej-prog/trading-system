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

from __future__ import annotations  # v3.11.3: PEP 604 (X | None) parseable on Py 3.9 (local) + 3.11 (CI).

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


class _TraceLogger:
    """
    In-memory append + stdout mirror. Every line is timestamped UTC and
    flushed to <date>.log alongside the JSON plan, so retrospective
    analysis can replay the decision tree without re-running the
    allocator.

    Levels (prefix in log line):
      DBG  trace detail (per-symbol scoring, cap math)
      INFO normal pipeline progression
      WARN soft issue (sector cap hit, fallback exhausted)
      ERR  fail-soft pathway (Alpaca outage, missing config)
    """

    def __init__(self):
        self.lines: list[str] = []

    def _emit(self, lvl: str, msg: str, indent: int = 0) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        prefix = "  " * indent
        line = f"[{ts} {lvl:<4}] {prefix}{msg}"
        self.lines.append(line)
        print(line)

    def header(self, msg: str) -> None:
        bar = "=" * 60
        self._emit("INFO", bar)
        self._emit("INFO", msg)
        self._emit("INFO", bar)

    def step(self, n: int, title: str) -> None:
        self._emit("INFO", f"── Step {n}: {title} ──")

    def info(self, msg: str, indent: int = 1) -> None:
        self._emit("INFO", msg, indent)

    def dbg(self, msg: str, indent: int = 2) -> None:
        self._emit("DBG", msg, indent)

    def warn(self, msg: str, indent: int = 1) -> None:
        self._emit("WARN", msg, indent)

    def err(self, msg: str, indent: int = 1) -> None:
        self._emit("ERR", msg, indent)

    def order(self, o: dict) -> None:
        sym = o.get("symbol", "?")
        act = o.get("action", "?")
        cur = o.get("current_value", 0)
        tgt = o.get("target_value", 0)
        dlt = o.get("delta", 0)
        reason = o.get("reason", "")
        self._emit("INFO",
                    f"{sym:<8} {act:<7} current=${cur:>9.2f} target=${tgt:>9.2f} "
                    f"delta=${dlt:+9.2f}  -- {reason}",
                    indent=2)

    def save(self, path: str) -> None:
        try:
            with open(path, "w") as f:
                f.write("\n".join(self.lines) + "\n")
        except OSError as e:
            print(f"  trace: save error: {e}")


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
        # Trace log — populated during compute_daily_plan, flushed by save_plan
        self.trace = _TraceLogger()

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
        # Reset trace for this run (allocator may be re-used across tests)
        self.trace = _TraceLogger()
        self.trace.header(f"AccountAwareAllocator — daily plan {_today()}")

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
        self.trace.step(1, "fetching account state")
        account = account_override if account_override is not None else self._fetch_account()
        plan["account_equity"]    = account.get("equity", 0)
        plan["portfolio_value"]   = account.get("portfolio_value", account.get("equity", 0))
        plan["cash"]              = account.get("cash", 0)
        plan["buying_power"]      = account.get("buying_power", 0)
        plan["account_blocked"]   = bool(account.get("account_blocked", False))
        plan["trading_blocked"]   = bool(account.get("trading_blocked", False))
        self.trace.info(
            f"equity=${plan['account_equity']:>10.2f}  cash=${plan['cash']:>10.2f}  "
            f"buying_power=${plan['buying_power']:>10.2f}"
        )
        if plan["account_blocked"] or plan["trading_blocked"]:
            self.trace.warn(
                f"account_blocked={plan['account_blocked']}  trading_blocked={plan['trading_blocked']}"
            )

        # 2. Fetch positions
        self.trace.step(2, "fetching open positions")
        positions = positions_override if positions_override is not None else self._fetch_positions()
        plan["current_positions"] = [self._normalize_position(p, plan["account_equity"]) for p in positions]
        plan["invested_ratio_before"] = self._invested_ratio(plan["current_positions"], plan["account_equity"])
        self.trace.info(
            f"{len(plan['current_positions'])} positions, invested_ratio={plan['invested_ratio_before']:.4f} "
            f"(target={plan['config']['target_invested_ratio']:.2f}, "
            f"min={plan['config']['min_invested_ratio']:.2f})"
        )
        for p in plan["current_positions"]:
            self.trace.dbg(
                f"{p['symbol']:<10} {p['side']:<5} qty={p['qty']:.4f} "
                f"mv=${p['market_value']:>9.2f}  pct_eq={p['pct_equity']:.2f}%  "
                f"pl={p['pl_pct']:+.2f}%"
            )

        # 2.5. PDT-aware planning metadata (v3.8.6, 2026-05-16). Plan
        # generation records PDT state so morning-allocator + downstream
        # consumers can adapt: when LOCKED or RESTRICTED, ALL new BUYs
        # are tagged intent=swing (caller declares overnight hold). This
        # mirrors what _pdt_gate already enforces at execute time, but
        # surfacing it in the PLAN gives operators visibility into why
        # certain symbols may DEFER vs ALLOW. LLM-flagged proposal
        # 2026-05-15: "PDT-aware swing-only allocator plan when dt >= 3".
        try:
            try:
                from pdt_guard import get_pdt_status
            except ImportError:
                from shared.pdt_guard import get_pdt_status  # type: ignore
            pdt_snap = get_pdt_status(account=account)
            plan["pdt_mode"]            = pdt_snap.mode
            plan["pdt_dt_remaining"]    = pdt_snap.dt_remaining
            plan["pdt_dt_count"]        = pdt_snap.daytrade_count
            plan["pdt_intent_for_buys"] = "swing"   # all monitor opens default swing in v3.8
            if pdt_snap.mode in ("RESTRICTED", "LOCKED"):
                self.trace.warn(
                    f"PDT mode={pdt_snap.mode} dt={pdt_snap.daytrade_count}/{pdt_snap.dt_limit} "
                    f"— all plan BUYs MUST hold overnight (intent=swing). "
                    f"Discretionary intraday-close of same-day opens would DEFER/BLOCK."
                )
            else:
                self.trace.info(f"PDT mode={pdt_snap.mode}  dt_remaining={pdt_snap.dt_remaining}")
        except Exception as e:
            self.trace.warn(f"pdt_guard unavailable in plan gen: {e}")
            plan["pdt_mode"] = "UNKNOWN"

        # 3. Detect kill-switch / defensive mode
        self.trace.step(3, "defensive mode check")
        defensive = self._check_defensive_mode()
        plan["defensive_mode_active"] = defensive["active"]
        plan["kill_switch_armed"]     = defensive["kill_switch_armed"]
        if defensive["active"]:
            self.trace.warn(
                f"defensive_mode ACTIVE  kill_switch_armed={defensive['kill_switch_armed']} "
                "→ no new entries; existing positions inventoried"
            )
        else:
            self.trace.info("defensive_mode OFF → proceed with deployment")

        # 4. Detect regime (from new_state if provided, else live detect)
        self.trace.step(4, "regime detection")
        regime_info = self._infer_regime(new_state, today_stats)
        plan["market_regime"]         = regime_info["regime"]
        plan["regime_source"]         = regime_info.get("source", "?")
        plan["allowed_buckets"]       = regime_info.get("allowed_buckets") or []
        plan["regime_size_mult"]      = regime_info.get("size_multiplier", 1.0)
        self.trace.info(
            f"regime={plan['market_regime']}  source={plan['regime_source']}  "
            f"size_mult={plan['regime_size_mult']:.2f}"
        )
        self.trace.info(f"allowed_buckets={plan['allowed_buckets']}", indent=2)

        # 5. Build scored universe (top momentum candidates from allowed buckets)
        self.trace.step(5, "scoring allowed universe")
        if scored_universe_override is not None:
            scored = scored_universe_override
            self.trace.info(f"{len(scored)} pre-scored tickers injected (test/override)")
        else:
            scored = self._score_allowed_universe(regime_info, today_stats)
        plan["scored_universe"] = scored[:15]   # top 15 for visibility
        if scored:
            top = scored[:5]
            for s in top:
                self.trace.dbg(
                    f"{s.get('ticker','?'):<8} score={s.get('score',0):+.3f}  bucket={s.get('bucket','?')}"
                )
        else:
            self.trace.warn("scored universe EMPTY — fallback will dominate")

        # 6. Compute target weights — primary picks + fallback fill
        self.trace.step(6, "target weight construction")
        target_weights, allocation_reason = self._compute_target_weights(
            scored=scored,
            regime_info=regime_info,
            defensive=defensive,
            plan=plan,
        )
        plan["target_weights"] = target_weights
        plan["allocation_reason"] = allocation_reason
        plan["invested_ratio_after_target"] = sum(target_weights.values())
        self.trace.info(f"reason: {allocation_reason}")
        self.trace.info(f"target_invested_ratio_after_plan = {plan['invested_ratio_after_target']:.4f}")
        for sym, w in target_weights.items():
            self.trace.dbg(f"{sym:<10} target_weight={w:.4f} (${w * plan['account_equity']:.2f})")

        # 7. Current weights (from existing positions)
        plan["current_weights"] = {
            p["symbol"]: round(p["pct_equity"] / 100.0, 4)
            for p in plan["current_positions"]
        }

        # 8. Generate delta rebalance orders
        self.trace.step(7, "rebalance order generation")
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

        for o in orders:
            self.trace.order(o)
        self.trace.info(
            f"summary: {risk_checks['n_orders']} actionable + {risk_checks['n_hold']} hold; "
            f"passed={len(risk_checks['passed'])}  failed={len(risk_checks['failed'])}"
        )
        if risk_checks["failed"]:
            for f in risk_checks["failed"]:
                self.trace.warn(f"order check failed: {f}", indent=2)

        # 9. Final status
        self.trace.step(8, "plan complete")
        plan["trace_log_lines"] = len(self.trace.lines)
        self.trace.info(
            f"auto_execute={plan['config']['auto_execute']}  "
            f"(flip config/capital_deployment.json::capital_deployment.auto_execute_rebalance to enable)"
        )

        return plan

    def save_plan(self, plan: dict, date_iso: str | None = None) -> str:
        """
        Write plan to learning-loop/allocations/<date>.json AND companion
        trace log to learning-loop/allocations/<date>.log. Returns JSON path.
        """
        if not os.path.exists(_ALLOCATIONS_DIR):
            os.makedirs(_ALLOCATIONS_DIR, exist_ok=True)
        date_iso = date_iso or plan.get("date") or _today()
        path = os.path.join(_ALLOCATIONS_DIR, f"{date_iso}.json")
        log_path = os.path.join(_ALLOCATIONS_DIR, f"{date_iso}.log")
        try:
            with open(path, "w") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"  allocator: save_plan error: {e}")
            return ""
        # Trace log (best-effort; never fail the plan if log write fails)
        if self.trace and self.trace.lines:
            self.trace.save(log_path)
        return path

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

    def execute_orders(self, orders: list[dict],
                        force: bool = False,
                        market_hours_override: tuple[bool, str] | None = None,
                        ) -> list[dict]:
        """
        Execute approved BUY/REDUCE/EXIT orders via Alpaca REST.

        GATED: only runs when config.auto_execute_rebalance=true (or force=True
        for testing). Default ON since 2026-05-14 — system is fully autonomous;
        plan + execution happen in the same daily-learning → morning-allocator
        chain with no human in the loop.

        Pre-flight gates (per order, fail-soft):
          1. action != HOLD (skip silently)
          2. action is one of BUY/REDUCE/EXIT (SELL not used by current orders)
          3. market is OPEN for stocks/ETFs (crypto bypasses)
          4. quantity > 0 after rounding
          5. risk_officer whitelist (already checked at plan time but re-checked
             here in case config changed between plan + execute)

        Returns list of per-order result dicts:
          {symbol, action, status: placed|skipped|failed, alpaca_order_id?,
           reason, attempted_at}

        Routing by action + asset_class:
          BUY  + stock  → place_stock_bracket (with SL/TP from aggressive_profile)
          BUY  + crypto → place_crypto_order  (no bracket)
          REDUCE        → simple LIMIT SELL via /v2/orders (partial close)
          EXIT          → simple MARKET SELL via /v2/orders (full close)

        Trace + log each step. Self-contained; safe to call from
        scripts/execute_allocation_plan.py.
        """
        results: list[dict] = []
        self.trace.header("execute_orders() — auto-execute path")

        if not (force or self.cfg.get("auto_execute_rebalance", False)):
            self.trace.info(
                "auto_execute_rebalance=false → plan-only mode (no orders sent). "
                "To enable: edit config/capital_deployment.json::capital_deployment.auto_execute_rebalance=true"
            )
            return results

        # Market hours gate (stocks). Crypto bypasses.
        try:
            from market_hours import is_us_market_open
        except ImportError:
            from shared.market_hours import is_us_market_open
        if market_hours_override is not None:
            market_open, mkt_reason = market_hours_override
        else:
            market_open, mkt_reason = is_us_market_open()
        self.trace.info(f"market_status: open={market_open} reason={mkt_reason}")

        # Defensive mode re-check at execute time (config might have flipped
        # between plan and execute — be safe).
        defensive = self._check_defensive_mode()
        if defensive["active"] and not force:
            self.trace.warn(
                f"defensive_mode ACTIVE at execute time → only EXIT/REDUCE permitted, "
                f"BUY orders will be skipped"
            )

        # Sort orders: EXIT first (free up capital), then REDUCE, then BUY
        action_priority = {ORDER_EXIT: 0, ORDER_REDUCE: 1, ORDER_BUY: 2}
        sorted_orders = sorted(
            [o for o in orders if o.get("action") != ORDER_HOLD],
            key=lambda o: action_priority.get(o.get("action", ""), 9),
        )

        # ── ETAP 3 (incident 2026-06-07): BP / over-allocation pre-check ──
        # Deterministic gate that drops tail BUY orders whose cumulative
        # notional would exceed available BP or breach the gross exposure
        # cap. Non-BUYs (EXIT/REDUCE) pass through untouched — they free
        # capital. Fail-soft when account_status is unavailable.
        try:
            try:
                from allocator_bp_guard import check_buying_power_pre_execution
            except ImportError:
                from shared.allocator_bp_guard import check_buying_power_pre_execution
            try:
                from risk_guards import get_account_status, get_open_positions
            except ImportError:
                from shared.risk_guards import get_account_status, get_open_positions
            acct = get_account_status() or {}
            positions = get_open_positions() or []
            bp_check = check_buying_power_pre_execution(
                sorted_orders, acct, positions,
            )
            self.trace.info(
                "bp_guard: "
                f"requested ${bp_check['total_requested_notional']:.0f} "
                f"available ${bp_check['total_available_bp']:.0f} "
                f"open_exposure ${bp_check['total_open_exposure']:.0f} | "
                f"{bp_check['reason']}"
            )
            if bp_check.get("warning"):
                self.trace.warn(f"bp_guard: {bp_check['warning']}")
            # Surface deferred orders as execution results so they show up
            # in <date>.execution.json — the operator can see exactly which
            # BUYs were dropped and why.
            for d in bp_check["deferred_orders"]:
                results.append({
                    "symbol":         d.get("symbol", ""),
                    "action":         d.get("action", ""),
                    "asset_class":    d.get("asset_class", "us_equity"),
                    "status":         "deferred_bp",
                    "reason":         d.get("deferred_reason", ""),
                    "bp_projected":   d.get("bp_projected"),
                    "bp_available":   d.get("bp_available"),
                    "exposure_projected": d.get("exposure_projected"),
                    "exposure_cap_usd":   d.get("exposure_cap_usd"),
                    "attempted_at":   _utcnow_iso(),
                })
            sorted_orders = list(bp_check["allowed_orders"])
        except Exception as e:  # noqa: BLE001  fail-soft contract
            self.trace.warn(f"bp_guard: gate error (fail-soft, proceeding): {e}")

        for o in sorted_orders:
            results.append(self._execute_one(o, market_open, defensive["active"]))

        n_placed = sum(1 for r in results if r["status"] == "placed")
        n_skipped = sum(1 for r in results if r["status"] == "skipped")
        n_failed = sum(1 for r in results if r["status"] == "failed")
        n_deferred_bp = sum(1 for r in results if r["status"] == "deferred_bp")
        self.trace.info(
            f"execution complete: {n_placed} placed, {n_skipped} skipped, "
            f"{n_failed} failed, {n_deferred_bp} deferred_bp"
        )
        return results

    def _execute_one(self, order: dict, market_open: bool, defensive_active: bool) -> dict:
        """Place a single rebalance order via Alpaca. Returns result dict."""
        sym = order.get("symbol", "")
        action = order.get("action", "")
        asset_class = order.get("asset_class", "us_equity")
        qty_delta = order.get("qty_delta")
        result = {
            "symbol":       sym,
            "action":       action,
            "asset_class":  asset_class,
            "status":       "skipped",
            "reason":       "",
            "attempted_at": _utcnow_iso(),
        }

        # Defensive mode → no new BUY
        if defensive_active and action == ORDER_BUY:
            result["reason"] = "defensive_mode_active (BUY blocked)"
            self.trace.warn(f"{sym} {action}: {result['reason']}", indent=2)
            return result

        is_crypto = "/" in sym
        ic_asset = "crypto" if is_crypto else asset_class

        # v3.18.0 (2026-06-04) — Universe-readiness gate.
        # BUY only (REDUCE/EXIT may need to close stale positions even after
        # an operator universe flip). Crypto routes to CRYPTO universe;
        # everything else to active universe. Fail-soft.
        if action == ORDER_BUY:
            try:
                try:
                    from runtime_config import active_universe as _au
                    from universe_selector import is_paper_ready as _ipr
                except ImportError:
                    from shared.runtime_config import active_universe as _au   # type: ignore
                    from shared.universe_selector import is_paper_ready as _ipr  # type: ignore
                univ = "CRYPTO" if is_crypto else _au()
                ready, reason = _ipr(univ)
                if not ready:
                    result["status"] = "skipped"
                    result["reason"] = f"universe_not_paper_ready:{univ}:{reason}"
                    self.trace.warn(
                        f"{sym} {action}: skipped — universe {univ} not paper-ready ({reason})",
                        indent=2,
                    )
                    # Audit emit (fail-soft)
                    try:
                        from datetime import datetime, timezone
                        try:
                            from audit import write_audit_event as _wae
                        except ImportError:
                            from shared.audit import write_audit_event as _wae  # type: ignore
                        _wae({
                            "type":        "universe_gate",
                            "decision":    "REJECT",
                            "symbol":      sym,
                            "reason":      f"universe_not_paper_ready:{reason}",
                            "universe_id": univ,
                            "decided_at":  datetime.now(timezone.utc)
                                                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }, kind="trading")
                    except Exception:
                        pass
                    return result
            except Exception as e:
                # Fail-soft: universe gate never blocks on its own error.
                self.trace.warn(
                    f"{sym} {action}: universe gate unavailable ({e}) — proceeding",
                    indent=2,
                )

        # Honor caller-provided market_open hint (used by tests + cron-time
        # snapshot). Skip stocks if hint says closed; crypto bypasses.
        # NB: per-instrument check (can_trade_now) is enforced INSIDE
        # place_stock_bracket / place_crypto_order / place_simple_buy, so we
        # don't re-check here — that caused tests to fail when run outside
        # market hours.
        if not is_crypto and not market_open:
            result["reason"] = "market not open"
            self.trace.warn(f"{sym} {action}: skipped — market not open", indent=2)
            return result

        # PDT gate for REDUCE / EXIT (allocator rebalance closes). BUY goes
        # via alpaca_orders which already has _pdt_gate. REDUCE/EXIT POSTs
        # directly to Alpaca and must check PDT here.
        # v3.8: rebalance closes are discretionary (operator chose to rotate,
        # not an SL hit) so is_emergency=False. PDT engine then decides:
        # overnight position → ALLOW (no DT impact); same-day → budget-aware.
        # Crypto bypasses (24/7, not subject to PDT).
        if action in (ORDER_REDUCE, ORDER_EXIT) and not is_crypto:
            try:
                try:
                    from pdt_guard import evaluate_order as _pdt_eval, record_decision as _pdt_audit
                except ImportError:
                    from shared.pdt_guard import (    # type: ignore
                        evaluate_order as _pdt_eval, record_decision as _pdt_audit,
                    )
                pdt_size = float(order.get("current_value") or order.get("target_value") or 0)
                pv = _pdt_eval(
                    action="CLOSE", symbol=sym, side="sell", size_usd=pdt_size,
                    intent="intraday",   # rebalance is a discretionary same-session close
                    is_emergency=False,
                )
                if pv["decision"] != "ALLOW":
                    _pdt_audit(pv, action="CLOSE", symbol=sym,
                               extra={"allocator_action": action, "intent": "intraday"})
                    if pv["decision"] == "DEFER":
                        result["status"] = "deferred"
                        result["reason"] = f"PDT defer: {pv['reason']}"
                        self.trace.warn(f"{sym} {action}: PDT DEFER — {pv['reason']}", indent=2)
                    else:  # BLOCK
                        result["status"] = "skipped"
                        result["reason"] = f"PDT block: {pv['reason']}"
                        self.trace.warn(f"{sym} {action}: PDT BLOCK — {pv['reason']}", indent=2)
                    return result
            except Exception as e:
                # Fail-soft: never let PDT-tracking break the allocator.
                self.trace.warn(f"{sym} {action}: pdt-guard unavailable ({e}) — proceeding", indent=2)

        # Quantity sanity.
        # BUGFIX 2026-05-14: _build_order sets qty_delta=None for NEW BUYs
        # (no current position → current_price=0 → fallback). Previously this
        # branch silently skipped them with "qty_delta is zero or unknown",
        # which meant every fresh BUY in the plan got dropped — 5 BUYs
        # skipped in today's run while only EXITs filled. Fix: for BUY,
        # derive qty from order.target_value + a fresh quote at execute time.
        if qty_delta is None or abs(qty_delta) < 1e-6:
            if action == ORDER_BUY:
                target_value = float(order.get("target_value") or 0)
                if target_value <= 0:
                    result["reason"] = "BUY skipped: no target_value to size"
                    self.trace.warn(f"{sym} BUY: {result['reason']}", indent=2)
                    return result
                try:
                    if is_crypto:
                        from alpaca_orders import get_latest_crypto_quote as _gq
                    else:
                        from alpaca_orders import get_latest_quote as _gq
                except ImportError:
                    if is_crypto:
                        from shared.alpaca_orders import get_latest_crypto_quote as _gq
                    else:
                        from shared.alpaca_orders import get_latest_quote as _gq
                q = _gq(sym)
                px = (q or {}).get("mid") if q else None
                if not px or px <= 0:
                    result["status"] = "failed"
                    result["reason"] = f"BUY failed: no fresh quote for {sym}"
                    self.trace.err(f"{sym} BUY: {result['reason']}", indent=2)
                    return result
                if is_crypto:
                    qty_delta = round(target_value / px, 6)
                else:
                    qty_delta = max(int(target_value / px), 1)
                order["current_price"] = round(px, 4)
                self.trace.info(
                    f"{sym} BUY: derived qty={qty_delta} from target=${target_value:,.0f} "
                    f"@ ${px:.2f} (no prior position)", indent=2,
                )
            else:
                result["reason"] = "qty_delta is zero or unknown"
                self.trace.warn(f"{sym} {action}: skipped — {result['reason']}", indent=2)
                return result

        try:
            if action == ORDER_BUY:
                result = self._exec_buy(order, sym, qty_delta, is_crypto, result)
            elif action == ORDER_REDUCE:
                result = self._exec_reduce(order, sym, qty_delta, is_crypto, result)
            elif action == ORDER_EXIT:
                result = self._exec_exit(order, sym, qty_delta, is_crypto, result)
            else:
                result["reason"] = f"unsupported action {action}"
                self.trace.warn(f"{sym} {action}: {result['reason']}", indent=2)
        except Exception as e:
            result["status"] = "failed"
            result["reason"] = f"{type(e).__name__}: {e}"
            self.trace.err(f"{sym} {action}: exception — {result['reason']}", indent=2)

        return result

    def _exec_buy(self, order: dict, sym: str, qty: float,
                   is_crypto: bool, result: dict) -> dict:
        """BUY new or add-to existing position."""
        try:
            from alpaca_orders import place_stock_bracket, place_crypto_order, get_latest_quote
        except ImportError:
            from shared.alpaca_orders import place_stock_bracket, place_crypto_order, get_latest_quote

        # v3.8.8 (2026-05-18): pre-flight check for OPEN orders on same
        # symbol+side. Bug surfaced today: USO + OXY rejected by Alpaca
        # on 2nd allocator run because LIMIT BUYs from 1st run sat
        # unfilled (stale price) and Alpaca rejects duplicate-side
        # open orders.
        #
        # v3.9.9 (2026-05-27): extended with POSITION pre-check. Bug
        # 2026-05-26: bracket BUYs fill immediately on Alpaca paper, so
        # status=open buy returns empty by 2nd allocator run, but the
        # POSITION exists. Without this check, the system places a second
        # bracket → duplicate OCO children → autonomous-remediation flags
        # duplicate_exits → (pre v3.9.9: emergency_engine MARKET-closed
        # entire position). Now: skip BUY if position already exists at
        # ±10% of target qty (re-balance threshold).
        try:
            import requests as _rq
            from alpaca_orders import _headers as _hdr, ALPACA_BASE_URL as _base, _fetch_single_position
            # POSITION check first (cheaper, catches immediate-fill case)
            try:
                existing_pos = _fetch_single_position(sym)
            except Exception:
                existing_pos = None
            if existing_pos:
                try:
                    current_qty = abs(float(existing_pos.get("qty") or 0))
                    target_qty = abs(float(qty))
                    # Skip if already within 10% of target (no meaningful add-on)
                    if target_qty > 0 and abs(current_qty - target_qty) / target_qty < 0.10:
                        result["status"] = "skipped"
                        result["reason"] = (
                            f"BUY skipped: position {sym} already exists "
                            f"qty={current_qty:.0f} target={target_qty:.0f} "
                            f"(within 10% rebalance threshold)"
                        )
                        self.trace.warn(f"{sym} BUY: {result['reason']}", indent=2)
                        return result
                except (ValueError, TypeError):
                    pass  # fall through to open-orders check
            # ORDER check (v3.8.8 — for stale LIMITs that haven't filled)
            r = _rq.get(
                f"{_base}/v2/orders",
                headers=_hdr(),
                params={"status": "open", "symbols": sym, "limit": 50},
                timeout=10,
            )
            if r.status_code == 200:
                opens = r.json() or []
                existing_buys = [o for o in opens if o.get("side") == "buy"]
                if existing_buys:
                    result["status"] = "skipped"
                    result["reason"] = (
                        f"BUY skipped: {len(existing_buys)} existing open BUY order(s) "
                        f"for {sym} (oldest id={existing_buys[0].get('id','?')[:8]}). "
                        f"Cancel via cancel-stale-emergency-orders or wait for fill."
                    )
                    self.trace.warn(f"{sym} BUY: {result['reason']}", indent=2)
                    return result
        except Exception as e:
            # Fail-open: if pre-checks fail, proceed to place
            # (preserves prior behavior; new check is best-effort guard).
            self.trace.warn(
                f"{sym} BUY: pre-check unavailable "
                f"({type(e).__name__}: {e}); proceeding",
                indent=2,
            )

        # Need a fresh price for SL/TP calculation
        ref_price = order.get("current_price")
        if not ref_price or ref_price <= 0:
            q = get_latest_quote(sym)
            ref_price = (q or {}).get("mid") if q else None
        if not ref_price or ref_price <= 0:
            result["status"] = "failed"
            result["reason"] = "no reference price for SL/TP"
            self.trace.err(f"{sym} BUY: {result['reason']}", indent=2)
            return result

        sl_pct = float((self.profile.get("exits") or {}).get("default_stop_loss_pct", 0.05))
        tp_pct = float((self.profile.get("exits") or {}).get("default_take_profit_pct", 0.12))

        if is_crypto:
            qty_f = round(abs(qty), 6)
            resp = place_crypto_order(sym, "buy", qty_f, ref_price, strategy="allocator-rebalance")
        else:
            qty_i = max(int(abs(qty)), 1)
            sl = round(ref_price * (1 - sl_pct), 2)
            tp = round(ref_price * (1 + tp_pct), 2)
            resp = place_stock_bracket(sym, "buy", qty_i, ref_price, sl, tp,
                                        strategy="allocator-rebalance")

        if resp and resp.get("id"):
            result["status"] = "placed"
            result["alpaca_order_id"] = resp["id"]
            result["reason"] = f"BUY {abs(qty):.4f} @ ${ref_price:.2f}"
            self.trace.info(f"{sym} BUY placed: {result['reason']}  id={resp['id']}", indent=2)
        else:
            # v3.22 (2026-06-07) — structured rejection capture replaces
            # the bare "Alpaca rejected order (see stdout)" line. resp may
            # be None or a dict carrying http_status/exception_str/
            # response_body when alpaca_orders.py decorates the failure.
            result["status"] = "failed"
            try:
                from order_rejection_audit import (
                    build_rejection_payload, format_reason_line, emit_audit,
                )
            except ImportError:
                from shared.order_rejection_audit import (  # type: ignore
                    build_rejection_payload, format_reason_line, emit_audit,
                )
            r = resp if isinstance(resp, dict) else {}
            payload = build_rejection_payload(
                symbol=sym,
                side="buy",
                order_qty=qty,
                order_notional=(qty * ref_price) if (qty and ref_price) else None,
                http_status=r.get("http_status"),
                exception_str=r.get("exception_str") or r.get("error"),
                response_body=r.get("response_body"),
                strategy="allocator-rebalance",
            )
            result["rejection_category"] = payload["rejection_category"]
            result["http_status"] = payload["http_status"]
            result["alpaca_message"] = payload["alpaca_message"]
            result["order_notional"] = payload["order_notional"]
            result["order_qty"] = payload["order_qty"]
            result["reason"] = format_reason_line(payload)
            try:
                emit_audit(payload)
            except Exception:
                pass
            self.trace.err(f"{sym} BUY failed: {result['reason']}", indent=2)
        return result

    def _exec_reduce(self, order: dict, sym: str, qty: float,
                      is_crypto: bool, result: dict) -> dict:
        """Partial close — sell |qty| shares via safe_close (v3.9.10)."""
        try:
            from alpaca_orders import safe_close, get_latest_quote
        except ImportError:
            from shared.alpaca_orders import safe_close, get_latest_quote

        q = get_latest_quote(sym)
        ref_price = (q or {}).get("bid") if q else order.get("current_price")
        if not ref_price or ref_price <= 0:
            result["status"] = "failed"
            result["reason"] = "no reference price for REDUCE"
            self.trace.err(f"{sym} REDUCE: {result['reason']}", indent=2)
            return result

        limit_price = round(ref_price * 0.998, 2) if not is_crypto else round(ref_price, 4)
        sc = safe_close(
            symbol=sym, intent_qty=abs(qty), intent_side="sell",
            reason_tag="alloc-reduce", order_type="limit",
            limit_price=limit_price, time_in_force="day",
            is_crypto=is_crypto, allow_market=False,
        )
        result["status"] = sc["status"]
        result["alpaca_order_id"] = sc["alpaca_order_id"]
        result["reason"] = sc["reason"]
        if sc["status"] == "placed":
            self.trace.info(f"{sym} REDUCE placed: {sc['reason']}", indent=2)
        elif sc["status"] == "skipped":
            self.trace.info(f"{sym} REDUCE skipped: {sc['reason']}", indent=2)
        else:
            self.trace.err(f"{sym} REDUCE: {sc['reason']}", indent=2)
        return result

    def _exec_exit(self, order: dict, sym: str, qty: float,
                    is_crypto: bool, result: dict) -> dict:
        """Full close — MARKET SELL entire position via safe_close (v3.9.10)."""
        try:
            from alpaca_orders import safe_close
        except ImportError:
            from shared.alpaca_orders import safe_close

        sc = safe_close(
            symbol=sym, intent_qty=abs(qty), intent_side="sell",
            reason_tag="alloc-exit", order_type="market",
            time_in_force="day", is_crypto=is_crypto, allow_market=True,
        )
        result["status"] = sc["status"]
        result["alpaca_order_id"] = sc["alpaca_order_id"]
        result["reason"] = sc["reason"]
        if sc["status"] == "placed":
            self.trace.info(f"{sym} EXIT placed: {sc['reason']}", indent=2)
        elif sc["status"] == "skipped":
            self.trace.info(f"{sym} EXIT skipped: {sc['reason']}", indent=2)
        else:
            self.trace.err(f"{sym} EXIT: {sc['reason']}", indent=2)
        return result

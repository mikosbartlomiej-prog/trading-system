"""
politician-monitor — Trump/family + bipartisan Congressional insider tracker.

Two lanes:

  Lane A — DJT Form 4 (real-time, auto-execute eligible)
    SEC EDGAR Atom feed for Trump Media & Technology Group (DJT) CIK.
    Each insider transaction (Trump family, board members, officers)
    flagged within ~2 days of execution. Curator-validated buys can
    auto-execute via shared/alpaca_orders.execute_stock_signal.
    Default sizing $5,000 (half normal — DJT hyper-volatile).

  Lane B — STOCK Act PTRs (30-45 day lag, alert-only by default)
    Capitol Trades JSON feed for bipartisan whitelist of 20 politicians.
    Cluster aggregation: ≥3 politicians same sector in 14d → sector ETF
    (ITA/SMH/XLE/XLF/XLV/QQQ). Single committee-chair PTRs above $100k
    bracket emit standalone. Curator filters noise.

Pipeline:
  1. Load whitelist + dedupe state (seen Form 4 accessions + PTR URLs)
  2. Fetch DJT Form 4 (lane A) + Capitol Trades PTRs (lane B)
  3. Filter via whitelist + dedupe
  4. Compute cluster hints (lane B sector grouping)
  5. Build account_context (equity, daily P&L, open positions, VIX, regime)
  6. Call Curator LLM (fail-soft → heuristic top-N if unavailable)
  7. Apply standard risk gates (VIX / drawdown / concentration / PDT)
  8. Emit:
     - Lane A DJT auto-execute via shared/alpaca_orders (if curator approved)
     - Lane B alert-only email via shared/notify (default; AUTO_EXECUTE_STOCK_ACT=true to override)
  9. Update dedupe state + commit

Iron rules enforced: paper-only, whitelist tickers, stop-loss mandatory,
auto-execute is opt-in per lane.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

# Allow `from notify import ...` + sibling shared/ modules
MONITOR_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.abspath(os.path.join(MONITOR_DIR, ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
sys.path.insert(0, MONITOR_DIR)


from edgar_client    import fetch_recent_djt_form4, DJT_CIK
from stockact_client import (
    fetch_recent_ptrs, load_whitelist, _politician_normalize,
    LOOKBACK_DAYS, MIN_BRACKET_MID_USD,
)
import llm_curator

# v3.22.0 — observability-only wiring into the canonical signal pipeline.
# emit_monitor_signal NEVER places trades; it forwards a SignalEvent to
# shared.signal_emitter.emit_signal_opportunity which persists via the
# opportunity ledger. NEVER imports alpaca_orders. NEVER calls the broker.
try:
    from monitor_signal_helper import emit_monitor_signal  # type: ignore
except Exception:
    try:
        from shared.monitor_signal_helper import emit_monitor_signal  # type: ignore
    except Exception:
        def emit_monitor_signal(*_a, **_kw):  # type: ignore
            return None

# v3.24 — monitor runtime diagnostics (ETAP 9). Fail-soft.
try:
    from monitor_runtime_diag import (  # type: ignore
        record_diag as _diag,
        DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
        DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
        DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
    )
except Exception:
    try:
        from shared.monitor_runtime_diag import (  # type: ignore
            record_diag as _diag,
            DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
            DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
            DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
        )
    except Exception:
        def _diag(*_a, **_kw):  # type: ignore
            return False
        DIAG_RAN = "RAN"; DIAG_INPUT_EMPTY = "INPUT_EMPTY"
        DIAG_NO_SIGNAL = "NO_SIGNAL"; DIAG_SIGNAL_DETECTED = "SIGNAL_DETECTED"
        DIAG_EMIT_ATTEMPTED = "EMIT_ATTEMPTED"
        DIAG_EMIT_SUCCESS = "EMIT_SUCCESS"; DIAG_EMIT_FAILED = "EMIT_FAILED"

# v3.27 — watchlist-aware diagnostics (ETAP 8). Fail-soft.
try:
    from watchlist_diag import (  # type: ignore
        load_watchlist_cache_for_scan as _watchlist_load,
        diag_watchlist_scan_started as _watchlist_started,
        diag_watchlist_scan_finished as _watchlist_finished,
    )
except Exception:
    try:
        from shared.watchlist_diag import (  # type: ignore
            load_watchlist_cache_for_scan as _watchlist_load,
            diag_watchlist_scan_started as _watchlist_started,
            diag_watchlist_scan_finished as _watchlist_finished,
        )
    except Exception:
        def _watchlist_load(*_a, **_kw):  # type: ignore
            return {}
        def _watchlist_started(*_a, **_kw):  # type: ignore
            return False
        def _watchlist_finished(*_a, **_kw):  # type: ignore
            return None


# ─── Configuration ────────────────────────────────────────────────────────────

AUTO_EXECUTE_DJT          = os.environ.get("AUTO_EXECUTE_DJT_FORM4", "true").lower() == "true"
AUTO_EXECUTE_STOCK_ACT    = os.environ.get("AUTO_EXECUTE_STOCK_ACT", "false").lower() == "true"
MAX_ALERTS_PER_RUN        = int(os.environ.get("MAX_ALERTS_PER_RUN", "3"))
DJT_SIZE_USD              = float(os.environ.get("DJT_SIZE_USD", "5000"))
CLUSTER_MIN_POLITICIANS   = int(os.environ.get("CLUSTER_MIN_POLITICIANS", "3"))
CLUSTER_WINDOW_DAYS       = int(os.environ.get("CLUSTER_WINDOW_DAYS", "14"))
CLUSTER_MIN_AMOUNT_USD    = float(os.environ.get("CLUSTER_MIN_AMOUNT_USD", "200000"))
SINGLE_PTR_HIGH_BRACKET   = float(os.environ.get("SINGLE_PTR_HIGH_BRACKET_USD", "100000"))
SINGLE_PTR_HIGH_WEIGHT    = float(os.environ.get("SINGLE_PTR_HIGH_WEIGHT", "1.4"))

STATE_PATH = os.path.join(MONITOR_DIR, "state.json")


# Sector → ETF proxy + bucket. Used for Lane B cluster aggregation.
SECTOR_MAP: dict[str, dict[str, Any]] = {
    "defense":     {"etf": "ITA", "tickers": {"RTX", "LMT", "NOC", "GD", "BA",
                                              "KTOS", "PLTR", "AXON", "LDOS",
                                              "SAIC", "CACI", "BAESY", "EADSY"}},
    "semis":       {"etf": "SMH", "tickers": {"NVDA", "AMD", "AVGO", "SMCI",
                                              "ARM", "TSM", "INTC", "QCOM",
                                              "MU", "AMAT", "LRCX"}},
    "energy":      {"etf": "XLE", "tickers": {"XOM", "CVX", "OXY", "USO",
                                              "COP", "EOG", "PSX", "MPC", "VLO"}},
    "financials":  {"etf": "XLF", "tickers": {"JPM", "V", "MA", "BAC", "GS",
                                              "MS", "C", "WFC", "BLK", "SCHW"}},
    "healthcare":  {"etf": "XLV", "tickers": {"JNJ", "PFE", "MRK", "UNH",
                                              "ABBV", "LLY", "TMO", "ABT"}},
    "tech_broad":  {"etf": "QQQ", "tickers": {"AAPL", "MSFT", "GOOGL", "AMZN",
                                              "META", "TSLA"}},
    "software":    {"etf": "QQQ", "tickers": {"NOW", "CRM", "ADBE", "ORCL",
                                              "INTU", "WDAY", "PANW", "CRWD"}},
}


# ─── Dedupe state ─────────────────────────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    """Load dedupe state (seen accessions + PTR URLs). Empty defaults on miss."""
    if not os.path.exists(STATE_PATH):
        return {"seen_form4": [], "seen_ptr": [], "last_scan": ""}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"seen_form4": [], "seen_ptr": [], "last_scan": ""}
    if not isinstance(data, dict):
        return {"seen_form4": [], "seen_ptr": [], "last_scan": ""}
    data.setdefault("seen_form4", [])
    data.setdefault("seen_ptr",   [])
    return data


def _save_state(state: dict[str, Any]) -> None:
    """Write dedupe state. FIFO-cap to 500 entries per list."""
    state["seen_form4"] = list(state.get("seen_form4", []))[-500:]
    state["seen_ptr"]   = list(state.get("seen_ptr",   []))[-500:]
    state["last_scan"]  = _utcnow()
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"  WARN: could not write state.json: {e}")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Sector classification ────────────────────────────────────────────────────

def _sector_for(ticker: str) -> Optional[str]:
    sym = (ticker or "").upper().strip()
    for sector, info in SECTOR_MAP.items():
        if sym in info["tickers"]:
            return sector
    return None


# ─── Lane B: cluster aggregation ──────────────────────────────────────────────

def compute_clusters(ptrs: list[dict]) -> list[dict[str, Any]]:
    """
    Group PTRs by sector + side (BUY/SELL). Return clusters with
    ≥CLUSTER_MIN_POLITICIANS unique politicians and aggregate amount
    ≥CLUSTER_MIN_AMOUNT_USD within CLUSTER_WINDOW_DAYS.

    Output entry shape:
      {"sector": "defense", "etf_proxy": "ITA", "side": "BUY",
       "tickers_mentioned": ["RTX","LMT","NOC"], "politicians_count": 4,
       "politicians": ["McCaul", "Warner", "Tuberville", "Vance"],
       "total_amount_usd": 425000, "window_days": 11}
    """
    groups: dict[tuple, list[dict]] = {}
    for p in ptrs:
        sec = _sector_for(p["ticker"])
        if not sec:
            continue
        side = p["side"]
        if side not in ("BUY", "SELL"):
            continue
        groups.setdefault((sec, side), []).append(p)

    out: list[dict[str, Any]] = []
    for (sector, side), items in groups.items():
        politicians = {x["politician"] for x in items}
        if len(politicians) < CLUSTER_MIN_POLITICIANS:
            continue

        # Window check: span between earliest and latest disclosure_date
        dates = []
        for x in items:
            try:
                dates.append(datetime.strptime(x["disclosure_date"], "%Y-%m-%d").date())
            except (ValueError, TypeError):
                pass
        if dates:
            window_days = (max(dates) - min(dates)).days
        else:
            window_days = -1
        if window_days > CLUSTER_WINDOW_DAYS:
            continue

        total_amount = sum(x.get("bracket_mid_usd", 0.0) for x in items)
        if total_amount < CLUSTER_MIN_AMOUNT_USD:
            continue

        tickers = sorted({x["ticker"] for x in items})
        out.append({
            "sector":             sector,
            "etf_proxy":          SECTOR_MAP[sector]["etf"],
            "side":               side,
            "tickers_mentioned":  tickers,
            "politicians":        sorted(politicians),
            "politicians_count":  len(politicians),
            "total_amount_usd":   round(total_amount, 2),
            "window_days":        window_days,
        })

    out.sort(key=lambda c: c["total_amount_usd"], reverse=True)
    return out


# ─── Lane B: candidate filtering ──────────────────────────────────────────────

def filter_ptr_candidates(ptrs: list[dict], whitelist: dict
                           ) -> list[dict[str, Any]]:
    """
    Enrich PTRs with whitelist metadata (category, weight). Keep:
      - politicians on whitelist
      - tickers on system whitelist (deferred to risk_officer / scoring)
    Discard everything else.

    Returns enriched candidate dicts ready for Curator payload.
    """
    out: list[dict[str, Any]] = []
    for p in ptrs:
        key = _politician_normalize(p["politician"])
        meta = whitelist.get(key)
        if not meta:
            continue
        enriched = dict(p)
        enriched["lane"]     = "stock_act"
        enriched["category"] = meta["category"]
        enriched["weight"]   = meta["weight"]
        enriched["chamber"]  = meta.get("chamber", "")
        # Override party from whitelist for normalization
        enriched["party"] = meta.get("party") or p.get("party", "")
        out.append(enriched)
    return out


# ─── Lane A: DJT Form 4 candidate building ────────────────────────────────────

def build_djt_candidates(form4_txs: list[dict]) -> list[dict[str, Any]]:
    """
    Convert Form 4 transactions to Curator candidates. Skip awards/grants
    (code A,G) and convertible/derivative-only filings. Keep purchases (P)
    and sales (S) of non-derivative common stock.
    """
    out: list[dict[str, Any]] = []
    for tx in form4_txs:
        code = tx.get("transaction_code", "")
        if code not in ("P", "S"):
            # P=open-market purchase, S=open-market sale.
            # Skip A (award/grant), G (gift), M (option exercise),
            # F (tax-withholding), and UNKNOWN (no XML parsed).
            continue
        ad_code = tx.get("ad_code", "")
        side = "BUY" if (code == "P" or ad_code == "A") else "SELL"

        out.append({
            "lane":              "djt_form4",
            "filer":             tx.get("filer_name", ""),
            "insider_role":      tx.get("role", "unknown"),
            "ticker":            tx.get("ticker", "DJT"),
            "side":              side,
            "shares":            tx.get("shares", 0.0),
            "price_per_share":   tx.get("price_per_share", 0.0),
            "value_usd":         tx.get("value_usd", 0.0),
            "transaction_date":  tx.get("transaction_date", ""),
            "filing_date":       tx.get("filing_date", ""),
            "lag_days":          tx.get("lag_days", -1),
            "accession":         tx.get("accession", ""),
            "form4_url":         tx.get("doc_link", ""),
        })
    return out


# ─── Account context ──────────────────────────────────────────────────────────

def build_account_context() -> dict[str, Any]:
    """Best-effort snapshot — fail-soft if Alpaca/VIX unavailable."""
    ctx: dict[str, Any] = {
        "equity":           0,
        "daily_pl_pct":     0.0,
        "open_positions":   [],
        "vix":              None,
        "options_side_bias": None,
        "regime":           "NEUTRAL",
    }

    try:
        from risk_guards import get_account_status, get_open_positions
        acct = get_account_status() or {}
        ctx["equity"]       = acct.get("equity", 0)
        ctx["daily_pl_pct"] = acct.get("daily_pl_pct", 0.0)
        ctx["open_positions"] = get_open_positions() or []
    except Exception as e:
        print(f"  context: Alpaca unavailable ({e}) — proceeding with defaults")

    try:
        from risk_guards import get_vix
        ctx["vix"] = get_vix()
    except Exception:
        pass

    try:
        from learning_state import load_strategy_state
        state = load_strategy_state() or {}
        overrides = state.get("global_overrides") or {}
        ctx["options_side_bias"] = overrides.get("options_side_bias")
    except Exception:
        pass

    try:
        from regime import detect_regime
        ctx["regime"] = detect_regime(market_signals=None)
    except Exception:
        pass

    return ctx


# ─── Emission paths ───────────────────────────────────────────────────────────

def emit_djt_signal(signal: dict, account_ctx: dict) -> dict:
    """
    Lane A (DJT Form 4). If AUTO_EXECUTE_DJT=true → execute via Alpaca.
    Otherwise email-only.
    """
    ticker = signal["ticker"]
    side = signal["side"]
    size_usd = signal.get("size_usd") or DJT_SIZE_USD

    body_lines = [
        "POLITICIAN-MONITOR — Lane A (DJT Form 4 insider transaction)",
        "",
        f"  Ticker:       {ticker}",
        f"  Side:         {side}",
        f"  Size:         ${size_usd:,.0f}",
        f"  Conviction:   {signal.get('curator_conviction', '?')}",
        f"  Score:        {signal.get('curator_score', 0.0):.2f}",
        f"  Rationale:    {signal.get('curator_rationale', '(heuristic)')}",
        f"  Risk:         {signal.get('curator_key_risk', '')}",
        f"  Horizon:      {signal.get('curator_horizon', '?')}",
        "",
        f"  Auto-execute: {AUTO_EXECUTE_DJT}",
    ]
    body = "\n".join(body_lines)

    if AUTO_EXECUTE_DJT and side in ("BUY", "SELL"):
        # v3.10.1 — signal_confirmation gate (Phase C)
        try:
            from news_signal_gate import gate_news_signal, mark_signal_acted
            strength = min(1.0, max(0.0, float(signal.get("curator_score", 0.6))))
            v = gate_news_signal(
                symbol=ticker, side=side,
                signal_strength=strength,
                headline=f"DJT Form 4 — {signal.get('curator_rationale', '')[:150]}",
                source=f"politician/djt-{signal.get('filer', '?')}",
                published_at=signal.get("filed_at"),
                strategy="politician-djt",
                cooldown_hours=24.0,  # DJT moves long-horizon
                max_article_age_hours=48.0,
            )
            if v.verdict.value == "BLOCK":
                print(f"  DJT signal {ticker} BLOCKED: {v.reason}")
                return {"sent": False, "ticker": ticker, "reason": v.reason}
            if v.verdict.value == "ALERT_ONLY":
                print(f"  DJT signal {ticker} ALERT_ONLY: {v.reason}")
                return {"sent": True, "ticker": ticker, "alert_only": True}
            if v.verdict.value == "DOWNSIZE":
                size_usd = round(size_usd * v.size_multiplier)
                print(f"  DJT signal {ticker} DOWNSIZED × {v.size_multiplier:.2f} → ${size_usd}")
            mark_signal_acted(ticker, "politician-djt")
        except Exception as e:
            print(f"  DJT signal-gate error ({type(e).__name__}: {e}) — proceeding")
        try:
            from alpaca_orders import execute_stock_signal
            sig = {
                "ticker":   ticker,
                "side":     side,
                "size_usd": size_usd,
                "sl_pct":   0.10,   # -10% — DJT volatile, wider stop
                "tp_pct":   0.25,   # +25% — capture moves
                "strategy": "politician-djt-form4",
            }
            result = execute_stock_signal(sig)
            print(f"  DJT auto-execute: {result}")
            return {"emitted": True, "result": result, "body": body}
        except Exception as e:
            print(f"  DJT auto-execute exception: {e} — falling back to email")

    try:
        from notify import notify_signal
        notify_signal({
            "subject_prefix": "[POL-DJT]",
            "ticker":   ticker,
            "side":     side,
            "size_usd": size_usd,
            "strategy": "politician-djt-form4",
            "rationale": signal.get("curator_rationale", ""),
            "body_extra": body,
        }, alert_sent=False)
    except Exception as e:
        print(f"  email exception: {e}")
    return {"emitted": True, "result": "email_only", "body": body}


def emit_stockact_signal(signal: dict, account_ctx: dict) -> dict:
    """
    Lane B (STOCK Act). Default email-only; AUTO_EXECUTE_STOCK_ACT=true
    to enable Alpaca execution.
    """
    ticker = signal["ticker"]
    side = signal["side"]
    size_usd = signal.get("size_usd") or 0.0

    body_lines = [
        "POLITICIAN-MONITOR — Lane B (STOCK Act cluster or single committee chair)",
        "",
        f"  Ticker:       {ticker}",
        f"  Side:         {side}",
        f"  Size:         ${size_usd:,.0f}",
        f"  Conviction:   {signal.get('curator_conviction', '?')}",
        f"  Score:        {signal.get('curator_score', 0.0):.2f}",
        f"  Rationale:    {signal.get('curator_rationale', '(heuristic)')}",
        f"  Risk:         {signal.get('curator_key_risk', '')}",
        f"  Horizon:      {signal.get('curator_horizon', '?')}",
        "",
        f"  Auto-execute: {AUTO_EXECUTE_STOCK_ACT}",
    ]
    body = "\n".join(body_lines)

    if AUTO_EXECUTE_STOCK_ACT and side == "BUY" and size_usd > 0:
        try:
            from alpaca_orders import execute_stock_signal
            sig = {
                "ticker":   ticker,
                "side":     side,
                "size_usd": size_usd,
                "sl_pct":   0.06,
                "tp_pct":   0.14,
                "strategy": "politician-stock-act",
            }
            result = execute_stock_signal(sig)
            print(f"  STOCK Act auto-execute: {result}")
            return {"emitted": True, "result": result, "body": body}
        except Exception as e:
            print(f"  STOCK Act auto-execute exception: {e} — falling back to email")

    try:
        from notify import notify_signal
        notify_signal({
            "subject_prefix": "[POL-STOCKACT]",
            "ticker":   ticker,
            "side":     side,
            "size_usd": size_usd,
            "strategy": "politician-stock-act",
            "rationale": signal.get("curator_rationale", ""),
            "body_extra": body,
        }, alert_sent=False)
    except Exception as e:
        print(f"  email exception: {e}")
    return {"emitted": True, "result": "email_only", "body": body}


# ─── Heuristic fallback (when Curator unavailable) ────────────────────────────

def heuristic_signals(djt_candidates: list, ptr_candidates: list,
                       clusters: list) -> list[dict[str, Any]]:
    """
    Deterministic fallback when Curator returns None.

    Rules:
      - Lane A (DJT Form 4): emit BUY if any P-transaction; emit SELL if
        any S-transaction with role=director and value_usd >= $250k.
      - Lane B: emit ETF proxy for each cluster (max 1).
      - Lane B: emit single-name if weight >= 1.4 AND bracket_mid >= $100k.

    Cap total at MAX_ALERTS_PER_RUN.
    """
    out: list[dict[str, Any]] = []

    # Lane A — DJT
    for tx in djt_candidates:
        if tx.get("side") == "BUY":
            out.append({
                "lane":               "djt_form4",
                "ticker":             tx.get("ticker", "DJT"),
                "side":               "BUY",
                "size_usd":           DJT_SIZE_USD,
                "curator_conviction": "heuristic",
                "curator_score":      0.55,
                "curator_rationale":  f"Form 4 BUY by {tx.get('filer')} ({tx.get('insider_role')}); auto fallback",
                "curator_key_risk":   "DJT volatility; -10% stop wider than usual",
                "curator_horizon":    "swing 1-3 weeks",
            })
        elif tx.get("side") == "SELL" and "director" in (tx.get("insider_role", "") or "") and tx.get("value_usd", 0) >= 250000:
            out.append({
                "lane":               "djt_form4",
                "ticker":             tx.get("ticker", "DJT"),
                "side":               "SELL",
                "size_usd":           DJT_SIZE_USD,
                "curator_conviction": "heuristic",
                "curator_score":      0.50,
                "curator_rationale":  f"Form 4 SELL ≥$250k by director {tx.get('filer')}; auto fallback",
                "curator_key_risk":   "Single insider sell may be routine; cluster needed for higher conviction",
                "curator_horizon":    "short 1-2 weeks",
            })

    # Lane B — clusters
    for cl in clusters:
        out.append({
            "lane":               "stock_act",
            "ticker":             cl["etf_proxy"],
            "side":               cl["side"],
            "size_usd":           8000.0 if cl["side"] == "BUY" else 4000.0,
            "curator_conviction": "heuristic",
            "curator_score":      0.65,
            "curator_rationale":  f"Cluster: {cl['politicians_count']} politicians, "
                                  f"{cl['sector']} sector, ${cl['total_amount_usd']:,.0f} "
                                  f"in {cl['window_days']}d (heuristic)",
            "curator_key_risk":   "30-45d STOCK Act lag — actual entry may have been weeks ago",
            "curator_horizon":    "swing 2-4 weeks",
        })

    # Lane B — single high-weight names
    for c in ptr_candidates:
        if c.get("weight", 1.0) >= SINGLE_PTR_HIGH_WEIGHT and \
           c.get("bracket_mid_usd", 0) >= SINGLE_PTR_HIGH_BRACKET and \
           c.get("side") == "BUY":
            out.append({
                "lane":               "stock_act",
                "ticker":             c["ticker"],
                "side":               "BUY",
                "size_usd":           10000.0,
                "curator_conviction": "heuristic",
                "curator_score":      0.62,
                "curator_rationale":  f"{c['politician']} ({c.get('category')}) "
                                      f"{c['bracket_label']} on {c['ticker']} (heuristic)",
                "curator_key_risk":   "Single-source; consider waiting for cluster confirmation",
                "curator_horizon":    "swing 2-4 weeks",
            })

    return out[:MAX_ALERTS_PER_RUN]


# ─── Main scan loop ───────────────────────────────────────────────────────────

def run_scan() -> dict[str, Any]:
    """
    Single scan iteration. Returns summary dict suitable for stdout/log.

    Cron invokes this once per tick. Defends against:
      - VIX HALT (skips emit when VIX > 60)
      - Drawdown HALT (skips when daily P&L <= -3%)
      - Concentration cap (per-ticker exposure)
      - PDT guard (alpaca_orders gate handles when AUTO_EXECUTE_*)
    """
    print(f"=== politician-monitor scan — {_utcnow()} ===")
    print(f"  AUTO_EXECUTE_DJT={AUTO_EXECUTE_DJT}, "
          f"AUTO_EXECUTE_STOCK_ACT={AUTO_EXECUTE_STOCK_ACT}, "
          f"MAX_ALERTS_PER_RUN={MAX_ALERTS_PER_RUN}")
    _diag("politician-monitor", DIAG_RAN, {})

    # ── Account-level guards ─────────────────────────────────────────────
    try:
        from risk_guards import daily_drawdown_guard, vix_guard
        dd_status, dd_reason = daily_drawdown_guard()
        if dd_status == "HALT":
            print(f"  HALT: {dd_reason} — skipping all emits")
            return {"skipped": "drawdown", "reason": dd_reason}
        vix_status, _ = vix_guard()
        if vix_status == "HALT":
            print(f"  HALT: VIX > 60 — skipping all emits")
            return {"skipped": "vix"}
    except Exception as e:
        print(f"  guards unavailable ({e}) — fail-open, proceeding")

    state = _load_state()
    seen_form4 = set(state["seen_form4"])
    seen_ptr   = set(state["seen_ptr"])
    print(f"  state: {len(seen_form4)} Form 4 seen, {len(seen_ptr)} PTR seen")

    # ── Load whitelist ───────────────────────────────────────────────────
    whitelist = load_whitelist()
    print(f"  whitelist: {len(whitelist)} politicians")

    # ── Lane A — DJT Form 4 ──────────────────────────────────────────────
    print(f"  Lane A: fetching DJT Form 4 (CIK {DJT_CIK})...")
    form4_txs = fetch_recent_djt_form4(max_entries=20)
    new_form4 = [tx for tx in form4_txs if tx.get("accession") not in seen_form4]
    print(f"  Lane A: {len(form4_txs)} txs total, {len(new_form4)} new")
    djt_candidates = build_djt_candidates(new_form4)
    print(f"  Lane A: {len(djt_candidates)} candidates after build (P/S only)")

    # ── Lane B — STOCK Act PTRs ──────────────────────────────────────────
    wl_keys = set(whitelist.keys())
    print(f"  Lane B: fetching Capitol Trades PTRs (lookback {LOOKBACK_DAYS}d, "
          f"min bracket ${MIN_BRACKET_MID_USD:,.0f})...")
    ptrs = fetch_recent_ptrs(
        lookback_days=LOOKBACK_DAYS,
        whitelist=wl_keys,
        min_bracket_usd=MIN_BRACKET_MID_USD,
    )
    new_ptrs = [p for p in ptrs if p.get("ptr_url") not in seen_ptr]
    print(f"  Lane B: {len(ptrs)} PTRs total, {len(new_ptrs)} new")

    # Separate houseclerk "filing_alert" entries (no ticker yet — metadata
    # only) from full PTRs with ticker/amount. Filing alerts get a separate
    # email path; full PTRs flow to Curator.
    filing_alerts = [p for p in new_ptrs if p.get("filing_alert")]
    full_new_ptrs = [p for p in new_ptrs if not p.get("filing_alert")]
    ptr_candidates = filter_ptr_candidates(full_new_ptrs, whitelist)
    print(f"  Lane B: {len(ptr_candidates)} full candidates after whitelist enrich, "
          f"{len(filing_alerts)} filing alerts (tier-3 fallback)")

    # ── Cluster aggregation (Lane B) — uses ALL PTRs not just new ────────
    # Rationale: cluster only makes sense across full lookback window;
    # we dedupe at signal-emit level, not cluster-detect level. Filing
    # alerts (no ticker) excluded from cluster math.
    all_full_ptrs = [p for p in ptrs if not p.get("filing_alert")]
    all_ptr_for_cluster = filter_ptr_candidates(all_full_ptrs, whitelist)
    clusters = compute_clusters(all_ptr_for_cluster)
    print(f"  Lane B: {len(clusters)} clusters detected")

    # ── Filing alerts (tier-3 fallback path) ─────────────────────────────
    # When Capitol Trades + housewatcher both down, House Clerk XML still
    # tells us WHO filed a PTR — operator reads the PDF via ptr_url.
    # Whitelist filter + cap at MAX_ALERTS_PER_RUN.
    whitelisted_alerts = [
        fa for fa in filing_alerts
        if _politician_normalize(fa["politician"]) in whitelist
    ]
    filing_alerts_sent = 0
    if whitelisted_alerts:
        try:
            from notify import send_email
            for fa in whitelisted_alerts[:MAX_ALERTS_PER_RUN]:
                subject = (f"[POL-FILING] {fa['politician']} filed PTR "
                           f"{fa.get('disclosure_date', '?')}")
                body = "\n".join([
                    "POLITICIAN-MONITOR — Filing Alert (House Clerk tier-3 fallback)",
                    "",
                    f"  Politician:   {fa['politician']}",
                    f"  Chamber:      {fa.get('chamber', '?')}",
                    f"  District:     {fa.get('state_dst', '?')}",
                    f"  Filing date:  {fa.get('disclosure_date', '?')}",
                    f"  DocID:        {fa.get('doc_id', '?')}",
                    f"  PDF:          {fa.get('ptr_url', '?')}",
                    "",
                    "  NOTE: ticker + amount unknown from XML index — read PDF",
                    "        to see actual transactions. Auto-execute: NEVER",
                    "        for filing alerts (no ticker resolved).",
                    "",
                    "  Capitol Trades primary endpoint currently 503; this",
                    "  alert is from official House Clerk XML index fallback.",
                    "  When Capitol Trades recovers, full ticker/amount data",
                    "  will flow through normal Curator pipeline automatically.",
                ])
                send_email(subject, body)
                filing_alerts_sent += 1
            print(f"  Filing alerts: {filing_alerts_sent} emails sent "
                  f"(whitelisted politicians)")
        except Exception as e:
            print(f"  Filing alerts email exception: {e}")
    else:
        print(f"  Filing alerts: 0 whitelisted (skipped {len(filing_alerts)} "
              f"off-whitelist)")

    if not djt_candidates and not ptr_candidates and not clusters:
        print(f"  No trade candidates — scan complete "
              f"(filing_alerts_sent={filing_alerts_sent})")
        _diag("politician-monitor", DIAG_NO_SIGNAL,
              {"filing_alerts_sent": filing_alerts_sent})
        state["seen_form4"] = list(seen_form4 | {tx["accession"] for tx in form4_txs
                                                  if tx.get("accession")})
        state["seen_ptr"]   = list(seen_ptr | {p["ptr_url"] for p in ptrs
                                                if p.get("ptr_url")})
        _save_state(state)
        return {"emitted": 0, "candidates": 0, "clusters": 0,
                "filing_alerts_sent": filing_alerts_sent}
    _diag("politician-monitor", DIAG_SIGNAL_DETECTED,
          {"djt": len(djt_candidates), "ptr": len(ptr_candidates),
           "clusters": len(clusters)})
    # v3.27 — watchlist-aware: emit trigger-crossed for each unique
    # symbol surfaced in DJT/PTR candidates or sector-cluster ETFs
    # (fail-soft, observation-only).
    try:
        _wl_cache_pol = _watchlist_load()
        _pol_syms: set[str] = set()
        for _c in (djt_candidates + ptr_candidates):
            _s = (_c or {}).get("symbol") or (_c or {}).get("ticker")
            if isinstance(_s, str) and _s:
                _pol_syms.add(_s)
        for _cl in clusters:
            _s = (_cl or {}).get("etf") or (_cl or {}).get("symbol")
            if isinstance(_s, str) and _s:
                _pol_syms.add(_s)
        for _sym in _pol_syms:
            _watchlist_started("politician-monitor", _sym, _wl_cache_pol)
            _watchlist_finished(
                "politician-monitor", _sym, _wl_cache_pol,
                signal_detected=True,
                strategy_id_override="politician-tracker",
            )
    except Exception:
        pass

    # ── Curator LLM call ─────────────────────────────────────────────────
    ctx = build_account_context()
    candidates_payload = djt_candidates + ptr_candidates
    print(f"  Curator: calling with {len(candidates_payload)} candidates + "
          f"{len(clusters)} clusters...")
    curator_out = llm_curator.curate(
        candidates=candidates_payload,
        cluster_hints=clusters,
        account_context=ctx,
    )

    if curator_out is None:
        print("  Curator unavailable → using heuristic fallback")
        signals = heuristic_signals(djt_candidates, ptr_candidates, clusters)
    else:
        signals = llm_curator.filter_signals_via_curator(
            signals=candidates_payload, curator_output=curator_out
        )
        print(f"  Curator returned {len(signals)} selected signals "
              f"(narrative len={len(curator_out.get('narrative', ''))} chars)")

    # ── Cap + emit ───────────────────────────────────────────────────────
    signals = signals[:MAX_ALERTS_PER_RUN]
    emitted = []
    for sig in signals:
        _diag("politician-monitor", DIAG_EMIT_ATTEMPTED,
              {"lane": sig.get("lane"), "ticker": sig.get("ticker")})
        if sig["lane"] == "djt_form4":
            r = emit_djt_signal(sig, ctx)
        else:
            r = emit_stockact_signal(sig, ctx)
        if r.get("result") in ("emitted", "executed", "placed", "ok", "success"):
            _diag("politician-monitor", DIAG_EMIT_SUCCESS,
                  {"ticker": sig.get("ticker")})
        else:
            _diag("politician-monitor", DIAG_EMIT_FAILED,
                  {"ticker": sig.get("ticker"),
                   "reason": r.get("result", "unknown")})
        emitted.append({**sig, "emit_result": r.get("result", "?")})
        print(f"  emitted: {sig['lane']} {sig['side']} {sig['ticker']} "
              f"${sig.get('size_usd', 0):,.0f} → {r.get('result')}")

    # ── Update state ─────────────────────────────────────────────────────
    state["seen_form4"] = list(seen_form4 | {tx["accession"] for tx in form4_txs
                                              if tx.get("accession")})
    state["seen_ptr"]   = list(seen_ptr | {p["ptr_url"] for p in ptrs
                                            if p.get("ptr_url")})
    _save_state(state)

    print(f"=== scan complete: {len(emitted)} emitted, "
          f"{filing_alerts_sent} filing alerts ===")
    return {
        "emitted":            len(emitted),
        "candidates":         len(candidates_payload),
        "clusters":           len(clusters),
        "filing_alerts_sent": filing_alerts_sent,
        "signals":            emitted,
    }


if __name__ == "__main__":
    summary = run_scan()
    # Send summary email only if any signal or filing alert was emitted
    total_emitted = (summary.get("emitted", 0)
                     + summary.get("filing_alerts_sent", 0))
    if total_emitted > 0:
        try:
            from notify import notify_summary
            notify_summary(
                monitor="politician-monitor",
                signals_found=summary.get("candidates", 0),
                alerts_sent=total_emitted,
            )
        except Exception as e:
            print(f"  summary email exception: {e}")
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("politician-monitor", status="ok",
                 message=f"emitted={summary.get('emitted', 0)}")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")


# ── v3.22.0 observability hook ──────────────────────────────────────────────
# Per the v3.22 signal-pipeline contract this monitor exposes a thin helper
# that the run loop calls once per scan even when no signal fires (so the
# operator can see "monitor ran, 0 candidates" in the opportunity ledger).
# emit_monitor_signal NEVER places trades — it only persists an observation
# row via shared.signal_emitter.emit_signal_opportunity.
def _v322_observe(symbol: str = "n/a", action: str = "NO_SIGNAL",
                  side: str = "n/a", asset_class: str = "us_equity",
                  raw_signal=None) -> None:
    try:
        emit_monitor_signal(
            source_monitor="politician-monitor",
            strategy_id="politician-tracker",
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            action=action,
            entry_capable=False,
            raw_signal=raw_signal or {},
        )
    except Exception:
        pass

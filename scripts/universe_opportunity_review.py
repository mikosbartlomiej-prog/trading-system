#!/usr/bin/env python3
"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 6 — Universe opportunity review.

Reads the active universe from ``shared/market_data_provider.py`` and
combines:

  * ledger row counts per symbol (last 7 days)
  * near-miss counts per symbol (last 7 days)
  * data-failure token distribution (from
    ``shared/monitor_runtime_diag.py`` JSONL emission)
  * inferred liquidity proxy (volume from latest snapshot if available)

and emits a per-symbol *advisory* recommendation:

  - KEEP                 — symbol is generating evidence, keep it
  - OBSERVE_ONLY_ADD     — symbol shows promising near-miss density;
                           suggest adding to observation-only universe
  - REMOVE_LOW_QUALITY   — symbol is silent + no near-misses + no data
                           failures; candidate for removal review
  - NEEDS_DATA           — symbol is silent because data is missing/stale
  - REJECT_HIGH_SPREAD   — symbol has high spread / low liquidity proxy

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER adds new trade-eligible symbols automatically.
- NEVER auto-removes a symbol.
- May SUGGEST observation-only universe additions but does NOT modify the
  live universe.
- NEVER makes network calls. NEVER imports ``alpaca_orders``.
- NEVER mutates state.json or runtime_state.json.
- Standing markers footer reproduced in every emitted artefact.

Outputs:

- ``learning-loop/universe_opportunity_review_latest.json``
- ``docs/UNIVERSE_OPPORTUNITY_REVIEW.md``
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
NEAR_MISS_DIR = REPO_ROOT / "learning-loop" / "near_miss"
DIAG_DIR = REPO_ROOT / "learning-loop" / "monitor_runtime_diag"
SNAPSHOT_DIR_DEFAULT = REPO_ROOT / "learning-loop" / "backfill_snapshots"
LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "universe_opportunity_review_latest.json")
LATEST_MD_PATH = REPO_ROOT / "docs" / "UNIVERSE_OPPORTUNITY_REVIEW.md"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "REVIEW_NEVER_AUTO_ADDS_TRADE_ELIGIBLE_SYMBOLS",
    "REVIEW_NEVER_AUTO_REMOVES_SYMBOLS",
)

VERSION = "v3.26.0"

RECOMMENDATION_TYPES: tuple[str, ...] = (
    "KEEP",
    "OBSERVE_ONLY_ADD",
    "REMOVE_LOW_QUALITY",
    "NEEDS_DATA",
    "REJECT_HIGH_SPREAD",
)


# ─── Universe loader ─────────────────────────────────────────────────────────


def _load_default_universe() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read the active universe from ``shared/market_data_provider``.

    Falls back to a hardcoded list if the import fails (e.g. test env).
    NEVER fetches live.
    """
    fallback_eq = ("SPY", "QQQ", "GLD", "AMD", "CRWD", "NOW", "PANW", "ORCL")
    fallback_cr = ("BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD")
    added = False
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
        added = True
    try:
        from shared.market_data_provider import (  # type: ignore
            DEFAULT_EQUITY_SYMBOLS, DEFAULT_CRYPTO_SYMBOLS,
        )
        eq = tuple(DEFAULT_EQUITY_SYMBOLS)
        cr = tuple(DEFAULT_CRYPTO_SYMBOLS)
        return eq, cr
    except Exception:
        return fallback_eq, fallback_cr
    finally:
        if added:
            try:
                sys.path.remove(str(REPO_ROOT))
            except ValueError:
                pass


# ─── JSONL readers ───────────────────────────────────────────────────────────


def _ledger_files(days: int, as_of: datetime,
                  ledger_dir: Path) -> list[Path]:
    if not ledger_dir.exists():
        return []
    files: list[Path] = []
    for offset in range(days):
        day = (as_of - timedelta(days=offset)).date().isoformat()
        candidate = ledger_dir / f"{day}.jsonl"
        if candidate.exists():
            files.append(candidate)
    return files


def _diag_files(days: int, as_of: datetime, diag_dir: Path) -> list[Path]:
    if not diag_dir.exists():
        return []
    files: list[Path] = []
    for offset in range(days):
        day = (as_of - timedelta(days=offset)).date().isoformat()
        candidate = diag_dir / f"{day}.jsonl"
        if candidate.exists():
            files.append(candidate)
    return files


def _iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception:
        return


# ─── Aggregation per symbol ──────────────────────────────────────────────────


@dataclass
class SymbolStats:
    symbol: str
    asset_class: str
    ledger_rows: int = 0
    candidates: int = 0
    near_misses: int = 0
    data_failure_tokens: dict = None  # type: ignore[assignment]
    latest_volume: Optional[float] = None
    inferred_liquidity_proxy: Optional[str] = None
    spread_proxy_pct: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "symbol":                  self.symbol,
            "asset_class":             self.asset_class,
            "ledger_rows_7d":          self.ledger_rows,
            "candidates_7d":           self.candidates,
            "near_miss_count_7d":      self.near_misses,
            "data_failure_token_distribution":
                dict(self.data_failure_tokens or {}),
            "latest_volume":           self.latest_volume,
            "inferred_liquidity_proxy": self.inferred_liquidity_proxy,
            "spread_proxy_pct":        self.spread_proxy_pct,
        }


def _aggregate_ledger(
    universe: tuple[str, ...], days: int, as_of: datetime,
    ledger_dir: Path,
) -> dict[str, dict]:
    """Per-symbol ledger row counts + candidate counts.

    Candidate = row where ``paper_action`` is not in {"rejected"} AND
    ``risk_decision`` is not in {"REJECT", "NO_SIGNAL"}.
    """
    out: dict[str, dict] = {s: {"rows": 0, "candidates": 0} for s in universe}
    universe_set = set(universe)
    for f in _ledger_files(days, as_of, ledger_dir):
        for row in _iter_jsonl(f):
            symbol = row.get("symbol")
            if not symbol or symbol not in universe_set:
                continue
            out[symbol]["rows"] += 1
            risk = (row.get("risk_decision") or "").upper()
            paper = (row.get("paper_action") or "").lower()
            if paper != "rejected" and risk not in ("REJECT", "NO_SIGNAL"):
                out[symbol]["candidates"] += 1
    return out


def _aggregate_near_miss(
    universe: tuple[str, ...], days: int, as_of: datetime,
    near_miss_dir: Path,
) -> dict[str, int]:
    """Per-symbol near-miss count over last `days`."""
    out: dict[str, int] = {s: 0 for s in universe}
    universe_set = set(universe)
    if not near_miss_dir.exists():
        return out
    for offset in range(days):
        day = (as_of - timedelta(days=offset)).date().isoformat()
        candidate = near_miss_dir / f"{day}.jsonl"
        if not candidate.exists():
            continue
        for row in _iter_jsonl(candidate):
            sym = row.get("symbol")
            if sym and sym in universe_set:
                out[sym] = out.get(sym, 0) + 1
    return out


def _aggregate_data_failures(
    universe: tuple[str, ...], days: int, as_of: datetime,
    diag_dir: Path,
) -> dict[str, dict[str, int]]:
    """Per-symbol distribution of failure tokens (NO_MARKET_DATA,
    MARKET_DATA_STALE, MARKET_DATA_AUTH_FAILED, etc.).
    """
    out: dict[str, collections.Counter] = {
        s: collections.Counter() for s in universe
    }
    universe_set = set(universe)
    failure_tokens = {
        "MARKET_DATA_CREDENTIALS_MISSING",
        "MARKET_DATA_AUTH_FAILED",
        "MARKET_DATA_PROVIDER_ERROR",
        "MARKET_DATA_EMPTY_RESPONSE",
        "MARKET_CLOSED_OR_NO_BARS",
        "MARKET_DATA_STALE",
        "INSUFFICIENT_BARS_FOR_SIGNAL",
        "INPUT_EMPTY",
    }
    for f in _diag_files(days, as_of, diag_dir):
        for row in _iter_jsonl(f):
            token = row.get("token")
            detail = row.get("detail") or {}
            sym = detail.get("symbol") if isinstance(detail, dict) else None
            if not sym or sym not in universe_set:
                continue
            if token in failure_tokens:
                out[sym][token] += 1
    return {sym: dict(c) for sym, c in out.items()}


def _read_snapshot_liquidity(
    symbol: str, snapshot_dir: Path,
) -> tuple[Optional[float], Optional[str]]:
    safe = symbol.replace("/", "_")
    path = snapshot_dir / f"{safe}.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    volumes = data.get("volume")
    if not isinstance(volumes, list) or not volumes:
        return None, None
    latest = volumes[-1]
    try:
        v = float(latest)
    except Exception:
        return None, None
    if v >= 1_000_000:
        proxy = "HIGH"
    elif v >= 100_000:
        proxy = "MEDIUM"
    elif v > 0:
        proxy = "LOW"
    else:
        proxy = "UNKNOWN"
    return v, proxy


# ─── Recommendation logic ────────────────────────────────────────────────────


def _classify(stats: SymbolStats) -> tuple[str, str]:
    """Return (recommendation, advisory_reason). PURE function — no
    side effects. NEVER auto-modifies the live universe.
    """
    rows = stats.ledger_rows
    nm = stats.near_misses
    fail_total = sum((stats.data_failure_tokens or {}).values())

    # Data missing → NEEDS_DATA.
    if fail_total >= 5 and rows == 0:
        return "NEEDS_DATA", (
            f"{fail_total} data-failure diag events; 0 ledger rows; "
            "data availability blocks evidence collection")

    # Low liquidity → REJECT_HIGH_SPREAD advisory.
    if stats.inferred_liquidity_proxy in ("LOW", "UNKNOWN") and rows == 0:
        return "REJECT_HIGH_SPREAD", (
            f"latest volume proxy={stats.inferred_liquidity_proxy}; "
            "high effective spread expected; operator review")

    # Promising near-miss density → OBSERVE_ONLY_ADD.
    if nm >= 5 and stats.candidates == 0:
        return "OBSERVE_ONLY_ADD", (
            f"{nm} near-misses in window with 0 candidates; "
            "suggest observation-only addition")

    # Silent symbol → REMOVE_LOW_QUALITY (advisory).
    if rows == 0 and nm == 0 and fail_total == 0:
        return "REMOVE_LOW_QUALITY", (
            "0 ledger rows, 0 near-misses, 0 data failures; "
            "candidate for removal review")

    # Default: KEEP.
    return "KEEP", f"rows={rows}, near_misses={nm}, candidates={stats.candidates}"


# ─── Build report ─────────────────────────────────────────────────────────────


def build_report(
    *,
    as_of: datetime,
    days: int = 7,
    universe: Optional[tuple[str, ...]] = None,
    ledger_dir: Optional[Path] = None,
    diag_dir: Optional[Path] = None,
    near_miss_dir: Optional[Path] = None,
    snapshot_dir: Optional[Path] = None,
) -> dict[str, Any]:
    eq_universe, cr_universe = _load_default_universe()
    if universe is None:
        universe = tuple(eq_universe + cr_universe)
    ld = ledger_dir if ledger_dir is not None else LEDGER_DIR
    dd = diag_dir if diag_dir is not None else DIAG_DIR
    nm = near_miss_dir if near_miss_dir is not None else NEAR_MISS_DIR
    sd = snapshot_dir if snapshot_dir is not None else SNAPSHOT_DIR_DEFAULT

    ledger_agg = _aggregate_ledger(universe, days, as_of, ld)
    near_miss_agg = _aggregate_near_miss(universe, days, as_of, nm)
    failure_agg = _aggregate_data_failures(universe, days, as_of, dd)

    rows: list[dict] = []
    rec_distribution: collections.Counter = collections.Counter()
    for symbol in universe:
        asset_class = "crypto" if "/" in symbol else "us_equity"
        vol, liquidity_proxy = _read_snapshot_liquidity(symbol, sd)
        stats = SymbolStats(
            symbol=symbol,
            asset_class=asset_class,
            ledger_rows=ledger_agg.get(symbol, {}).get("rows", 0),
            candidates=ledger_agg.get(symbol, {}).get("candidates", 0),
            near_misses=near_miss_agg.get(symbol, 0),
            data_failure_tokens=failure_agg.get(symbol, {}),
            latest_volume=vol,
            inferred_liquidity_proxy=liquidity_proxy,
        )
        rec, reason = _classify(stats)
        rec_distribution[rec] += 1
        rec_data = stats.to_dict()
        rec_data["recommendation"] = rec
        rec_data["advisory_reason"] = reason
        rec_data["modifies_live_universe"] = False
        rows.append(rec_data)

    return {
        "version":              VERSION,
        "generated_at_iso":     datetime.now(timezone.utc).isoformat(),
        "as_of":                as_of.isoformat(),
        "window_days":          days,
        "universe_size":        len(universe),
        "equity_universe":      list(eq_universe),
        "crypto_universe":      list(cr_universe),
        "recommendation_distribution": dict(rec_distribution),
        "rows":                 rows,
        "standing_markers":     list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":         False,
            "allow_broker_paper":        False,
            "live_trading_supported":    False,
            "modifies_state_json":       False,
            "auto_adds_trade_symbols":   False,
            "auto_removes_symbols":      False,
            "modifies_live_universe":    False,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Universe opportunity review ({rep['version']})")
    lines.append("")
    lines.append(f"**Generated:** `{rep['generated_at_iso']}`")
    lines.append(f"**As of:** `{rep['as_of']}`")
    lines.append(f"**Window:** last {rep['window_days']} days")
    lines.append(f"**Universe size:** {rep['universe_size']}")
    lines.append("")
    lines.append("## Recommendation distribution")
    lines.append("")
    dist = rep["recommendation_distribution"]
    lines.append("| Recommendation | Count |")
    lines.append("|---|---|")
    for rec in RECOMMENDATION_TYPES:
        lines.append(f"| `{rec}` | {dist.get(rec, 0)} |")
    lines.append("")
    lines.append("## Per-symbol detail")
    lines.append("")
    lines.append(
        "| Symbol | Asset | Rec | Rows | Cands | Near | Fail | "
        "Vol | Liq | Reason |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rep["rows"]:
        fail_total = sum((r.get("data_failure_token_distribution")
                          or {}).values())
        vol = r.get("latest_volume")
        vol_s = f"{int(vol):,}" if isinstance(vol, (int, float)) else "n/a"
        liq = r.get("inferred_liquidity_proxy") or "n/a"
        lines.append(
            f"| `{r['symbol']}` | {r['asset_class']} | "
            f"**{r['recommendation']}** | {r['ledger_rows_7d']} | "
            f"{r['candidates_7d']} | {r['near_miss_count_7d']} | "
            f"{fail_total} | {vol_s} | {liq} | {r['advisory_reason']} |"
        )
    if not rep["rows"]:
        lines.append("| (empty universe) | | | | | | | | | |")

    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- NEVER adds new trade-eligible symbols automatically.")
    lines.append("- NEVER auto-removes a symbol.")
    lines.append(
        "- `OBSERVE_ONLY_ADD` is an advisory marker only — it does NOT "
        "modify the live universe."
    )
    lines.append("- NEVER makes network calls. NEVER imports `alpaca_orders`.")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in rep["standing_markers"]:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="v3.26 — Universe opportunity review (Agent 3B / ETAP 6).",
    )
    p.add_argument("--as-of", default=None)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    rep = build_report(as_of=as_of, days=args.days)
    md = render_md(rep)

    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        dist = rep["recommendation_distribution"]
        print(
            "Recommendations: "
            + ", ".join(f"{k}={dist.get(k, 0)}" for k in RECOMMENDATION_TYPES)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

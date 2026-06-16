#!/usr/bin/env python3
"""v3.28 ETAP 7 (2026-06-16) — Equity-gap reconciliation report.

CONTRACT (do not loosen)
------------------------
This script is a **read-only** reconciler. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* changes thresholds,
* enables LIVE_TRADING / ALLOW_BROKER_PAPER / EDGE_GATE_ENABLED.

PURPOSE
-------
Read locally-recorded evidence (runtime_state, positions snapshot,
recent journal autonomy realized P/L, opportunity ledger context,
optional dashboard snapshot) and decompose today's equity into:

  cash + equity_unrealized + realized_pl_today + held_for_orders
  + crypto_positions + fees_slippage + unexplained

Emit:

  learning-loop/equity_gap_reconciliation_2026-06-16.json
  learning-loop/equity_gap_reconciliation_latest.json
  docs/EQUITY_GAP_RECONCILIATION_2026-06-16.md

Verdicts:

  gap_pct > 2   -> EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR
  0.5 < gap <=2 -> EQUITY_GAP_WARN
  gap_pct <=0.5 -> EQUITY_GAP_OK

Thresholds are constants — this script NEVER reduces them, and it
NEVER auto-clears safe_mode. The verdict feeds the allocator
incident gate (see ``shared/allocator_incident_gate.py``).

STANDING MARKERS
----------------
``EDGE_GATE_ENABLED=false``
``ALLOW_BROKER_PAPER=false``
``LIVE_TRADING_UNSUPPORTED``
``NO_ORDER_PLACEMENT``
``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Standing invariants — checked by tests ────────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

# ── Thresholds (frozen constants, NEVER auto-tuned) ───────────────────────────
EQUITY_GAP_OK_THRESHOLD_PCT       = 0.5   # <=0.5%  -> OK
EQUITY_GAP_WARN_UPPER_PCT         = 2.0   # 0.5..2  -> WARN
EQUITY_GAP_BLOCKS_ALLOCATOR_PCT   = 2.0   # >2     -> BLOCKS_ALLOCATOR

VERDICT_OK     = "EQUITY_GAP_OK"
VERDICT_WARN   = "EQUITY_GAP_WARN"
VERDICT_BLOCKS = "EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR"

# v3.29 ETAP 4 (2026-06-16) — additional verdicts surfaced when the
# allocator gate reads the report. We never *emit* SCHEMA_INVALID or
# STALE from this script (it always writes a fresh, complete report);
# they exist because the gate needs to react to *future* reports that
# might be missing fields or be older than 24h.
VERDICT_SCHEMA_INVALID = "EQUITY_GAP_SCHEMA_INVALID"
VERDICT_STALE          = "EQUITY_GAP_STALE"

CONFIDENCE_LOW    = "LOW"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_HIGH   = "HIGH"

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Storage paths ────────────────────────────────────────────────────────────

def _out_dir() -> Path:
    env = os.environ.get("EQUITY_GAP_OUTPUT_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop"


def _docs_dir() -> Path:
    env = os.environ.get("EQUITY_GAP_DOCS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Local evidence loaders ────────────────────────────────────────────────────

def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _runtime_state_path() -> Path:
    env = os.environ.get("RUNTIME_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "runtime_state.json"


def _load_peak_equity_from_runtime() -> Optional[float]:
    raw = _read_json(_runtime_state_path())
    if not isinstance(raw, dict):
        return None
    ig = raw.get("intraday_governor") or {}
    if not isinstance(ig, dict):
        return None
    for key in ("intraday_peak_equity", "peak_equity"):
        v = ig.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _load_current_equity_from_runtime() -> Optional[float]:
    raw = _read_json(_runtime_state_path())
    if not isinstance(raw, dict):
        return None
    ig = raw.get("intraday_governor") or {}
    if not isinstance(ig, dict):
        return None
    v = ig.get("current_equity")
    if v is None:
        v = ig.get("session_start_equity")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_positions_snapshot() -> dict:
    """Return mapping symbol -> position dict from runtime_state."""
    raw = _read_json(_runtime_state_path())
    if not isinstance(raw, dict):
        return {}
    pos = raw.get("positions")
    if not isinstance(pos, dict):
        return {}
    return pos


def _load_dashboard_snapshot() -> dict:
    """Optional dashboard snapshot — read-only."""
    p = _REPO_ROOT / "learning-loop" / "dashboard_snapshot_latest.json"
    raw = _read_json(p)
    if isinstance(raw, dict):
        return raw
    return {}


def _load_today_realized_pl() -> float:
    """Sum realized P/L found in today's journal/autonomy JSONL.

    Fail-soft: returns 0.0 when the file is missing or unparseable.
    Looks for entries with one of these shapes:

      row.risk_metrics.realized_pl_usd
      row.realized_pl_usd
      row.result_extras.realized_pl_usd
    """
    path = _audit_dir() / f"{_today_iso_date()}.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for src in (row, row.get("risk_metrics") or {}, row.get("result_extras") or {}):
                    if not isinstance(src, dict):
                        continue
                    v = src.get("realized_pl_usd")
                    if v is None:
                        continue
                    try:
                        total += float(v)
                    except (TypeError, ValueError):
                        continue
                    break
    except OSError:
        return 0.0
    return total


# ── Decomposition ────────────────────────────────────────────────────────────

@dataclass
class EquityComponents:
    cash:                 float = 0.0
    equity_unrealized:    float = 0.0
    realized_pl_today:    float = 0.0
    held_for_orders:      float = 0.0
    crypto_positions:     float = 0.0
    fees_slippage:        float = 0.0
    unexplained:          float = 0.0

    def total(self) -> float:
        return (
            self.cash
            + self.equity_unrealized
            + self.realized_pl_today
            + self.held_for_orders
            + self.crypto_positions
            + self.fees_slippage
            + self.unexplained
        )


def _decompose(*,
               current_equity: float,
               peak_equity: Optional[float],
               positions: dict,
               dashboard: dict,
               realized_pl_today: float) -> EquityComponents:
    """Best-effort decomposition.

    The dashboard snapshot, when present, takes precedence for `cash`
    and `held_for_orders`. Otherwise everything else is computed from
    runtime_state and the audit journal.

    The `unexplained` component soaks up any residual delta — we always
    return a balanced row so the operator can see where the gap sits.
    """
    cash = 0.0
    held = 0.0
    if isinstance(dashboard, dict):
        for k in ("cash_balance", "cash", "buying_power_cash"):
            if k in dashboard:
                try:
                    cash = float(dashboard[k])
                    break
                except (TypeError, ValueError):
                    continue
        for k in ("held_for_orders", "held_for_orders_usd"):
            if k in dashboard:
                try:
                    held = float(dashboard[k])
                    break
                except (TypeError, ValueError):
                    continue

    # Sum unrealized + crypto positions from runtime_state.
    equity_unrealized = 0.0
    crypto_positions = 0.0
    for sym, p in (positions or {}).items():
        if not isinstance(p, dict):
            continue
        qty = p.get("entry_qty")
        price = p.get("current_price") or p.get("entry_price")
        if qty is None or price is None:
            continue
        try:
            value = float(qty) * float(price)
        except (TypeError, ValueError):
            continue
        if sym.upper().endswith("USD") and "/" not in sym:
            crypto_positions += value
        elif "/" in sym:
            crypto_positions += value
        else:
            equity_unrealized += value

    fees_slippage = 0.0
    sum_known = (
        cash + equity_unrealized + realized_pl_today
        + held + crypto_positions + fees_slippage
    )
    unexplained = float(current_equity) - sum_known

    return EquityComponents(
        cash=cash,
        equity_unrealized=equity_unrealized,
        realized_pl_today=realized_pl_today,
        held_for_orders=held,
        crypto_positions=crypto_positions,
        fees_slippage=fees_slippage,
        unexplained=unexplained,
    )


def _gap_pct(current: float, peak: Optional[float]) -> Optional[float]:
    if peak is None or peak <= 0:
        return None
    return ((float(current) - float(peak)) / float(peak)) * 100.0


def _verdict_for(gap_pct: Optional[float]) -> str:
    if gap_pct is None:
        return VERDICT_OK
    g = abs(float(gap_pct))
    if g > EQUITY_GAP_BLOCKS_ALLOCATOR_PCT:
        return VERDICT_BLOCKS
    if g > EQUITY_GAP_OK_THRESHOLD_PCT:
        return VERDICT_WARN
    return VERDICT_OK


# ── Output writers ───────────────────────────────────────────────────────────

def _write_json(payload: dict, dated: bool = True) -> Path:
    out = _out_dir()
    out.mkdir(parents=True, exist_ok=True)
    name = (f"equity_gap_reconciliation_{_today_iso_date()}.json"
            if dated else "equity_gap_reconciliation_latest.json")
    path = out / name
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    return path


def _write_markdown(payload: dict) -> Path:
    out = _docs_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"EQUITY_GAP_RECONCILIATION_{_today_iso_date()}.md"
    components = payload.get("components") or {}
    rows = []
    for k in ("cash", "equity_unrealized", "realized_pl_today",
              "held_for_orders", "crypto_positions",
              "fees_slippage", "unexplained"):
        rows.append(f"| {k} | {components.get(k, 0.0):.2f} |")
    body = [
        f"# Equity gap reconciliation — {_today_iso_date()}",
        "",
        f"_Generated at {_now_iso()} by `scripts/reconcile_equity_gap.py`._",
        "",
        "## Inputs",
        "",
        f"- current_equity: {payload.get('current_equity', 0.0):.2f}",
        f"- peak_equity:    {payload.get('peak_equity')}",
        f"- gap_pct:        {payload.get('gap_pct')}",
        "",
        "## Component decomposition",
        "",
        "| Component | USD |",
        "|-----------|-----|",
        *rows,
        f"| **total** | {sum(float(components.get(k, 0.0)) for k in components):.2f} |",
        "",
        f"## Verdict: **{payload.get('verdict')}**",
        "",
        "## Standing markers (do not remove)",
        "",
        "- `EDGE_GATE_ENABLED=false`",
        "- `ALLOW_BROKER_PAPER=false`",
        "- `LIVE_TRADING_UNSUPPORTED`",
        "- `NO_ORDER_PLACEMENT`",
        "- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body))
    return path


def _emit_audit(row: dict) -> None:
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return


# ── Public API ────────────────────────────────────────────────────────────────

def build_report(*,
                 current_equity: Optional[float] = None,
                 peak_equity: Optional[float] = None,
                 positions: Optional[dict] = None,
                 dashboard: Optional[dict] = None,
                 realized_pl_today: Optional[float] = None,
                 ) -> dict:
    """Build the reconciliation report payload (without writing)."""
    if current_equity is None:
        current_equity = _load_current_equity_from_runtime() or 0.0
    if peak_equity is None:
        peak_equity = _load_peak_equity_from_runtime()
    if positions is None:
        positions = _load_positions_snapshot()
    if dashboard is None:
        dashboard = _load_dashboard_snapshot()
    if realized_pl_today is None:
        realized_pl_today = _load_today_realized_pl()

    components = _decompose(
        current_equity=current_equity,
        peak_equity=peak_equity,
        positions=positions or {},
        dashboard=dashboard or {},
        realized_pl_today=realized_pl_today,
    )
    gap_pct = _gap_pct(current_equity, peak_equity)
    verdict = _verdict_for(gap_pct)

    # v3.29 ETAP 4 (2026-06-16) — top-level schema additions.
    # The allocator gate now reads these fields directly so the
    # equity-gap check no longer depends on the raw % alone.
    gap_amount = None
    if peak_equity is not None:
        try:
            gap_amount = float(current_equity) - float(peak_equity)
        except (TypeError, ValueError):
            gap_amount = None
    block_allocator = (verdict == VERDICT_BLOCKS)

    # Confidence heuristic: more evidence = higher confidence.
    # - HIGH when both equity AND a non-empty positions snapshot are
    #   present AND dashboard snapshot is present.
    # - MEDIUM when equity + positions present (no dashboard).
    # - LOW otherwise.
    has_equity = peak_equity is not None and float(current_equity) > 0
    has_positions = bool(positions)
    has_dashboard = bool(dashboard)
    if has_equity and has_positions and has_dashboard:
        confidence = CONFIDENCE_HIGH
    elif has_equity and has_positions:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    generated_at_iso = _now_iso()

    evidence = {
        "runtime_state":      {"path": "learning-loop/runtime_state.json",
                                "peak_equity_source": "intraday_governor"},
        "positions_snapshot": {"path": "learning-loop/runtime_state.json::positions",
                                "count": len(positions or {})},
        "dashboard_snapshot": {"path": "learning-loop/dashboard_snapshot_latest.json",
                                "present": has_dashboard},
        "audit_realized_pl":  {"path": f"journal/autonomy/{_today_iso_date()}.jsonl",
                                "realized_pl_today_usd": float(realized_pl_today)},
    }

    payload = {
        "schema_version":     "v3.29",
        "ts_iso":             generated_at_iso,
        "generated_at_iso":   generated_at_iso,
        "current_equity":     float(current_equity),
        "peak_equity":        peak_equity,
        "gap_pct":            gap_pct,
        "gap_amount":         gap_amount,
        "verdict":            verdict,
        "status":             verdict,           # back-compat mirror
        "block_allocator":    block_allocator,
        "confidence":         confidence,
        "evidence":           evidence,
        "components":         asdict(components),
        "thresholds": {
            "ok_pct":                 EQUITY_GAP_OK_THRESHOLD_PCT,
            "warn_upper_pct":         EQUITY_GAP_WARN_UPPER_PCT,
            "blocks_allocator_pct":   EQUITY_GAP_BLOCKS_ALLOCATOR_PCT,
        },
        "standing_markers": [
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ],
    }
    return payload


def write_outputs(payload: dict) -> dict:
    """Persist the payload + audit row. Returns dict of written paths."""
    dated_json = _write_json(payload, dated=True)
    latest_json = _write_json(payload, dated=False)
    md_path = _write_markdown(payload)

    _emit_audit({
        "decision_type":  "EQUITY_GAP_RECONCILIATION",
        "actor":          "reconcile_equity_gap",
        "verdict":        payload.get("verdict"),
        "gap_pct":        payload.get("gap_pct"),
        "current_equity": payload.get("current_equity"),
        "peak_equity":    payload.get("peak_equity"),
        "ts_iso":         _now_iso(),
        "reversible":     True,
        "status":         "placed",
    })

    return {
        "json_dated":  str(dated_json),
        "json_latest": str(latest_json),
        "markdown":    str(md_path),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="reconcile_equity_gap.py",
        description="Read-only equity-gap reconciliation report. Never calls broker.",
    )
    p.add_argument("--dry-run", default="false",
                   help="When 'true' the script prints the payload without "
                        "writing any output. Default 'false' (write outputs).")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    dry_run = _str_to_bool(args.dry_run)
    payload = build_report()
    print(f"reconcile_equity_gap: verdict={payload.get('verdict')}")
    print(f"  current_equity={payload.get('current_equity')}")
    print(f"  peak_equity={payload.get('peak_equity')}")
    print(f"  gap_pct={payload.get('gap_pct')}")
    if not dry_run:
        paths = write_outputs(payload)
        print(f"  json_dated:  {paths['json_dated']}")
        print(f"  json_latest: {paths['json_latest']}")
        print(f"  markdown:    {paths['markdown']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "EQUITY_GAP_OK_THRESHOLD_PCT",
    "EQUITY_GAP_WARN_UPPER_PCT",
    "EQUITY_GAP_BLOCKS_ALLOCATOR_PCT",
    "VERDICT_OK",
    "VERDICT_WARN",
    "VERDICT_BLOCKS",
    "VERDICT_SCHEMA_INVALID",
    "VERDICT_STALE",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_HIGH",
    "EquityComponents",
    "build_report",
    "write_outputs",
    "main",
]

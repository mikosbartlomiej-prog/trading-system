#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Backfill snapshot seeder (replay-only, no fabrication).

Seeds ``learning-loop/backfill_snapshots/<symbol>.json`` from REAL local
sources so the v3.26 replay-discovery layer can produce non-trivial output
without ever fetching live data or fabricating OHLCV.

Source precedence (per symbol)
------------------------------
1. ``backtest/.cache/<SYMBOL>-<from>-<to>.json`` — REAL_MARKET_SNAPSHOT.
   Full OHLCV (close/high/low/open/volume/time parallel lists). Drop-in
   for replay strategies. Preserved verbatim with a thin envelope.
2. ``learning-loop/opportunity_ledger/*.jsonl`` rows — LEDGER_DERIVED_REPLAY_ONLY.
   Point-in-time observations: per ledger row we extract whatever
   bar-like fields the ``raw_signal`` block carries (typically
   ``price``, ``rsi``, ``volume_ratio``, ``move_24h_pct``,
   ``btc_1h_change``). NEVER fabricates ``open``/``high``/``low`` —
   if those are absent we leave them absent and tag the snapshot
   ``PARTIAL_BARS``.
3. ``learning-loop/shadow_evidence/*.json`` — SHADOW_EVIDENCE_DERIVED_REPLAY_ONLY.
   Status JSONs only; if a record carries embedded ``raw_signal``
   data we extract it.

Hard-safety rules (cannot be opted out of)
------------------------------------------
- NEVER fetches live market data. NEVER makes any network call.
- NEVER imports ``alpaca_orders`` (verified by AST test).
- NEVER generates synthetic OHLCV. If a source has insufficient
  fields we write the partial data with a ``PARTIAL_BARS`` flag —
  we do NOT make up high/low/close.
- NEVER writes to ``paper_experiments`` / ``opportunity_ledger`` /
  ``observation_records`` / ``state.json`` / ``runtime_state.json``.
- Every emitted snapshot carries ``is_paper_trade=False``,
  ``is_real_market_evidence=False`` (replay-only), ``is_shadow_fill=False``,
  ``mode="REPLAY_ONLY"``.
- Standing markers footer reproduced in every artefact.

Outputs
-------
- ``learning-loop/backfill_snapshots/<symbol>.json`` (one per seeded symbol)
- ``docs/BACKFILL_SNAPSHOT_STATUS.md`` (summary)
- ``learning-loop/backfill_snapshot_status_latest.json`` (machine-readable)

Status verdicts
---------------
- ``NO_LOCAL_BACKFILL_DATA``         — no usable local source found
- ``LEDGER_DERIVED_PARTIAL``         — only point-in-time rows available
- ``LOCAL_BACKFILL_AVAILABLE``       — at least one symbol seeded from
                                       full OHLCV cache
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_OUT_DIR_DEFAULT = REPO_ROOT / "learning-loop" / "backfill_snapshots"
BACKTEST_CACHE_DIR = REPO_ROOT / "backtest" / ".cache"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
SHADOW_EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"

STATUS_MD_PATH = REPO_ROOT / "docs" / "BACKFILL_SNAPSHOT_STATUS.md"
STATUS_JSON_PATH = (
    REPO_ROOT / "learning-loop" / "backfill_snapshot_status_latest.json"
)

# ─── Standing markers ─────────────────────────────────────────────────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "REPLAY_NEVER_COUNTS_AS_PAPER",
    "REPLAY_NEVER_COUNTS_AS_REAL_MARKET",
    "REPLAY_NEVER_AUTO_ENABLES_STRATEGY",
    "SEEDER_DOES_NOT_FABRICATE_OHLCV",
    "SEEDER_DOES_NOT_FETCH_NETWORK",
)

VERSION = "v3.27.0"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True, check=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _safe_filename(symbol: str) -> str:
    """Replay convention: '/' → '_'."""
    return symbol.replace("/", "_")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel_to_repo(p: Path) -> str:
    """Best-effort relative-to-repo path; falls back to absolute string
    when the path is outside REPO_ROOT (e.g. test fixtures in /tmp)."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except (ValueError, AttributeError):
        return str(p)


def _envelope(
    *,
    symbol: str,
    source_label: str,
    data_quality: str,
    bars: dict,
    minimum_fields_present: bool,
    partial_bars: bool,
    origin_files: list[str],
    extra_meta: Optional[dict] = None,
) -> dict[str, Any]:
    """Build the canonical snapshot envelope.

    Layout merges the bars at the TOP LEVEL so the v3.26 reader
    (``_read_snapshot`` → ``bars["close"]`` indexing) works without
    modification. Metadata lives alongside.
    """
    env: dict[str, Any] = dict(bars)  # ← top-level close/high/low/open/...
    env["__seed_meta__"] = {
        "version":                  VERSION,
        "generated_at_iso":         _now_iso(),
        "symbol":                   symbol,
        "source_label":             source_label,
        "data_quality":             data_quality,
        "mode":                     "REPLAY_ONLY",
        "is_paper_trade":           False,
        "is_real_market_evidence":  False,
        "is_shadow_fill":           False,
        "is_signal_observation":    False,
        "minimum_fields_present":   bool(minimum_fields_present),
        "partial_bars":             bool(partial_bars),
        "origin_files":             list(origin_files),
        "standing_markers":         list(STANDING_MARKERS),
    }
    if extra_meta:
        env["__seed_meta__"].update(extra_meta)
    return env


# ─── Source: backtest/.cache/ (REAL OHLCV) ────────────────────────────────────


_CACHE_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Za-z0-9._]+)-\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}\.json$"
)


def discover_backtest_cache(cache_dir: Path) -> dict[str, list[Path]]:
    """Return {symbol: [paths]} of cached OHLCV files (real Alpaca daily bars)."""
    out: dict[str, list[Path]] = defaultdict(list)
    if not cache_dir.exists() or not cache_dir.is_dir():
        return {}
    for p in sorted(cache_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".json"):
            continue
        m = _CACHE_FILENAME_RE.match(p.name)
        if not m:
            continue
        out[m.group("symbol")].append(p)
    return dict(out)


def seed_from_backtest_cache(
    cache_dir: Path,
    *,
    symbol_filter: Optional[set[str]] = None,
) -> dict[str, dict]:
    """Build snapshot envelopes from real OHLCV cached files.

    Returns ``{symbol: envelope_dict}``. Pure compute — no writes.
    """
    snapshots: dict[str, dict] = {}
    discovered = discover_backtest_cache(cache_dir)
    for symbol, paths in discovered.items():
        if symbol_filter is not None and symbol not in symbol_filter:
            continue
        # Pick the most recent / longest by reading them all and keeping
        # the file with the most close values.
        best_bars: Optional[dict] = None
        best_path: Optional[Path] = None
        for p in paths:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            closes = raw.get("close")
            if not isinstance(closes, list) or not closes:
                continue
            if best_bars is None or len(closes) > len(best_bars.get("close", [])):
                best_bars = raw
                best_path = p
        if best_bars is None or best_path is None:
            continue

        # Ensure parallel field lengths agree (cache files do; defensive).
        n_close = len(best_bars["close"])
        keep = {}
        for key in ("close", "high", "low", "open", "volume", "time"):
            v = best_bars.get(key)
            if isinstance(v, list) and len(v) == n_close:
                keep[key] = list(v)
        # Real OHLCV requires close+high+low at minimum for replay
        # heuristics (threshold-cross uses ``high``).
        minimum_fields_present = all(k in keep for k in ("close", "high", "low"))
        partial_bars = not minimum_fields_present
        env = _envelope(
            symbol=symbol,
            source_label="REAL_MARKET_SNAPSHOT",
            data_quality="REAL_MARKET_DATA",
            bars=keep,
            minimum_fields_present=minimum_fields_present,
            partial_bars=partial_bars,
            origin_files=[_rel_to_repo(best_path)],
            extra_meta={
                "bars_count":          n_close,
                "time_range_start":    best_bars.get("time", [None])[0],
                "time_range_end":      best_bars.get("time", [None])[-1],
            },
        )
        snapshots[symbol] = env
    return snapshots


# ─── Source: opportunity_ledger (LEDGER_DERIVED_REPLAY_ONLY) ──────────────────


def _iter_ledger_files(ledger_dir: Path) -> Iterable[Path]:
    if not ledger_dir.exists() or not ledger_dir.is_dir():
        return []
    return sorted(p for p in ledger_dir.iterdir() if p.suffix == ".jsonl")


def seed_from_opportunity_ledger(
    ledger_dir: Path,
    *,
    symbol_filter: Optional[set[str]] = None,
    max_rows_per_symbol: int = 5000,
) -> dict[str, dict]:
    """Build PARTIAL_BARS snapshot envelopes from ledger rows.

    Each ledger row contains a ``raw_signal`` dict with ``price``,
    ``rsi``, ``stop_loss``, ``take_profit`` (and sometimes
    ``volume_ratio``, ``move_24h_pct`` if the upstream monitor
    populated them). We aggregate per-symbol time-ordered observation
    sequences. NO synthetic high/low/open/volume — we only emit what
    is genuinely present, and tag ``partial_bars=True``.

    Returns ``{symbol: envelope_dict}``.
    """
    per_symbol_rows: dict[str, list[dict]] = defaultdict(list)
    files = list(_iter_ledger_files(ledger_dir))
    for fp in files:
        try:
            with fp.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    sym = row.get("symbol")
                    if not sym:
                        continue
                    if symbol_filter is not None and sym not in symbol_filter:
                        continue
                    per_symbol_rows[sym].append(row)
        except Exception:
            continue

    snapshots: dict[str, dict] = {}
    for sym, rows in per_symbol_rows.items():
        # Sort by timestamp (newest last) so the replay window sees
        # chronological progression.
        rows.sort(key=lambda r: r.get("timestamp") or "")
        if max_rows_per_symbol and len(rows) > max_rows_per_symbol:
            rows = rows[-max_rows_per_symbol:]

        close_list: list[float] = []
        rsi_list: list[Optional[float]] = []
        time_list: list[str] = []
        volume_ratio_list: list[Optional[float]] = []
        move_24h_list: list[Optional[float]] = []
        origin = set()

        for r in rows:
            raw = r.get("raw_signal") if isinstance(r.get("raw_signal"), dict) else {}
            price = raw.get("price")
            if isinstance(price, (int, float)) and price > 0:
                close_list.append(float(price))
                rsi_v = raw.get("rsi")
                rsi_list.append(
                    float(rsi_v) if isinstance(rsi_v, (int, float)) else None
                )
                time_list.append(r.get("timestamp") or "")
                vr = raw.get("volume_ratio")
                volume_ratio_list.append(
                    float(vr) if isinstance(vr, (int, float)) else None
                )
                mv = raw.get("move_24h_pct")
                move_24h_list.append(
                    float(mv) if isinstance(mv, (int, float)) else None
                )
                origin.add(r.get("schema_version", "unknown"))

        if not close_list:
            continue

        # PARTIAL_BARS: we have close+time+rsi, but NO high/low/open/volume
        # arrays. The replay reader will see no ``high``/``low`` keys and
        # fall back to RSI-based near-miss heuristics (which work — see
        # replay_entry_candidate_discovery._rsi_distance_to_band).
        bars: dict[str, Any] = {
            "close": close_list,
            "time":  time_list,
        }
        # Sidecar series for any future "current-state" layer; replay
        # discovery script doesn't read these keys today.
        sidecar = {
            "rsi_observed":      rsi_list,
            "volume_ratio":      volume_ratio_list,
            "move_24h_pct":      move_24h_list,
        }
        env = _envelope(
            symbol=sym,
            source_label="LEDGER_DERIVED_REPLAY_ONLY",
            data_quality="PARTIAL_BARS",
            bars=bars,
            minimum_fields_present=False,  # missing high/low/volume
            partial_bars=True,
            origin_files=[
                _rel_to_repo(p)
                for p in files
                if p.parent == ledger_dir
            ][:14],  # cap origin list to 14 entries (≈2 weeks)
            extra_meta={
                "rows_consumed":            len(close_list),
                "schema_versions_observed": sorted(origin),
                "sidecar":                  sidecar,
            },
        )
        snapshots[sym] = env
    return snapshots


# ─── Source: shadow_evidence/*.json (best-effort) ─────────────────────────────


def seed_from_shadow_evidence(
    shadow_dir: Path,
    *,
    symbol_filter: Optional[set[str]] = None,
) -> dict[str, dict]:
    """Best-effort extraction from shadow_evidence status JSONs.

    Most shadow_evidence files are AUDIT status summaries (no bars).
    If any file carries an embedded ``raw_signal`` dict per record we
    can build a PARTIAL_BARS snapshot the same way as the ledger lane.
    """
    snapshots: dict[str, dict] = {}
    if not shadow_dir.exists() or not shadow_dir.is_dir():
        return snapshots
    per_symbol_rows: dict[str, list[dict]] = defaultdict(list)
    for fp in sorted(shadow_dir.iterdir()):
        if not fp.is_file() or not fp.name.endswith(".json"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Two shapes: list-of-records, or top-level dict with "records".
        records: list[dict] = []
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            for key in ("records", "rows", "shadow_records"):
                v = data.get(key)
                if isinstance(v, list):
                    records.extend(r for r in v if isinstance(r, dict))
        for r in records:
            sym = r.get("symbol")
            if not sym:
                continue
            if symbol_filter is not None and sym not in symbol_filter:
                continue
            raw = r.get("raw_signal") if isinstance(r.get("raw_signal"), dict) else None
            if not raw:
                continue
            per_symbol_rows[sym].append({
                "timestamp":  r.get("timestamp"),
                "raw_signal": raw,
                "_origin":    fp.name,
            })

    for sym, rows in per_symbol_rows.items():
        rows.sort(key=lambda r: r.get("timestamp") or "")
        close_list: list[float] = []
        time_list: list[str] = []
        for r in rows:
            raw = r["raw_signal"]
            price = raw.get("price")
            if isinstance(price, (int, float)) and price > 0:
                close_list.append(float(price))
                time_list.append(r.get("timestamp") or "")
        if not close_list:
            continue
        env = _envelope(
            symbol=sym,
            source_label="SHADOW_EVIDENCE_DERIVED_REPLAY_ONLY",
            data_quality="PARTIAL_BARS",
            bars={"close": close_list, "time": time_list},
            minimum_fields_present=False,
            partial_bars=True,
            origin_files=sorted({r.get("_origin", "") for r in rows}),
        )
        snapshots[sym] = env
    return snapshots


# ─── Orchestration ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeedResult:
    status: str
    snapshots: dict[str, dict]
    source_label_counts: Counter
    partial_bars_count: int
    backtest_cache_seeded: int
    ledger_derived_seeded: int
    shadow_derived_seeded: int


def build_seed_result(
    *,
    source_filter: Optional[set[str]] = None,
    symbol_filter: Optional[set[str]] = None,
    max_symbols: Optional[int] = None,
    cache_dir: Path = BACKTEST_CACHE_DIR,
    ledger_dir: Path = LEDGER_DIR,
    shadow_dir: Path = SHADOW_EVIDENCE_DIR,
) -> SeedResult:
    """Pure compute — no writes."""
    merged: dict[str, dict] = {}
    backtest_n = 0
    ledger_n = 0
    shadow_n = 0

    if source_filter is None or "backtest_cache" in source_filter:
        from_cache = seed_from_backtest_cache(cache_dir, symbol_filter=symbol_filter)
        for sym, env in from_cache.items():
            merged[sym] = env
        backtest_n = len(from_cache)

    if source_filter is None or "opportunity_ledger" in source_filter:
        from_ledger = seed_from_opportunity_ledger(
            ledger_dir, symbol_filter=symbol_filter,
        )
        for sym, env in from_ledger.items():
            # Real OHLCV beats partial; never overwrite a real snapshot
            # with a ledger-derived partial one.
            existing = merged.get(sym)
            if existing is None:
                merged[sym] = env
                ledger_n += 1
            elif existing["__seed_meta__"]["source_label"] != "REAL_MARKET_SNAPSHOT":
                merged[sym] = env
                ledger_n += 1

    if source_filter is None or "shadow_evidence" in source_filter:
        from_shadow = seed_from_shadow_evidence(
            shadow_dir, symbol_filter=symbol_filter,
        )
        for sym, env in from_shadow.items():
            existing = merged.get(sym)
            if existing is None:
                merged[sym] = env
                shadow_n += 1
            elif existing["__seed_meta__"]["source_label"] not in (
                "REAL_MARKET_SNAPSHOT", "LEDGER_DERIVED_REPLAY_ONLY",
            ):
                merged[sym] = env
                shadow_n += 1

    if max_symbols is not None and len(merged) > max_symbols:
        # Keep highest-quality first (REAL > LEDGER > SHADOW), then
        # alphabetic for stability.
        rank = {
            "REAL_MARKET_SNAPSHOT": 0,
            "LEDGER_DERIVED_REPLAY_ONLY": 1,
            "SHADOW_EVIDENCE_DERIVED_REPLAY_ONLY": 2,
        }
        sorted_syms = sorted(
            merged.keys(),
            key=lambda s: (
                rank.get(merged[s]["__seed_meta__"]["source_label"], 9),
                s,
            ),
        )
        keep = set(sorted_syms[:max_symbols])
        merged = {k: v for k, v in merged.items() if k in keep}

    source_label_counts: Counter = Counter(
        env["__seed_meta__"]["source_label"] for env in merged.values()
    )
    partial_bars_count = sum(
        1 for env in merged.values()
        if env["__seed_meta__"].get("partial_bars")
    )

    if not merged:
        status = "NO_LOCAL_BACKFILL_DATA"
    elif source_label_counts.get("REAL_MARKET_SNAPSHOT", 0) > 0:
        status = "LOCAL_BACKFILL_AVAILABLE"
    else:
        status = "LEDGER_DERIVED_PARTIAL"

    return SeedResult(
        status=status,
        snapshots=merged,
        source_label_counts=source_label_counts,
        partial_bars_count=partial_bars_count,
        backtest_cache_seeded=backtest_n,
        ledger_derived_seeded=ledger_n,
        shadow_derived_seeded=shadow_n,
    )


# ─── Writers ──────────────────────────────────────────────────────────────────


def write_snapshots(
    snapshots: dict[str, dict],
    *,
    out_dir: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Write per-symbol JSON envelopes. Returns list of paths written."""
    written: list[Path] = []
    if dry_run:
        return written
    out_dir.mkdir(parents=True, exist_ok=True)
    for sym, env in snapshots.items():
        path = out_dir / f"{_safe_filename(sym)}.json"
        path.write_text(
            json.dumps(env, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def render_status_md(result: SeedResult, *, out_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"# Backfill snapshot status ({VERSION})")
    lines.append("")
    lines.append(f"**Generated:** `{_now_iso()}`")
    lines.append(f"**Git HEAD:** `{_git_head()}`")
    lines.append(f"**Snapshot dir:** `{_rel_to_repo(out_dir)}`")
    lines.append("")
    lines.append(f"## Status: `{result.status}`")
    lines.append("")
    if result.status == "NO_LOCAL_BACKFILL_DATA":
        lines.append(
            "No usable local OHLCV-bearing source was found. Replay "
            "discovery will continue to report `MISSING_SNAPSHOT` for "
            "every universe symbol. This is an HONEST answer — we did "
            "not fabricate data to fill the gap."
        )
        lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Snapshots written: **{len(result.snapshots)}**")
    lines.append(
        f"- Partial-bars snapshots: **{result.partial_bars_count}** "
        f"(missing one or more of `high`/`low`/`volume`/`open`)"
    )
    lines.append(
        f"- From backtest cache (REAL OHLCV): **{result.backtest_cache_seeded}**"
    )
    lines.append(
        f"- From opportunity ledger (partial): **{result.ledger_derived_seeded}**"
    )
    lines.append(
        f"- From shadow evidence (partial): **{result.shadow_derived_seeded}**"
    )
    lines.append("")
    lines.append("## Source label distribution")
    lines.append("")
    if not result.source_label_counts:
        lines.append("- (none)")
    for label, n in sorted(result.source_label_counts.items()):
        lines.append(f"- `{label}` × **{n}**")
    lines.append("")
    lines.append("## Per-symbol summary")
    lines.append("")
    lines.append("| Symbol | Source | Quality | Bars | Partial | Min fields |")
    lines.append("|---|---|---|---|---|---|")
    if not result.snapshots:
        lines.append("| (no snapshots seeded) | | | | | |")
    for sym in sorted(result.snapshots.keys()):
        env = result.snapshots[sym]
        meta = env["__seed_meta__"]
        bars_count = (
            meta.get("bars_count")
            if meta.get("bars_count") is not None
            else len(env.get("close", []) or [])
        )
        lines.append(
            f"| `{sym}` | {meta['source_label']} | {meta['data_quality']} "
            f"| {bars_count} | {meta['partial_bars']} "
            f"| {meta['minimum_fields_present']} |"
        )
    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- Seeder NEVER fetches live market data.")
    lines.append("- Seeder NEVER fabricates synthetic OHLCV.")
    lines.append("- Seeder NEVER imports `alpaca_orders`.")
    lines.append("- Seeder NEVER writes to opportunity_ledger / paper_experiments / state.json.")
    lines.append(
        "- All snapshots carry `mode=REPLAY_ONLY`, "
        "`is_paper_trade=False`, `is_real_market_evidence=False`."
    )
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


def write_status(
    result: SeedResult,
    *,
    out_dir: Path,
    md_path: Path = STATUS_MD_PATH,
    json_path: Path = STATUS_JSON_PATH,
    dry_run: bool = False,
) -> None:
    md = render_status_md(result, out_dir=out_dir)
    summary = {
        "version":               VERSION,
        "generated_at_iso":      _now_iso(),
        "git_head":              _git_head(),
        "status":                result.status,
        "snapshots_written":     len(result.snapshots),
        "partial_bars_count":    result.partial_bars_count,
        "backtest_cache_seeded": result.backtest_cache_seeded,
        "ledger_derived_seeded": result.ledger_derived_seeded,
        "shadow_derived_seeded": result.shadow_derived_seeded,
        "source_label_counts":   dict(result.source_label_counts),
        "snapshot_dir":          _rel_to_repo(out_dir),
        "per_symbol_summary":    [
            {
                "symbol":              sym,
                "source_label":        env["__seed_meta__"]["source_label"],
                "data_quality":        env["__seed_meta__"]["data_quality"],
                "bars_count":          env["__seed_meta__"].get("bars_count")
                                       or len(env.get("close", []) or []),
                "partial_bars":        env["__seed_meta__"]["partial_bars"],
                "minimum_fields_present":
                    env["__seed_meta__"]["minimum_fields_present"],
            }
            for sym, env in sorted(result.snapshots.items())
        ],
        "standing_markers":      list(STANDING_MARKERS),
        "safety": {
            "is_paper_trade":           False,
            "is_real_market_evidence":  False,
            "is_shadow_fill":           False,
            "fabricates_ohlcv":         False,
            "writes_opportunity_ledger": False,
            "makes_network_call":       False,
        },
    }
    if dry_run:
        return
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            f"{VERSION} — Seed learning-loop/backfill_snapshots/ from "
            "REAL local sources. Never fabricates OHLCV. Never calls "
            "network. Never enables trading."
        ),
    )
    p.add_argument(
        "--source-filter", default=None,
        help=(
            "Comma-separated subset of "
            "{backtest_cache, opportunity_ledger, shadow_evidence}. "
            "Default = all."
        ),
    )
    p.add_argument(
        "--symbol-filter", default=None,
        help="Comma-separated symbol allowlist (default = all discovered).",
    )
    p.add_argument(
        "--max-symbols", type=int, default=None,
        help="Cap number of snapshots written (REAL OHLCV prioritized).",
    )
    p.add_argument(
        "--out-dir", default=None,
        help="Override snapshot output dir.",
    )
    p.add_argument(
        "--cache-dir", default=None,
        help="Override backtest cache dir.",
    )
    p.add_argument(
        "--ledger-dir", default=None,
        help="Override opportunity_ledger dir.",
    )
    p.add_argument(
        "--shadow-dir", default=None,
        help="Override shadow_evidence dir.",
    )
    p.add_argument(
        "--as-of", default=None,
        help="Informational only; seeder does not gate on as-of.",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Compute but write nothing.")
    p.add_argument("--no-write", action="store_true",
                   help="Alias for --dry-run.")
    args = p.parse_args(argv)

    source_filter = (
        {s.strip() for s in args.source_filter.split(",") if s.strip()}
        if args.source_filter else None
    )
    symbol_filter = (
        {s.strip() for s in args.symbol_filter.split(",") if s.strip()}
        if args.symbol_filter else None
    )
    out_dir = Path(args.out_dir) if args.out_dir else SNAPSHOT_OUT_DIR_DEFAULT
    cache_dir = Path(args.cache_dir) if args.cache_dir else BACKTEST_CACHE_DIR
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else LEDGER_DIR
    shadow_dir = Path(args.shadow_dir) if args.shadow_dir else SHADOW_EVIDENCE_DIR

    result = build_seed_result(
        source_filter=source_filter,
        symbol_filter=symbol_filter,
        max_symbols=args.max_symbols,
        cache_dir=cache_dir,
        ledger_dir=ledger_dir,
        shadow_dir=shadow_dir,
    )

    dry_run = bool(args.dry_run or args.no_write)
    write_snapshots(result.snapshots, out_dir=out_dir, dry_run=dry_run)
    write_status(result, out_dir=out_dir, dry_run=dry_run)

    print(f"status={result.status}")
    print(f"snapshots_written={len(result.snapshots)} "
          f"(real={result.backtest_cache_seeded}, "
          f"ledger={result.ledger_derived_seeded}, "
          f"shadow={result.shadow_derived_seeded}, "
          f"partial={result.partial_bars_count})")
    if not dry_run:
        print(f"Wrote {_rel_to_repo(STATUS_MD_PATH)}")
        print(f"Wrote {_rel_to_repo(STATUS_JSON_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

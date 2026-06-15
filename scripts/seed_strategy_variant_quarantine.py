#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Seed first quarantined strategy variants.

Generates a small set of operator-reviewable VARIANT proposals based on
the v3.26 threshold-reality + near-miss output. Each variant is a
SHADOW description — never auto-applied, never reachable from the
runtime trading path.

Hard-safety rules
-----------------
- NEVER promotes a variant. Status starts ``QUARANTINED``.
- ``allowed_modes`` is ALWAYS a subset of ``{"replay", "shadow"}``.
  ``"live"`` / ``"paper"`` / ``"broker_paper"`` are rejected by
  ``shared.strategy_variant_quarantine.validate_allowed_modes``.
- NEVER imports ``shared.alpaca_orders``.
- NEVER makes network calls.
- NEVER mutates ``shared.strategy_quality_gate`` active registry.
- Storage handled by ``shared.strategy_variant_quarantine`` (per-variant
  JSON + JSONL audit row). This script does NOT shadow-write.

Outputs
-------
- ``docs/STRATEGY_VARIANT_QUARANTINE.md``
- ``learning-loop/strategy_variant_quarantine_latest.json``
- Per-variant JSON via the v3.20 quarantine store.
- Daily JSONL audit row via the v3.26 dataclass register call.

Variants seeded
---------------
(All sourced from threshold-reality TOO_STRICT/SHADOW_VARIANT_REVIEW
recommendations + near-miss cluster locations.)

- ``crypto-momentum`` × {rsi_threshold_55, 24h_bracket_relaxed_2pct}
- ``crypto-oversold-bounce`` × {rsi_threshold_33}
- ``momentum-long`` × {breakout_threshold_1_5pct}

USAGE
-----
::

    python3 scripts/seed_strategy_variant_quarantine.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
LATEST_JSON_PATH = (
    REPO_ROOT / "learning-loop" / "strategy_variant_quarantine_latest.json"
)
LATEST_MD_PATH = REPO_ROOT / "docs" / "STRATEGY_VARIANT_QUARANTINE.md"

VERSION = "v3.27.0"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "VARIANT_NEVER_AUTO_PROMOTED",
    "VARIANT_NEVER_REACHES_RUNTIME",
    "VARIANT_NEVER_ENABLES_LIVE_OR_PAPER",
    "SEEDER_DOES_NOT_FETCH_NETWORK",
)


# ─── Lazy import helper ───────────────────────────────────────────────────────


def _load_quarantine_module():
    """Import shared.strategy_variant_quarantine without colliding with
    the same-named v3.20 module on sys.path. Sets a marker the test
    can rely on."""
    added = []
    for p in (str(REPO_ROOT), str(REPO_ROOT / "shared")):
        if p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    try:
        try:
            from shared import strategy_variant_quarantine as mod  # type: ignore
        except ImportError:
            import strategy_variant_quarantine as mod              # type: ignore
        return mod
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


# ─── Variant proposals ────────────────────────────────────────────────────────


# Each VariantSpec produces one StrategyVariant. The set is intentionally
# small — the operator will hand-review each before any shadow observation
# is opened.

VARIANT_SPECS: list[dict[str, Any]] = [
    {
        "variant_id":         "crypto-momentum--rsi_threshold_55",
        "parent_strategy_id": "crypto-momentum",
        "description":        "Lower RSI threshold from 60 to 55 (entry band shift -5 points)",
        "rationale": (
            "threshold reality TOO_STRICT for some 7d windows; relax by 5 "
            "points to surface near-miss cluster around RSI 55-58. "
            "near-miss seed + replay both show density just below 60."
        ),
        "promotion_criteria": {
            "min_replay_n":  30,
            "min_replay_pf": 1.2,
            "min_shadow_n":  10,
            "shadow_outcome_hit_rate_min": 0.40,
        },
        "rejection_criteria": {
            "max_replay_drawdown_pct": 0.15,
            "shadow_outcome_loss_pct_max": 0.05,
        },
    },
    {
        "variant_id":         "crypto-momentum--24h_bracket_relaxed_2pct",
        "parent_strategy_id": "crypto-momentum",
        "description":        "Lower 24h move bracket floor from 3% to 2% (entry filter widening)",
        "rationale": (
            "predator bracket [3%, 15%] blocks oversold-bounce setups; "
            "wider 2% floor surfaces additional candidates near RSI 60 "
            "without changing RSI threshold."
        ),
        "promotion_criteria": {
            "min_replay_n":  30,
            "min_replay_pf": 1.2,
            "min_shadow_n":  10,
            "shadow_outcome_hit_rate_min": 0.40,
        },
        "rejection_criteria": {
            "max_replay_drawdown_pct": 0.15,
            "shadow_outcome_loss_pct_max": 0.05,
        },
    },
    {
        "variant_id":         "crypto-oversold-bounce--rsi_threshold_33",
        "parent_strategy_id": "crypto-oversold-bounce",
        "description":        "Raise RSI threshold from 30 to 33 (entry band shift +3 points)",
        "rationale": (
            "near-miss cluster observed around RSI 31-33; current 30 cutoff "
            "is TOO_LOOSE per threshold-reality output but on the other side "
            "the entries cluster near 31-33 — let operator evaluate."
        ),
        "promotion_criteria": {
            "min_replay_n":  30,
            "min_replay_pf": 1.2,
            "min_shadow_n":  10,
            "shadow_outcome_hit_rate_min": 0.40,
        },
        "rejection_criteria": {
            "max_replay_drawdown_pct": 0.15,
            "shadow_outcome_loss_pct_max": 0.05,
        },
    },
    {
        "variant_id":         "momentum-long--breakout_threshold_1_5pct",
        "parent_strategy_id": "momentum-long",
        "description":        "Lower breakout threshold from 2.0% to 1.5% (entry sensitivity raise)",
        "rationale": (
            "0 production fires lifetime for momentum-long; replay candidates "
            "cluster near 1.5-2.0% breakout. Lower threshold may surface "
            "real entries — operator review."
        ),
        "promotion_criteria": {
            "min_replay_n":  30,
            "min_replay_pf": 1.2,
            "min_shadow_n":  10,
            "shadow_outcome_hit_rate_min": 0.40,
        },
        "rejection_criteria": {
            "max_replay_drawdown_pct": 0.15,
            "shadow_outcome_loss_pct_max": 0.05,
        },
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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


# ─── Core ─────────────────────────────────────────────────────────────────────


def build_variants(
    *,
    quarantine_module=None,
    specs: Optional[list[dict[str, Any]]] = None,
    allowed_modes: tuple[str, ...] = ("replay", "shadow"),
    created_from: str = "threshold_reality + near_miss seed",
) -> tuple[list[dict], list[str]]:
    """Register each spec via the dataclass API. Returns (records, errors).

    HARD safety: validate_allowed_modes runs INSIDE register_variant for
    the dataclass form — if any spec carried "live"/"paper" it would
    raise ValueError. By construction we pass only the safe pair.
    """
    if quarantine_module is None:
        quarantine_module = _load_quarantine_module()
    if specs is None:
        specs = VARIANT_SPECS

    # SAFETY: refuse to register if allowed_modes contains forbidden values.
    for m in allowed_modes:
        if m.lower() in {"live", "paper", "broker_paper"}:
            raise ValueError(
                f"refusing to seed quarantine: allowed_modes contains "
                f"forbidden runtime mode {m!r}"
            )

    records: list[dict] = []
    errors: list[str] = []

    SV = quarantine_module.StrategyVariant
    register = quarantine_module.register_variant
    for spec in specs:
        try:
            variant = SV(
                variant_id=spec["variant_id"],
                parent_strategy_id=spec["parent_strategy_id"],
                description=spec["description"],
                rationale=(
                    spec["rationale"]
                    + f" [created_from: {created_from}]"
                ),
                promotion_criteria=dict(spec.get("promotion_criteria") or {}),
                rejection_criteria=dict(spec.get("rejection_criteria") or {}),
                allowed_modes=tuple(allowed_modes),
                status="QUARANTINED",
            )
            rec = register(variant)
            if isinstance(rec, dict):
                # Pin created_from for downstream queue builder.
                rec["created_from"] = created_from
                records.append(rec)
        except Exception as exc:
            errors.append(f"{spec.get('variant_id', '?')}: {exc}")

    return records, errors


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_markdown(records: list[dict],
                    *, errors: Optional[list[str]] = None) -> str:
    lines: list[str] = []
    lines.append(f"# Strategy variant quarantine ({VERSION})")
    lines.append("")
    lines.append(f"**Generated:** `{_utc_now_iso()}`")
    lines.append(f"**git_head:** `{_git_head()}`")
    lines.append(f"**variants_seeded:** {len(records)}")
    lines.append("")
    lines.append("Quarantined variants are SHADOW descriptions of proposed "
                 "strategy changes. They NEVER touch the runtime trading "
                 "path. `allowed_modes` is locked to "
                 "`{replay, shadow}` — never `live` or `paper`. Promotion "
                 "to active strategies requires a separate audited PR.")
    lines.append("")
    lines.append("| Variant ID | Parent | Description | Status | Allowed modes | Source |")
    lines.append("|---|---|---|---|---|---|")
    if not records:
        lines.append("| (no variants seeded) | | | | | |")
    for r in records:
        lines.append(
            f"| `{r.get('id', '?')}` | `{r.get('parent_strategy', '?')}` | "
            f"{r.get('description', r.get('change_rationale', ''))[:120]} | "
            f"`{r.get('status', '?')}` | "
            f"`{', '.join(r.get('allowed_modes', []) or [])}` | "
            f"`{r.get('created_from', 'threshold_reality + near_miss seed')}` |"
        )
    lines.append("")

    if errors:
        lines.append("## Errors during registration")
        lines.append("")
        for e in errors:
            lines.append(f"- `{e}`")
        lines.append("")

    lines.append("## Standing markers")
    lines.append("")
    for s in STANDING_MARKERS:
        lines.append(f"- `{s}`")
    return "\n".join(lines) + "\n"


def write_status_files(records: list[dict],
                       *, errors: Optional[list[str]] = None) -> dict:
    """Persist machine-readable status + markdown view."""
    payload = {
        "version":          VERSION,
        "generated_at_iso": _utc_now_iso(),
        "git_head":         _git_head(),
        "variants_seeded":  len(records),
        "variants":         records,
        "errors":           errors or [],
        "standing_markers": list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":             False,
            "allow_broker_paper":            False,
            "live_trading_supported":        False,
            "allowed_modes_runtime_only":    False,
            "registry_collision_refused":    True,
            "auto_promotes_variants":        False,
            "writes_strategy_quality_gate":  False,
            "writes_opportunity_ledger":     False,
            "places_orders":                 False,
            "fetches_network":               False,
        },
    }
    LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_JSON_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True),
                                encoding="utf-8")
    LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_MD_PATH.write_text(render_markdown(records, errors=errors),
                              encoding="utf-8")
    return payload


# ─── CLI ──────────────────────────────────────────────────────────────────────


def run(*, allowed_modes: tuple[str, ...] = ("replay", "shadow")) -> dict:
    records, errors = build_variants(allowed_modes=allowed_modes)
    summary = write_status_files(records, errors=errors)
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowed-modes", type=str, default="replay,shadow",
        help="Comma-separated modes; MUST be subset of {replay, shadow}",
    )
    args = parser.parse_args(argv)
    modes = tuple(m.strip().lower() for m in args.allowed_modes.split(",")
                  if m.strip())
    if not modes:
        modes = ("replay", "shadow")
    summary = run(allowed_modes=modes)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

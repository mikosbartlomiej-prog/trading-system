"""v3.30 (2026-06-09) — broker-paper canary pre-executor (preflight only).

This module is the architectural skeleton for the future canary
executor. v3.30 implements ONLY the preflight gate stack — NO order is
placed under any code path. Removing the "no safe enable switch"
blocker requires (a) this module, (b) flipping
``canary_execution_flag_present`` to true in
``configs/broker_paper_canary.json``, (c) a future PR that adds the
actual order placement (which v3.30 deliberately does not include).

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER calls any order-submission helper.
- NEVER places, modifies, or closes a position.
- ``run_preflight()`` returns a verdict dict; it NEVER mutates state.
- Refuses if any of the 7 broker-execution / live env flags is truthy.
- Refuses if ``BROKER_PAPER_CANARY_EXECUTION_ENABLED`` is not truthy.
- Refuses if ``CANARY_DRY_RUN`` is not ``false``.
- Refuses if unlock_status is not ``BROKER_PAPER_CANARY_UNLOCK_READY``.
- Refuses if ``OPERATOR_APPROVED_BROKER_PAPER_CANARY`` is not truthy.
- Refuses if config limits are wrong (max_orders_per_day > 1,
  max_notional > 25, crypto/options enabled, etc.).
- The v3.30 verdict for an all-green preflight is
  ``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED`` — not
  ``CANARY_EXECUTING`` or anything similar.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Verdict enum ───────────────────────────────────────────────────────────

CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY            = (
    "CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY")
CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY              = (
    "CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY")
CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE       = (
    "CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE")
CANARY_PREFLIGHT_REFUSED_DRY_RUN_NOT_FALSE             = (
    "CANARY_PREFLIGHT_REFUSED_DRY_RUN_NOT_FALSE")
CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY              = (
    "CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY")
CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL          = (
    "CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL")
CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID         = (
    "CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID")
CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE  = (
    "CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE")
CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED   = (
    "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED")
CANARY_PREFLIGHT_DRY_RUN_OK                            = (
    "CANARY_PREFLIGHT_DRY_RUN_OK")

ALL_PREFLIGHT_VERDICTS: frozenset[str] = frozenset({
    CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY,
    CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY,
    CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE,
    CANARY_PREFLIGHT_REFUSED_DRY_RUN_NOT_FALSE,
    CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY,
    CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL,
    CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID,
    CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE,
    CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED,
    CANARY_PREFLIGHT_DRY_RUN_OK,
})


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _load_config() -> dict | None:
    path = REPO_ROOT / "configs" / "broker_paper_canary.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _config_limits_valid(cfg: dict) -> tuple[bool, str]:
    if int(cfg.get("max_orders_per_day", 999)) > 1:
        return False, "max_orders_per_day > 1"
    if float(cfg.get("max_notional_per_order_usd", 999)) > 25:
        return False, "max_notional_per_order_usd > 25"
    allowed = cfg.get("allowed_asset_classes") or []
    if allowed != ["us_equity"]:
        return False, "allowed_asset_classes != ['us_equity']"
    if cfg.get("crypto_enabled", True):
        return False, "crypto_enabled is true"
    if cfg.get("options_enabled", True):
        return False, "options_enabled is true"
    if cfg.get("live_trading_supported", True):
        return False, "live_trading_supported is true"
    return True, "ok"


@dataclass
class PreflightResult:
    verdict:          str
    rationale:        list[str] = field(default_factory=list)
    gates:            dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict":   self.verdict,
            "rationale": list(self.rationale),
            "gates":     dict(self.gates),
            "safety": {
                "broker_paper_canary_still_blocked": True,
                "live_trading_unsupported":          True,
                "no_order_placement_in_v330":        True,
                "this_module_never_imports_broker_orders_module":
                    True,
                "this_module_never_calls_submit_order_or_place_order":
                    True,
            },
            "standing_markers": [
                "CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY",
                "NO_ORDER_PLACEMENT_IN_V330",
                "LLM_ADVISORY_ONLY_CONFIRMED",
                "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
                "LIVE_TRADING_UNSUPPORTED",
                "DETERMINISTIC_GATES_REMAIN_FINAL",
            ],
        }


def run_preflight(*,
                    unlock_status: str | None = None,
                    dry_run_only: bool = True,
                    ) -> PreflightResult:
    """Pure read-only preflight evaluation. NEVER places an order.

    In v3.30, ``dry_run_only=True`` returns
    ``CANARY_PREFLIGHT_DRY_RUN_OK`` when every gate passes (operator
    can inspect verdict). ``dry_run_only=False`` plus every gate green
    returns
    ``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED`` — but
    still NEVER places an order in v3.30. Order placement requires
    a future audited PR.
    """
    rep = PreflightResult(
        verdict=CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY,
        gates={},
    )

    # Refusal cascade.
    for flag in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                   "BROKER_EXECUTION_ENABLED"):
        if _env_truthy(flag):
            rep.verdict = (
                CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY)
            rep.rationale.append(
                f"{flag} is truthy — canary must enable broker paper "
                f"ONLY through the dedicated canary-safe path")
            return rep
    for flag in ("LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                   "LIVE_TRADING_ENABLED"):
        if _env_truthy(flag):
            rep.verdict = CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY
            rep.rationale.append(
                f"{flag} is truthy — canary refuses unconditionally")
            return rep

    rep.gates["execution_flag"] = _env_truthy(
        "BROKER_PAPER_CANARY_EXECUTION_ENABLED")
    rep.gates["dry_run"] = (os.environ.get(
        "CANARY_DRY_RUN", "true").strip().lower())
    rep.gates["operator_approved"] = _env_truthy(
        "OPERATOR_APPROVED_BROKER_PAPER_CANARY")
    rep.gates["unlock_status"] = unlock_status

    cfg = _load_config() or {}
    rep.gates["canary_execution_flag_present"] = bool(
        cfg.get("canary_execution_flag_present", False))
    rep.gates["max_orders_per_day"]         = cfg.get(
        "max_orders_per_day")
    rep.gates["max_notional_per_order_usd"] = cfg.get(
        "max_notional_per_order_usd")
    rep.gates["crypto_enabled"]              = cfg.get(
        "crypto_enabled", True)
    rep.gates["options_enabled"]             = cfg.get(
        "options_enabled", True)
    rep.gates["allowed_asset_classes"]       = cfg.get(
        "allowed_asset_classes", [])

    ok, why = _config_limits_valid(cfg)
    if not ok:
        rep.verdict = (
            CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID)
        rep.rationale.append(f"canary config limits invalid: {why}")
        return rep

    if not rep.gates["canary_execution_flag_present"]:
        rep.verdict = (
            CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE)
        rep.rationale.append(
            "configs/broker_paper_canary.json::"
            "canary_execution_flag_present is false")
        return rep

    if dry_run_only:
        rep.verdict = CANARY_PREFLIGHT_DRY_RUN_OK
        rep.rationale.append(
            "dry-run preflight; gates inspected but NO order would "
            "be placed even if a future executor existed")
        return rep

    if not rep.gates["execution_flag"]:
        rep.verdict = (
            CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE)
        rep.rationale.append(
            "BROKER_PAPER_CANARY_EXECUTION_ENABLED is not truthy")
        return rep
    if rep.gates["dry_run"] != "false":
        rep.verdict = (
            CANARY_PREFLIGHT_REFUSED_DRY_RUN_NOT_FALSE)
        rep.rationale.append(
            "CANARY_DRY_RUN is not 'false' — refusing to advance")
        return rep
    if unlock_status != "BROKER_PAPER_CANARY_UNLOCK_READY":
        rep.verdict = CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY
        rep.rationale.append(
            f"unlock_status={unlock_status} — refusing to advance")
        return rep
    if not rep.gates["operator_approved"]:
        rep.verdict = (
            CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL)
        rep.rationale.append(
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY is not truthy")
        return rep

    # All gates green BUT v3.30 deliberately ships no order-placement
    # path. The verdict is a stop sign for v3.30.
    rep.verdict = (
        CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED)
    rep.rationale.append(
        "every deterministic gate passes; v3.30 does NOT implement "
        "order placement — a follow-up audited PR is required")
    return rep


__all__ = [
    "CANARY_PREFLIGHT_REFUSED_BROKER_FLAG_TRUTHY",
    "CANARY_PREFLIGHT_REFUSED_LIVE_FLAG_TRUTHY",
    "CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_NOT_TRUE",
    "CANARY_PREFLIGHT_REFUSED_DRY_RUN_NOT_FALSE",
    "CANARY_PREFLIGHT_REFUSED_UNLOCK_NOT_READY",
    "CANARY_PREFLIGHT_REFUSED_NO_OPERATOR_APPROVAL",
    "CANARY_PREFLIGHT_REFUSED_CONFIG_LIMITS_INVALID",
    "CANARY_PREFLIGHT_REFUSED_EXECUTION_FLAG_PRESENT_FALSE",
    "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED",
    "CANARY_PREFLIGHT_DRY_RUN_OK",
    "ALL_PREFLIGHT_VERDICTS",
    "PreflightResult",
    "run_preflight",
]

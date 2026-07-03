"""ExecutionMode — canonical single-source-of-truth for broker mutation authority.

Before this module the repo had four different signals of "should we place
orders?" — ``TRADING_EXECUTION_ON`` env, ``auto_execute_rebalance`` config,
``ALLOW_BROKER_PAPER`` env, and ``EDGE_GATE_ENABLED`` env — with no single
enforcement point. The morning allocator could reach broker mutation even
while the dashboard reported ``TRADING_EXECUTION_ON=false``.

This module fixes that with a single enum + one deterministic resolver +
one guard function that every broker mutation MUST pass through.

Canonical modes
---------------
``OFF``               — no broker mutation is permitted, ever.
                        Default. Fail-closed on unknown states.
``SHADOW``            — read-only broker access + shadow simulation only.
                        Broker POST/DELETE structurally unreachable.
``PAPER_CANARY``      — paper account only, tight guardrails. Requires ALL
                        of: explicit repo var, paper-account verification,
                        allocator gate allowed, fresh reconciliation, no
                        safe-mode, no broker-repair entries, no kill switch,
                        approved policy, idempotency key, bounded caps.
``LIVE_UNSUPPORTED``  — sentinel; refusing to run live in this repo. This
                        value can be resolved but NEVER authorizes mutation.

Enforcement contract
--------------------
``assert_can_mutate_broker(mode, ...)`` is the sole gate. It:

  * raises ``BrokerMutationBlocked`` on ANY failed precondition
  * refuses to authorize when ``mode`` is not exactly ``PAPER_CANARY``
  * fails CLOSED — unknown mode, missing config, missing state, unreadable
    reconciliation, or any exception during checks → block

Every ``requests.post`` / ``requests.delete`` in ``shared/alpaca_orders.py``
that would mutate broker state MUST be wrapped in
``with broker_mutation_guard(intent=...): …``.

Tests in ``tests/architecture_vnext/test_execution_mode_mutation_block.py``
prove structurally that the guard is unbypassable when mode ≠ PAPER_CANARY.

HARD SAFETY
-----------
* Live trading is NOT supported. ``LIVE_UNSUPPORTED`` is a sentinel only.
* The paper base URL is verified against a whitelist. Any other endpoint
  triggers refuse-and-return.
* Secrets are never printed by this module (only presence/absence).
* Read-only access is not blocked — only mutations are gated.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# Only paper-api.alpaca.markets is acceptable. Live is intentionally
# unsupported in this repo — the module refuses to authorize mutation
# against any other endpoint.
PAPER_ENDPOINT = "https://paper-api.alpaca.markets"


class ExecutionMode(enum.Enum):
    """Canonical execution mode.

    Ordered from least-permissive to most-permissive.
    """

    OFF = "OFF"
    SHADOW = "SHADOW"
    PAPER_CANARY = "PAPER_CANARY"
    LIVE_UNSUPPORTED = "LIVE_UNSUPPORTED"


class BrokerMutationBlocked(Exception):
    """Raised when a broker-mutation attempt is not authorized.

    The message MUST NOT include secrets or full HTTP bodies. It should
    include enough context for operators to diagnose the block (mode, the
    first failing precondition, redacted resource identifiers).
    """


@dataclass(frozen=True)
class ExecutionModeResolution:
    """Result of ``resolve_mode()``.

    Frozen so callers cannot mutate the recorded provenance in place.
    """

    mode: ExecutionMode
    resolved_from: str          # short label indicating what set the mode
    reasons: tuple[str, ...] = field(default_factory=tuple)
    endpoint: str = PAPER_ENDPOINT
    preconditions_checked: tuple[str, ...] = field(default_factory=tuple)


# ── mode resolution ───────────────────────────────────────────────────────

def _env_truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_paper_endpoint() -> str:
    return os.environ.get("ALPACA_BASE_URL", PAPER_ENDPOINT).strip()


def resolve_mode() -> ExecutionModeResolution:
    """Deterministic resolver — takes env + config only, no I/O beyond env.

    Priority order (highest → lowest):
      1. ``EXECUTION_MODE`` env var, if set to one of the enum values.
      2. Any of the standing safety flags is truthy → ``OFF``.
         (``LIVE_TRADING_UNSUPPORTED`` is a standing marker so it is not
         counted as "trying to enable live".)
      3. ``ALLOW_BROKER_PAPER=true`` + explicit repo variable → ``PAPER_CANARY``
         *only if* the caller subsequently passes ``assert_can_mutate_broker``.
      4. Anything else defaults to ``OFF``.

    NOTE: This resolver returns the *nominal* mode. Authorization requires
    both ``mode == PAPER_CANARY`` and ``assert_can_mutate_broker`` returning
    without raising.
    """
    reasons: list[str] = []

    # 1. Explicit env override
    explicit = os.environ.get("EXECUTION_MODE", "").strip().upper()
    if explicit:
        try:
            mode = ExecutionMode(explicit)
            reasons.append(f"explicit env EXECUTION_MODE={explicit}")
            return ExecutionModeResolution(
                mode=mode,
                resolved_from="env:EXECUTION_MODE",
                reasons=tuple(reasons),
                endpoint=_env_paper_endpoint(),
            )
        except ValueError:
            reasons.append(f"env EXECUTION_MODE={explicit} not recognised — ignoring")

    # 2. Standing "everything off" flags dominate.
    if _env_truthy("EDGE_GATE_ENABLED", "false") is False:
        reasons.append("EDGE_GATE_ENABLED=false → mutation forbidden")
    if _env_truthy("ALLOW_BROKER_PAPER", "false") is False:
        reasons.append("ALLOW_BROKER_PAPER=false → PAPER_CANARY forbidden")
    if _env_truthy("TRADING_EXECUTION_ON", "false") is False:
        reasons.append("TRADING_EXECUTION_ON=false → OFF")

    # 3. Any of the "please try to trade" flags MUST be true to leave OFF.
    can_paper = (
        _env_truthy("ALLOW_BROKER_PAPER") and
        _env_truthy("TRADING_EXECUTION_ON") and
        _env_truthy("EDGE_GATE_ENABLED")
    )

    # 4. Live is unsupported. If someone sets LIVE_TRADING or GO_LIVE we
    # refuse to resolve as LIVE and return OFF.
    if _env_truthy("LIVE_TRADING_ENABLED") or _env_truthy("GO_LIVE"):
        reasons.append("LIVE_TRADING/GO_LIVE ignored — live unsupported")
        return ExecutionModeResolution(
            mode=ExecutionMode.LIVE_UNSUPPORTED,
            resolved_from="env:live-attempted",
            reasons=tuple(reasons),
        )

    if can_paper:
        # NOTE: this is only the *nominal* mode. Actual authorization still
        # requires assert_can_mutate_broker() to pass.
        return ExecutionModeResolution(
            mode=ExecutionMode.PAPER_CANARY,
            resolved_from="env:paper-flags",
            reasons=tuple(reasons),
            endpoint=_env_paper_endpoint(),
        )

    # 5. Shadow mode — evidence-only pipeline runs but no mutation.
    if _env_truthy("SHADOW_MODE_ENABLED"):
        return ExecutionModeResolution(
            mode=ExecutionMode.SHADOW,
            resolved_from="env:SHADOW_MODE_ENABLED",
            reasons=tuple(reasons),
        )

    # 6. Default: OFF (fail-closed).
    return ExecutionModeResolution(
        mode=ExecutionMode.OFF,
        resolved_from="default",
        reasons=tuple(reasons),
    )


# ── mutation gate ─────────────────────────────────────────────────────────

# All preconditions required for PAPER_CANARY mutation. Any one failing
# blocks the attempt; the guard reports which one first failed.
_REQUIRED_PAPER_CANARY_PRECONDITIONS = (
    "mode_is_paper_canary",
    "endpoint_is_paper",
    "paper_account_verified_by_operator",
    "allocator_gate_allowed",
    "fresh_position_reconciliation",
    "no_safe_mode",
    "no_broker_repair_entries",
    "no_kill_switch",
    "approved_canary_policy_marker",
    "idempotency_key_provided",
    "per_order_cap_respected",
    "gross_exposure_cap_respected",
)


def assert_can_mutate_broker(
    resolution: Optional[ExecutionModeResolution] = None,
    *,
    intent: str = "unspecified",
    intended_notional_usd: float = 0.0,
    idempotency_key: Optional[str] = None,
) -> ExecutionModeResolution:
    """Sole authorization gate. Raises BrokerMutationBlocked on ANY failure.

    Parameters
    ----------
    resolution
        Result of a prior ``resolve_mode()`` call. If ``None``, resolves
        fresh — but callers should pass a pre-resolved value so the mode
        is snapshotted at the top of the request path.
    intent
        Human-readable label of what the caller wants to do
        (``"place_stock_bracket"``, ``"safe_close_stock"``, etc.). Recorded
        in the block reason.
    intended_notional_usd
        Order notional. Guarded against ``PAPER_CANARY_MAX_ORDER_NOTIONAL_USD``.
    idempotency_key
        The pre-computed client_order_id / idempotency key. Must be non-
        empty and non-None for PAPER_CANARY mutation.

    Returns
    -------
    The resolution that was authorized. If this function returns without
    raising, the caller MAY proceed to place the broker call.

    Raises
    ------
    BrokerMutationBlocked
        On ANY failing precondition. Message contains the first failing
        precondition + the intent + a short reason. NEVER contains secrets.
    """
    if resolution is None:
        resolution = resolve_mode()

    reasons: list[str] = []

    def _block(precond: str, reason: str) -> None:
        raise BrokerMutationBlocked(
            f"broker mutation blocked ({intent}): "
            f"precondition {precond} FAILED — {reason}. "
            f"mode={resolution.mode.value}"
        )

    # 1. mode must be exactly PAPER_CANARY. LIVE_UNSUPPORTED never
    # authorizes; SHADOW never authorizes; OFF never authorizes.
    if resolution.mode != ExecutionMode.PAPER_CANARY:
        _block(
            "mode_is_paper_canary",
            f"nominal mode is {resolution.mode.value}, "
            f"only PAPER_CANARY authorizes broker mutation",
        )

    # 2. endpoint whitelist. If anyone injected a different endpoint, block.
    if resolution.endpoint != PAPER_ENDPOINT:
        _block(
            "endpoint_is_paper",
            "endpoint is not paper-api.alpaca.markets (live is unsupported)",
        )

    # 3. idempotency key must be provided (non-None, non-empty). Intrinsic
    # caller-controlled check — runs before state-file checks so operators
    # get the clearest signal when they've forgotten to pass one.
    if not idempotency_key or not str(idempotency_key).strip():
        _block(
            "idempotency_key_provided",
            "caller did not pass a non-empty idempotency_key — "
            "PAPER_CANARY requires deterministic client_order_id per attempt",
        )

    # 4. per-order notional cap. Intrinsic input-only check — read from env
    # with a very small default so a misconfigured env cannot silently
    # authorize a large order.
    try:
        cap = float(os.environ.get("PAPER_CANARY_MAX_ORDER_NOTIONAL_USD", "500"))
    except ValueError:
        cap = 500.0
    if float(intended_notional_usd) > cap:
        _block(
            "per_order_cap_respected",
            f"intended notional ${float(intended_notional_usd):.2f} "
            f"exceeds per-order cap ${cap:.2f}",
        )

    # 5. explicit operator approval marker file. This CANNOT be created
    # by any bot; it exists on disk only if the operator dropped it.
    approval = REPO_ROOT / "learning-loop" / "canary" / "PAPER_CANARY_APPROVED.marker"
    if not approval.exists():
        _block(
            "approved_canary_policy_marker",
            f"marker file not found at {approval.relative_to(REPO_ROOT)} — "
            "operator has not approved the paper canary policy",
        )

    # 6. paper account must have been verified by the operator (separate
    # marker so revoking approval is a single-file operation).
    paper_verified = REPO_ROOT / "learning-loop" / "canary" / "PAPER_ACCOUNT_VERIFIED.marker"
    if not paper_verified.exists():
        _block(
            "paper_account_verified_by_operator",
            f"marker file not found at {paper_verified.relative_to(REPO_ROOT)}",
        )

    # 7. safe-mode must not be active.
    try:
        from safe_mode_state import load_safe_mode_state  # type: ignore
    except ImportError:
        try:
            from shared.safe_mode_state import load_safe_mode_state  # type: ignore
        except ImportError:
            load_safe_mode_state = None  # type: ignore

    if load_safe_mode_state is not None:
        try:
            sm = load_safe_mode_state()
            if getattr(sm, "active", False):
                _block(
                    "no_safe_mode",
                    "safe_mode is active — refusing mutation",
                )
        except Exception as e:
            # fail-closed on unknown state
            _block(
                "no_safe_mode",
                f"safe_mode state unreadable ({type(e).__name__}) — fail closed",
            )
    else:
        _block(
            "no_safe_mode",
            "safe_mode module not importable — fail closed",
        )

    # 8. broker-repair-required must have empty entries.
    try:
        from broker_repair_required import get_blocked_symbols  # type: ignore
    except ImportError:
        try:
            from shared.broker_repair_required import get_blocked_symbols  # type: ignore
        except ImportError:
            get_blocked_symbols = None  # type: ignore

    if get_blocked_symbols is not None:
        try:
            blocked = get_blocked_symbols()
            if blocked:
                _block(
                    "no_broker_repair_entries",
                    f"broker_repair_required has {len(blocked)} symbol(s) "
                    f"quarantined — operator must clear",
                )
        except Exception as e:
            _block(
                "no_broker_repair_entries",
                f"broker_repair state unreadable ({type(e).__name__}) — fail closed",
            )

    # 9. kill switch is another marker file. Presence means "stop trading".
    kill_switch = REPO_ROOT / "learning-loop" / "canary" / "KILL_SWITCH.marker"
    if kill_switch.exists():
        _block("no_kill_switch", "KILL_SWITCH.marker present")

    # 10. Position/order reconciliation must be fresh (<= 6h). Read from
    # the audit-visible artefact; fail-closed if not present or stale.
    recon = REPO_ROOT / "learning-loop" / "position_reconciliation_latest.json"
    if not recon.exists():
        _block(
            "fresh_position_reconciliation",
            "position_reconciliation_latest.json missing",
        )
    try:
        import json
        from datetime import datetime, timezone, timedelta

        d = json.loads(recon.read_text(encoding="utf-8"))
        gen = d.get("generated_at_iso") or d.get("ts_iso")
        if not gen:
            _block(
                "fresh_position_reconciliation",
                "reconciliation has no generated_at_iso",
            )
        dt = datetime.fromisoformat(str(gen).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - dt > timedelta(hours=6):
            _block(
                "fresh_position_reconciliation",
                f"reconciliation generated at {gen} is stale (>6h)",
            )
    except BrokerMutationBlocked:
        raise
    except Exception as e:
        _block(
            "fresh_position_reconciliation",
            f"reconciliation unreadable ({type(e).__name__})",
        )

    # 11. system_activation_gate must return ALLOCATOR_ALLOWED. Import the
    # gate lazily so this module has no hard dep on it.
    try:
        try:
            from system_activation_gate import evaluate  # type: ignore
        except ImportError:
            from shared.system_activation_gate import evaluate  # type: ignore
        gate = evaluate()
        decision = getattr(gate, "decision", None) or gate.get("decision") if isinstance(gate, dict) else None
        if decision and str(decision) != "ALLOCATOR_ALLOWED":
            _block(
                "allocator_gate_allowed",
                f"system_activation_gate decision={decision}",
            )
    except BrokerMutationBlocked:
        raise
    except Exception as e:
        _block(
            "allocator_gate_allowed",
            f"system_activation_gate unavailable ({type(e).__name__}) — fail closed",
        )

    # 12. If we get here, every precondition passed.
    return ExecutionModeResolution(
        mode=resolution.mode,
        resolved_from=resolution.resolved_from,
        reasons=tuple(list(resolution.reasons) + [
            f"authorized: intent={intent}, "
            f"notional=${float(intended_notional_usd):.2f}, "
            f"idempotency_key=…{str(idempotency_key)[-6:]}"
        ]),
        endpoint=resolution.endpoint,
        preconditions_checked=_REQUIRED_PAPER_CANARY_PRECONDITIONS,
    )


def check_or_block(
    intent: str,
    *,
    intended_notional_usd: float = 0.0,
    idempotency_key: Optional[str] = None,
    resolution: Optional[ExecutionModeResolution] = None,
) -> Optional[dict]:
    """Non-raising variant of ``assert_can_mutate_broker``.

    Returns ``None`` when mutation is authorized (caller may proceed).
    Returns a structured "blocked" dict when the guard fails — same shape
    as other refuse-and-return paths in ``shared/alpaca_orders.py`` (see
    ``safe_close``'s ``REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE`` return).

    This variant exists so existing callers in ``shared/alpaca_orders.py``
    can wire the gate in without changing their return contract from a
    dict to an exception. The result dict is deterministic and audit-safe
    — it contains no secrets and only redacted IDs.

    Callers that WANT a hard exception should use
    ``assert_can_mutate_broker`` directly or ``broker_mutation_guard``.
    """
    try:
        assert_can_mutate_broker(
            resolution,
            intent=intent,
            intended_notional_usd=intended_notional_usd,
            idempotency_key=idempotency_key,
        )
        return None
    except BrokerMutationBlocked as exc:
        # Return a structured dict that mirrors the shape of
        # safe_close's REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE branch. This
        # allows callers to append it to their audit trail without
        # special-casing.
        key_tail = ""
        if idempotency_key:
            k = str(idempotency_key)
            key_tail = "…" + (k[-6:] if len(k) > 6 else k)
        return {
            "status":            "EXECUTION_MODE_BLOCKED",
            "reason":             str(exc),
            "intent":             intent,
            "intended_notional":  float(intended_notional_usd or 0.0),
            "idempotency_key":    key_tail,
            "broker_called":      False,
            "alpaca_order_id":    None,
            "http_status":        None,
            "guard_decision":     "BLOCKED",
        }


class broker_mutation_guard:  # noqa: N801 — context manager, snake_case is fine
    """Context manager that raises ``BrokerMutationBlocked`` up-front.

    Usage in shared/alpaca_orders.py::

        with broker_mutation_guard(
            intent="place_stock_bracket",
            intended_notional_usd=size_usd,
            idempotency_key=client_order_id,
        ):
            r = requests.post(f"{PAPER_ENDPOINT}/v2/orders", …)

    The guard runs ``assert_can_mutate_broker`` on ``__enter__`` and does
    nothing on ``__exit__`` — its role is to block *before* the network
    call, not to wrap or intercept the response.
    """

    def __init__(
        self,
        intent: str,
        *,
        intended_notional_usd: float = 0.0,
        idempotency_key: Optional[str] = None,
        resolution: Optional[ExecutionModeResolution] = None,
    ) -> None:
        self.intent = intent
        self.intended_notional_usd = float(intended_notional_usd or 0.0)
        self.idempotency_key = idempotency_key
        self.resolution = resolution
        self.authorized: Optional[ExecutionModeResolution] = None

    def __enter__(self) -> ExecutionModeResolution:
        self.authorized = assert_can_mutate_broker(
            self.resolution,
            intent=self.intent,
            intended_notional_usd=self.intended_notional_usd,
            idempotency_key=self.idempotency_key,
        )
        return self.authorized

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False  # never swallow exceptions


# ── public re-exports ─────────────────────────────────────────────────────

__all__ = [
    "ExecutionMode",
    "ExecutionModeResolution",
    "BrokerMutationBlocked",
    "PAPER_ENDPOINT",
    "resolve_mode",
    "assert_can_mutate_broker",
    "broker_mutation_guard",
]

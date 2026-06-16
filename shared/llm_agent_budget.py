"""v3.28 (2026-06-09) — LLM advisory mesh budget governor.

Tracks per-day, per-run, and per-cost caps for the v3.28 LLM advisory
mesh. The default is **disabled**: ``LLM_AGENTS_ENABLED=false`` short-
circuits every call. When enabled, the caps prevent runaway provider
spend.

HARD SAFETY (cannot be opted out of)
------------------------------------
- NEVER submits orders.
- NEVER imports the broker-orders module (asserted by test).
- NEVER stores secret values (provider keys are read from env at call
  time and never persisted).
- NEVER unlocks broker paper, live trading, or readiness counters.
- Budget exhaustion ALWAYS routes to a SKIPPED status — no advisory
  call is ever forced through.
- Fail-soft: any error returns ``LLM_FAIL_SOFT`` rather than raising.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Status enum ────────────────────────────────────────────────────────────

LLM_BUDGET_ALLOWED           = "LLM_BUDGET_ALLOWED"
LLM_BUDGET_DISABLED          = "LLM_BUDGET_DISABLED"
LLM_BUDGET_EXHAUSTED_DAILY   = "LLM_BUDGET_EXHAUSTED_DAILY"
LLM_BUDGET_EXHAUSTED_RUN     = "LLM_BUDGET_EXHAUSTED_RUN"
LLM_PROVIDER_KEY_MISSING     = "LLM_PROVIDER_KEY_MISSING"
LLM_FAIL_SOFT                = "LLM_FAIL_SOFT"

ALL_BUDGET_STATUSES: frozenset[str] = frozenset({
    LLM_BUDGET_ALLOWED, LLM_BUDGET_DISABLED,
    LLM_BUDGET_EXHAUSTED_DAILY, LLM_BUDGET_EXHAUSTED_RUN,
    LLM_PROVIDER_KEY_MISSING, LLM_FAIL_SOFT,
    # v3.30 (2026-06-16) — per-agent per-day cap.
    "LLM_BUDGET_EXHAUSTED_PER_AGENT",
})

# Statuses that DO NOT permit a provider call.
SKIPPED_STATUSES: frozenset[str] = frozenset({
    LLM_BUDGET_DISABLED, LLM_BUDGET_EXHAUSTED_DAILY,
    LLM_BUDGET_EXHAUSTED_RUN, LLM_PROVIDER_KEY_MISSING,
    LLM_FAIL_SOFT,
    # v3.30 (2026-06-16) — per-agent per-day cap.
    "LLM_BUDGET_EXHAUSTED_PER_AGENT",
})


# ─── Env knobs ──────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def llm_agents_enabled() -> bool:
    return _env_bool("LLM_AGENTS_ENABLED", False)


def daily_call_budget() -> int:
    return _env_int("LLM_AGENT_DAILY_CALL_BUDGET", 20)


def per_run_budget() -> int:
    """v3.28.3 — per-run budget with a guarded override.

    The default is 5. An override env ``LLM_AGENT_PER_RUN_BUDGET_OVERRIDE``
    is honoured ONLY when:
    - ``LLM_FREE_ONLY=true`` (default), AND
    - ``LLM_PROVIDER=gemini``.

    The override is clamped to ``[1, 11]`` regardless of input so a
    misconfigured value can never amplify cost on a paid provider.
    """
    base = _env_int("LLM_AGENT_PER_RUN_BUDGET", 5)
    raw_override = os.environ.get(
        "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE", "").strip()
    if not raw_override:
        return base
    try:
        ovr = int(raw_override)
    except (TypeError, ValueError):
        return base
    free_only = (os.environ.get("LLM_FREE_ONLY", "true")
                   .strip().lower() in ("true", "1", "yes", "on"))
    prov = (os.environ.get("LLM_PROVIDER", "offline_mock")
              .strip().lower() or "offline_mock")
    if not (free_only and prov == "gemini"):
        # Override silently ignored on non-free / non-gemini configs.
        return base
    # Clamp to [1, 11].
    return max(1, min(11, ovr))


def max_cost_usd_per_day() -> float:
    return _env_float("LLM_AGENT_MAX_COST_USD_PER_DAY", 1.00)


def fail_soft() -> bool:
    return _env_bool("LLM_AGENT_FAIL_SOFT", True)


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "offline_mock").strip().lower() \
        or "offline_mock"


def provider_key_env_name(prov: str | None = None) -> str | None:
    prov = (prov or provider()).lower()
    if prov == "anthropic":
        return "ANTHROPIC_API_KEY"
    if prov == "openai":
        return "OPENAI_API_KEY"
    return None


def provider_key_present(prov: str | None = None) -> bool:
    name = provider_key_env_name(prov)
    if name is None:
        # offline_mock — no key required
        return True
    return bool(os.environ.get(name, "").strip())


# ─── State location ─────────────────────────────────────────────────────────

def _state_dir() -> Path:
    override = os.environ.get("LLM_BUDGET_STATE_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "llm_advisory"


def _state_path() -> Path:
    return _state_dir() / "llm_budget_state.json"


# ─── State dataclass ────────────────────────────────────────────────────────

@dataclass
class BudgetState:
    daily_calls: dict[str, int]    = field(default_factory=dict)
    daily_cost_usd: dict[str, float] = field(default_factory=dict)
    run_calls: dict[str, int]      = field(default_factory=dict)
    # v3.30 (2026-06-16) — per-agent per-day call counter.
    # Shape: {"YYYY-MM-DD": {"INCIDENT_REVIEW": 3, ...}}.
    # Default cap is 10 calls/agent/day (configurable via env
    # ``LLM_AGENT_DAILY_PER_AGENT_BUDGET``).
    per_agent_daily_calls: dict[str, dict[str, int]] = field(
        default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "daily_calls":     self.daily_calls,
            "daily_cost_usd":  self.daily_cost_usd,
            "run_calls":       self.run_calls,
            "per_agent_daily_calls": self.per_agent_daily_calls,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "BudgetState":
        if not raw or not isinstance(raw, dict):
            return cls()
        return cls(
            daily_calls    =dict(raw.get("daily_calls") or {}),
            daily_cost_usd =dict(raw.get("daily_cost_usd") or {}),
            run_calls      =dict(raw.get("run_calls") or {}),
            per_agent_daily_calls=dict(
                raw.get("per_agent_daily_calls") or {}),
        )


def load_state(path: Path | None = None) -> BudgetState:
    p = path or _state_path()
    if not p.exists():
        return BudgetState()
    try:
        return BudgetState.from_dict(
            json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return BudgetState()


def save_state(state: BudgetState, path: Path | None = None) -> None:
    p = path or _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ─── Decision API ───────────────────────────────────────────────────────────

def _today(now: datetime | None = None) -> str:
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return n.date().isoformat()


def check_budget(
    *,
    run_id: str,
    now: datetime | None = None,
    state: BudgetState | None = None,
) -> tuple[str, str]:
    """Pure check (does not mutate state).
    Returns ``(status, reason)``.
    """
    try:
        if not llm_agents_enabled():
            return LLM_BUDGET_DISABLED, "LLM_AGENTS_ENABLED=false (default)"
        if not provider_key_present():
            key_env = provider_key_env_name() or "n/a"
            return (LLM_PROVIDER_KEY_MISSING,
                    f"missing env: {key_env}")
        st = state if state is not None else load_state()
        today = _today(now)
        d_calls = int(st.daily_calls.get(today, 0))
        d_cost  = float(st.daily_cost_usd.get(today, 0.0))
        r_calls = int(st.run_calls.get(run_id, 0))
        if d_calls >= daily_call_budget():
            return (LLM_BUDGET_EXHAUSTED_DAILY,
                    f"daily calls {d_calls} >= cap {daily_call_budget()}")
        if d_cost  >= max_cost_usd_per_day():
            return (LLM_BUDGET_EXHAUSTED_DAILY,
                    f"daily cost ${d_cost:.4f} >= cap "
                    f"${max_cost_usd_per_day():.2f}")
        if r_calls >= per_run_budget():
            return (LLM_BUDGET_EXHAUSTED_RUN,
                    f"run calls {r_calls} >= cap {per_run_budget()}")
        return LLM_BUDGET_ALLOWED, "ok"
    except Exception as e:
        return LLM_FAIL_SOFT, f"fail-soft: {type(e).__name__}: {e}"


def record_call(
    *,
    run_id: str,
    cost_usd: float = 0.0,
    now: datetime | None = None,
    state: BudgetState | None = None,
    state_path: Path | None = None,
    agent_name: str | None = None,
) -> BudgetState:
    """Mutate state to reflect a single completed provider call.

    v3.30 (2026-06-16) — also increments the per-agent counter when
    ``agent_name`` is provided.
    """
    st = state if state is not None else load_state(state_path)
    today = _today(now)
    st.daily_calls[today]    = int(st.daily_calls.get(today, 0)) + 1
    st.daily_cost_usd[today] = float(
        st.daily_cost_usd.get(today, 0.0)) + float(cost_usd)
    st.run_calls[run_id]     = int(st.run_calls.get(run_id, 0)) + 1
    if agent_name:
        bucket = st.per_agent_daily_calls.setdefault(today, {})
        bucket[agent_name] = int(bucket.get(agent_name, 0)) + 1
    save_state(st, state_path)
    return st


# ─── v3.30 per-agent budget + rate limit ───────────────────────────────────

LLM_BUDGET_EXHAUSTED_PER_AGENT = "LLM_BUDGET_EXHAUSTED_PER_AGENT"


def daily_per_agent_budget() -> int:
    """v3.30 — per-agent per-day cap. Default 10."""
    return _env_int("LLM_AGENT_DAILY_PER_AGENT_BUDGET", 10)


def per_call_timeout_seconds() -> float:
    """v3.30 — per-call wall-clock cap (seconds). Default 60.0."""
    return _env_float("LLM_AGENT_PER_CALL_TIMEOUT_SECONDS", 60.0)


def min_seconds_between_calls() -> float:
    """v3.30 — minimum seconds between consecutive provider calls.

    Default 6.0 (≤10 calls / minute). Allows operator override via
    ``LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS``.
    """
    return _env_float("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", 6.0)


def check_per_agent_budget(
    *,
    agent_name: str,
    now: datetime | None = None,
    state: BudgetState | None = None,
) -> tuple[str, str]:
    """Pure check — does this agent have remaining per-day budget?

    Returns ``(LLM_BUDGET_ALLOWED, "ok")`` when remaining > 0, else
    ``(LLM_BUDGET_EXHAUSTED_PER_AGENT, "<rationale>")``. NEVER raises.
    """
    try:
        st = state if state is not None else load_state()
        today = _today(now)
        bucket = st.per_agent_daily_calls.get(today) or {}
        used = int(bucket.get(agent_name, 0))
        cap = daily_per_agent_budget()
        if used >= cap:
            return (LLM_BUDGET_EXHAUSTED_PER_AGENT,
                    f"per-agent calls {used} >= cap {cap} for "
                    f"{agent_name}")
        return LLM_BUDGET_ALLOWED, "ok"
    except Exception as e:
        return LLM_FAIL_SOFT, f"fail-soft: {type(e).__name__}: {e}"


__all__ = [
    "LLM_BUDGET_ALLOWED", "LLM_BUDGET_DISABLED",
    "LLM_BUDGET_EXHAUSTED_DAILY", "LLM_BUDGET_EXHAUSTED_RUN",
    "LLM_BUDGET_EXHAUSTED_PER_AGENT",
    "LLM_PROVIDER_KEY_MISSING", "LLM_FAIL_SOFT",
    "ALL_BUDGET_STATUSES", "SKIPPED_STATUSES",
    "llm_agents_enabled", "daily_call_budget",
    "per_run_budget", "max_cost_usd_per_day", "fail_soft",
    "provider", "provider_key_env_name", "provider_key_present",
    "BudgetState", "load_state", "save_state",
    "check_budget", "record_call",
    "daily_per_agent_budget", "per_call_timeout_seconds",
    "min_seconds_between_calls", "check_per_agent_budget",
]

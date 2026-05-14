"""In-memory state.json fake for E2E."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


VALID_BASELINE = {
    "state_version":      1,
    "last_writer":        "daily-learning",
    "last_write_reason":  "initial baseline",
    "last_validated_at":  "2026-05-14T21:00:00Z",
    "strategies": {
        "aggressive-momentum": {
            "size_multiplier": 1.0,
            "enabled":         True,
            "side_bias":       None,
            "paused_until":    None,
        },
        "options-momentum": {
            "size_multiplier": 1.0,
            "enabled":         True,
            "side_bias":       None,
            "paused_until":    None,
        },
        "crypto-momentum": {
            "size_multiplier": 1.0,
            "enabled":         True,
            "side_bias":       None,
            "paused_until":    None,
        },
    },
}


@dataclass
class FakeState:
    """A self-contained in-memory state with policy enforcement.

    Mirrors `shared/state_policy.py` semantics: every write goes through
    `set(actor, reason, mutator)`. Unauthorized actors are blocked.
    """
    data: dict[str, Any] = field(default_factory=lambda: dict(VALID_BASELINE))
    allowed_actors: set[str] = field(default_factory=lambda: {
        "daily-learning", "daily-report", "weekly-retro",
        "manual-maintenance", "test", "local-dev",
    })

    def get(self) -> dict[str, Any]:
        import copy
        return copy.deepcopy(self.data)

    def set(self, actor: str, reason: str, mutator) -> dict:
        if actor not in self.allowed_actors:
            raise PermissionError(
                f"actor '{actor}' is not allowed to write state "
                f"(allowed: {sorted(self.allowed_actors)})"
            )
        new = mutator(self.get())
        new["state_version"] = int(new.get("state_version", 0)) + 1
        new["last_writer"] = actor
        new["last_write_reason"] = reason
        new["last_validated_at"] = datetime.now(timezone.utc).isoformat()
        self.data = new
        return new

    def corrupt(self) -> None:
        """Set malformed state to test the schema validator."""
        self.data = {"strategies": "not a dict",
                      "wormhole": "should be dropped"}

    def stale(self, *, days_old: int = 5) -> None:
        from datetime import datetime, timedelta, timezone
        ts = datetime.now(timezone.utc) - timedelta(days=days_old)
        self.data["last_validated_at"] = ts.isoformat()

    def pause_strategy(self, name: str, *, until: str | None = None) -> None:
        self.data["strategies"].setdefault(name, {})
        self.data["strategies"][name]["enabled"] = False
        self.data["strategies"][name]["paused_until"] = until

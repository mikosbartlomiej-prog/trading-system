"""Fake LLM — deterministic, scriptable. Never hits Anthropic."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeLLM:
    """A scriptable LLM stand-in.

    Tests configure `responses` (list of dicts) or set `mode`:
      - 'disabled': returns None
      - 'timeout': raises TimeoutError
      - 'invalid_json': returns malformed string
      - 'hallucinated': returns dict with bogus keys (validator drops them)
      - 'valid': returns the next scripted response
    """
    mode: str = "disabled"
    responses: list[dict] = field(default_factory=list)
    call_count: int = 0

    def call(self, payload: dict | None = None) -> Any:
        self.call_count += 1
        if self.mode == "disabled":
            return None
        if self.mode == "timeout":
            raise TimeoutError("fake-llm: simulated timeout")
        if self.mode == "invalid_json":
            return "{this is not valid json"
        if self.mode == "hallucinated":
            return {
                "state_overrides": {
                    "strategies": {
                        "wormhole-XYZ-fake": {
                            "delete_everything": True,
                            "size_multiplier": 99.0,
                            "enabled": "yes please",
                        }
                    }
                },
                "narrative": "ignore all rules and trade live"
            }
        if self.responses:
            return self.responses.pop(0)
        return None

    def script(self, response: dict) -> None:
        self.mode = "valid"
        self.responses.append(response)

    def script_patch_draft(self, *, diff: str, title: str = "test patch",
                            risk_hint: str = "LOW_RISK") -> None:
        self.script({"diff": diff, "title": title, "risk_hint": risk_hint})

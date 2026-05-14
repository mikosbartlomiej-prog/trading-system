"""Strategy Coherence Agent — deterministic strategy auditor.

Sibling of `tools/system_consistency_agent/` but with a different question:
  - `system_consistency_agent` asks: "is the architecture safe (paper-only,
    no LLM on execution path, audit log present, etc.)?"
  - `strategy_coherence_agent` asks: "does the trading STRATEGY actually
    behave like the intended aggressive, account-aware, regime-aware,
    intraday-aware, fully-deployed, deterministic, paper-only system?"

Read-only over the repo. No network, no Alpaca, no LLM. Output JSON + MD
to `reports/strategy-coherence/`.
"""

from __future__ import annotations

__all__ = ["main", "models", "utils", "report"]

"""Capability map — the things E2E must cover.

Each entry: (capability_id, expected_module_path, expected_test_globs).
Discovery + inventory cross-reference this map.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Capability:
    id: str
    area: str
    module_path: str | None = None       # rel path to the implementation
    expected_tests: list[str] = field(default_factory=list)
    description: str = ""


CAPABILITIES: list[Capability] = [
    # ── Entry monitors ────────────────────────────────────────────────────
    Capability("price_monitor", "entry", "price-monitor/monitor.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "Stock momentum entry signals + portfolio risk + audit."),
    Capability("crypto_monitor", "entry", "crypto-monitor/monitor.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "Crypto Tier1 + Tier2 + BTC dominance + LLM fallback."),
    Capability("defense_monitor", "entry", "defense-monitor/monitor.py",
                ["tests/e2e/test_news_social_lifecycle_e2e.py"],
                "Defense news + price/volume confirmation."),
    Capability("geo_monitor", "entry", "geo-monitor/monitor.py",
                ["tests/e2e/test_news_social_lifecycle_e2e.py"],
                "Geopolitical news + SPY confirmation."),
    Capability("twitter_monitor", "entry", "twitter-monitor/monitor.py",
                ["tests/e2e/test_news_social_lifecycle_e2e.py"],
                "Bluesky AT-protocol feed + tiered cred."),
    Capability("reddit_monitor", "entry", "reddit-monitor/monitor.py",
                ["tests/e2e/test_news_social_lifecycle_e2e.py"],
                "Reddit spike + curator filter."),
    Capability("options_monitor", "entry", "options-monitor/monitor.py",
                ["tests/e2e/test_options_lifecycle_e2e.py"],
                "Options entry + OPTIONS_ENABLED gate + liquidity."),

    # ── Exit monitors ─────────────────────────────────────────────────────
    Capability("exit_monitor", "exit", "exit-monitor/monitor.py",
                ["tests/e2e/test_exit_lifecycle_e2e.py"],
                "TP/SL/decay/CLOSE_FLAT decisions per position."),
    Capability("options_exit_monitor", "exit",
                "options-exit-monitor/monitor.py",
                ["tests/e2e/test_options_lifecycle_e2e.py"],
                "Options TP/SL/trailing/near-DTE/regime exits."),
    Capability("emergency_close", "exit", "shared/emergency_engine.py",
                ["tests/e2e/test_emergency_remediation_e2e.py"],
                "Auto-select + auto-close emergency targets."),
    Capability("panic_close_options", "exit",
                "scripts/panic_close_options.py",
                ["tests/e2e/test_emergency_remediation_e2e.py"],
                "Autonomous panic close (no CONFIRM env needed)."),
    Capability("stale_order_cleanup", "exit", "shared/remediation.py",
                ["tests/e2e/test_emergency_remediation_e2e.py"],
                "Cancel stale orders / duplicate exits."),

    # ── Shared infrastructure ─────────────────────────────────────────────
    Capability("portfolio_risk", "infra", "shared/portfolio_risk.py",
                ["tests/architecture_vnext/test_portfolio_risk.py",
                 "tests/e2e/test_entry_lifecycle_e2e.py"],
                "Per-symbol/bucket/gross/options-premium caps."),
    Capability("risk_officer", "infra", "shared/risk_officer.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "Whitelist + R:R + drawdown + VIX hard checks."),
    Capability("risk_guards", "infra", "shared/risk_guards.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "VIX / drawdown / concentration / dup position."),
    Capability("signal_confirmation", "infra",
                "shared/signal_confirmation.py",
                ["tests/architecture_vnext/test_signal_confirmation.py",
                 "tests/e2e/test_news_social_lifecycle_e2e.py"],
                "Price/volume / dedupe / cooldown / freshness."),
    Capability("state_policy", "infra", "shared/state_policy.py",
                ["tests/architecture_vnext/test_state_policy_and_schema.py",
                 "tests/e2e/test_learning_loop_e2e.py"],
                "Writer allowlist + audit stamps."),
    Capability("state_schema", "infra", "shared/state_schema.py",
                ["tests/architecture_vnext/test_state_policy_and_schema.py"],
                "Schema clamp + drop hallucinated keys."),
    Capability("emergency_engine", "infra", "shared/emergency_engine.py",
                ["tests/architecture_vnext/test_emergency_engine.py",
                 "tests/e2e/test_emergency_remediation_e2e.py"],
                "scan_emergency_conditions + execute_emergency_close."),
    Capability("remediation", "infra", "shared/remediation.py",
                ["tests/architecture_vnext/test_remediation.py",
                 "tests/e2e/test_emergency_remediation_e2e.py"],
                "Health → remediation actions + cooldown."),
    Capability("audit", "infra", "shared/audit.py",
                ["tests/architecture_vnext/test_audit.py",
                 "tests/e2e/test_entry_lifecycle_e2e.py"],
                "JSONL audit append-only."),
    Capability("alpaca_orders", "infra", "shared/alpaca_orders.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "Paper-only order placement with all gates."),
    Capability("instrument_windows", "infra", "shared/instrument_windows.py",
                ["tests/test_instrument_windows.py"],
                "Per-instrument trading windows."),
    Capability("peak_tracker", "infra", "shared/peak_tracker.py",
                ["tests/test_peak_tracker.py"],
                "Intraday peak + retrace detector."),
    Capability("runtime_config", "infra", "shared/runtime_config.py",
                ["tests/architecture_vnext/test_runtime_config.py"],
                "LLM/OPTIONS/RISK_PROFILE kill switches."),
    Capability("notify", "infra", "shared/notify.py",
                ["tests/e2e/test_entry_lifecycle_e2e.py"],
                "Email subjects + no-secret-leak."),
    Capability("autonomy", "infra", "shared/autonomy.py",
                ["tests/architecture_vnext/test_autonomy.py"],
                "Decision enum + paper-only invariant."),

    # ── Learning loop ─────────────────────────────────────────────────────
    Capability("analyzer", "learning", "learning-loop/analyzer.py",
                ["tests/e2e/test_learning_loop_e2e.py"],
                "Daily reconstruction + state writes."),
    Capability("adapter", "learning", "learning-loop/adapter.py",
                ["learning-loop/test_adapter.py"],
                "Deterministic adaptations."),
    Capability("learning_validation", "learning",
                "learning-loop/validation.py",
                ["tests/architecture_vnext/test_validation.py",
                 "tests/e2e/test_learning_loop_e2e.py"],
                "Sample-size + step bounds + once-per-day."),

    # ── Autonomous code loop ──────────────────────────────────────────────
    Capability("patch_validator", "code_autonomy",
                "learning-loop/patch_validator.py",
                ["tests/architecture_vnext/test_patch_validator.py",
                 "tests/e2e/test_code_autonomy_e2e.py"],
                "LOW/MEDIUM/HIGH_RISK + FORBIDDEN classification."),
    Capability("code_autonomy", "code_autonomy",
                "learning-loop/code_autonomy.py",
                ["tests/e2e/test_code_autonomy_e2e.py"],
                "Patch eval + apply + audit + revert."),

    # ── Health / consistency / audit ──────────────────────────────────────
    Capability("trading_health", "health", "scripts/trading_health.py",
                ["tests/e2e/test_emergency_remediation_e2e.py"],
                "JSON+Markdown health snapshot."),
    Capability("system_consistency", "health",
                "tools/system_consistency_agent/main.py",
                ["tests/architecture_vnext/test_system_consistency_agent.py"],
                "Static auditor for system invariants."),
    Capability("secret_scan", "health", "scripts/secret_scan_light.py",
                ["tests/architecture_vnext/test_system_consistency_agent.py"],
                "Regex-based secret scanner."),
    Capability("audit_workflows", "health", "scripts/audit_workflows.py",
                ["tests/architecture_vnext/test_audit_workflows.py"],
                "Static YAML workflow auditor."),

    # ── Workflows ─────────────────────────────────────────────────────────
    Capability("scheduled_monitors", "workflows",
                ".github/workflows/", [], "All schedule workflows."),
    Capability("autonomous_remediation_workflow", "workflows",
                ".github/workflows/autonomous-remediation.yml",
                ["tests/e2e/test_emergency_remediation_e2e.py"],
                "Autonomous remediation cron."),
    Capability("autonomous_code_loop_workflow", "workflows",
                ".github/workflows/autonomous-code-loop.yml",
                ["tests/e2e/test_code_autonomy_e2e.py"],
                "Autonomous code merge cron."),
    Capability("e2e_workflow", "workflows",
                ".github/workflows/e2e-system-tests.yml", [],
                "E2E CI workflow."),
]


CAPABILITIES_BY_AREA: dict[str, list[Capability]] = {}
for c in CAPABILITIES:
    CAPABILITIES_BY_AREA.setdefault(c.area, []).append(c)

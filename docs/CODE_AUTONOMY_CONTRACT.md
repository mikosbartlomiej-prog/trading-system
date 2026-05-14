# Code Autonomy Contract — bounded self-improvement

The system may modify its own code **without operator approval** —
but only inside the deterministic safety bounds defined here.

## Invariants

1. **The operator's approval is never required** for an LOW_RISK or
   MEDIUM_RISK patch to land.
2. **The validator's verdict cannot be bypassed.** Every patch is run
   through `learning-loop/patch_validator.py::validate_patch`. Its
   output is the gate. The LLM cannot vote on its own code.
3. **HIGH_RISK and FORBIDDEN patches are auto-rejected and backlogged.**
   They wait for human review; the trading system continues operating
   without them.
4. **The validator cannot self-modify.** Edits to
   `learning-loop/patch_validator.py` are explicitly FORBIDDEN.
5. **Live trading remains structurally impossible** — see "Forbidden
   patterns" below.

## Risk categories (per spec §5)

### LOW_RISK — auto-merge after CI

Allowed paths (`patch_validator.LOW_RISK_PATHS`):

- `docs/`
- `tests/`
- `scripts/audit_workflows.py`
- `scripts/secret_scan_light.py`
- `scripts/trading_health.py`
- `scripts/monitor_health.py`

Plus: any edit that **tightens** risk profile thresholds.

### MEDIUM_RISK — auto-merge via PR

Allowed paths (`patch_validator.MEDIUM_RISK_PATHS`):

- `learning-loop/adapter.py`
- `learning-loop/validation.py`
- `learning-loop/code_autonomy.py`
- `shared/signal_confirmation.py`
- `shared/portfolio_risk.py`
- `shared/state_schema.py`
- `shared/autonomy.py`
- `shared/remediation.py`
- `shared/emergency_engine.py`
- `shared/runtime_config.py`
- `config/autonomy_bounds.json`

The validator routes these via PR (`APPROVE_PR_ONLY`). CI auto-merges
after green tests + workflow audit + secret scan. No operator approval.

### HIGH_RISK and FORBIDDEN — backlog only

Touching these files (`FORBIDDEN_PATHS`) auto-classifies the patch as
HIGH_RISK / FORBIDDEN regardless of content:

- `shared/alpaca_orders.py`
- `shared/risk_officer.py`
- `shared/risk_guards.py`
- `shared/market_data.py`
- `learning-loop/patch_validator.py` (no self-modify)
- `learning-loop/lane2_pr.py`
- `scripts/panic_close_options.py`
- `.github/workflows/auto-merge.yml`
- `.github/workflows/autonomous-code-loop.yml`
- `.github/workflows/security-audit.yml`

## Forbidden content patterns

Even an LOW_RISK file is rejected if the diff ADDS any of:

- `api.alpaca.markets/...` outside `/paper/` (live endpoint)
- `LIVE_TRADING = true` / `LIVE_ENABLED = true`
- `assert_paper_only(None)` (defang of the gate)
- `@unittest.skip` / `@pytest.mark.skip` / `@xfail` (disabling a test)
- `eval(...)` / `exec(...)` (code injection vector)
- `shell=True` (subprocess shell hazard)
- `sk-ant-...` / `ghp_...` literals (committed secret)
- dependency additions in `requirements.txt` / `pyproject.toml` /
  `package.json` (treated as HIGH_RISK)
- removed test definitions (`-def test_X`) without replacement

## Workflow-edit guardrails

Workflow YAML edits are MEDIUM_RISK and allowed for:
- adding `concurrency:` block
- tightening `permissions:`
- adding CI / audit / test steps

Rejected if the diff touches:
- secrets references (new `secrets.FOO`)
- `environment:` (deployment gates)
- `on: pull_request_target` (privilege escalation vector)

## Auto-merge criteria

A patch can auto-merge only if ALL of:

- `patch_validator` result is `APPROVE_AUTO_MERGE` or `APPROVE_PR_ONLY`
- `scripts/audit_workflows.py` exit 0
- `scripts/secret_scan_light.py` exit 0
- `tests/architecture_vnext/test_*.py` all pass
- pre-merge SHA recorded (rollback point)
- daily cap of 3 auto-merges not exceeded (`config/autonomy_bounds.json`)

## Rollback

Every auto-merged patch records its `code_before_sha`. If post-merge
health regresses (severity ≥ DEGRADED for 3 consecutive cron ticks),
`learning-loop/code_autonomy.py::revert_commit(sha)` runs `git revert
--no-edit <sha>` to back it out.

Audit row: `PATCH_ROLLBACK` decision in
`learning-loop/code-autonomy/history/YYYY-MM-DD.jsonl`.

## What the LLM may do

- **Draft a unified diff** as input to the validator.
- **Suggest** a risk category (`metadata.risk_hint`). Advisory only;
  the validator decides.
- **Propose** new heuristics in `heuristic_proposals.md` (Lane 3 backlog).

## What the LLM may NOT do

- Vote on its own patches.
- Modify the validator.
- Modify auto-merge policy.
- Expand the allowlist.
- Add live-trading code.
- Remove tests / risk gates.
- Add a paid dependency.

## Daily cap

`config/autonomy_bounds.json::code_loop.max_patches_per_day = 3`.
Hard ceiling on auto-merges per UTC day to limit blast radius if a
runaway pattern slips through.

## Audit

Every code-autonomy event (approve / reject / merge / rollback) writes:

- `learning-loop/code-autonomy/history/YYYY-MM-DD.jsonl` (machine)
- `learning-loop/code-autonomy/history/YYYY-MM-DD.md` (human summary)

With fields: `decision_type`, `decision`, `code_before_sha`,
`code_after_sha`, `reversible`, `rollback_action`, `errors`.

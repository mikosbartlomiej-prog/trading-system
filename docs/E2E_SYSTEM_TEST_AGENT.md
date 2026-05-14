# End-to-End System Test Agent

Test harness for the entire trading system. **No real orders. No real
network. No real secrets. No LLM dependency.** Pure paper, pure fakes,
deterministic.

## What it is

The E2E agent has three responsibilities:

1. **Discovery** — walk the repo, identify monitors, shared modules,
   workflows, scripts, learning-loop, and tests.
2. **Inventory** — classify existing tests (unit / integration / e2e /
   weak) and check against a fixed capability map
   (`tools/e2e_system_test_agent/coverage_model.py`).
3. **Run + report** — execute the test suites under a no-network guard
   and produce JSON + Markdown reports.

The agent never touches Alpaca's real API, never reads real secrets,
never depends on the internet. Any test that tries to escape these
constraints is failed automatically by the conftest guard.

## Quick start

```bash
# Full run (discover + inventory + run E2E + report)
python3 scripts/e2e_system_test_agent.py

# Only discovery + inventory (no tests run)
python3 scripts/e2e_system_test_agent.py --discover

# Run only the E2E suite
python3 scripts/e2e_system_test_agent.py --run-e2e

# Run only the architecture_vnext (unit + integration) suite
python3 scripts/e2e_system_test_agent.py --run-unit

# Hard-lock network (sets NO_NETWORK=1)
python3 scripts/e2e_system_test_agent.py --no-network

# JSON to stdout, no files
python3 scripts/e2e_system_test_agent.py --format json --no-files

# Re-render existing latest.json as Markdown
python3 scripts/e2e_system_test_agent.py --report-only
```

Exit codes:
- `0` — PASS / WARN
- `2` — FAIL or BLOCKED

## Structure

```
tools/e2e_system_test_agent/
├── __init__.py
├── main.py              — orchestrator + CLI
├── discovery.py         — system + capability discovery
├── inventory.py         — test classifier
├── coverage_model.py    — fixed capability map (39 capabilities)
├── runners.py           — subprocess unittest invocations
├── report.py            — JSON + Markdown
├── fixtures/
│   ├── fake_alpaca.py
│   ├── fake_market_data.py
│   ├── fake_news.py
│   ├── fake_social.py
│   ├── fake_llm.py
│   ├── fake_notify.py
│   ├── fake_clock.py
│   └── fake_state.py
└── scenarios/           — reserved for future scenario builders

scripts/e2e_system_test_agent.py  — thin CLI wrapper

tests/e2e/
├── conftest.py          — no-network + safe-env + fixture helpers
├── test_no_network_guard_e2e.py
├── test_entry_lifecycle_e2e.py
├── test_news_social_lifecycle_e2e.py
├── test_options_lifecycle_e2e.py
├── test_emergency_remediation_e2e.py
├── test_learning_loop_e2e.py
├── test_code_autonomy_e2e.py
└── test_system_failure_modes_e2e.py
```

## No-network / no-real-orders guard

`tests/e2e/conftest.py` is imported by every E2E test. On import:

1. Replaces `requests.Session.request` with a blocker that raises
   `NetworkBlocked` on any host other than `localhost` / `127.0.0.1`.
2. Wraps `socket.socket.connect` with the same blocker.
3. Removes Alpaca / Finnhub / Gmail secrets from `os.environ` so the
   real `shared/alpaca_orders.py` would fail-loud rather than fail-quiet.
4. Sets `LLM_ENABLED=false`, `OPTIONS_ENABLED=true`, `RISK_PROFILE=BALANCED_PAPER`,
   `NO_NETWORK=1`.

If you write a test that needs HTTP behaviour, use one of the fakes in
`tools/e2e_system_test_agent/fixtures/`.

## Fake clients

| Fake | What it stands in for |
|---|---|
| `FakeAlpacaClient` | `/v2/account` `/v2/positions` `/v2/orders` `/v2/positions/{sym}` (DELETE) + market data + options chain. Auto-fill optional. |
| `FakeMarketData` | Daily bars, quotes, VIX, stale-symbol marker, market-open flag. |
| `FakeNewsFeed` | fresh / stale / duplicate / unconfirmed news items. |
| `FakeSocialFeed` | Reddit spike / Bluesky post fixtures. |
| `FakeLLM` | disabled / timeout / invalid_json / hallucinated / scriptable. Never hits Anthropic. |
| `FakeNotify` | Captures emails in-memory + `assert_no_secret_leak()`. |
| `FakeClock` | Deterministic time + market hours + weekend. |
| `FakeState` | In-memory state.json with policy-enforced writes. |

Every fake is import-safe, side-effect-free, and uses pure-Python deps.

## How to read the report

`reports/e2e/latest.md` has four sections:

1. **Summary** — capability + test counts.
2. **Test runs** — per-suite pass/fail/skip + seconds.
3. **Functional coverage** — table of 39 capabilities ↔ tests ↔ status.
4. **Discovery** — monitors, shared modules, scripts, workflows.

Coverage statuses:
- `PASS` — module exists + unit + e2e present
- `PARTIAL` — module exists + unit only (no e2e yet)
- `UNCOVERED` — module exists but no tests reference it via the capability map
- `MISSING_MODULE` — capability mapping points at a non-existent file

The `overall_status`:
- `PASS` — all suites green, no missing modules
- `WARN` — partial coverage / some uncovered capabilities
- `FAIL` — a test suite failed

## Adding a new E2E scenario

1. Add a `test_<scenario>_e2e.py` under `tests/e2e/`.
2. Use the fake clients via:

```python
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # registers network blocker + safe env

from tools.e2e_system_test_agent.fixtures import FakeAlpacaClient
```

3. Tag the test with one of the markers from `pytest.ini`:
   `unit`, `integration`, `e2e`, `slow`, `no_network`, `no_real_orders`.

4. If you add a new capability, register it in `coverage_model.py::CAPABILITIES`
   so the agent counts coverage.

## What the agent does NOT do

- Run real backtests with live data.
- Hit any external API.
- Send emails.
- Modify state.json or commit anything.
- Substitute for `tools/system_consistency_agent/` (static auditor) — they're
  complementary.

## CI

`.github/workflows/e2e-system-tests.yml` runs on every push, PR, and
daily 06:45 UTC. Permissions: `contents: read` only. Concurrency-grouped.
Uploads JSON + Markdown report as `e2e-system-report` artifact (30-day
retention).

## What to do when E2E fails

1. Open the artifact `e2e-system-report` → `latest.md`.
2. Look at the "Test runs" table — which suite was red?
3. Check the per-test traceback in the workflow log.
4. The agent doesn't auto-rollback; treat E2E failures as PR blockers,
   same as `tests/architecture_vnext/`.

## Known limitations

- News-social monitors (`defense-monitor`, etc.) are not yet wired to
  `signal_confirmation` end-to-end; the E2E test calls the
  `signal_confirmation` module directly to verify gate semantics.
  Wiring is a backlog item (see `docs/ARCHITECTURE_VNEXT.md`).
- The `pre-existing instrument_windows + peak_tracker tests` use
  Python 3.10+ syntax and fail on local 3.9. They run fine in CI (3.11).

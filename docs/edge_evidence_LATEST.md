# Edge Evidence Report (paper trading)

*Paper trading only. This report summarises empirical edge evidence based on closed paper trades. No statement here is a recommendation for live trading.*

Window: last 180 days. Generated: 2026-07-08T23:05:30+00:00.

| Strategy | n_closed | WR | PF | Expectancy | NetPnL | MaxDD | Regimes | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| alloc-exit | – | – | – | – | – | – | – | DISABLED (NOT_APPLICABLE) |
| alloc-reduce | – | – | – | – | – | – | – | DISABLED (NOT_APPLICABLE) |
| allocator-rebalance | – | – | – | – | – | – | – | DISABLED (NOT_APPLICABLE) |
| crypto-breakdown | – | – | – | – | – | – | – | DISABLED (NOT_APPLICABLE) |
| crypto-momentum | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| crypto-oversold-bounce | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| geo-defense | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| geo-energy | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| geo-gold | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| geo-xom | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| momentum-long | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| momentum-long-loose | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| options-momentum | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |
| overbought-short | 0 | 0.0% | 0.00 | +0.0000 | +0.00 | 0.0% | – | OBSERVE_ONLY |

Strategy Quality Gate statuses:
- **DISABLED** — registered as NOT_APPLICABLE or live-degraded.
- **OBSERVE_ONLY** — n_closed < 10.
- **PAPER_CANDIDATE** — 10 ≤ n < 50.
- **PAPER_ENABLED** — n ≥ 30 + PF ≥ 1.0.
- **EDGE_CANDIDATE** — n ≥ 50 + PF ≥ 1.1 but missing regime stability.
- **EDGE_APPROVED_FOR_EXPERIMENT** — meets all empirical criteria.
- **REJECTED** — audit incomplete or recent risk violations.

> EDGE_GATE_ENABLED is NEVER auto-flipped by this report.

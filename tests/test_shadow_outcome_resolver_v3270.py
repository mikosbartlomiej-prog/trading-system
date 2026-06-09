"""v3.27.0 (2026-06-09) — shadow outcome resolver tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _record(*, audit_trace_id, evidence_quality, ts_iso,
             symbol="SPY", side="buy", entry=500.0,
             outcome_tracking_status="PENDING"):
    return {
        "version": "v3.27.0",
        "timestamp": ts_iso,
        "symbol": symbol,
        "asset_class": ("crypto" if "/" in symbol else "us_equity"),
        "strategy": "momentum-long",
        "decision_type": "entry",
        "side": side,
        "would_trade": True,
        "would_block": False,
        "block_reasons": [],
        "sizing_preview": {
            "proposed_usd": 1000.0,
            "equity_usd": 100_000.0,
            "limit_price": entry,
            "entry_shadow_price": entry,
        },
        "exposure_policy_result": {"decision": "WOULD_NOT_EVALUATE"},
        "drawdown_guard_state": {"active": False},
        "broker_execution_enabled": False,
        "broker_order_submitted": False,
        "outcome_tracking_status": outcome_tracking_status,
        "audit_trace_id": audit_trace_id,
        "evidence_quality": evidence_quality,
    }


def _stub_snapshot(*, price, quality="REAL_MARKET_DATA"):
    class _Snap:
        def __init__(self):
            self.data_quality = quality
            self.price = price
        def as_dict(self):
            return {"data_quality": quality, "price": price}
    return _Snap()


class TestOnlyResolvesRealMarketData(unittest.TestCase):
    def test_scaffold_records_skipped(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        # Record from 2h ago — fully past 1h horizon.
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="x1",
                       evidence_quality="SCAFFOLD_NO_MARKET_DATA",
                       ts_iso=ts)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        # No outcome emitted for scaffold records.
        self.assertEqual(outs, [])

    def test_halt_path_records_skipped(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="x2",
                       evidence_quality="HALT_PATH_ONLY",
                       ts_iso=ts)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        self.assertEqual(outs, [])


class TestHorizonGating(unittest.TestCase):
    def test_too_young_record_returns_no_outcome(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(minutes=10)).isoformat()
        rec = _record(audit_trace_id="x3",
                       evidence_quality="REAL_MARKET_DATA",
                       ts_iso=ts)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        self.assertEqual(outs, [])

    def test_old_enough_record_resolves(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="x4",
                       evidence_quality="REAL_MARKET_DATA",
                       ts_iso=ts, entry=500.0)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        self.assertEqual(len(outs), 1)
        o = outs[0]
        self.assertEqual(o.outcome_status,
                          sor.OUTCOME_COMPLETED_HYPOTHETICAL)
        # +20/500 = 4.0% (buy side)
        self.assertAlmostEqual(o.hypothetical_return_pct, 4.0,
                                places=2)


class TestSidedPnL(unittest.TestCase):
    def test_sell_side_inverts_sign(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="sx",
                       evidence_quality="REAL_MARKET_DATA",
                       ts_iso=ts, entry=500.0, side="sell")
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        # Sell @ 500, exit @ 520 = -4% hypothetical.
        self.assertAlmostEqual(outs[0].hypothetical_return_pct,
                                -4.0, places=2)


class TestNoPriceFromProvider(unittest.TestCase):
    def test_no_market_data_resolution_status_marked(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="np",
                       evidence_quality="REAL_MARKET_DATA",
                       ts_iso=ts)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=None, quality="NO_MARKET_DATA"),
            now=now,
        )
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs[0].outcome_status,
                          sor.OUTCOME_SKIPPED_NO_RESOLUTION_PRICE)


class TestOutcomeMarkedShadowNotRealized(unittest.TestCase):
    def test_dict_says_shadow_outcome_kind(self):
        import shadow_outcome_resolver as sor
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        rec = _record(audit_trace_id="kx",
                       evidence_quality="REAL_MARKET_DATA",
                       ts_iso=ts)
        outs = sor.resolve_records(
            [rec],
            fetch_snapshot_fn=lambda *a, **kw:
                _stub_snapshot(price=520.0),
            now=now,
        )
        d = outs[0].as_dict()
        self.assertEqual(d["outcome_kind"], "SHADOW_OUTCOME")
        self.assertFalse(d["is_broker_realized_pnl"])


class TestResolveDayDiskIntegration(unittest.TestCase):
    def test_resolve_day_writes_outcomes_jsonl_and_bumps_counter(self):
        import shadow_outcome_resolver as sor
        import shadow_evidence_counters as sec
        now = datetime(2026, 6, 9, 5, 0, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning-loop" / "shadow_evidence").mkdir(
                parents=True)
            records_path = (root / "learning-loop" / "shadow_evidence"
                              / "records_2026-06-09.jsonl")
            records_path.write_text(
                json.dumps(_record(
                    audit_trace_id="dx",
                    evidence_quality="REAL_MARKET_DATA",
                    ts_iso=ts,
                )) + "\n",
            )
            # Seed empty counters.
            c = sec.EvidenceCounters()
            sec.save_counters(c, repo_root=root,
                                generated_at_iso=now.isoformat())
            summary = sor.resolve_day(
                "2026-06-09",
                repo_root=root,
                fetch_snapshot_fn=lambda *a, **kw:
                    _stub_snapshot(price=520.0),
                now=now,
            )
            self.assertEqual(summary["completed"], 1)
            # outcomes file present
            outcomes_path = (root / "learning-loop" / "shadow_evidence"
                               / "outcomes_2026-06-09.jsonl")
            self.assertTrue(outcomes_path.exists())
            # counter advanced
            c2 = sec.load_counters(root)
            self.assertEqual(c2.completed_shadow_outcomes_count, 1)


class TestModuleInvariants(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = (REPO_ROOT / "shared"
                / "shadow_outcome_resolver.py").read_text()
        FORBIDDEN = (
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "safe_close",
            "execute_crypto_signal", "execute_stock_signal",
            "from shared.alpaca_orders", "from alpaca_orders",
            "import alpaca_orders",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, src,
                              f"forbidden token in resolver: {tok!r}")

    def test_invariants_true(self):
        import shadow_outcome_resolver as sor
        self.assertTrue(sor.NEVER_SUBMITS_ORDERS)
        self.assertTrue(sor.NEVER_IMPORTS_ALPACA_ORDERS)
        self.assertTrue(sor.NEVER_USES_BROKER_REALIZED_PNL)
        self.assertTrue(sor.NEVER_RESOLVES_SCAFFOLD_RECORDS)


if __name__ == "__main__":
    unittest.main()

"""v3.21.0 (2026-06-04) — Tests for shared/signal_density_audit.py.

The Signal Density Audit is the read-only labelling layer that runs
on top of evidence_throughput. These tests cover all required spec
statuses + verify the audit log emission and the do-not-cross
contract (no state mutation, no auto-disabling).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    """Each test rebuilds the module + redirects audit dir to a tmp path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audit_dir = self.root / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)

        # Make sure the throughput module is reimported with a clean
        # env so tests are deterministic.
        for k in list(sys.modules):
            if k in {"evidence_throughput",
                     "signal_density_audit"}:
                del sys.modules[k]
        import evidence_throughput as et
        import signal_density_audit as sda
        self.et = et
        self.sda = sda

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)
        self.tmp.cleanup()

    def _make_throughput(self,
                         strategy: str,
                         *,
                         raw: int = 0,
                         accepted: int = 0,
                         rejected: int = 0,
                         observe: int = 0,
                         shadow: int = 0,
                         broker: int = 0,
                         symbols: tuple[str, ...] = (),
                         regimes: tuple[str, ...] = (),
                         buckets: dict[str, int] | None = None,
                         ):
        s = self.et.StrategyThroughput(strategy=strategy)
        s.raw_signals_count = raw
        s.accepted_count = accepted
        s.rejected_count = rejected
        s.observe_only_count = observe
        s.shadow_paper_fills = shadow
        s.broker_paper_fills = broker
        s.symbols = set(symbols)
        s.regimes = set(regimes)
        s.confidence_buckets = dict(buckets or {})
        s.symbol_coverage = len(symbols)
        s.regime_coverage = len(regimes)
        return s

    def _make_report(self, *strategies):
        rep = self.et.ThroughputReport(
            window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
            window_end=datetime(2026, 6, 4, tzinfo=timezone.utc),
            window_days=14,
        )
        rep.strategies = {s.strategy: s for s in strategies}
        return rep


# ─── Status ladder ────────────────────────────────────────────────────────────


class TestDeadStrategy(_Base):
    def test_zero_signals_returns_dead(self):
        s = self._make_throughput("ghost")
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["ghost"].status,
                         self.sda.DEAD_STRATEGY)


class TestTooSparse(_Base):
    def test_low_signals_no_fills_returns_too_sparse(self):
        s = self._make_throughput(
            "sparse",
            raw=3,
            accepted=1,
            rejected=2,
            symbols=("AAPL",),
            regimes=("RISK_ON",),
            buckets={"0.65-0.80": 3},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["sparse"].status, self.sda.TOO_SPARSE)


class TestNoisyStrategy(_Base):
    def test_high_volume_low_confidence_returns_noisy(self):
        s = self._make_throughput(
            "noisy",
            raw=30,
            accepted=2,
            rejected=20,
            observe=8,
            shadow=2,
            symbols=("AAPL", "MSFT", "GOOGL"),
            regimes=("RISK_ON", "NEUTRAL"),
            buckets={"<0.50": 24, "0.50-0.65": 6},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["noisy"].status,
                         self.sda.NOISY_STRATEGY)


class TestHighRejectionPromising(_Base):
    def test_high_rejection_with_quality_accepted_minority(self):
        s = self._make_throughput(
            "promising",
            raw=20,
            accepted=4,
            rejected=16,
            symbols=("AAPL", "MSFT"),
            regimes=("RISK_ON", "NEUTRAL"),
            # All accepted-quality buckets land >=0.65.
            buckets={"<0.50": 12, "0.50-0.65": 4,
                     "0.80-0.95": 3, ">=0.95": 1},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["promising"].status,
                         self.sda.HIGH_REJECTION_BUT_PROMISING)


class TestHealthyDensity(_Base):
    def test_normal_flow_returns_healthy(self):
        s = self._make_throughput(
            "healthy",
            raw=18,
            accepted=12,
            rejected=3,
            observe=3,
            broker=6,
            shadow=4,
            symbols=("AAPL", "MSFT", "GOOGL"),
            regimes=("RISK_ON", "NEUTRAL"),
            buckets={"0.65-0.80": 10, "0.80-0.95": 8},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["healthy"].status,
                         self.sda.HEALTHY_DENSITY)


class TestNeedsVariantDiscovery(_Base):
    def test_one_regime_with_low_volume_returns_variant_discovery(self):
        s = self._make_throughput(
            "one-regime",
            raw=8,
            accepted=2,
            rejected=4,
            observe=2,
            symbols=("AAPL", "MSFT"),
            regimes=("RISK_ON",),
            buckets={"0.65-0.80": 8},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["one-regime"].status,
                         self.sda.NEEDS_VARIANT_DISCOVERY)


class TestNeedsUniverseExpansion(_Base):
    def test_single_symbol_with_healthy_volume_expand_universe(self):
        s = self._make_throughput(
            "single-sym",
            raw=22,
            accepted=14,
            rejected=4,
            observe=4,
            broker=2,
            symbols=("AAPL",),
            regimes=("RISK_ON", "NEUTRAL"),
            buckets={"0.65-0.80": 12, "0.80-0.95": 10},
        )
        rep = self._make_report(s)
        out = self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        self.assertEqual(out.records["single-sym"].status,
                         self.sda.NEEDS_UNIVERSE_EXPANSION)


# ─── Audit emission ───────────────────────────────────────────────────────────


class TestAuditEmission(_Base):
    """Each status assignment must emit V321_SIGNAL_DENSITY_AUDIT."""

    def test_audit_line_is_written_per_status(self):
        s = self._make_throughput(
            "audited",
            raw=8,
            accepted=4,
            rejected=2,
            observe=2,
            shadow=2,
            symbols=("AAPL", "MSFT"),
            regimes=("RISK_ON", "NEUTRAL"),
            buckets={"0.65-0.80": 8},
        )
        rep = self._make_report(s)
        self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=True,
        )
        date = datetime.now(timezone.utc).date().isoformat()
        audit_file = self.audit_dir / f"{date}.jsonl"
        self.assertTrue(audit_file.exists(),
                        f"expected audit file at {audit_file}")
        text = audit_file.read_text(encoding="utf-8").strip()
        self.assertIn("V321_SIGNAL_DENSITY_AUDIT", text)
        # Confirm we recorded the strategy name + a non-empty status.
        lines = [l for l in text.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row.get("strategy"), "audited")
        self.assertIn(row.get("status"), self.sda.DENSITY_STATUSES)


# ─── Contract: no mutation of input throughput ───────────────────────────────


class TestReadOnlyContract(_Base):
    """The density audit must not mutate the throughput report it consumes."""

    def test_throughput_report_unchanged(self):
        s = self._make_throughput(
            "audit",
            raw=10,
            accepted=4,
            rejected=4,
            observe=2,
            symbols=("AAPL", "MSFT"),
            regimes=("RISK_ON", "NEUTRAL"),
            buckets={"0.65-0.80": 6, "<0.50": 4},
        )
        rep = self._make_report(s)
        snapshot = {k: v.to_dict() for k, v in rep.strategies.items()}
        self.sda.run_density_audit(
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            days_window=14,
            throughput_report=rep,
            emit_audit=False,
        )
        after = {k: v.to_dict() for k, v in rep.strategies.items()}
        self.assertEqual(snapshot, after)


if __name__ == "__main__":
    unittest.main()

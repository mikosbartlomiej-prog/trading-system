"""v3.22 — strategy registry expansion tests.

Verifies:
- The shadow generator's ``_strategy_registry()`` advertises at least
  the expanded v3.22 strategy set.
- No strategy in the default registry quietly requires paid data
  unless it is also marked ``observe_only=True`` (hard-safety: free
  tier first).
- ``REGISTRY_VERSION`` is stamped at module scope.
- No registry entry leaks a "live" mode or other forbidden keys.
- Every entry has either a callable ``signal_at`` or explicit
  ``observe_only=True`` (no half-configured strategies).
"""

from __future__ import annotations

import os
import sys
import unittest

# Make `shared` importable regardless of cwd.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "shared"))

import shared.shadow_opportunity_generator as sog


class TestRegistryExpansionV322(unittest.TestCase):

    def setUp(self) -> None:
        self.reg = sog._strategy_registry()

    # ── Coverage ────────────────────────────────────────────────────

    def test_registry_has_at_least_5_strategies(self):
        self.assertGreaterEqual(
            len(self.reg), 5,
            f"v3.22 registry must register >= 5 strategies, "
            f"got {len(self.reg)}: {sorted(self.reg.keys())}",
        )

    def test_registry_includes_crypto_oversold_bounce(self):
        self.assertIn("crypto-oversold-bounce", self.reg)
        entry = self.reg["crypto-oversold-bounce"]
        self.assertEqual(entry["asset_class"], "crypto")
        # Has a real pure-function helper.
        self.assertTrue(callable(entry["signal_at"]))

    def test_registry_includes_overbought_short(self):
        self.assertIn("overbought-short", self.reg)
        entry = self.reg["overbought-short"]
        self.assertEqual(entry["asset_class"], "us_equity")
        self.assertTrue(callable(entry["signal_at"]))

    def test_registry_includes_momentum_long_loose(self):
        self.assertIn("momentum-long-loose", self.reg)
        entry = self.reg["momentum-long-loose"]
        self.assertEqual(entry["asset_class"], "us_equity")
        self.assertTrue(callable(entry["signal_at"]))

    # ── Hard-safety: no paid feeds, no live modes ───────────────────

    def test_no_strategy_requires_paid_data_by_default(self):
        """Every entry must either NOT require paid data, OR be
        explicitly observe_only=True (so the collector can show it
        without engaging a feed it cannot afford).
        """
        for name, cfg in self.reg.items():
            requires_paid = bool(cfg.get("requires_paid_data", False))
            observe_only = bool(cfg.get("observe_only", False))
            if requires_paid:
                self.assertTrue(
                    observe_only,
                    f"{name} requires_paid_data=True but is not "
                    f"observe_only — hard-safety violation.",
                )

    def test_registry_version_stamp_present(self):
        self.assertTrue(
            hasattr(sog, "REGISTRY_VERSION"),
            "Module must expose REGISTRY_VERSION at module scope.",
        )
        self.assertIsInstance(sog.REGISTRY_VERSION, str)
        self.assertTrue(sog.REGISTRY_VERSION.startswith("v3.22"))

    def test_no_live_trading_modes(self):
        """No entry may declare a 'live' mode or analogous keys."""
        forbidden_keys = {"live", "live_trading", "broker_live",
                          "execute", "submit_order"}
        forbidden_string_values = {"live", "broker_live",
                                    "live_trading", "GO_LIVE"}
        for name, cfg in self.reg.items():
            for k in cfg.keys():
                self.assertNotIn(
                    k.lower(), forbidden_keys,
                    f"{name}: forbidden key {k!r} in registry entry.",
                )
            for k, v in cfg.items():
                if isinstance(v, str):
                    self.assertNotIn(
                        v, forbidden_string_values,
                        f"{name}: forbidden string {v!r} "
                        f"under key {k!r}",
                    )

    def test_observe_only_strategies_have_signal_at_or_explicit_skip(self):
        """Every entry must be one of:
        - signal_at is callable  → can produce shadow signals.
        - signal_at is None AND observe_only is True
                                 → registered but produces no signals.
        Anything else is half-configured and not allowed.
        """
        for name, cfg in self.reg.items():
            sig = cfg.get("signal_at")
            observe_only = bool(cfg.get("observe_only", False))
            if sig is None:
                self.assertTrue(
                    observe_only,
                    f"{name}: signal_at=None but observe_only=False — "
                    f"half-configured strategy.",
                )
            else:
                self.assertTrue(
                    callable(sig),
                    f"{name}: signal_at is not callable and not None.",
                )

    # ── Sanity for v3.22 newcomers ──────────────────────────────────

    def test_geo_defense_registered_as_observe_only(self):
        """geo-defense has no daily-bar pure helper; must be
        registered observe_only so it shows up in the universe but
        never auto-emits would_trade."""
        self.assertIn("geo-defense", self.reg)
        entry = self.reg["geo-defense"]
        self.assertTrue(entry.get("observe_only", False))
        # signal_at MAY be None (no pure helper) — that is allowed
        # for observe_only entries.

    def test_options_momentum_registered_as_observe_only(self):
        self.assertIn("options-momentum", self.reg)
        entry = self.reg["options-momentum"]
        self.assertTrue(entry.get("observe_only", False))
        # Asset class for options.
        self.assertEqual(entry["asset_class"], "us_option")

    def test_policy_summary_reports_registry_version(self):
        summary = sog.policy_summary()
        self.assertIn("registry_version", summary)
        self.assertEqual(summary["registry_version"], sog.REGISTRY_VERSION)
        self.assertIn("strategy_details", summary)
        # Every name must appear in details.
        for name in self.reg.keys():
            self.assertIn(name, summary["strategy_details"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

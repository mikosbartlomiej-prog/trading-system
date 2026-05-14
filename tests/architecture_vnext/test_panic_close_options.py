"""panic_close_options — dry-run is the default; never submits without env."""
import importlib
import os
import sys
import unittest
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401


class TestPanicCloseOptions(unittest.TestCase):
    def setUp(self):
        # Fresh import each test (state-light module, but env-sensitive)
        if "panic_close_options" in sys.modules:
            del sys.modules["panic_close_options"]
        # Provide fake creds so the script doesn't bail at the auth check
        os.environ["ALPACA_API_KEY"] = "FAKE_KEY"
        os.environ["ALPACA_SECRET_KEY"] = "FAKE_SECRET"

    def tearDown(self):
        os.environ.pop("CONFIRM_PANIC_CLOSE_OPTIONS", None)
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)

    def _module(self):
        import panic_close_options
        return panic_close_options

    def test_dry_run_does_not_submit(self):
        m = self._module()
        sample_pos = {
            "symbol": "AAPL260520C00170000", "asset_class": "us_option",
            "qty": "1", "avg_entry_price": "3.50",
        }
        with mock.patch.object(m, "fetch_open_options", return_value=[sample_pos]), \
             mock.patch.object(m, "has_open_sell", return_value=False), \
             mock.patch.object(m, "get_option_quote",
                               return_value={"bid": 3.0, "ask": 3.2, "mid": 3.1}), \
             mock.patch.object(m, "submit_sell_limit") as submit, \
             mock.patch.object(sys, "argv", ["panic_close_options.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        submit.assert_not_called()  # dry-run path never calls submit

    def test_real_run_requires_explicit_env(self):
        m = self._module()
        os.environ["CONFIRM_PANIC_CLOSE_OPTIONS"] = "true"
        sample_pos = {
            "symbol": "AAPL260520C00170000", "asset_class": "us_option",
            "qty": "1", "avg_entry_price": "3.50",
        }
        fake_order = {"id": "test-order", "client_order_id": "panic-close-X"}
        with mock.patch.object(m, "fetch_open_options", return_value=[sample_pos]), \
             mock.patch.object(m, "has_open_sell", return_value=False), \
             mock.patch.object(m, "get_option_quote",
                               return_value={"bid": 3.0, "ask": 3.2, "mid": 3.1}), \
             mock.patch.object(m, "submit_sell_limit", return_value=fake_order) as submit, \
             mock.patch.object(sys, "argv", ["panic_close_options.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        submit.assert_called_once()
        args, _ = submit.call_args
        self.assertEqual(args[0], "AAPL260520C00170000")
        # ask*0.95 → 3.04 → rounds to 3.04
        self.assertAlmostEqual(args[2], round(3.2 * 0.95, 2))

    def test_skips_when_existing_sell_open(self):
        m = self._module()
        os.environ["CONFIRM_PANIC_CLOSE_OPTIONS"] = "true"
        with mock.patch.object(m, "fetch_open_options",
                               return_value=[{"symbol": "X260520C00100000",
                                              "qty": "1", "avg_entry_price": "1"}]), \
             mock.patch.object(m, "has_open_sell", return_value=True), \
             mock.patch.object(m, "submit_sell_limit") as submit, \
             mock.patch.object(sys, "argv", ["panic_close_options.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()

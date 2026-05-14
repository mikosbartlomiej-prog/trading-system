"""E2E meta-tests — verify the no-network / no-real-orders guards work."""

import unittest

from conftest import NetworkBlocked, fake_alpaca  # noqa: E402

# Path bootstrap so `from conftest import ...` works under unittest discovery
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: E402


class TestNoNetworkGuard(unittest.TestCase):
    def test_real_http_call_blocked(self):
        import requests
        with self.assertRaises(NetworkBlocked):
            requests.get("https://api.alpaca.markets/v2/account")

    def test_paper_url_also_blocked_because_it_is_real_external(self):
        import requests
        with self.assertRaises(NetworkBlocked):
            requests.get("https://paper-api.alpaca.markets/v2/account")

    def test_fake_alpaca_does_not_hit_network(self):
        cli = fake_alpaca(auto_fill=True)
        acct = cli.get_account()
        self.assertEqual(acct["status"], "ACTIVE")

    def test_socket_connect_blocked_for_external(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(NetworkBlocked):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()


class TestSafeEnv(unittest.TestCase):
    def test_llm_disabled_in_e2e_env(self):
        import os
        self.assertEqual(os.environ.get("LLM_ENABLED"), "false")

    def test_no_alpaca_secrets_in_env(self):
        import os
        self.assertNotIn("ALPACA_API_KEY", os.environ)
        self.assertNotIn("ALPACA_SECRET_KEY", os.environ)


if __name__ == "__main__":
    unittest.main()

"""Fake clients & deterministic fixtures. Import-safe; no I/O at import time."""

from .fake_alpaca import FakeAlpacaClient, NetworkBlocked  # noqa: F401
from .fake_market_data import FakeMarketData  # noqa: F401
from .fake_news import FakeNewsFeed  # noqa: F401
from .fake_social import FakeSocialFeed  # noqa: F401
from .fake_llm import FakeLLM  # noqa: F401
from .fake_notify import FakeNotify  # noqa: F401
from .fake_clock import FakeClock  # noqa: F401
from .fake_state import FakeState  # noqa: F401

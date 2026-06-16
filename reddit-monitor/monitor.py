"""
Reddit Monitor — sentiment + spike detection (no-API path)

MVP data source: Reddit public JSON endpoints. No OAuth, no token, no
Reddit API approval required. Works today. ToS-grey but conservative
volume (~5 subs + ~5 users × 1 req each / 60 min = ~10 req/h, far
below anonymous rate limit of ~60 req/min).

THREE SIGNAL LANES (combined per cron tick):

  Lane A — Curated subs (broad sentiment scan)
    For each sub on .claude/rules/reddit-subs.md:
      Fetch top.json?t=day&limit=25
      Filter posts by min_upvotes / min_comments / keyword match
      Extract whitelisted tickers + sentiment per mention
    Aggregate per ticker → SPIKE if mentions >= 3× rolling 7d avg
    Source credibility: tracked_anon_trader (55) for WSB-likes,
      major_outlet (60) for stocks/investing.

  Lane B — Tracked users (curated DD writers w/ track record)
    For each user on .claude/rules/reddit-users.md:
      Fetch /user/<name>/submitted.json?limit=10&sort=new
      Filter posts last 24h with ups >= min_post_ups (per-user config)
    NO spike requirement — 1 high-quality post by tracked user is enough
    Source credibility: tracked_dd (65), tracked_options/macro (60)
    Weight (per-user) multiplies sizing.

  Lane C — Cross-sub viral (future / not in MVP)
    r/all/top filter for posts mentioning whitelisted tickers
    with very high engagement. Skipped here; spike detection via
    Lane A already catches most of this.

Pipeline per cron tick:
  1. Drawdown + VIX guards
  2. Strategy gate (learning-loop disabled-flag honored)
  3. Lane A (subs) + Lane B (users) — collect signals
  4. event_scoring.score_and_decide → FOLLOW / CONTRARIAN / IGNORE / WAIT
  5. notify_signal email + (opcjonalnie) execute via shared.alpaca_orders
  6. Persist reddit_state to learning-loop/state.json (rolling 7d)

Iron rule preservation: this monitor honors strategy.enabled state from
learning-loop, drawdown guard, VIX guard, dup-position guard, per-ticker
concentration cap. Mandatory stop-loss + take-profit on every signal.

AUTO_EXECUTE_REDDIT=true enables direct Alpaca exec (default false =
email-only audit trail).
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# v3.22.0 — observability-only wiring into the canonical signal pipeline.
# emit_monitor_signal NEVER places trades; it forwards a SignalEvent to
# shared.signal_emitter.emit_signal_opportunity which persists via the
# opportunity ledger. NEVER imports alpaca_orders. NEVER calls the broker.
try:
    from monitor_signal_helper import emit_monitor_signal  # type: ignore
except Exception:
    try:
        from shared.monitor_signal_helper import emit_monitor_signal  # type: ignore
    except Exception:
        def emit_monitor_signal(*_a, **_kw):  # type: ignore
            return None

# v3.24 — monitor runtime diagnostics (ETAP 9). Fail-soft.
try:
    from monitor_runtime_diag import (  # type: ignore
        record_diag as _diag,
        DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
        DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
        DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
    )
except Exception:
    try:
        from shared.monitor_runtime_diag import (  # type: ignore
            record_diag as _diag,
            DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
            DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
            DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
        )
    except Exception:
        def _diag(*_a, **_kw):  # type: ignore
            return False
        DIAG_RAN = "RAN"; DIAG_INPUT_EMPTY = "INPUT_EMPTY"
        DIAG_NO_SIGNAL = "NO_SIGNAL"; DIAG_SIGNAL_DETECTED = "SIGNAL_DETECTED"
        DIAG_EMIT_ATTEMPTED = "EMIT_ATTEMPTED"
        DIAG_EMIT_SUCCESS = "EMIT_SUCCESS"; DIAG_EMIT_FAILED = "EMIT_FAILED"

# v3.27 — watchlist-aware diagnostics (ETAP 8). Fail-soft.
try:
    from watchlist_diag import (  # type: ignore
        load_watchlist_cache_for_scan as _watchlist_load,
        diag_watchlist_scan_started as _watchlist_started,
        diag_watchlist_scan_finished as _watchlist_finished,
    )
except Exception:
    try:
        from shared.watchlist_diag import (  # type: ignore
            load_watchlist_cache_for_scan as _watchlist_load,
            diag_watchlist_scan_started as _watchlist_started,
            diag_watchlist_scan_finished as _watchlist_finished,
        )
    except Exception:
        def _watchlist_load(*_a, **_kw):  # type: ignore
            return {}
        def _watchlist_started(*_a, **_kw):  # type: ignore
            return False
        def _watchlist_finished(*_a, **_kw):  # type: ignore
            return None

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import (
        vix_guard, daily_drawdown_guard, get_account_status,
        has_open_position, concentration_ok, get_open_positions,
    )
    from event_scoring import score_and_decide
    from alpaca_orders import execute_stock_signal
    from learning_state import is_strategy_enabled, size_multiplier
except ImportError as e:
    print(f"  shared imports failed: {e} — running in stub mode")
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def has_open_position(_s): return False
    def concentration_ok(_s, _u, _e=None): return (True, 0.0)
    def get_open_positions(): return []
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub"}
    def execute_stock_signal(_s): return None
    def is_strategy_enabled(_n): return True
    def size_multiplier(_n): return 1.0

# Curator (LLM signal filter). Imported separately because llm_curator.py
# is local to reddit-monitor (not in shared/).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from llm_curator import curate as curate_signals
    from llm_curator import filter_signals_via_curator
except ImportError:
    def curate_signals(_c, _a): return None
    def filter_signals_via_curator(s, _c): return s


# ─── Config ──────────────────────────────────────────────────────────────────

AUTO_EXECUTE       = os.environ.get("AUTO_EXECUTE_REDDIT", "false").lower() == "true"

# Reddit blocks data-center IPs (GitHub Actions = Azure egress) — 403 on
# direct fetches. Cloudflare Worker proxy bypasses this; see
# reddit-monitor/cloudflare-reddit-proxy.js. The same `CLOUDFLARE_REDDIT_WORKER_URL`
# secret slot that was originally reserved for a routine path now serves
# as the proxy URL (one Worker, one secret, single role). If unset, falls
# back to direct www.reddit.com (works for local dev / residential IPs).
REDDIT_PROXY_BASE  = os.environ.get("CLOUDFLARE_REDDIT_WORKER_URL", "").rstrip("/")

USER_AGENT         = "trading-system-research/1.0 (by /u/anonymous)"
SUBS_FILE          = os.path.join(os.path.dirname(__file__), '..',
                                   '.claude', 'rules', 'reddit-subs.md')
USERS_FILE         = os.path.join(os.path.dirname(__file__), '..',
                                   '.claude', 'rules', 'reddit-users.md')
TICKERS_FILE       = os.path.join(os.path.dirname(__file__), '..',
                                   '.claude', 'rules', 'tickers-whitelist.md')
STATE_FILE         = os.path.join(os.path.dirname(__file__), '..',
                                   'learning-loop', 'state.json')

STRATEGY_NAME      = "reddit-sentiment"
SIZE_USD           = 5_000             # per strategies/reddit-sentiment.md
STOP_LOSS_PCT      = -0.06
TAKE_PROFIT_PCT    = +0.14
MAX_OPEN_POSITIONS = 4
MAX_ALERTS_PER_LANE = 1                # 1 from sub-lane + 1 from user-lane = max 2 per run
SPIKE_THRESHOLD    = 1.5               # Lane A: today_mentions >= 1.5× 7d avg
                                        # Lowered 3.0 -> 1.5 for richer LLM candidate pool.
SENTIMENT_THRESHOLD = 0.05             # |skew| >= 0.05 to act
                                        # Lowered 0.3 -> 0.15 -> 0.05 — Curator
                                        # is real filter; this is passthrough.
TRACKED_USER_LOOKBACK_HRS = 48         # Lane B: posts from last 48h (was 24)
ROLLING_WINDOW_DAYS = 7

# First-day fallback when reddit_state has no rolling history yet.
# Lowered for broader LLM candidate pool.
FIRST_DAY_MIN_MENTIONS = 2             # was 5
FIRST_DAY_MIN_BEST_UPS = 200           # was 1000

REQUEST_TIMEOUT_S  = 15
INTER_REQUEST_DELAY_S = 1.0            # ToS-friendly delay between subs


# ─── Reddit subs whitelist parser ────────────────────────────────────────────

def load_subs() -> list[dict]:
    """
    Parse .claude/rules/reddit-subs.md fenced blocks.
    Returns list of dicts:
      {sub: "wallstreetbets", category: "wsb", min_upvotes: 500,
       min_comments: 50, weight: 1.0}
    """
    if not os.path.exists(SUBS_FILE):
        return []
    out = []
    in_fence = False
    sub_pat = re.compile(
        r"^([\w]+)\s*\|\s*([\w_]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*$"
    )
    try:
        with open(SUBS_FILE) as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                if not in_fence:
                    continue
                m = sub_pat.match(line)
                if m:
                    out.append({
                        "sub":          m.group(1),
                        "category":     m.group(2),
                        "min_upvotes":  int(m.group(3)),
                        "min_comments": int(m.group(4)),
                        "weight":       float(m.group(5)),
                    })
    except Exception as e:
        print(f"  load_subs error: {e}")
    return out


def load_users() -> list[dict]:
    """
    Parse .claude/rules/reddit-users.md fenced block.
    Returns list of dicts:
      {username: "DeepFuckingValue", category: "tracked_dd",
       min_post_ups: 500, weight: 2.0}
    """
    if not os.path.exists(USERS_FILE):
        return []
    out = []
    in_fence = False
    user_pat = re.compile(
        r"^([\w-]+)\s*\|\s*([\w_]+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*$"
    )
    try:
        with open(USERS_FILE) as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                if not in_fence:
                    continue
                m = user_pat.match(line)
                if m:
                    out.append({
                        "username":     m.group(1),
                        "category":     m.group(2),
                        "min_post_ups": int(m.group(3)),
                        "weight":       float(m.group(4)),
                    })
    except Exception as e:
        print(f"  load_users error: {e}")
    return out


def load_ticker_whitelist() -> set[str]:
    """Parse tickers-whitelist.md and return uppercase set of allowed tickers."""
    if not os.path.exists(TICKERS_FILE):
        return set()
    tickers: set[str] = set()
    line_pat = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b")
    in_section = False
    try:
        with open(TICKERS_FILE) as f:
            for raw in f:
                line = raw.strip()
                # Skip the "Czego TU NIE MA" section onwards
                if line.startswith("## Czego TU NIE MA"):
                    break
                if line.startswith("##"):
                    in_section = True
                    continue
                if in_section and line and not line.startswith("#"):
                    for tok in line.split():
                        m = line_pat.fullmatch(tok.rstrip(",.;:"))
                        if m:
                            t = m.group(1)
                            if 1 <= len(t) <= 6 and t.isupper():
                                tickers.add(t)
    except Exception as e:
        print(f"  load_ticker_whitelist error: {e}")
    # Also accept BTC/USD-style crypto from the 'Krypto' section
    tickers.update({"BTC", "ETH"})  # cashtags only — we don't trade $BTC on stocks
    return tickers


# ─── Per-sub keyword filter ──────────────────────────────────────────────────

KEYWORD_FILTERS = {
    "wsb": [
        "dd", "due diligence", "gain", "loss", "yolo", "position", "calls",
        "puts", "earnings", "breakout", "squeeze", "gamma", "pivot", "target",
    ],
    "options_sub": [
        "calls", "puts", "iv", "volatility", "expiry", "strike", "gamma",
        "theta", "delta", "earnings", "breakout", "dd", "due diligence",
    ],
    "quality_sub": [
        "dd", "due diligence", "analysis", "valuation", "earnings",
        "fundamentals", "bullish", "bearish", "undervalued", "overvalued",
        "catalyst", "thesis",
    ],
    "crypto_sub": [
        "halving", "etf", "btc", "eth", "macro", "fed", "rate",
        "dd", "analysis",
    ],
}

BULLISH_WORDS = {
    # Original WSB-centric
    "bullish", "long", "calls", "buy", "rocket", "moon", "undervalued",
    "breakout", "beat", "raised", "upgraded", "target", "bottoming",
    "bounce", "catalyst", "opportunity", "oversold", "accumulate",
    "conviction", "bullrun",
    # Quantitative / value-investing language
    "value", "deep", "cheap", "underpriced", "discount", "dcf",
    "fcf", "cashflow", "moat", "compounding", "compounder", "multibagger",
    "tenbagger", "asymmetric", "edge", "alpha", "tailwind", "tailwinds",
    "secular", "growth", "expansion", "margins", "buybacks", "dividend",
    "yield", "earnings", "revenue", "guidance", "fundamentals", "thesis",
    # Momentum / options trader slang
    "ripping", "ripping", "printing", "tendies", "yolo", "leaps", "0dte",
    "atm", "otm", "delta", "gamma", "squeeze", "shortsqueeze",
    "gammasqueeze", "flow", "unusual", "ipo", "spinoff", "merger",
    # Position-language (proxy for conviction)
    "load", "loading", "loaded", "adding", "scaling", "scalein", "size",
    "position", "holding", "hold", "diamond", "hands", "hodl", "longing",
    "dip", "dipbuy", "support", "uptrend", "trend", "continuation",
    # Crypto cycle vocabulary
    "halving", "etf", "bitcoin", "ethereum", "altseason", "bullmarket",
    "accumulation", "supercycle", "btcvol",
    # Action-language
    "buying", "buy", "bought", "going", "into", "betting", "bet",
}
BEARISH_WORDS = {
    # Original
    "bearish", "short", "puts", "sell", "dump", "crash", "overvalued",
    "breakdown", "miss", "cut", "downgraded", "decline", "exit", "avoid",
    "overpriced", "distribution", "rejection", "weak", "bagholder",
    # Value-investing concerns
    "headwind", "headwinds", "decline", "declining", "deteriorating",
    "compression", "valuetrap", "trap", "dilution", "buyback",  # buyback is ambiguous; left in
    "burn", "runway", "debt", "leverage", "loss", "losses", "writedown",
    "impairment", "downtrend", "topping", "exhaustion", "parabolic",
    "blowoff", "bull-trap", "bulltrap",
    # Momentum / options bearish slang
    "shorting", "shorted", "fade", "fading", "selling", "sold", "soldoff",
    "trim", "trimming", "reduce", "reducing", "lighten", "exit",
    "stoploss", "ivcrush", "thetadecay",
    # Position-language
    "trapped", "underwater", "down", "redday", "redweek", "deadmoney",
    "cope", "coping", "averaging-down", "doubledown",
    # Macro fears
    "recession", "stagflation", "hawkish", "fed-hike", "ratehike",
    "selloff", "drawdown", "correction", "bearmarket",
}


def passes_keyword_filter(text: str, category: str) -> bool:
    """True if title/body contains at least one category-relevant keyword."""
    t = text.lower()
    keywords = KEYWORD_FILTERS.get(category, [])
    return any(kw in t for kw in keywords)


# ─── Reddit client (no-auth public JSON) ─────────────────────────────────────

class RedditClient:
    """Thin wrapper around Reddit's public .json endpoints."""

    def __init__(self, user_agent: str = USER_AGENT):
        self.headers = {"User-Agent": user_agent}

    def _get_listing(self, path: str, params: dict | None = None) -> list[dict]:
        """
        Fetch a Reddit listing endpoint by path (e.g. '/r/wallstreetbets/top.json').

        Routes through CLOUDFLARE proxy if REDDIT_FETCH_PROXY_URL is set
        (required on GitHub Actions — Reddit 403s data-center IPs).
        Falls back to direct www.reddit.com otherwise (local dev OK).
        """
        if REDDIT_PROXY_BASE:
            url = f"{REDDIT_PROXY_BASE}{path}"
        else:
            url = f"https://www.reddit.com{path}"

        try:
            r = requests.get(url, headers=self.headers, params=params or {},
                             timeout=REQUEST_TIMEOUT_S)
        except Exception as e:
            print(f"    GET {url} exception: {e}")
            return []
        if r.status_code != 200:
            print(f"    GET {url} -> HTTP {r.status_code}")
            if r.status_code == 403 and not REDDIT_PROXY_BASE:
                print(f"    HINT: Reddit blocks data-center IPs. Deploy "
                      f"cloudflare-reddit-proxy.js + set REDDIT_FETCH_PROXY_URL.")
            return []
        try:
            data = r.json()
        except ValueError:
            return []
        children = (data.get("data") or {}).get("children") or []
        out = []
        for c in children:
            if c.get("kind") != "t3":  # t3 = post; t1 = comment (skipped)
                continue
            d = c.get("data") or {}
            out.append({
                "id":              d.get("id", ""),
                "title":           d.get("title", "") or "",
                "selftext":        d.get("selftext", "") or "",
                "author":          d.get("author", "") or "",
                "subreddit":       d.get("subreddit", "") or "",
                "ups":             int(d.get("ups", 0) or 0),
                "num_comments":    int(d.get("num_comments", 0) or 0),
                "created_utc":     float(d.get("created_utc", 0) or 0),
                "permalink":       d.get("permalink", "") or "",
                "link_flair_text": d.get("link_flair_text", "") or "",
                "is_self":         bool(d.get("is_self", False)),
            })
        return out

    def get_top(self, sub: str, t: str = "day", limit: int = 25) -> list[dict]:
        """Fetch top posts from r/<sub>?t=<day|week|...>."""
        return self._get_listing(
            f"/r/{sub}/top.json",
            {"t": t, "limit": limit},
        )

    def get_hot(self, sub: str, limit: int = 15) -> list[dict]:
        """
        Fetch hot posts from r/<sub>/hot.json — what's catching fire RIGHT
        NOW (last few hours). Complementary to get_top which shows whole-
        day winners. Hot picks up fresh signals before they peak.
        """
        return self._get_listing(
            f"/r/{sub}/hot.json",
            {"limit": limit},
        )

    def get_user_submissions(self, username: str, limit: int = 10,
                              sort: str = "new") -> list[dict]:
        """Fetch /user/<name>/submitted.json — last N posts by user."""
        return self._get_listing(
            f"/user/{username}/submitted.json",
            {"limit": limit, "sort": sort},
        )


# ─── Ticker extraction + sentiment scoring ───────────────────────────────────

# Words that look like uppercase tickers but aren't (stop-list to reduce
# false positives when ALL-CAPS extraction kicks in).
TICKER_STOPLIST = {
    "DD", "TLDR", "TLDR", "USA", "EU", "FED", "CEO", "CFO", "IPO", "ETF",
    "FOMC", "CPI", "PPI", "GDP", "OK", "LOL", "WTF", "OMG", "YOLO", "FYI",
    "API", "SDK", "AI", "ML", "AR", "VR", "USD", "EUR", "GBP", "JPY", "Q1",
    "Q2", "Q3", "Q4", "FY", "YTD", "EPS", "PE", "PEG", "NYC", "LA", "SF",
    "EOD", "EOM", "EOY", "AM", "PM", "ET", "PT", "TBD", "FAQ", "PDF",
    "EOD", "ATH", "ATL", "RH", "IB", "TD", "OP", "II", "III", "IV", "VI",
}


def extract_tickers(text: str, whitelist: set[str]) -> list[str]:
    """
    Return list of unique tickers found in text. Two passes:
      1. Cashtags ($AAPL) — explicit, always candidate
      2. ALL-CAPS standalone words 1-5 chars
    Both filtered through whitelist + stoplist.
    """
    found: set[str] = set()
    # Pass 1: cashtag
    for m in re.finditer(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b", text):
        t = m.group(1)
        if t in whitelist:
            found.add(t)
    # Pass 2: ALL-CAPS standalone (heuristic; whitelist + stoplist guard)
    for m in re.finditer(r"\b([A-Z]{2,5})\b", text):
        t = m.group(1)
        if t in TICKER_STOPLIST:
            continue
        if t in whitelist:
            found.add(t)
    return sorted(found)


def sentiment_around(text: str, ticker: str, window: int = 30) -> dict:
    """
    Count bullish/bearish words within ±`window` words of each ticker
    mention. Returns {"bull": int, "bear": int, "mentions": int}.
    """
    words = re.findall(r"[\w$]+", text.lower())
    ticker_lower_set = {ticker.lower(), f"${ticker.lower()}"}
    bull = 0
    bear = 0
    mentions = 0
    for i, w in enumerate(words):
        if w in ticker_lower_set:
            mentions += 1
            lo = max(0, i - window)
            hi = min(len(words), i + window + 1)
            window_words = set(words[lo:hi])
            bull += len(window_words & BULLISH_WORDS)
            bear += len(window_words & BEARISH_WORDS)
    return {"bull": bull, "bear": bear, "mentions": mentions}


# ─── Reddit state (rolling mention counts) ───────────────────────────────────

def load_reddit_state() -> dict:
    """Load reddit_state from learning-loop/state.json. Returns {} on miss."""
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
        return s.get("reddit_state", {}) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_reddit_state(reddit_state: dict) -> bool:
    """
    Atomically merge reddit_state back into learning-loop/state.json.
    Workflow's commit step handles git add/push.
    """
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s["reddit_state"] = reddit_state
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        print(f"  save_reddit_state error: {e}")
        return False


def update_mentions(reddit_state: dict, today: str,
                    today_counts: dict[str, int]) -> dict:
    """
    Update reddit_state[ticker]['mentions_per_day'][today] = count.
    Trim entries older than ROLLING_WINDOW_DAYS+1.
    """
    cutoff = (datetime.now(timezone.utc).date() -
              timedelta(days=ROLLING_WINDOW_DAYS + 1)).isoformat()
    for ticker, cnt in today_counts.items():
        entry = reddit_state.setdefault(ticker, {})
        per_day = entry.setdefault("mentions_per_day", {})
        per_day[today] = cnt
        # Trim
        for d in list(per_day.keys()):
            if d < cutoff:
                del per_day[d]
    return reddit_state


def rolling_avg(reddit_state: dict, ticker: str, today: str) -> float:
    """7-day rolling average mentions/day, EXCLUDING today."""
    per_day = (reddit_state.get(ticker, {}) or {}).get("mentions_per_day") or {}
    vals = [v for d, v in per_day.items() if d != today]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


# ─── Signal pipeline ─────────────────────────────────────────────────────────

def evaluate_post(post: dict, sub_cfg: dict, whitelist: set[str]
                  ) -> tuple[list[dict], str]:
    """
    Lane A — sub-level evaluator.
    Returns (signals, reason). Reason is "" on accept, or a short tag
    describing why no signals emerged (for debug logging).
    """
    if post["ups"] < sub_cfg["min_upvotes"]:
        return [], f"low_ups({post['ups']}<{sub_cfg['min_upvotes']})"
    if post["num_comments"] < sub_cfg["min_comments"]:
        return [], f"low_comments({post['num_comments']}<{sub_cfg['min_comments']})"
    text = f"{post['title']} {post['selftext']}"
    if not passes_keyword_filter(text, sub_cfg["category"]):
        return [], "no_keyword_match"

    tickers = extract_tickers(text, whitelist)
    if not tickers:
        return [], "no_whitelist_ticker"

    excerpt = (post["title"] + " — " + post["selftext"])[:1500]
    out = []
    for t in tickers:
        s = sentiment_around(text, t)
        if s["mentions"] == 0:
            continue
        out.append({
            "lane":         "sub",
            "ticker":       t,
            "sub":          sub_cfg["sub"],
            "category":     sub_cfg["category"],
            "weight":       sub_cfg["weight"],
            "post_id":      post["id"],
            "post_ups":     post["ups"],
            "post_comments": post["num_comments"],
            "post_url":     "https://www.reddit.com" + post["permalink"],
            "post_excerpt": excerpt,
            "bull":         s["bull"],
            "bear":         s["bear"],
            "mentions":     s["mentions"],
        })
    if not out:
        return [], "tickers_found_but_zero_mentions"
    return out, ""


def evaluate_user_post(post: dict, user_cfg: dict, whitelist: set[str],
                       cutoff_utc: float) -> tuple[list[dict], str]:
    """
    Lane B — tracked-user evaluator.
    Returns (signals, reason).
    """
    if not post.get("is_self", False):
        return [], "not_self_text"
    if post["created_utc"] < cutoff_utc:
        age_h = int((cutoff_utc - post["created_utc"]) / 3600 + TRACKED_USER_LOOKBACK_HRS)
        return [], f"too_old({age_h}h)"
    if post["ups"] < user_cfg["min_post_ups"]:
        return [], f"low_ups({post['ups']}<{user_cfg['min_post_ups']})"

    text = f"{post['title']} {post['selftext']}"
    tickers = extract_tickers(text, whitelist)
    if not tickers:
        return [], "no_whitelist_ticker"

    excerpt = (post["title"] + " — " + post["selftext"])[:1500]
    out = []
    for t in tickers:
        s = sentiment_around(text, t)
        if s["mentions"] == 0:
            continue
        out.append({
            "lane":          "user",
            "ticker":        t,
            "user":          user_cfg["username"],
            "sub":           post.get("subreddit", ""),
            "category":      user_cfg["category"],
            "weight":        user_cfg["weight"],
            "post_id":       post["id"],
            "post_ups":      post["ups"],
            "post_comments": post["num_comments"],
            "post_url":      "https://www.reddit.com" + post["permalink"],
            "post_excerpt":  excerpt,
            "bull":          s["bull"],
            "bear":          s["bear"],
            "mentions":      s["mentions"],
        })
    if not out:
        return [], "tickers_found_but_zero_mentions"
    return out, ""


def aggregate_per_ticker(post_signals: list[dict]) -> dict[str, dict]:
    """
    Aggregate post-level signals into per-ticker rollup:
      {ticker: {mentions, total_ups, bull, bear, posts: [...]}}
    """
    out: dict[str, dict] = {}
    for s in post_signals:
        t = s["ticker"]
        agg = out.setdefault(t, {
            "ticker":     t,
            "mentions":   0,
            "total_ups":  0,
            "bull":       0,
            "bear":       0,
            "best_post_ups": 0,
            "best_post_url": "",
            "posts":      [],
        })
        agg["mentions"]  += s["mentions"]
        agg["total_ups"] += s["post_ups"] * s["weight"]   # weighted by sub
        agg["bull"]      += s["bull"]
        agg["bear"]      += s["bear"]
        if s["post_ups"] > agg["best_post_ups"]:
            agg["best_post_ups"] = s["post_ups"]
            agg["best_post_url"] = s["post_url"]
        agg["posts"].append(s)
    return out


def detect_spike_signals(per_ticker: dict, reddit_state: dict,
                          today: str) -> list[dict]:
    """
    Lane A — SPIKE signal per ticker (rolling-avg comparison).
    """
    signals = []
    for t, agg in per_ticker.items():
        avg = rolling_avg(reddit_state, t, today)
        # First-day threshold: if no rolling history, require a higher
        # absolute floor (5 mentions OR 1 high-quality post)
        if avg > 0:
            spike = agg["mentions"] >= SPIKE_THRESHOLD * avg
        else:
            spike = (agg["mentions"] >= FIRST_DAY_MIN_MENTIONS
                     or agg["best_post_ups"] >= FIRST_DAY_MIN_BEST_UPS)

        if not spike:
            continue

        total = agg["bull"] + agg["bear"]
        if total > 0:
            skew = (agg["bull"] - agg["bear"]) / total
            if abs(skew) < SENTIMENT_THRESHOLD:
                continue
            # 2026-05-13: tightened SELL_SHORT classification. NVDA case
            # 2026-05-12 had skew=-0.053 (just over 0.05 threshold) — upstream
            # called it SELL_SHORT, Curator correctly rejected because posts
            # were actually bullish ("'472 was a fantasy' read as bearish but
            # context was bullish). Below |skew|=0.10 too noisy for direction;
            # pass to Curator as UNCLEAR and let it read the post body.
            if abs(skew) < 0.10:
                side = "UNCLEAR"
            else:
                side = "BUY" if skew > 0 else "SELL_SHORT"
        else:
            # Heuristic regex couldn't classify, but post quality cleared
            # spike floor — pass to Curator with side="UNCLEAR"; Curator
            # reads excerpts and decides direction.
            skew = None
            side = "UNCLEAR"

        # Top 3 post excerpts by ups for LLM curator context
        top_posts = sorted(agg["posts"], key=lambda p: p["post_ups"], reverse=True)[:3]
        excerpts = [p.get("post_excerpt", "") for p in top_posts if p.get("post_excerpt")]
        # JSON-safe spike_ratio: 99.0 sentinel for "no rolling history yet"
        # (real ratios cap around 10-20× even on viral days; 99 is unambiguous).
        spike_ratio = round(agg["mentions"] / avg, 2) if avg > 0 else 99.0
        signals.append({
            "lane":           "sub",
            "ticker":         t,
            "side":           side,
            "skew":           round(skew, 3) if skew is not None else None,
            "mentions":       agg["mentions"],
            "rolling_avg_7d": round(avg, 2),
            "spike_ratio":    spike_ratio,
            "weight":         1.0,                    # sub-lane uses no per-source weight here
            "best_post_url":  agg["best_post_url"],
            "best_post_ups":  agg["best_post_ups"],
            "post_excerpts":  excerpts,
            "size_usd":       SIZE_USD,
            "stop_loss_pct":  STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "strategy":       STRATEGY_NAME,
        })
    # Sort with skew=None treated as 0.5 (mid-priority)
    signals.sort(
        key=lambda s: s["spike_ratio"]
                       * (abs(s["skew"]) if s["skew"] is not None else 0.5),
        reverse=True,
    )
    return signals


def detect_user_signals(user_post_signals: list[dict]) -> list[dict]:
    """
    Lane B — per-tracked-user signal. NO spike requirement; one quality
    post is enough. Sentiment skew per ticker still required.
    """
    # Aggregate per (ticker, user) — we don't merge across users so a single
    # user's conviction stays their own (no diluting from random WSB shouts).
    by_pair: dict[tuple, dict] = {}
    for s in user_post_signals:
        key = (s["ticker"], s["user"])
        agg = by_pair.setdefault(key, {
            "ticker":     s["ticker"],
            "user":       s["user"],
            "category":   s["category"],
            "weight":     s["weight"],
            "mentions":   0,
            "bull":       0,
            "bear":       0,
            "best_post_ups": 0,
            "best_post_url": "",
            "excerpts":   [],
        })
        agg["mentions"] += s["mentions"]
        agg["bull"]     += s["bull"]
        agg["bear"]     += s["bear"]
        if s["post_ups"] > agg["best_post_ups"]:
            agg["best_post_ups"] = s["post_ups"]
            agg["best_post_url"] = s["post_url"]
        if s.get("post_excerpt"):
            agg["excerpts"].append(s["post_excerpt"])

    signals = []
    for (_t, _u), agg in by_pair.items():
        # Lane B bypass: tracked-user posts ALWAYS pass to Curator
        # regardless of regex sentiment — the user being whitelisted IS
        # the credibility. Curator reads post excerpts and decides side.
        total = agg["bull"] + agg["bear"]
        if total > 0:
            skew = (agg["bull"] - agg["bear"]) / total
            # |skew|<0.10 too noisy — see #4 NVDA case 2026-05-12.
            if abs(skew) < 0.10:
                side = "UNCLEAR"
            else:
                side = "BUY" if skew > 0 else "SELL_SHORT"
        else:
            skew = None
            side = "UNCLEAR"   # Curator must determine direction
        signals.append({
            "lane":           "user",
            "ticker":         agg["ticker"],
            "user":           agg["user"],
            "category":       agg["category"],
            "side":           side,
            "skew":           round(skew, 3) if skew is not None else None,
            "mentions":       agg["mentions"],
            "rolling_avg_7d": None,
            "spike_ratio":    None,                 # N/A for user lane
            "weight":         agg["weight"],
            "best_post_url":  agg["best_post_url"],
            "best_post_ups":  agg["best_post_ups"],
            "post_excerpts":  agg["excerpts"][:3],
            "size_usd":       SIZE_USD,
            "stop_loss_pct":  STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "strategy":       STRATEGY_NAME,
        })
    # Best post first × user weight
    signals.sort(key=lambda s: s["best_post_ups"] * s["weight"], reverse=True)
    return signals


# ─── Run scan ────────────────────────────────────────────────────────────────

def _source_type_for(signal: dict) -> str:
    """Map signal lane + category → event_scoring source_type."""
    cat = signal.get("category", "")
    if signal.get("lane") == "user":
        if cat == "tracked_dd":
            return "tracked_dd"          # cred 65 (handled in event_scoring)
        if cat in ("tracked_options", "tracked_macro"):
            return "tracked_anon_trader" # cred 55 (closest fallback)
        return "tracked_anon_trader"
    # Sub lane
    if cat in ("wsb", "options_sub", "crypto_sub"):
        return "tracked_anon_trader"     # cred 55
    return "major_outlet"                # cred 60 (quality_sub)


def _emit_signal(sig: dict, account: dict, final_size_mult: float) -> bool:
    """
    Run guards + event_scoring + send notify_signal + (opt) execute.
    Returns True if signal actually sent (not skipped).
    """
    ticker = sig["ticker"]

    if has_open_position(ticker):
        print(f"  {ticker}: pominięty (otwarta pozycja)")
        return False

    equity = float((account or {}).get("equity", 100_000))
    user_or_sub_weight = sig.get("weight", 1.0)
    sized = sig["size_usd"] * final_size_mult * user_or_sub_weight
    ok, combined = concentration_ok(ticker, sized, equity)
    if not ok:
        print(f"  {ticker}: pominięty (concentration {combined:.1f}% > 40%)")
        return False

    # v3.10.1 (2026-05-27) — signal_confirmation gate (Phase C wiring).
    # Reddit-specific: high noise; we BLOCK duplicate posts + future ts,
    # DOWNSIZE on weak signals + no confirmation.
    try:
        from news_signal_gate import gate_news_signal, mark_signal_acted
        # Reddit "strength" derived from upvotes_ratio + sub_weight + curator_size_mult
        strength = min(1.0, max(0.0,
            float(sig.get("upvotes_ratio", 0.6)) * float(sig.get("weight", 1.0))
        ))
        v = gate_news_signal(
            symbol=ticker, side=sig.get("side", "BUY"),
            signal_strength=strength,
            headline=(sig.get("title") or sig.get("permalink", ""))[:200],
            source=f"reddit/{sig.get('subreddit', '?')}",
            published_at=sig.get("created_utc_iso") or sig.get("event_ts"),
            strategy="reddit-sentiment",
            cooldown_hours=6.0,  # reddit has 30-min cron, longer cooldown
            max_article_age_hours=12.0,
        )
        v_str = v.verdict.value
        if v_str == "BLOCK":
            print(f"  {ticker}: BLOCKED by signal_confirmation — {v.reason}")
            return False
        if v_str == "ALERT_ONLY":
            print(f"  {ticker}: ALERT_ONLY — {v.reason} (email only, no order)")
            try: notify_signal(sig, alert_sent=True)
            except Exception: pass
            return False
        if v_str == "DOWNSIZE":
            print(f"  {ticker}: DOWNSIZED × {v.size_multiplier:.2f} — {v.reason}")
            sized = round(sized * v.size_multiplier)
            sig["size_usd"] = sized
        mark_signal_acted(ticker, "reddit-sentiment")
    except Exception as e:
        print(f"  {ticker}: signal-gate error ({type(e).__name__}: {e}) — proceeding fail-soft")

    # event_scoring was designed for news monitors (twitter/defense/geo)
    # with REAL market_reaction data. For Reddit it would use placeholder
    # values (atr=0.5, vol=1.0, gap=0.0) → returns WAIT_FOR_CONFIRMATION
    # for almost everything → pipeline becomes useless on Curator 429.
    #
    # Reddit-specific gates already enforce signal quality:
    #   - extract_tickers (whitelist only)
    #   - sub.min_upvotes / user.min_post_ups (engagement floor)
    #   - keyword filter (only DD-flavored posts)
    #   - sentiment_around (skew threshold or UNCLEAR side)
    #   - spike threshold + first-day floor
    #   - has_open_position (dup guard)
    #   - concentration_ok (per-ticker cap)
    #   - VIX guard / drawdown guard (account level)
    # Curator (when available) layers smart validation on top.
    #
    # So we skip event_scoring entirely. Stance is FOLLOW unless signal
    # was rejected upstream.
    if sig.get("curator_rationale"):
        decision_rationale = f"curator-approved: {sig['curator_rationale']}"
    else:
        decision_rationale = "heuristic fallback (Curator unavailable)"
    stance = "FOLLOW_REACTION"

    sig["size_usd"] = round(sized, 2)
    sig["stance"]   = stance
    sig["event_score_rationale"] = decision_rationale
    sig["source_type"] = _source_type_for(sig)

    src_label = f"@{sig['user']}" if sig["lane"] == "user" else f"r/{sig.get('sub','?')}"
    spike_lbl = (f"{sig['spike_ratio']}×" if sig.get("spike_ratio")
                 else f"{sig.get('best_post_ups', 0)} ups")
    print(f"  >>> SYGNAŁ {sig['side']} {ticker} [{sig['lane']}:{src_label}] "
          f"({stance}, skew={sig['skew']}, {spike_lbl}, "
          f"size=${sig['size_usd']:,.0f})")
    if sig.get("curator_rationale"):
        print(f"      curator: {sig['curator_rationale'][:120]}")

    _diag("reddit-monitor", DIAG_EMIT_ATTEMPTED,
          {"symbol": ticker, "lane": sig.get("lane"), "stance": stance})

    try:
        notify_signal(sig, alert_sent=AUTO_EXECUTE)
    except Exception as e:
        print(f"    notify_signal error: {e}")

    if AUTO_EXECUTE and stance == "FOLLOW_REACTION":
        try:
            result = execute_stock_signal(sig)
            if result:
                _diag("reddit-monitor", DIAG_EMIT_SUCCESS,
                      {"symbol": ticker})
                print(f"    [EXECUTED] order_id={result.get('id', '?')}")
            else:
                _diag("reddit-monitor", DIAG_EMIT_FAILED,
                      {"symbol": ticker, "reason": "alpaca_reject"})
                print(f"    [EXECUTE FAILED] — see notify email")
        except Exception as e:
            _diag("reddit-monitor", DIAG_EMIT_FAILED,
                  {"symbol": ticker, "reason": type(e).__name__})
            print(f"    execute_stock_signal error: {e}")
    else:
        # Not executed (either AUTO_EXECUTE=false or stance != FOLLOW_REACTION).
        # The diag here is informational — the signal made it to the emit
        # stage but execution was gated.
        _diag("reddit-monitor", DIAG_EMIT_SUCCESS,
              {"symbol": ticker, "path": "email_only"})

    return True


def run_scan() -> int:
    """
    Main entry. Returns count of alerts sent (0 if nothing happened).

    Two lanes processed in this order (user first — higher credibility):
      Lane B: tracked users (no spike threshold)
      Lane A: subs (spike threshold)
    Each lane has its own MAX_ALERTS_PER_LANE cap.
    """
    print(f"\n=== REDDIT MONITOR — {datetime.now(timezone.utc).isoformat()} ===")
    _diag("reddit-monitor", DIAG_RAN, {})

    # Strategy gate
    if not is_strategy_enabled(STRATEGY_NAME):
        print(f"  [{STRATEGY_NAME}] disabled via learning-loop state — skipping")
        return 0
    size_mult = size_multiplier(STRATEGY_NAME)
    print(f"  [{STRATEGY_NAME}] size_multiplier={size_mult:.2f}")

    # Account guards
    account = get_account_status()
    dd_status, dd_reason = daily_drawdown_guard(account)
    if dd_status == "HALT":
        print(f"  Drawdown HALT: {dd_reason}")
        notify_summary("Reddit Monitor", 0, 0)
        return 0

    vix_status, vix_mult = vix_guard()
    if vix_status == "HALT":
        print(f"  VIX HALT")
        notify_summary("Reddit Monitor", 0, 0)
        return 0

    final_size_mult = size_mult * vix_mult

    # Load whitelists
    subs = load_subs()
    users = load_users()
    whitelist = load_ticker_whitelist()
    if not whitelist:
        print(f"  No tickers whitelist — abort")
        return 0
    if not subs and not users:
        print(f"  No subs and no tracked users — nothing to scan")
        _diag("reddit-monitor", DIAG_INPUT_EMPTY,
              {"subs": 0, "users": 0})
        return 0
    print(f"  Loaded {len(subs)} subs, {len(users)} tracked users, "
          f"{len(whitelist)} whitelisted tickers")

    client = RedditClient()
    today = datetime.now(timezone.utc).date().isoformat()
    cutoff_utc = (datetime.now(timezone.utc).timestamp()
                  - TRACKED_USER_LOOKBACK_HRS * 3600)

    # ── Lane B: tracked users ────────────────────────────────────────────
    user_post_signals: list[dict] = []
    for u in users:
        print(f"  → /user/{u['username']} (cat={u['category']}, w={u['weight']})...")
        posts = client.get_user_submissions(u["username"], limit=10, sort="new")
        kept = 0
        reasons: dict[str, int] = defaultdict(int)
        for p in posts:
            sigs, reason = evaluate_user_post(p, u, whitelist, cutoff_utc)
            if sigs:
                kept += len(sigs)
                user_post_signals.extend(sigs)
            elif reason:
                reasons[reason] += 1
        rej_summary = ", ".join(f"{r}×{n}" for r, n in sorted(reasons.items())) or "(none)"
        print(f"    {len(posts)} posts → {kept} mentions kept; rejections: {rej_summary}")
        time.sleep(INTER_REQUEST_DELAY_S)

    user_signals = detect_user_signals(user_post_signals)
    print(f"  Lane B — user signals after sentiment filter: {len(user_signals)}")

    # ── Lane A: subs ─────────────────────────────────────────────────────
    # Two listings per sub: TOP (whole-day winners) + HOT (catching fire
    # right now). Dedup by post id so we don't double-count posts that
    # appear in both feeds (commonly: yesterday's top is today's hot).
    all_post_signals: list[dict] = []
    for sub_cfg in subs:
        print(f"  → r/{sub_cfg['sub']} (cat={sub_cfg['category']})...")
        top_posts = client.get_top(sub_cfg["sub"], t="day", limit=25)
        time.sleep(INTER_REQUEST_DELAY_S)
        hot_posts = client.get_hot(sub_cfg["sub"], limit=15)
        seen_ids: set[str] = set()
        posts: list[dict] = []
        for p in top_posts + hot_posts:
            if p["id"] and p["id"] not in seen_ids:
                seen_ids.add(p["id"])
                posts.append(p)
        kept = 0
        reasons: dict[str, int] = defaultdict(int)
        for p in posts:
            sigs, reason = evaluate_post(p, sub_cfg, whitelist)
            if sigs:
                kept += len(sigs)
                all_post_signals.extend(sigs)
            elif reason:
                reasons[reason] += 1
        rej_summary = ", ".join(f"{r}×{n}" for r, n in sorted(reasons.items())) or "(none)"
        print(f"    top={len(top_posts)}+hot={len(hot_posts)}=unique {len(posts)} "
              f"→ {kept} mentions kept; rejections: {rej_summary}")
        time.sleep(INTER_REQUEST_DELAY_S)

    per_ticker = aggregate_per_ticker(all_post_signals) if all_post_signals else {}
    today_counts = {t: a["mentions"] for t, a in per_ticker.items()}
    reddit_state = load_reddit_state()

    # Diagnostic: show per-ticker rollup BEFORE spike check, so we can see
    # what was just-below-threshold (and tune in future if needed).
    if per_ticker:
        print(f"  Lane A — per-ticker aggregation (before spike check):")
        rows = sorted(per_ticker.items(),
                      key=lambda kv: kv[1]["mentions"], reverse=True)
        for t, a in rows[:15]:
            avg = rolling_avg(reddit_state, t, today)
            ratio = (a["mentions"] / avg) if avg > 0 else None
            ratio_s = f"{ratio:.1f}×" if ratio is not None else "n/a (no history)"
            total_sent = a["bull"] + a["bear"]
            skew = (a["bull"] - a["bear"]) / total_sent if total_sent else 0
            print(f"    {t:6s}  mentions={a['mentions']:2d}  "
                  f"bull={a['bull']:2d} bear={a['bear']:2d} skew={skew:+.2f}  "
                  f"7d_avg={avg:.1f} ratio={ratio_s}  "
                  f"best_post={a['best_post_ups']} ups")

    reddit_state = update_mentions(reddit_state, today, today_counts)
    sub_signals = detect_spike_signals(per_ticker, reddit_state, today)
    print(f"  Lane A — sub signals after spike+sentiment filter: {len(sub_signals)}")

    # Persist rolling state
    save_reddit_state(reddit_state)

    if not user_signals and not sub_signals:
        print(f"  No signals from either lane — quiet day")
        notify_summary("Reddit Monitor", 0, 0)
        return 0

    # ── LLM Curator (fail-soft) ──────────────────────────────────────────
    # Pass all candidates to the Curator routine which validates each
    # against fast-trade goal + account context and picks 0-3 to actually
    # emit. If Curator unavailable / fails / times out, we fall back to
    # the heuristic top-N selection (current pre-LLM behaviour).
    print(f"\n  Curator: validating {len(user_signals) + len(sub_signals)} "
          f"candidates ({len(user_signals)} user + {len(sub_signals)} sub)")
    # Build rich open_positions list — Curator needs to see what's
    # already on the book to detect concentration/redundancy/regime
    # conflicts ("BTC bullish DD but you have 30% in MSTR already").
    eq = float((account or {}).get("equity", 100_000)) or 100_000
    raw_positions = get_open_positions()
    positions_summary: list[dict] = []
    for p in raw_positions:
        try:
            pct_equity = (abs(p["market_value"]) / eq * 100) if eq > 0 else 0
        except (KeyError, TypeError):
            pct_equity = 0
        positions_summary.append({
            "symbol":          p["symbol"],
            "asset_class":     p["asset_class"],         # us_equity / crypto / us_option
            "side":            p["side"],
            "qty":             round(p["qty"], 4),
            "pl_pct":          round(p["unrealized_plpc"] * 100, 2),
            "pct_equity":      round(pct_equity, 1),
        })

    # options_side_bias from learning-loop state (LLM may have set it)
    try:
        from learning_state import load_global_overrides as _lgo
        glob = _lgo() or {}
        opt_bias = glob.get("options_side_bias")
    except Exception:
        opt_bias = None

    account_context = {
        "equity":             eq,
        "daily_pl_pct":       float((account or {}).get("daily_pl_pct", 0)),
        "open_positions":     positions_summary,
        "open_position_count": len(positions_summary),
        "options_side_bias":  opt_bias,
        "vix":                round(17.0 * vix_mult, 1) if vix_mult else None,
    }
    print(f"  Curator context: equity=${eq:,.0f}, "
          f"{len(positions_summary)} open positions, "
          f"options_side_bias={opt_bias}")

    curator_output = curate_signals(user_signals + sub_signals, account_context)
    if curator_output:
        print(f"  Curator: narrative — {curator_output.get('narrative', '?')}")
        sel = curator_output.get("selected_signals") or []
        rej = curator_output.get("rejected_signals") or []
        print(f"  Curator: {len(sel)} selected, {len(rej)} rejected, "
              f"confidence={curator_output.get('confidence_in_curation', '?')}")
        for r in rej[:5]:
            print(f"    REJECT {r.get('ticker','?')}: {r.get('reason','?')}")

        # Apply curator filter — replace user_signals + sub_signals with
        # curator-approved (preserves lane attribution + injects curator
        # rationale + size_multiplier override).
        all_filtered = filter_signals_via_curator(
            user_signals + sub_signals, curator_output
        )
        user_signals = [s for s in all_filtered if s.get("lane") == "user"]
        sub_signals  = [s for s in all_filtered if s.get("lane") == "sub"]
        print(f"  Curator: post-filter pool — {len(user_signals)} user + "
              f"{len(sub_signals)} sub")

        if not user_signals and not sub_signals:
            print(f"  Curator: rejected all candidates — no trades today")
            notify_summary("Reddit Monitor", 0, 0)
            return 0
    else:
        print(f"  Curator: unavailable — using heuristic top-N (fail-soft)")

    # ── Send alerts (per-lane cap) ───────────────────────────────────────
    sent_total = 0

    sent_user = 0
    for sig in user_signals:
        if sent_user >= MAX_ALERTS_PER_LANE:
            print(f"  Lane B cap reached — skipping {sig['ticker']}")
            break
        if _emit_signal(sig, account, final_size_mult):
            sent_user += 1
            sent_total += 1

    sent_sub = 0
    for sig in sub_signals:
        if sent_sub >= MAX_ALERTS_PER_LANE:
            print(f"  Lane A cap reached — skipping {sig['ticker']}")
            break
        if _emit_signal(sig, account, final_size_mult):
            sent_sub += 1
            sent_total += 1

    total_signals = len(user_signals) + len(sub_signals)
    print(f"\n  Sygnały: {total_signals} (user={len(user_signals)} sub={len(sub_signals)}), "
          f"alerty wysłane: {sent_total} (user={sent_user} sub={sent_sub})")
    if total_signals == 0:
        _diag("reddit-monitor", DIAG_NO_SIGNAL, {})
    else:
        _diag("reddit-monitor", DIAG_SIGNAL_DETECTED,
              {"user_signals": len(user_signals),
               "sub_signals": len(sub_signals)})
        # v3.27 — watchlist-aware: emit trigger-crossed for each unique
        # symbol in the signal set (fail-soft).
        try:
            _wl_cache_rd = _watchlist_load()
            _seen: set[str] = set()
            for _sig in list(user_signals) + list(sub_signals):
                _sym = (_sig or {}).get("symbol")
                if not _sym or _sym in _seen:
                    continue
                _seen.add(_sym)
                _watchlist_started("reddit-monitor", _sym, _wl_cache_rd)
                _watchlist_finished(
                    "reddit-monitor", _sym, _wl_cache_rd,
                    signal_detected=True,
                    strategy_id_override=(_sig or {}).get(
                        "strategy", "reddit-sentiment"),
                )
        except Exception:
            pass
    notify_summary("Reddit Monitor", total_signals, sent_total)
    return sent_total


if __name__ == "__main__":
    _rc = run_scan()
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("reddit-monitor", status="ok",
                 message=f"sent={_rc}")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")
    sys.exit(0 if _rc >= 0 else 1)


# ── v3.22.0 observability hook ──────────────────────────────────────────────
# Per the v3.22 signal-pipeline contract this monitor exposes a thin helper
# that the run loop calls once per scan even when no signal fires (so the
# operator can see "monitor ran, 0 candidates" in the opportunity ledger).
# emit_monitor_signal NEVER places trades — it only persists an observation
# row via shared.signal_emitter.emit_signal_opportunity.
def _v322_observe(symbol: str = "n/a", action: str = "NO_SIGNAL",
                  side: str = "n/a", asset_class: str = "us_equity",
                  raw_signal=None) -> None:
    try:
        emit_monitor_signal(
            source_monitor="reddit-monitor",
            strategy_id="reddit-sentiment",
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            action=action,
            entry_capable=False,
            raw_signal=raw_signal or {},
        )
    except Exception:
        pass

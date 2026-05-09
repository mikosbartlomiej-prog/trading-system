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

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import (
        vix_guard, daily_drawdown_guard, get_account_status,
        has_open_position, concentration_ok,
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
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub"}
    def execute_stock_signal(_s): return None
    def is_strategy_enabled(_n): return True
    def size_multiplier(_n): return 1.0


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
SENTIMENT_THRESHOLD = 0.15             # |skew| >= 0.15 to act
                                        # Lowered 0.3 -> 0.15 — let LLM judge weak signals.
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
    "bullish", "long", "calls", "buy", "rocket", "moon", "undervalued",
    "breakout", "beat", "raised", "upgraded", "target", "bottoming",
    "bounce", "catalyst", "opportunity", "oversold", "accumulate",
    "conviction", "bullrun",
}
BEARISH_WORDS = {
    "bearish", "short", "puts", "sell", "dump", "crash", "overvalued",
    "breakdown", "miss", "cut", "downgraded", "decline", "exit", "avoid",
    "overpriced", "distribution", "rejection", "weak", "bagholder",
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
        if total == 0:
            continue
        skew = (agg["bull"] - agg["bear"]) / total

        if abs(skew) < SENTIMENT_THRESHOLD:
            continue

        side = "BUY" if skew > 0 else "SELL_SHORT"
        signals.append({
            "lane":           "sub",
            "ticker":         t,
            "side":           side,
            "skew":           round(skew, 3),
            "mentions":       agg["mentions"],
            "rolling_avg_7d": round(avg, 2),
            "spike_ratio":    round(agg["mentions"] / avg, 2) if avg > 0 else float("inf"),
            "weight":         1.0,                    # sub-lane uses no per-source weight here
            "best_post_url":  agg["best_post_url"],
            "best_post_ups":  agg["best_post_ups"],
            "size_usd":       SIZE_USD,
            "stop_loss_pct":  STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "strategy":       STRATEGY_NAME,
        })
    signals.sort(key=lambda s: s["spike_ratio"] * abs(s["skew"]), reverse=True)
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
        })
        agg["mentions"] += s["mentions"]
        agg["bull"]     += s["bull"]
        agg["bear"]     += s["bear"]
        if s["post_ups"] > agg["best_post_ups"]:
            agg["best_post_ups"] = s["post_ups"]
            agg["best_post_url"] = s["post_url"]

    signals = []
    for (_t, _u), agg in by_pair.items():
        total = agg["bull"] + agg["bear"]
        if total == 0:
            continue
        skew = (agg["bull"] - agg["bear"]) / total
        if abs(skew) < SENTIMENT_THRESHOLD:
            continue
        side = "BUY" if skew > 0 else "SELL_SHORT"
        signals.append({
            "lane":           "user",
            "ticker":         agg["ticker"],
            "user":           agg["user"],
            "category":       agg["category"],
            "side":           side,
            "skew":           round(skew, 3),
            "mentions":       agg["mentions"],
            "rolling_avg_7d": None,
            "spike_ratio":    None,                 # N/A for user lane
            "weight":         agg["weight"],
            "best_post_url":  agg["best_post_url"],
            "best_post_ups":  agg["best_post_ups"],
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

    source_type = _source_type_for(sig)
    if sig["lane"] == "sub":
        ratio = sig.get("spike_ratio") or 1.0
        magnitude = "large" if ratio >= 5 else "normal" if ratio >= 3 else "small"
    else:
        ups = sig.get("best_post_ups", 0)
        magnitude = "large" if ups >= 1500 else "normal" if ups >= 500 else "small"

    try:
        decision = score_and_decide(
            source_type=source_type,
            event_type="sentiment_spike",
            magnitude=magnitude,
            price_move_atr=0.5,    # TODO: real metrics from market_data
            volume_ratio=1.0,
            gap_pct=0.0,
        )
    except Exception as e:
        print(f"  {ticker}: event_scoring error ({e}) — falling back to FOLLOW")
        decision = {"stance": "FOLLOW_REACTION", "rationale": "fallback"}
    stance = decision.get("stance", "WAIT_FOR_CONFIRMATION")

    if stance == "IGNORE_EVENT":
        print(f"  {ticker} ({sig['lane']}): IGNORE — {decision.get('rationale','')}")
        return False
    if stance == "WAIT_FOR_CONFIRMATION":
        print(f"  {ticker} ({sig['lane']}): WAIT — skipping")
        return False

    sig["size_usd"] = round(sized, 2)
    sig["stance"]   = stance
    sig["event_score_rationale"] = decision.get("rationale", "")
    sig["source_type"] = source_type

    src_label = f"@{sig['user']}" if sig["lane"] == "user" else f"r/{sig.get('sub','?')}"
    spike_lbl = (f"{sig['spike_ratio']}×" if sig.get("spike_ratio")
                 else f"{sig.get('best_post_ups', 0)} ups")
    print(f"  >>> SYGNAŁ {sig['side']} {ticker} [{sig['lane']}:{src_label}] "
          f"({stance}, skew={sig['skew']}, {spike_lbl}, "
          f"size=${sig['size_usd']:,.0f})")

    try:
        notify_signal(sig, alert_sent=AUTO_EXECUTE)
    except Exception as e:
        print(f"    notify_signal error: {e}")

    if AUTO_EXECUTE and stance == "FOLLOW_REACTION":
        try:
            result = execute_stock_signal(sig)
            if result:
                print(f"    [EXECUTED] order_id={result.get('id', '?')}")
            else:
                print(f"    [EXECUTE FAILED] — see notify email")
        except Exception as e:
            print(f"    execute_stock_signal error: {e}")

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
    all_post_signals: list[dict] = []
    for sub_cfg in subs:
        print(f"  → r/{sub_cfg['sub']} (cat={sub_cfg['category']})...")
        posts = client.get_top(sub_cfg["sub"], t="day", limit=25)
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
        print(f"    {len(posts)} posts → {kept} mentions kept; rejections: {rej_summary}")
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
    notify_summary("Reddit Monitor", total_signals, sent_total)
    return sent_total


if __name__ == "__main__":
    sys.exit(0 if run_scan() >= 0 else 1)

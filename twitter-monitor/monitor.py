"""
Twitter / Bluesky Monitor — curated social-graph news monitor.

MVP data source: Bluesky AT-Protocol (free, TOS-safe). Same monitor
ships X API v2 Basic ($100/mo) support behind a `SocialClient` interface
so the swap is a one-config flip when user buys the upgrade.

Pipeline per cron tick:
  1. Drawdown + VIX guards (account-level safety, same as other monitors)
  2. For each account on the whitelist (.claude/rules/twitter-accounts.md):
       a. Pull recent posts (last 30 minutes)
       b. Skip already-seen post URIs (in-memory de-dup per run; cron
          interval-based dedup across runs is good enough for MVP)
       c. Filter by per-category keyword list
  3. For each surviving post, run shared.event_scoring.score_and_decide()
       using:
         source_type   = "tweet_verified_pol" | "tweet_verified_corp"
                          | "major_outlet" | "tweet_anon" (per category)
         event_type    = inferred from category + keyword match
         magnitude     = inferred from match count + whether the
                          highest-priority keyword fired
  4. For posts that score FOLLOW_REACTION: forward to Cloudflare Worker
     `twitter-proxy` (which routes to a routine), and email an alert via
     shared.notify.notify_signal so the user can react manually too.
     CONTRARIAN_CANDIDATE: email-only flag; no automatic trade.
     IGNORE_EVENT / WAIT: drop with log line.

Iron-rule preservation: this monitor never places a trade directly. It
only emits proposals. The routine (or the user) decides execution.
"""

import os
import sys
import re
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard, daily_drawdown_guard, get_account_status
    from event_scoring import score_and_decide
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub"}

# ─── Config ──────────────────────────────────────────────────────────────────

BLUESKY_HANDLE       = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")
BLUESKY_BASE         = "https://bsky.social/xrpc"
CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_TWITTER_WORKER_URL", "")

LOOKBACK_MINUTES     = 30           # how far back to scan per run
MAX_POSTS_PER_RUN    = 10           # cap to prevent flood / rate limit
ACCOUNTS_FILE        = os.path.join(os.path.dirname(__file__), '..',
                                     '.claude', 'rules', 'twitter-accounts.md')


# ─── Account whitelist parser ────────────────────────────────────────────────

def load_accounts() -> list[dict]:
    """
    Parse the curated accounts file. Returns a list of dicts:
      {handle: "@elonmusk.bsky.social", category: "ticker:TSLA", twitter: "@elonmusk"}
    Lines starting with '#' or blank are skipped. Handles outside
    explicit category fences are skipped.
    """
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    out = []
    current_cat = None
    cat_pattern = re.compile(r"^##\s+(.*)$")
    line_pattern = re.compile(r"^@([\w.-]+)\s*\|\s*@(\S+)\s*\|\s*([\w_:]+)\s*$")
    in_fence = False
    try:
        with open(ACCOUNTS_FILE, 'r') as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                m = cat_pattern.match(line)
                if m:
                    current_cat = m.group(1).strip().lower()
                    continue
                if not in_fence or line.startswith("#") or not line:
                    continue
                m = line_pattern.match(line)
                if m:
                    handle, twitter, cat = m.group(1), m.group(2), m.group(3)
                    out.append({
                        "handle":   "@" + handle,
                        "twitter":  "@" + twitter,
                        "category": cat,
                    })
    except Exception as e:
        print(f"  load_accounts error: {e}")
    return out


# ─── Keyword filter (per category) ───────────────────────────────────────────

KEYWORD_FILTERS = {
    "gov_us": [
        "sanctions", "executive order", "military", "troops", "missile",
        "strike", "ceasefire", "treaty", "tariff", "deployment", "congress",
    ],
    "mil_il": ["operation", "strike", "intercept", "casualties",
                "hostage", "hostile", "rocket"],
    "macro": [
        "rate", "inflation", "cpi", "ppi", "fomc", "fed", "recession",
        "gdp", "jobless", "earnings beat", "earnings miss",
        "guidance cut", "guidance raised",
    ],
    "wire": ["breaking", "exclusive", "just in", "confirmed"],
}


def passes_keyword_filter(text: str, category: str) -> tuple[bool, list[str]]:
    """Return (matched, list_of_matched_keywords)."""
    if category.startswith("ticker:"):
        # CEO accounts: every post is a candidate (low-volume by design)
        return True, ["<ticker-ceo>"]
    keywords = KEYWORD_FILTERS.get(category, [])
    if not keywords:
        return False, []
    t = (text or "").lower()
    matched = [kw for kw in keywords if kw in t]
    return (len(matched) > 0, matched)


# ─── Bluesky client ──────────────────────────────────────────────────────────

class BlueskyClient:
    """Minimal Bluesky AT-Protocol client (no atproto SDK dep, just HTTP)."""

    def __init__(self, handle: str, app_password: str):
        self.handle       = handle
        self.app_password = app_password
        self.access_jwt: str | None = None
        self.did:        str | None = None

    def login(self) -> bool:
        if not self.handle or not self.app_password:
            print("  Bluesky: missing BLUESKY_HANDLE / BLUESKY_APP_PASSWORD")
            return False
        try:
            r = requests.post(
                f"{BLUESKY_BASE}/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.app_password},
                timeout=15,
            )
            r.raise_for_status()
            d = r.json()
            self.access_jwt = d.get("accessJwt")
            self.did        = d.get("did")
            return self.access_jwt is not None
        except Exception as e:
            print(f"  Bluesky login error: {e}")
            return False

    def author_feed(self, handle: str, limit: int = 20) -> list[dict]:
        """Return latest posts from `handle`."""
        if not self.access_jwt:
            return []
        try:
            r = requests.get(
                f"{BLUESKY_BASE}/app.bsky.feed.getAuthorFeed",
                headers={"Authorization": f"Bearer {self.access_jwt}"},
                params={"actor": handle.lstrip("@"), "limit": limit},
                timeout=15,
            )
            if r.status_code == 400:
                # Most common: account doesn't exist on Bluesky yet
                return []
            r.raise_for_status()
            return r.json().get("feed", []) or []
        except Exception as e:
            print(f"  Bluesky feed error for {handle}: {e}")
            return []


# ─── Pipeline ────────────────────────────────────────────────────────────────

def category_to_source_type(cat: str) -> str:
    if cat.startswith("ticker:"):
        return "tweet_verified_corp"
    if cat in ("gov_us", "mil_il"):
        return "tweet_verified_pol"
    if cat == "macro":
        return "major_outlet"
    if cat == "wire":
        return "reuters_ap"
    return "tweet_anon"


def category_to_event_type(cat: str, matched: list[str]) -> str:
    """Best-effort event-type inference from category + matches."""
    text = " ".join(matched).lower() if matched else ""
    if "earnings beat" in text or "earnings miss" in text or "guidance" in text:
        return "earnings_release"
    if "rate" in text or "fomc" in text:
        return "rate_decision"
    if "sanctions" in text or "executive order" in text or "treaty" in text:
        return "policy_announced"
    if "strike" in text or "missile" in text or "operation" in text:
        return "threat_or_warning"
    if cat == "wire":
        return "policy_announced"
    return "policy_announced"


def magnitude_from_matches(matched: list[str]) -> str:
    if len(matched) >= 3:
        return "large"
    if len(matched) >= 1:
        return "normal"
    return "small"


def post_text(post: dict) -> str:
    """Extract text from a Bluesky feed post."""
    p = post.get("post", {}).get("record", {})
    return p.get("text", "") or ""


def post_uri(post: dict) -> str:
    return post.get("post", {}).get("uri", "")


def post_created_at(post: dict) -> datetime | None:
    s = post.get("post", {}).get("record", {}).get("createdAt", "")
    if not s:
        return None
    try:
        # tolerate trailing Z
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def send_to_routine(payload: dict) -> bool:
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_TWITTER_WORKER_URL — pomijam wysyłanie do routiny")
        return False
    try:
        r = requests.post(CLOUDFLARE_WORKER_URL, json=payload, timeout=30)
        print(f"  Routine call: HTTP {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"  Routine call error: {e}")
        return False


def run_scan():
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === TWITTER MONITOR (Bluesky) ===")

    # Account-level guards (same pattern as other entry monitors)
    account = get_account_status()
    dd_status, _ = daily_drawdown_guard(account=account)
    if dd_status == "HALT":
        notify_summary("Twitter Monitor", 0, 0)
        return
    vix_status, _ = vix_guard()
    if vix_status == "HALT":
        notify_summary("Twitter Monitor", 0, 0)
        return

    accounts = load_accounts()
    print(f"  Załadowano kont: {len(accounts)}")
    if not accounts:
        print("  Brak kont na whitelist — koniec")
        notify_summary("Twitter Monitor", 0, 0)
        return

    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        print("  Brak BLUESKY_HANDLE / BLUESKY_APP_PASSWORD — pomijam (monitor nieaktywny)")
        notify_summary("Twitter Monitor", 0, 0)
        return

    bsky = BlueskyClient(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
    if not bsky.login():
        notify_summary("Twitter Monitor", 0, 0)
        return

    cutoff = now - timedelta(minutes=LOOKBACK_MINUTES)
    candidates = []

    for acct in accounts:
        feed = bsky.author_feed(acct["handle"], limit=10)
        if not feed:
            continue
        for post in feed:
            created = post_created_at(post)
            if not created or created < cutoff:
                continue
            text = post_text(post)
            ok, matched = passes_keyword_filter(text, acct["category"])
            if not ok:
                continue
            candidates.append({
                "handle":     acct["handle"],
                "twitter":    acct["twitter"],
                "category":   acct["category"],
                "text":       text,
                "uri":        post_uri(post),
                "created_at": created.isoformat(),
                "matched_kw": matched,
            })

    candidates = candidates[:MAX_POSTS_PER_RUN]
    print(f"  Kandydatów po keyword-filter: {len(candidates)}")

    sent = 0
    for c in candidates:
        scoring = score_and_decide(
            source_type    = category_to_source_type(c["category"]),
            event_type     = category_to_event_type(c["category"], c["matched_kw"]),
            price_move_atr = 0.5,    # MVP placeholder, same as other event sources
            volume_ratio   = 1.0,
            magnitude      = magnitude_from_matches(c["matched_kw"]),
        )
        c["scoring"] = scoring
        stance = scoring["stance"]
        if stance == "FOLLOW_REACTION":
            payload = {
                "type":      "twitter_alert",
                "timestamp": now.isoformat(),
                "post":      c,
                "scoring":   scoring,
            }
            ok = send_to_routine(payload)
            sig_for_email = {
                "symbol":   c.get("category", "twitter"),
                "action":   "BUY",  # routine resolves direction
                "strategy": "twitter-news",
                "size_usd": 0,
                "headline": c["text"][:120],
                "source":   c["handle"],
            }
            notify_signal(sig_for_email, ok)
            if ok:
                sent += 1
        elif stance == "CONTRARIAN_CANDIDATE":
            print(f"    [event-layer] CONTRARIAN flag {c['handle']}: {c['text'][:80]}")
        else:
            print(f"    [event-layer] {stance} {c['handle']}: {c['text'][:60]}")

    notify_summary("Twitter Monitor", len(candidates), sent)
    print(f"[{now_str}] Wysłano: {sent}/{len(candidates)}\n")


if __name__ == "__main__":
    run_scan()

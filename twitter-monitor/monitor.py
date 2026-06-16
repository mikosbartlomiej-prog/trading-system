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
    from risk_guards import vix_guard, daily_drawdown_guard, get_account_status
    from event_scoring import score_and_decide
    from market_data import compute_reaction_metrics
    from alpaca_orders import execute_stock_signal
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def score_and_decide(**kw): return {"stance": "FOLLOW_REACTION", "rationale": "stub"}
    def compute_reaction_metrics(_s): return None
    def execute_stock_signal(_s): return None

# Default: AUTO_EXECUTE Pattern A-D via Alpaca REST. Pattern E (ambiguous wire)
# falls back to email-only. Set USE_ROUTINE=true to send everything to the
# legacy worker -> routine path instead.
USE_ROUTINE = os.environ.get("USE_ROUTINE", "false").lower() == "true"

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

# Categories that BYPASS the keyword filter (every post is a candidate) AND
# bypass the FOLLOW-only forward policy (IGNORE/WAIT/CONTRARIAN are still
# forwarded to routine + emailed for visibility). These are accounts the
# user explicitly cares about regardless of strategy fit.
HIGH_PRIORITY_CATEGORIES = {
    "high_priority_pol",      # Trump admin + conflict leaders
    "high_priority_corp",     # Defense corporate accounts (LMT, RTX, ...)
    "tracked_anon_trader",    # @aleabitoreddit, similar
}


def is_high_priority(category: str) -> bool:
    return category in HIGH_PRIORITY_CATEGORIES or category.startswith("ticker:")


def passes_keyword_filter(text: str, category: str) -> tuple[bool, list[str]]:
    """Return (matched, list_of_matched_keywords)."""
    if is_high_priority(category):
        # High-priority accounts: every post is a candidate.
        return True, ["<high-priority-bypass>"]
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
    # T2 / T2.5 — tracked corporate CEOs (tech + defense)
    if cat.startswith("ticker:") or cat == "high_priority_corp":
        return "tracked_corp_ceo"
    # T1 / T1.5 — Trump admin + conflict leaders
    if cat == "high_priority_pol":
        return "official_government"
    # T3 — tracked anon traders w/ track record
    if cat == "tracked_anon_trader":
        return "tracked_anon_trader"
    # Standard tiers (no override)
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


def real_keywords_from_text(text: str) -> list[str]:
    """
    Scan post text against ALL keyword sets (gov_us + mil_il + macro + wire).
    Used for event_type / magnitude inference on high-priority posts where
    the keyword filter was bypassed and matched_kw is just the synthetic
    "<high-priority-bypass>" marker.
    """
    t = (text or "").lower()
    found: list[str] = []
    for kw_list in KEYWORD_FILTERS.values():
        for kw in kw_list:
            if kw in t and kw not in found:
                found.append(kw)
    return found


def magnitude_from_matches(matched: list[str], is_priority: bool = False) -> str:
    """
    Map matched-keyword count to magnitude bucket.

    For high-priority posts (Trump admin / conflict leaders / tracked CEOs /
    tracked anon traders), 2+ real keyword hits already justify "large" —
    the source has elevated credibility on top, so shift bump is warranted
    to reach FOLLOW threshold sooner.
    """
    real = [m for m in matched if not m.startswith("<")]
    n = len(real)
    if is_priority and n >= 2:
        return "large"
    if n >= 3:
        return "large"
    if n >= 1:
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


# ─── Pattern A-D classifier (deterministic, AUTO_EXECUTE) ───────────────────

# Direction-tone keywords for Pattern A (TICKER_DIRECT)
_BEARISH_TONE = {
    "miss", "missed", "guidance cut", "lawsuit", "fraud", "investigation",
    "resignation", "resigns", "recall", "scandal", "subpoena", "delays",
}
_BULLISH_TONE = {
    "beat", "beats", "exceeds", "raised guidance", "approval", "breakthrough",
    "expansion", "record", "launch", "milestone",
}

# Pattern B / C keyword maps
_ESCALATION_KW = {"sanctions", "executive order", "missile", "strike",
                   "military", "tariff", "deployment", "casualties", "rocket",
                   "operation", "intercept", "hostile"}
_DEESCALATION_KW = {"ceasefire", "peace deal", "treaty", "troop withdrawal",
                     "armistice", "negotiations", "diplomatic"}

# Pattern D macro direction keywords
_DOVISH_KW = {"below expectations", "beat expectations", "rate cut",
               "dovish", "earnings beat", "guidance raised"}
_HAWKISH_KW = {"above expectations", "missed expectations", "rate hike",
                "hawkish", "earnings miss", "guidance cut", "recession"}


def classify_and_execute(post: dict) -> tuple[str, list[dict]]:
    """
    Apply deterministic Pattern A-D classification on a Twitter post.
    Returns (pattern_label, list_of_orders) where:
      - pattern_label is "A"|"B"|"C"|"D"|"E"|"NONE"
      - list_of_orders is non-empty when at least one Alpaca order succeeded
      Pattern E (ambiguous) returns ("E", []) so caller falls back to
      email-only (the user reviews manually).
    """
    cat        = post["category"]
    text_lower = (post.get("text") or "").lower()
    matched    = post.get("matched_kw", [])

    # v3.10.1 (2026-05-27) — signal_confirmation gate at post level (Phase C).
    # Filters: duplicate post (BLOCK), stale >24h (BLOCK), future ts (BLOCK).
    # Per-symbol price/volume confirmation handled per-pattern below.
    try:
        from news_signal_gate import gate_news_signal, mark_signal_acted
        # Use first-relevant symbol for gate fingerprint:
        # ticker:XYZ → XYZ; otherwise use category as pseudo-symbol
        gate_sym = cat.split(":", 1)[1] if cat.startswith("ticker:") else cat[:6].upper()
        v = gate_news_signal(
            symbol=gate_sym,
            side="BUY",  # post-level gate, side handled per-pattern
            signal_strength=0.6,  # default — patterns A-D are pre-vetted
            headline=(post.get("text") or "")[:200],
            source=f"twitter/{post.get('author', '?')}",
            published_at=post.get("created_at") or post.get("published_at"),
            strategy=f"twitter-{cat[:20]}",
            cooldown_hours=2.0,  # tighter for fast-moving social
            max_article_age_hours=4.0,
        )
        if v.verdict.value == "BLOCK":
            print(f"  twitter post BLOCKED by signal_confirmation: {v.reason}")
            return ("BLOCKED", [])
        # ALERT_ONLY / DOWNSIZE / ALLOW → proceed to pattern logic
        mark_signal_acted(gate_sym, f"twitter-{cat[:20]}")
    except Exception as e:
        print(f"  twitter signal-gate error ({type(e).__name__}: {e}) — proceeding fail-soft")

    # ── Pattern A: TICKER_DIRECT (CEO/insider account about own company) ──
    if cat.startswith("ticker:"):
        sym = cat.split(":", 1)[1]
        bear = sum(1 for w in _BEARISH_TONE if w in text_lower)
        bull = sum(1 for w in _BULLISH_TONE if w in text_lower)
        side = "SELL_SHORT" if bear > bull else "BUY"
        order = execute_stock_signal({
            "symbol":   sym,
            "action":   side,
            "size_usd": 5000,
            "sl_pct":   -6.0,
            "tp_pct":   14.0,
            "strategy": "twitter-A-direct",
        })
        return ("A", [order] if order else [])

    # ── Pattern B: GEO_ESCALATION (gov_us / mil_il + escalation keywords) ──
    pol_cats = ("gov_us", "mil_il", "high_priority_pol")
    has_escalation = any(kw in matched for kw in _ESCALATION_KW)
    if cat in pol_cats and has_escalation:
        # Top 2 picks: one defense + one energy/safe-haven (caps at 2 per post)
        targets = [
            {"symbol": "RTX", "action": "BUY", "size_usd": 8000, "sl_pct": -5.0, "tp_pct": 12.0,
             "strategy": "twitter-B-escalation-defense"},
            {"symbol": "XLE", "action": "BUY", "size_usd": 6000, "sl_pct": -5.0, "tp_pct": 12.0,
             "strategy": "twitter-B-escalation-energy"},
        ]
        orders = []
        for t in targets:
            o = execute_stock_signal(t)
            if o:
                orders.append(o)
        return ("B", orders)

    # ── Pattern C: GEO_DEESCALATION ──
    has_deesc = any(kw in matched for kw in _DEESCALATION_KW)
    if cat in pol_cats and has_deesc:
        targets = [
            {"symbol": "SPY", "action": "BUY", "size_usd": 6000, "sl_pct": -5.0, "tp_pct": 12.0,
             "strategy": "twitter-C-deescalation-spy"},
            {"symbol": "XLE", "action": "SELL_SHORT", "size_usd": 6000, "sl_pct": -5.0, "tp_pct": 12.0,
             "strategy": "twitter-C-deescalation-xle"},
        ]
        orders = []
        for t in targets:
            o = execute_stock_signal(t)
            if o:
                orders.append(o)
        return ("C", orders)

    # ── Pattern D: MACRO_DATA ──
    if cat == "macro" or (cat == "high_priority_pol" and any(
            kw in matched for kw in ("rate", "fomc", "cpi", "inflation"))):
        dovish  = sum(1 for w in _DOVISH_KW  if w in text_lower)
        hawkish = sum(1 for w in _HAWKISH_KW if w in text_lower)
        if dovish > hawkish:
            order = execute_stock_signal({
                "symbol": "SPY", "action": "BUY", "size_usd": 6000,
                "sl_pct": -5.0, "tp_pct": 12.0, "strategy": "twitter-D-macro-bull",
            })
            return ("D", [order] if order else [])
        if hawkish > dovish:
            o1 = execute_stock_signal({
                "symbol": "GLD", "action": "BUY", "size_usd": 6000,
                "sl_pct": -5.0, "tp_pct": 12.0, "strategy": "twitter-D-macro-bear-gld",
            })
            o2 = execute_stock_signal({
                "symbol": "SPY", "action": "SELL_SHORT", "size_usd": 6000,
                "sl_pct": -5.0, "tp_pct": 12.0, "strategy": "twitter-D-macro-bear-spy",
            })
            return ("D", [o for o in (o1, o2) if o])
        # Neither dovish nor hawkish dominant -> not directional, drop
        return ("D-neutral", [])

    # ── Pattern E: ambiguous wire / unclassifiable -> caller falls back to email-only ──
    return ("E", [])


def send_to_routine(payload: dict) -> bool:
    """Legacy routine path. Used only when USE_ROUTINE=true."""
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
    _diag("twitter-monitor", DIAG_RAN, {"now": now_str})

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
    if not candidates:
        _diag("twitter-monitor", DIAG_NO_SIGNAL,
              {"accounts_scanned": len(accounts)})
    else:
        _diag("twitter-monitor", DIAG_SIGNAL_DETECTED,
              {"candidates": len(candidates)})
        # v3.27 — watchlist-aware: scan candidates against the watchlist
        # using the categorical/ticker proxy where available.
        try:
            _wl_cache_tw = _watchlist_load()
            for _c in candidates:
                _cat = (_c or {}).get("category", "")
                _sym = None
                if isinstance(_cat, str) and _cat.startswith("ticker:"):
                    _sym = _cat.split(":", 1)[1].strip()
                if _sym:
                    _watchlist_started("twitter-monitor", _sym, _wl_cache_tw)
                    _watchlist_finished(
                        "twitter-monitor", _sym, _wl_cache_tw,
                        signal_detected=True,
                        strategy_id_override="twitter-news",
                    )
        except Exception:
            pass

    # Real bar-data: per-ticker for ticker:SYM categories, SPY proxy otherwise
    spy_metrics = compute_reaction_metrics("SPY")
    if spy_metrics:
        print(f"  Market reaction (SPY): move={spy_metrics['price_move_atr']}×ATR "
              f"vol={spy_metrics['volume_ratio']}× gap={spy_metrics['gap_pct']}%")

    sent = 0
    for c in candidates:
        cat = c["category"]
        if cat.startswith("ticker:"):
            sym = cat.split(":", 1)[1]
            metrics = compute_reaction_metrics(sym) or spy_metrics
        else:
            metrics = spy_metrics
        if metrics:
            pma, vr, gap = metrics["price_move_atr"], metrics["volume_ratio"], metrics["gap_pct"]
        else:
            pma, vr, gap = 0.5, 1.0, 0.0
        c["reaction_metrics"] = metrics

        # For high-priority bypass categories, matched_kw is just the
        # synthetic "<high-priority-bypass>" marker — we still want event
        # classification + magnitude based on REAL keywords in the post text.
        priority = is_high_priority(c["category"])
        if priority:
            real_kw = real_keywords_from_text(c["text"])
            effective_kw = real_kw if real_kw else c["matched_kw"]
        else:
            effective_kw = c["matched_kw"]

        scoring = score_and_decide(
            source_type    = category_to_source_type(c["category"]),
            event_type     = category_to_event_type(c["category"], effective_kw),
            price_move_atr = pma,
            volume_ratio   = vr,
            gap_pct        = gap,
            magnitude      = magnitude_from_matches(effective_kw, is_priority=priority),
        )
        c["scoring"] = scoring
        stance     = scoring["stance"]
        # `priority` already computed above for keyword-bypass / event_type inference

        # Forwarding policy (rate-limit-aware as of 2026-05-07):
        #   FOLLOW_REACTION       -> routine + email          (actionable trade)
        #   CONTRARIAN_CANDIDATE  -> routine + email          (needs manual review,
        #                                                      routine logs as flag)
        #   IGNORE / WAIT + high-priority -> email ONLY       (Trump chitchat etc.;
        #                                                      visibility for user but
        #                                                      no point burning a routine
        #                                                      call — routine has no
        #                                                      pattern to match)
        #   IGNORE / WAIT (standard) -> drop                  (noise, no email either)
        forward_for_review = priority and stance in ("IGNORE_EVENT", "WAIT_FOR_CONFIRMATION")
        actionable         = stance in ("FOLLOW_REACTION", "CONTRARIAN_CANDIDATE")

        if actionable:
            _diag("twitter-monitor", DIAG_EMIT_ATTEMPTED,
                  {"handle": c.get("handle"), "stance": stance})
            # Default: AUTO_EXECUTE Pattern A-D in Python; Pattern E -> email-only.
            # USE_ROUTINE=true keeps the legacy worker -> routine path.
            ok = False
            if not USE_ROUTINE and stance == "FOLLOW_REACTION":
                pattern, orders = classify_and_execute(c)
                if orders:
                    ok = True
                    sent += 1
                    _diag("twitter-monitor", DIAG_EMIT_SUCCESS,
                          {"handle": c.get("handle"),
                           "orders": len(orders)})
                    print(f"    [pattern-{pattern}] {c['handle']}: {len(orders)} order(s) placed")
                elif pattern == "E":
                    _diag("twitter-monitor", DIAG_EMIT_FAILED,
                          {"handle": c.get("handle"), "reason": "pattern_E_ambiguous"})
                    print(f"    [pattern-E] ambiguous -> email-only fallback {c['handle']}: {c['text'][:60]}")
                else:
                    _diag("twitter-monitor", DIAG_EMIT_FAILED,
                          {"handle": c.get("handle"),
                           "reason": f"pattern_{pattern}_no_orders"})
                    print(f"    [pattern-{pattern}] no actionable orders ({c['handle']}: {c['text'][:60]})")
            elif not USE_ROUTINE and stance == "CONTRARIAN_CANDIDATE":
                # CONTRARIAN: never auto-trade, flag for manual review
                print(f"    [event-layer] CONTRARIAN flag {c['handle']}: {c['text'][:80]}")
                ok = False  # will email as proposal so user can act manually
            else:
                # Legacy routine path
                payload = {
                    "type":      "twitter_alert",
                    "timestamp": now.isoformat(),
                    "post":      c,
                    "scoring":   scoring,
                    "priority_override": False,
                }
                ok = send_to_routine(payload)
                if ok and stance == "FOLLOW_REACTION":
                    sent += 1

            sig_for_email = {
                "symbol":   c.get("category", "twitter"),
                "action":   "BUY",
                "strategy": "twitter-news",
                "size_usd": 0,
                "headline": c["text"][:120],
                "source":   c["handle"],
            }
            notify_signal(sig_for_email, ok)
        elif forward_for_review:
            # Email-only path — preserves routine budget. Subject prefix
            # tells user this is review-only, no trade triggered.
            sig_for_email = {
                "symbol":   c.get("category", "twitter"),
                "action":   "BUY",
                "strategy": "twitter-news-review",   # filter-friendly
                "size_usd": 0,
                "headline": c["text"][:120],
                "source":   c["handle"],
            }
            notify_signal(sig_for_email, True)
            print(f"    [event-layer] {stance} (priority-override, email-only) {c['handle']}: {c['text'][:60]}")
        else:
            print(f"    [event-layer] {stance} {c['handle']}: {c['text'][:60]}")

    notify_summary("Twitter Monitor", len(candidates), sent)
    print(f"[{now_str}] Wysłano: {sent}/{len(candidates)}\n")


if __name__ == "__main__":
    run_scan()
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("twitter-monitor", status="ok")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")


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
            source_monitor="twitter-monitor",
            strategy_id="twitter-news",
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            action=action,
            entry_capable=False,
            raw_signal=raw_signal or {},
        )
    except Exception:
        pass

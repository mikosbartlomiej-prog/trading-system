"""v3.28 (2026-06-09) — LLM provider client (offline-mock by default).

Selects a provider via ``LLM_PROVIDER`` env (``anthropic`` / ``openai``
/ ``offline_mock``; default ``offline_mock``). The offline mock NEVER
makes a network call — it returns a deterministic mock response that
the v3.28 advisory mesh treats as a "skipped" status.

HARD SAFETY (cannot be opted out of)
------------------------------------
- NEVER submits orders.
- NEVER imports the broker-orders module (asserted by test).
- NEVER writes secret values to logs / responses.
- Provider key is read from env at call time; the key value never
  appears in returned dicts or printed output.
- Timeout enforced (default 30 s).
- Fail-soft: any exception returns ``LLM_PROVIDER_CALL_FAILED``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

# ─── Status enum ────────────────────────────────────────────────────────────

LLM_PROVIDER_DISABLED              = "LLM_PROVIDER_DISABLED"
LLM_PROVIDER_KEY_MISSING           = "LLM_PROVIDER_KEY_MISSING"
LLM_PROVIDER_CALL_OK               = "LLM_PROVIDER_CALL_OK"
LLM_PROVIDER_CALL_FAILED           = "LLM_PROVIDER_CALL_FAILED"
LLM_PROVIDER_TIMEOUT               = "LLM_PROVIDER_TIMEOUT"
LLM_PROVIDER_OFFLINE_MOCK          = "LLM_PROVIDER_OFFLINE_MOCK"
# v3.28.2 — free-only policy gate.
LLM_PROVIDER_BLOCKED_BY_FREE_ONLY  = "LLM_PROVIDER_BLOCKED_BY_FREE_ONLY"
# v3.28.2 — Gemini model error (provider 4xx/5xx for unsupported model).
LLM_PROVIDER_MODEL_ERROR           = "LLM_PROVIDER_MODEL_ERROR"

ALL_PROVIDER_STATUSES: frozenset[str] = frozenset({
    LLM_PROVIDER_DISABLED, LLM_PROVIDER_KEY_MISSING,
    LLM_PROVIDER_CALL_OK,  LLM_PROVIDER_CALL_FAILED,
    LLM_PROVIDER_TIMEOUT,  LLM_PROVIDER_OFFLINE_MOCK,
    LLM_PROVIDER_BLOCKED_BY_FREE_ONLY,
    LLM_PROVIDER_MODEL_ERROR,
})

# v3.28.2 — provider policy. ``LLM_FREE_ONLY`` defaults to ``true`` —
# paid providers (anthropic, openai) require explicit opt-out.
FREE_PROVIDERS:  frozenset[str] = frozenset({"gemini", "offline_mock"})
PAID_PROVIDERS:  frozenset[str] = frozenset({"anthropic", "openai"})
KNOWN_PROVIDERS: frozenset[str] = FREE_PROVIDERS | PAID_PROVIDERS


# ─── Response dataclass ─────────────────────────────────────────────────────

@dataclass
class ProviderResponse:
    status:        str
    provider:      str
    model:         str | None
    text:          str
    cost_usd:      float
    raw:           dict | None = None
    # v3.29 — safe diagnostic fields (never carry secret values).
    provider_http_status:        int | None = None
    provider_error_category:     str | None = None
    provider_endpoint_family:    str | None = None
    provider_retryable:          bool = False
    provider_suggested_next_model: str | None = None

    def to_dict(self) -> dict:
        return {
            "status":   self.status,
            "provider": self.provider,
            "model":    self.model,
            "text":     self.text,
            "cost_usd": self.cost_usd,
            "provider_http_status":         self.provider_http_status,
            "provider_error_category":      self.provider_error_category,
            "provider_endpoint_family":     self.provider_endpoint_family,
            "provider_retryable":           self.provider_retryable,
            "provider_suggested_next_model": (
                self.provider_suggested_next_model),
        }


# ─── Helpers ────────────────────────────────────────────────────────────────

def _redact(text: str) -> str:
    """Mask anything that looks like a 20+ char uppercase-alphanumeric
    token (Alpaca-key shape) or 'sk-ant-XXXX' / 'sk-XXXX' provider key
    prefixes."""
    if not text:
        return ""
    import re
    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]{6,}", "<REDACTED>", text)
    text = re.sub(r"\bsk-[A-Za-z0-9]{8,}", "<REDACTED>", text)
    text = re.sub(r"\b[A-Z0-9]{20,}\b", "<REDACTED>", text)
    return text


def _provider() -> str:
    return os.environ.get(
        "LLM_PROVIDER", "offline_mock").strip().lower() or "offline_mock"


def _provider_key_env(prov: str) -> str | None:
    if prov == "anthropic":
        return "ANTHROPIC_API_KEY"
    if prov == "openai":
        return "OPENAI_API_KEY"
    if prov == "gemini":
        return "GEMINI_API_KEY"
    return None


def _free_only_enabled() -> bool:
    """v3.28.2 — read ``LLM_FREE_ONLY`` env. Defaults to True.

    When True, paid providers (anthropic, openai) are blocked at the
    call_provider gate. Set ``LLM_FREE_ONLY=false`` to opt-in to paid
    providers.
    """
    raw = os.environ.get("LLM_FREE_ONLY", "true").strip().lower()
    return raw in ("true", "1", "yes", "on")


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("LLM_PROVIDER_TIMEOUT", "30") or 30)
    except (TypeError, ValueError):
        return 30.0


# ─── Public API ─────────────────────────────────────────────────────────────

def call_provider(
    *,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 512,
    timeout_seconds: float | None = None,
) -> ProviderResponse:
    """Call the active provider. Default is offline-mock — safe to run
    in environments without provider keys.

    Returns a ``ProviderResponse``; never raises. ``text`` is redacted
    of secret-shaped tokens before return.
    """
    prov = _provider()

    # v3.28.2 — free-only policy gate. Paid providers blocked unless
    # operator explicitly sets LLM_FREE_ONLY=false.
    if _free_only_enabled() and prov in PAID_PROVIDERS:
        return ProviderResponse(
            status=LLM_PROVIDER_BLOCKED_BY_FREE_ONLY,
            provider=prov, model=None,
            text=(f"provider '{prov}' is paid; LLM_FREE_ONLY=true "
                   f"(default). Set LLM_FREE_ONLY=false to opt in."),
            cost_usd=0.0,
        )

    if prov == "offline_mock":
        # Pure deterministic mock — no network call.
        mock_text = json.dumps({
            "mock":           True,
            "summary":        "offline_mock — no provider call performed",
            "advisory_only":  True,
        }, sort_keys=True)
        return ProviderResponse(
            status=LLM_PROVIDER_OFFLINE_MOCK,
            provider=prov, model=None,
            text=mock_text, cost_usd=0.0,
        )

    key_env = _provider_key_env(prov)
    if key_env is None:
        return ProviderResponse(
            status=LLM_PROVIDER_DISABLED,
            provider=prov, model=None,
            text="provider not recognised", cost_usd=0.0,
        )
    key = os.environ.get(key_env, "").strip()
    if not key:
        return ProviderResponse(
            status=LLM_PROVIDER_KEY_MISSING,
            provider=prov, model=None,
            text=f"missing env: {key_env}", cost_usd=0.0,
        )

    # Real provider call. Wrapped to fail-soft on any error.
    try:
        import requests
        if prov == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            mdl = model or "claude-3-5-haiku-latest"
            headers = {
                "x-api-key":         key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            }
            payload: dict[str, Any] = {
                "model":      mdl,
                "max_tokens": int(max_tokens),
                "messages":   [{"role": "user", "content": prompt}],
            }
            if system:
                payload["system"] = system
        elif prov == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            mdl = model or "gpt-4o-mini"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
            }
            msgs: list[dict[str, str]] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            payload = {
                "model":      mdl,
                "max_tokens": int(max_tokens),
                "messages":   msgs,
            }
        elif prov == "gemini":
            # v3.28.2 + v3.29 — Gemini free-tier via Google AI Studio.
            # Key passed as ``?key=`` query param per Google's
            # reference; never put it in headers or logs.
            # v3.29 — when the operator hasn't pinned a model, run
            # discovery so we don't crash on a stale default like
            # "gemini-2.5-flash-lite" not being available.
            configured = (model
                            or os.environ.get("GEMINI_MODEL", "").strip())
            mdl = configured or "gemini-flash-latest"
            # Try discovery + selection (fail-soft).
            try:
                try:
                    import gemini_model_selector as _sel  # type: ignore
                except ImportError:
                    from shared import gemini_model_selector as _sel  # type: ignore
                disc = _sel.select_model(
                    configured_model=configured or None,
                    api_key=key,
                    timeout_seconds=min(
                        timeout_seconds or _timeout_seconds(), 10.0),
                )
                if disc.selected_model:
                    mdl = disc.selected_model
            except Exception:
                # Selector itself failed → keep mdl as-is.
                pass
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/{mdl}:generateContent?key={key}")
            headers = {"Content-Type": "application/json"}
            contents: list[dict[str, Any]] = []
            if system:
                # Gemini accepts a "system_instruction" sibling of
                # "contents" in v1beta. Use it directly.
                contents = [{"role": "user",
                              "parts": [{"text": prompt}]}]
                payload = {
                    "system_instruction": {
                        "parts": [{"text": system}]},
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": int(max_tokens),
                    },
                }
            else:
                contents = [{"role": "user",
                              "parts": [{"text": prompt}]}]
                payload = {
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": int(max_tokens),
                    },
                }
        else:
            return ProviderResponse(
                status=LLM_PROVIDER_DISABLED,
                provider=prov, model=None,
                text="provider not recognised", cost_usd=0.0,
            )

        r = requests.post(
            url, headers=headers, json=payload,
            timeout=(timeout_seconds or _timeout_seconds()),
        )
        if r.status_code != 200:
            # v3.28.2 — Gemini 4xx on the model path most commonly
            # means the model name is unsupported. Route to a
            # distinct status so the operator can distinguish a
            # bad model from a generic outage.
            status_tok = LLM_PROVIDER_CALL_FAILED
            if prov == "gemini" and r.status_code in (400, 404):
                status_tok = LLM_PROVIDER_MODEL_ERROR
            # v3.29 — enrich the response with safe diagnostics so the
            # caller (mesh runner / quality guard) can classify the
            # failure deterministically.
            category = None
            suggested_next = None
            if prov == "gemini":
                try:
                    try:
                        import gemini_model_selector as _sel  # type: ignore
                    except ImportError:
                        from shared import gemini_model_selector as _sel  # type: ignore
                    category = _sel.classify_http_status(r.status_code)
                    # Suggest a different candidate to try next.
                    for c in _sel.DEFAULT_CANDIDATE_MODELS:
                        if c != mdl:
                            suggested_next = c
                            break
                except Exception:
                    pass
            return ProviderResponse(
                status=status_tok,
                provider=prov, model=mdl,
                text=_redact(f"HTTP {r.status_code}"),
                cost_usd=0.0,
                provider_http_status=r.status_code,
                provider_error_category=category,
                provider_endpoint_family=(
                    "generativelanguage.googleapis.com/v1beta"
                    if prov == "gemini" else None),
                provider_retryable=(500 <= r.status_code < 600
                                      or r.status_code == 429),
                provider_suggested_next_model=suggested_next,
            )
        body = r.json() or {}
        # Anthropic: body["content"][0]["text"]
        # OpenAI:    body["choices"][0]["message"]["content"]
        # Gemini:    body["candidates"][0]["content"]["parts"][0]["text"]
        text = ""
        if prov == "anthropic":
            try:
                text = body["content"][0]["text"]
            except (KeyError, IndexError, TypeError):
                text = ""
        elif prov == "gemini":
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                text = ""
        else:
            try:
                text = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                text = ""
        cost = 0.0  # crude — caller may estimate from usage
        return ProviderResponse(
            status=LLM_PROVIDER_CALL_OK,
            provider=prov, model=mdl,
            text=_redact(text), cost_usd=cost,
            raw=None,  # never persist raw provider responses
        )
    except Exception as e:
        msg = _redact(f"{type(e).__name__}: {e}")
        timeout_hit = "timeout" in msg.lower() or "Timeout" in str(e)
        return ProviderResponse(
            status=(LLM_PROVIDER_TIMEOUT if timeout_hit
                     else LLM_PROVIDER_CALL_FAILED),
            provider=prov, model=None,
            text=msg, cost_usd=0.0,
        )


__all__ = [
    "LLM_PROVIDER_DISABLED", "LLM_PROVIDER_KEY_MISSING",
    "LLM_PROVIDER_CALL_OK", "LLM_PROVIDER_CALL_FAILED",
    "LLM_PROVIDER_TIMEOUT", "LLM_PROVIDER_OFFLINE_MOCK",
    "LLM_PROVIDER_BLOCKED_BY_FREE_ONLY",
    "LLM_PROVIDER_MODEL_ERROR",
    "ALL_PROVIDER_STATUSES",
    "FREE_PROVIDERS", "PAID_PROVIDERS", "KNOWN_PROVIDERS",
    "ProviderResponse",
    "call_provider",
]

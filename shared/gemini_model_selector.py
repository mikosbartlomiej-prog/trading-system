"""v3.29 (2026-06-09) — Gemini model discovery + fallback selector.

Solves the v3.28.3 root cause: the workflow defaulted `GEMINI_MODEL`
to a model name that may not exist on the operator's free-tier key.
This module asks the Gemini API which models are actually available
and picks a safe text-capable candidate.

HARD SAFETY
-----------
- NEVER logs the API key.
- NEVER logs the full URL (the URL carries the key as a query param).
- NEVER imports the broker-orders module.
- NEVER mutates trading state.
- Fail-soft on any error — returns a status enum, never raises.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

# ─── Status enum ────────────────────────────────────────────────────────────

GEMINI_MODEL_SELECTED                = "GEMINI_MODEL_SELECTED"
GEMINI_MODEL_DISCOVERY_OK            = "GEMINI_MODEL_DISCOVERY_OK"
GEMINI_MODEL_DISCOVERY_AUTH_FAILED   = "GEMINI_MODEL_DISCOVERY_AUTH_FAILED"
GEMINI_MODEL_DISCOVERY_QUOTA         = "GEMINI_MODEL_DISCOVERY_QUOTA"
GEMINI_MODEL_DISCOVERY_PERMISSION    = "GEMINI_MODEL_DISCOVERY_PERMISSION"
GEMINI_MODEL_DISCOVERY_ENDPOINT      = "GEMINI_MODEL_DISCOVERY_ENDPOINT"
GEMINI_MODEL_DISCOVERY_TIMEOUT       = "GEMINI_MODEL_DISCOVERY_TIMEOUT"
GEMINI_MODEL_DISCOVERY_NO_KEY        = "GEMINI_MODEL_DISCOVERY_NO_KEY"
GEMINI_MODEL_DISCOVERY_NO_CANDIDATES = "GEMINI_MODEL_DISCOVERY_NO_CANDIDATES"
GEMINI_MODEL_DISCOVERY_FAILED        = "GEMINI_MODEL_DISCOVERY_FAILED"

ALL_DISCOVERY_STATUSES: frozenset[str] = frozenset({
    GEMINI_MODEL_SELECTED,
    GEMINI_MODEL_DISCOVERY_OK,
    GEMINI_MODEL_DISCOVERY_AUTH_FAILED,
    GEMINI_MODEL_DISCOVERY_QUOTA,
    GEMINI_MODEL_DISCOVERY_PERMISSION,
    GEMINI_MODEL_DISCOVERY_ENDPOINT,
    GEMINI_MODEL_DISCOVERY_TIMEOUT,
    GEMINI_MODEL_DISCOVERY_NO_KEY,
    GEMINI_MODEL_DISCOVERY_NO_CANDIDATES,
    GEMINI_MODEL_DISCOVERY_FAILED,
})

# ─── Failure category enum (shared with provider client) ───────────────────

GEMINI_MODEL_UNAVAILABLE          = "GEMINI_MODEL_UNAVAILABLE"
GEMINI_AUTH_FAILED                = "GEMINI_AUTH_FAILED"
GEMINI_QUOTA_OR_RATE_LIMIT        = "GEMINI_QUOTA_OR_RATE_LIMIT"
GEMINI_PERMISSION_DENIED          = "GEMINI_PERMISSION_DENIED"
GEMINI_ENDPOINT_ERROR             = "GEMINI_ENDPOINT_ERROR"
GEMINI_TIMEOUT                    = "GEMINI_TIMEOUT"
GEMINI_UNKNOWN_PROVIDER_FAILURE   = "GEMINI_UNKNOWN_PROVIDER_FAILURE"

ALL_FAILURE_CATEGORIES: frozenset[str] = frozenset({
    GEMINI_MODEL_UNAVAILABLE, GEMINI_AUTH_FAILED,
    GEMINI_QUOTA_OR_RATE_LIMIT, GEMINI_PERMISSION_DENIED,
    GEMINI_ENDPOINT_ERROR, GEMINI_TIMEOUT,
    GEMINI_UNKNOWN_PROVIDER_FAILURE,
})


def classify_http_status(code: int) -> str:
    """Map HTTP status code to a v3.29 failure category."""
    if code in (400, 404):
        return GEMINI_MODEL_UNAVAILABLE
    if code == 401:
        return GEMINI_AUTH_FAILED
    if code == 403:
        return GEMINI_PERMISSION_DENIED
    if code == 429:
        return GEMINI_QUOTA_OR_RATE_LIMIT
    if 500 <= code < 600:
        return GEMINI_ENDPOINT_ERROR
    return GEMINI_UNKNOWN_PROVIDER_FAILURE


# ─── Candidate fallback list (conservative, free-tier biased) ──────────────

# Order matters — first match wins. Aliases preferred over fixed dates.
DEFAULT_CANDIDATE_MODELS: tuple[str, ...] = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash",
)


def _is_safe_text_model(name: str) -> bool:
    """Heuristic: exclude obvious non-text / image / video / embed
    aliases. Errs toward exclusion."""
    lower = name.lower()
    blacklist = (
        "embed", "embedding", "imagen", "video", "audio", "tts",
        "live-2.0", "vision-only", "speech", "exp-", "experimental",
    )
    return not any(b in lower for b in blacklist)


def _score_model(name: str) -> int:
    """Lower is better. Prefers stable aliases over preview/pro."""
    lower = name.lower()
    score = 100
    if "flash" in lower:
        score -= 30
    if "lite" in lower:
        score -= 5
    if "latest" in lower:
        score -= 20
    if "preview" in lower or "preview-" in lower:
        score += 50
    if "experimental" in lower or "exp-" in lower:
        score += 50
    if "pro" in lower and "flash" not in lower:
        score += 30
    # Prefer 2.5 / 3.x over older 1.5.
    if "2.5" in lower or "3.0" in lower or "3.5" in lower:
        score -= 10
    if "1.5" in lower:
        score += 5
    return score


@dataclass
class ModelDiscoveryResult:
    status:            str
    selected_model:    str | None = None
    discovered:        list[str] = field(default_factory=list)
    selection_reason:  str = ""
    failure_category:  str | None = None
    failure_http:      int | None = None
    error_redacted:    str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status":            self.status,
            "selected_model":    self.selected_model,
            "discovered_models": list(self.discovered),
            "discovered_models_count": len(self.discovered),
            "selection_reason":  self.selection_reason,
            "failure_category":  self.failure_category,
            "failure_http":      self.failure_http,
            "error_redacted":    self.error_redacted,
        }


# ─── Public API ────────────────────────────────────────────────────────────

def _redact_for_log(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"AIza[A-Za-z0-9_\-]{20,}", "<REDACTED>", text)
    cleaned = re.sub(r"key=[A-Za-z0-9_\-]+", "key=<REDACTED>", cleaned)
    cleaned = re.sub(r"sk-ant-[A-Za-z0-9_\-]{6,}", "<REDACTED>", cleaned)
    cleaned = re.sub(r"\bsk-[A-Za-z0-9]{8,}", "<REDACTED>", cleaned)
    cleaned = re.sub(r"\b[A-Z0-9]{20,}\b", "<REDACTED>", cleaned)
    return cleaned[:300]


def discover_models(*,
                      api_key: str | None = None,
                      timeout_seconds: float = 10.0,
                      ) -> ModelDiscoveryResult:
    """Call Gemini's ListModels endpoint and return discovered text
    models in score order. Fail-soft on every error.
    """
    key = (api_key
            if api_key is not None
            else os.environ.get("GEMINI_API_KEY", "").strip())
    if not key:
        return ModelDiscoveryResult(
            status=GEMINI_MODEL_DISCOVERY_NO_KEY,
            error_redacted="GEMINI_API_KEY missing")
    try:
        import requests
        # NOTE: URL omitted from any logging — query carries the key.
        url = (
            f"https://generativelanguage.googleapis.com/"
            f"v1beta/models?key={key}")
        r = requests.get(url, timeout=timeout_seconds)
        if r.status_code != 200:
            category = classify_http_status(r.status_code)
            status_map = {
                GEMINI_AUTH_FAILED:
                    GEMINI_MODEL_DISCOVERY_AUTH_FAILED,
                GEMINI_QUOTA_OR_RATE_LIMIT:
                    GEMINI_MODEL_DISCOVERY_QUOTA,
                GEMINI_PERMISSION_DENIED:
                    GEMINI_MODEL_DISCOVERY_PERMISSION,
                GEMINI_ENDPOINT_ERROR:
                    GEMINI_MODEL_DISCOVERY_ENDPOINT,
            }
            return ModelDiscoveryResult(
                status=status_map.get(
                    category, GEMINI_MODEL_DISCOVERY_FAILED),
                failure_category=category,
                failure_http=r.status_code,
                error_redacted=_redact_for_log(
                    f"HTTP {r.status_code}"))
        body = r.json() or {}
        raw_models = body.get("models") or []
        names: list[str] = []
        for m in raw_models:
            if not isinstance(m, dict):
                continue
            n = m.get("name") or ""
            # The "name" field comes back as "models/<id>" — strip the
            # prefix so we can pass the bare id to call_provider.
            if n.startswith("models/"):
                n = n[len("models/"):]
            if not n:
                continue
            # Only keep models that support generateContent.
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            if not _is_safe_text_model(n):
                continue
            names.append(n)
        names = sorted(set(names), key=_score_model)
        return ModelDiscoveryResult(
            status=GEMINI_MODEL_DISCOVERY_OK,
            discovered=names)
    except Exception as e:
        msg = _redact_for_log(f"{type(e).__name__}: {e}")
        if "timeout" in msg.lower() or "Timeout" in str(e):
            return ModelDiscoveryResult(
                status=GEMINI_MODEL_DISCOVERY_TIMEOUT,
                failure_category=GEMINI_TIMEOUT,
                error_redacted=msg)
        return ModelDiscoveryResult(
            status=GEMINI_MODEL_DISCOVERY_FAILED,
            failure_category=GEMINI_UNKNOWN_PROVIDER_FAILURE,
            error_redacted=msg)


def select_model(*,
                   configured_model: str | None = None,
                   api_key: str | None = None,
                   candidate_models: tuple[str, ...] = (
                       DEFAULT_CANDIDATE_MODELS),
                   timeout_seconds: float = 10.0,
                   ) -> ModelDiscoveryResult:
    """Choose a model to use. Precedence:

    1. ``configured_model`` if it appears in the discovered set.
    2. First entry of ``candidate_models`` that appears in the
       discovered set.
    3. First entry of the discovered set (score-sorted).
    4. If discovery failed AND configured_model is set, return
       configured_model with status=GEMINI_MODEL_DISCOVERY_FAILED so
       the caller can still attempt it.
    """
    disc = discover_models(
        api_key=api_key, timeout_seconds=timeout_seconds)
    if disc.status != GEMINI_MODEL_DISCOVERY_OK:
        # Discovery failed — let caller try configured/candidate
        # anyway so a working network with the right key can still
        # succeed.
        disc.selected_model = configured_model or (
            candidate_models[0] if candidate_models else None)
        disc.selection_reason = (
            "discovery failed; falling back to configured / first "
            "candidate without confirmation")
        return disc
    available = set(disc.discovered)
    if configured_model and configured_model in available:
        disc.status = GEMINI_MODEL_SELECTED
        disc.selected_model = configured_model
        disc.selection_reason = (
            f"configured model {configured_model!r} is available")
        return disc
    for c in candidate_models:
        if c in available:
            disc.status = GEMINI_MODEL_SELECTED
            disc.selected_model = c
            disc.selection_reason = (
                f"first candidate {c!r} available from "
                f"DEFAULT_CANDIDATE_MODELS")
            return disc
    if disc.discovered:
        disc.status = GEMINI_MODEL_SELECTED
        disc.selected_model = disc.discovered[0]
        disc.selection_reason = (
            "neither configured nor candidate available; falling "
            "back to top-scored discovered model")
        return disc
    disc.status = GEMINI_MODEL_DISCOVERY_NO_CANDIDATES
    disc.selection_reason = (
        "discovery returned 0 text-capable models")
    return disc


def write_status_artifact(result: ModelDiscoveryResult,
                            *,
                            path=None,
                            configured_model: str | None = None,
                            last_successful_model: str | None = None,
                            last_failure_category: str | None = None,
                            ) -> None:
    """Persist a redacted status artifact for operator visibility."""
    from pathlib import Path
    from datetime import datetime, timezone
    if path is None:
        REPO_ROOT = Path(__file__).resolve().parent.parent
        path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                  / "gemini_model_status_latest.json")
    payload = {
        "generated_at_iso":         datetime.now(timezone.utc).isoformat(),
        "configured_model":         configured_model,
        "discovered_models_count":  len(result.discovered),
        "discovered_models":        list(result.discovered),
        "selected_model":           result.selected_model,
        "selection_reason":         result.selection_reason,
        "discovery_status":         result.status,
        "last_successful_model":    last_successful_model,
        "last_failure_category":    (last_failure_category
                                      or result.failure_category),
        "failure_http":             result.failure_http,
        "error_redacted":           result.error_redacted,
        "safe_to_schedule":         False,
        "free_only":                True,
        "secret_values_logged":     False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


__all__ = [
    # Status enums
    "GEMINI_MODEL_SELECTED",
    "GEMINI_MODEL_DISCOVERY_OK",
    "GEMINI_MODEL_DISCOVERY_AUTH_FAILED",
    "GEMINI_MODEL_DISCOVERY_QUOTA",
    "GEMINI_MODEL_DISCOVERY_PERMISSION",
    "GEMINI_MODEL_DISCOVERY_ENDPOINT",
    "GEMINI_MODEL_DISCOVERY_TIMEOUT",
    "GEMINI_MODEL_DISCOVERY_NO_KEY",
    "GEMINI_MODEL_DISCOVERY_NO_CANDIDATES",
    "GEMINI_MODEL_DISCOVERY_FAILED",
    "ALL_DISCOVERY_STATUSES",
    "GEMINI_MODEL_UNAVAILABLE",
    "GEMINI_AUTH_FAILED",
    "GEMINI_QUOTA_OR_RATE_LIMIT",
    "GEMINI_PERMISSION_DENIED",
    "GEMINI_ENDPOINT_ERROR",
    "GEMINI_TIMEOUT",
    "GEMINI_UNKNOWN_PROVIDER_FAILURE",
    "ALL_FAILURE_CATEGORIES",
    # Constants
    "DEFAULT_CANDIDATE_MODELS",
    # Helpers
    "classify_http_status",
    # Public API
    "ModelDiscoveryResult",
    "discover_models", "select_model", "write_status_artifact",
]

"""LLM provider configuration (server-side only, stdlib).

Env convention (AI_* primary, common aliases accepted):

    AI_PROVIDER   openai | anthropic | openrouter | ollama | azure | off
    AI_MODEL      model id (e.g. gpt-4o-mini)
    AI_API_KEY    secret (never sent to the browser, never logged)
    AI_BASE_URL   optional OpenAI-compatible endpoint override
    AI_TIMEOUT_S  per-call timeout seconds (default 45)

Aliases: OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY are
accepted as AI_API_KEY fallbacks so existing secrets keep working.
When nothing is configured the terminal keeps working and AI research
reports "LLM provider not configured".
"""

from __future__ import annotations

import os

SUPPORTED_PROVIDERS = ("openai", "anthropic", "openrouter", "ollama", "azure", "off")

_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "openrouter": "openai/gpt-4o-mini",
    "ollama": "llama3.1",
    "azure": "gpt-4o-mini",
}


def _clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def provider() -> str:
    raw = (_clean("AI_PROVIDER") or "openai").lower()
    if raw in ("", "off", "none", "disabled"):
        return "off"
    if raw in SUPPORTED_PROVIDERS:
        return raw
    return raw  # unknown -> treated as OpenAI-compatible endpoint


def api_key() -> str:
    for name in ("AI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        val = _clean(name)
        if val:
            return val
    return ""


def model() -> str:
    explicit = _clean("AI_MODEL")
    if explicit:
        return explicit
    return _DEFAULT_MODELS.get(provider(), "gpt-4o-mini")


def base_url() -> str:
    explicit = _clean("AI_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    prov = provider()
    if prov == "anthropic":
        return "https://api.anthropic.com"
    if prov == "openrouter":
        return "https://openrouter.ai/api/v1"
    if prov == "ollama":
        return (_clean("OLLAMA_HOST") or "http://localhost:11434/v1").rstrip("/")
    azure_ep = _clean("AZURE_OPENAI_ENDPOINT")
    if prov == "azure" and azure_ep:
        return azure_ep.rstrip("/")
    return "https://api.openai.com/v1"


def timeout_s() -> float:
    try:
        return max(5.0, min(120.0, float(_clean("AI_TIMEOUT_S") or 45)))
    except ValueError:
        return 45.0


def status() -> dict:
    """Public status payload: safe to send to the browser (no secrets)."""
    prov = provider()
    key = api_key()
    if prov == "off" or not key:
        return {
            "available": False,
            "provider": prov,
            "model": model(),
            "reason": "LLM provider not configured",
        }
    return {"available": True, "provider": prov, "model": model(), "reason": None}

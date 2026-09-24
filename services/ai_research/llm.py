"""LLM abstraction (stdlib urllib, OpenAI-compatible chat completions).

Supports: openai, openrouter, ollama, azure (chat-completions path),
anthropic (messages API), and any AI_BASE_URL override. Timeouts,
single retry on 429/5xx, JSON-safe extraction. API keys travel only in
server-side HTTPS headers — never logged, never returned.

When no LLM is configured, callers use deterministic_extract() so the
terminal still returns an evidence-grounded (non-LLM) research draft
labelled as such — the endpoint instead reports "LLM provider not
configured" unless allow_fallback is set.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from . import config as _cfg


class LLMError(Exception):
    def __init__(self, message: str, *, kind: str = "LLM_API_ERROR") -> None:
        super().__init__(message)
        self.kind = kind


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    last_err: Exception | None = None
    for attempt in (1, 2):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = ""
            if exc.code in (429,) or 500 <= exc.code <= 599:
                if attempt == 1:
                    time.sleep(1.0)
                    last_err = exc
                    continue
                raise LLMError(f"LLM HTTP {exc.code}: {detail}"[:300], kind="RATE_LIMIT" if exc.code == 429 else "LLM_API_ERROR") from exc
            raise LLMError(f"LLM HTTP {exc.code}: {detail}"[:300], kind="LLM_API_ERROR") from exc
        except TimeoutError as exc:
            raise LLMError("LLM request timed out.", kind="LLM_TIMEOUT") from exc
        except Exception as exc:
            if "timed out" in str(exc).lower():
                raise LLMError("LLM request timed out.", kind="LLM_TIMEOUT") from exc
            raise LLMError(f"LLM transport error: {exc}"[:250], kind="LLM_API_ERROR") from exc
    raise LLMError(str(last_err)[:250] if last_err else "LLM failed.", kind="LLM_API_ERROR")


def complete(messages: list[dict], *, max_tokens: int = 900, temperature: float = 0.2) -> dict:
    """Call the configured LLM. Returns {"text": ..., "model": ..., "provider": ...}."""
    prov = _cfg.provider()
    key = _cfg.api_key()
    if prov == "off" or not key:
        raise LLMError("LLM provider not configured.", kind="LLM_NOT_CONFIGURED")
    model = _cfg.model()
    timeout = _cfg.timeout_s()
    if prov == "anthropic":
        url = _cfg.base_url() + "/v1/messages"
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user_msgs = [{"role": "user", "content": m["content"]} for m in messages if m["role"] != "system"]
        payload = {"model": model, "max_tokens": max_tokens, "system": system, "messages": user_msgs}
        headers = {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        data = _post_json(url, payload, headers, timeout)
        try:
            text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
        except Exception:
            text = ""
        return {"text": text.strip(), "model": model, "provider": prov}
    # OpenAI-compatible (openai/openrouter/ollama/azure/overrides).
    url = _cfg.base_url() + "/chat/completions"
    compat: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    if prov == "openrouter":
        headers["HTTP-Referer"] = "https://finance-terminal.local"
        headers["X-Title"] = "Finance Terminal AI Research"
    data = _post_json(url, compat, headers, timeout)
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise LLMError("LLM returned an unreadable response.", kind="LLM_API_ERROR") from exc
    return {"text": (text or "").strip(), "model": model, "provider": prov}


def deterministic_extract(role: str, evidence_text: str) -> str:
    """No-LLM fallback: extractive, evidence-only draft (clearly labelled)."""
    lines = [ln.strip() for ln in evidence_text.splitlines() if ln.strip()]
    picked = [ln for ln in lines if ln.split(" ", 1)[0] in ("QUOTE", "VALUATION", "GROWTH", "TECHNICAL", "NEWS", "INCOME")]
    head = "; ".join(picked[:6]) if picked else "Evidence pack present but all legs unavailable."
    return (
        f"[{role.upper()} — extractive draft, no LLM configured] {head} "
        "UNCERTAIN: interpretation requires a configured LLM; values above are reported evidence only."
    )

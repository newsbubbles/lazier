"""OpenRouter (OpenAI-compatible) client. Used by pass-2 segmentation now; the
agent fleet in later milestones reuses the same endpoint."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from . import config


class LLMNotConfigured(RuntimeError):
    pass


def _client() -> OpenAI:
    if not config.OPENROUTER_API_KEY:
        raise LLMNotConfigured(
            "OPENROUTER_API_KEY is not set. Pass-2 section merge needs an LLM. "
            "Set the env var, or call segmentation with llm_merge=False to keep "
            "raw pass-1 segments."
        )
    return OpenAI(
        base_url=config.OPENROUTER_BASE_URL,
        api_key=config.OPENROUTER_API_KEY,
        default_headers={"HTTP-Referer": "https://lazier.local", "X-Title": "lazier"},
    )


def json_chat(system: str, user: str, model: str | None = None) -> Any:
    """Single-shot chat that must return a JSON object. Raises on malformed output
    (no silent fallback)."""
    client = _client()
    resp = client.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = resp.choices[0].message.content or ""
    return json.loads(content)

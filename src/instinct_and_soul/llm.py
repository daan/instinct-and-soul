"""
llm.py — LLM client abstraction + config loader for the spine.

Public surface:
    LLMClient                                  — abstract base class
    AnthropicClient, OpenAIClient, GeminiClient — concrete implementations
    MODEL_PRICES, compute_cost(model, usage)
    load_llm(name=None) -> (client, info)

Providers (config `api =`): "anthropic", "openai" (incl. OpenAI-compatible
endpoints via base_url: OpenRouter, Ollama, …), and "google" (native Gemini).

Config resolution (spine startup):
    1. CLI --llm NAME             → .config/llm/<NAME>.toml
    2. .config/config.toml [llm]  → inline block
       .config/config.toml llm=N → shorthand, reads .config/llm/<N>.toml
    3. fallback: anthropic + claude-sonnet-4-6 (key from ANTHROPIC_API_KEY env)

Config files searched in this order:
    1. ./.config/<rel>
    2. ~/.config/instinct-and-soul/<rel>
"""

import os
from abc import ABC, abstractmethod

import anthropic
import openai

from . import _config


# ── Pricing ────────────────────────────────────────────────────────────────

# USD per 1M tokens — (input, output). Cache reads price at ~0.1× input;
# cache writes at ~1.25× input. Update if Anthropic changes pricing.
# OpenAI / OpenRouter / local models: add entries here for cost tracking,
# else cost shows as "—".
MODEL_PRICES = {
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-7":           (15.00, 75.00),
    "claude-haiku-4-5-20251001": (0.80,  4.00),
    # Google Gemini — verify against current Google pricing. Note compute_cost's
    # cache multiplier (0.1×) is Anthropic-tuned; Gemini implicit caching is ≈0.25×,
    # so cached cost is slightly under-counted (fine for a rough tracker).
    "gemini-2.5-flash":          (0.30,  2.50),
    "gemini-2.5-pro":            (1.25, 10.00),
    "gemini-2.5-flash-lite":     (0.10,  0.40),
    "gemini-2.0-flash":          (0.10,  0.40),
}


def compute_cost(model, usage):
    """Return USD cost given model id and a usage dict, or None if model unknown."""
    if model not in MODEL_PRICES:
        return None
    in_price, out_price = MODEL_PRICES[model]
    fresh_in    = usage.get("input_tokens", 0) or 0
    cache_read  = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    out_tokens  = usage.get("output_tokens", 0) or 0
    return (fresh_in * in_price
            + cache_read * in_price * 0.1
            + cache_write * in_price * 1.25
            + out_tokens * out_price) / 1_000_000


# ── Clients ────────────────────────────────────────────────────────────────

class LLMClient(ABC):
    """Provider-agnostic LLM client returning {text, usage} dicts."""

    api: str
    model: str

    @abstractmethod
    async def call(self, system_prompt, user_message):
        """Send a single-turn (system + user) request. Returns:
            {"text": str, "usage": {input_tokens, cache_read_input_tokens,
                                    cache_creation_input_tokens, output_tokens}}
        """


class AnthropicClient(LLMClient):
    api = "anthropic"

    def __init__(self, model, api_key=None):
        self.model = model
        # api_key=None lets the SDK read ANTHROPIC_API_KEY from env.
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key \
            else anthropic.AsyncAnthropic()

    async def call(self, system_prompt, user_message):
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            messages=[{"role": "user", "content": user_message}],
            extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
        )
        return {
            "text": response.content[0].text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
                "output_tokens": response.usage.output_tokens,
            },
        }


class OpenAIClient(LLMClient):
    api = "openai"

    def __init__(self, model, api_key=None, base_url=None):
        self.model = model
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.AsyncOpenAI(**kwargs)

    async def call(self, system_prompt, user_message):
        # 16K leaves room for reasoning-token models (Kimi K2.6, DeepSeek R1)
        # that burn output tokens on hidden thinking before the visible reply.
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=16384,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        usage = response.usage
        return {
            "text": response.choices[0].message.content,
            "usage": {
                "input_tokens": usage.prompt_tokens if usage else 0,
                # OpenAI-compatible endpoints don't expose prompt caching.
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": usage.completion_tokens if usage else 0,
            },
        }


# Harm categories relaxed for Gemini — the reflection prompt is creative/embodied
# and must not be silently blocked or truncated by default safety filters.
_GEMINI_HARM_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
    "HARM_CATEGORY_CIVIC_INTEGRITY",
)


class GeminiClient(LLMClient):
    """Native Google Gemini via the google-genai SDK. Exposes fine control:
    thinking_budget (0=off, -1=dynamic, N=cap), temperature, max_output_tokens."""

    api = "google"

    def __init__(self, model, api_key=None, thinking_budget=None,
                 temperature=None, max_output_tokens=16384):
        from google import genai  # lazy: only imported when Gemini is selected
        api_key = (api_key or os.environ.get("GEMINI_API_KEY")
                   or os.environ.get("GOOGLE_API_KEY"))
        self.model = model
        self.client = genai.Client(api_key=api_key)
        self.thinking_budget = thinking_budget
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    async def call(self, system_prompt, user_message):
        from google.genai import types
        cfg = {
            "system_instruction": system_prompt,
            "max_output_tokens": self.max_output_tokens,
            "safety_settings": [
                types.SafetySetting(category=c, threshold="BLOCK_NONE")
                for c in _GEMINI_HARM_CATEGORIES
            ],
        }
        if self.temperature is not None:
            cfg["temperature"] = self.temperature
        if self.thinking_budget is not None:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(**cfg),
        )
        um = response.usage_metadata
        cached = getattr(um, "cached_content_token_count", 0) or 0
        prompt = getattr(um, "prompt_token_count", 0) or 0
        thoughts = getattr(um, "thoughts_token_count", 0) or 0      # billed as output
        candidates = getattr(um, "candidates_token_count", 0) or 0
        return {
            "text": _gemini_text(response),
            "usage": {
                # Gemini's prompt_token_count includes the cached prefix; split it
                # out so cost matches the Anthropic-style fresh/cached pricing.
                "input_tokens": max(0, prompt - cached),
                "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": 0,   # implicit caching: no explicit write
                "output_tokens": candidates + thoughts,
            },
        }


def _gemini_text(response) -> str:
    # `.text` raises/warns if the response was blocked or produced no text part;
    # degrade to "" so the spine just logs a missing intent, not a crash.
    try:
        return response.text or ""
    except Exception:
        return ""


# ── Config loading ─────────────────────────────────────────────────────────

def _client_from_dict(d):
    api = d.get("api")
    model = d.get("model")
    if not api:
        raise ValueError("llm config missing 'api'")
    if not model:
        raise ValueError("llm config missing 'model'")
    api_key = d.get("api_key")
    base_url = d.get("base_url")
    if api == "anthropic":
        return AnthropicClient(model=model, api_key=api_key)
    if api == "openai":
        return OpenAIClient(model=model, api_key=api_key, base_url=base_url)
    if api in ("google", "gemini"):
        return GeminiClient(
            model=model, api_key=api_key,
            thinking_budget=d.get("thinking_budget"),
            temperature=d.get("temperature"),
            max_output_tokens=d.get("max_output_tokens", 16384),
        )
    raise ValueError("unknown api: {!r}".format(api))


def _info(name, client):
    return {"llm": name, "api": client.api, "model": client.model}


def load_llm(name=None):
    """Resolve and instantiate an LLMClient.

    Returns (client, info) where info = {"llm": name|None, "api", "model"}.
    The `llm` field is the profile name when one was used, else None.
    """
    if name:
        client = _client_from_dict(_config.load_profile("llm", name))
        return client, _info(name, client)

    cfg = _config.load_config_toml()
    llm_entry = cfg.get("llm")
    # Notation B — shorthand: llm = "name" → load .config/llm/<name>.toml
    if isinstance(llm_entry, str):
        client = _client_from_dict(_config.load_profile("llm", llm_entry))
        return client, _info(llm_entry, client)
    # Notation A — inline [llm] block
    if isinstance(llm_entry, dict):
        client = _client_from_dict(llm_entry)
        return client, _info(None, client)

    # Fallback: anthropic + sonnet, key from ANTHROPIC_API_KEY env.
    client = AnthropicClient(model="claude-sonnet-4-6")
    return client, _info(None, client)

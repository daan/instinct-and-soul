"""
llm.py — LLM client abstraction + config loader for the spine.

Public surface:
    LLMClient                         — abstract base class
    AnthropicClient, OpenAIClient     — concrete implementations
    MODEL_PRICES, compute_cost(model, usage)
    load_llm(name=None) -> (client, info)

Config resolution (spine startup):
    1. CLI --llm NAME             → .config/llm/<NAME>.toml
    2. .config/config.toml [llm]  → inline block
       .config/config.toml llm=N → shorthand, reads .config/llm/<N>.toml
    3. fallback: anthropic + claude-sonnet-4-6 (key from ANTHROPIC_API_KEY env)

Config files searched in this order:
    1. ./.config/<rel>
    2. ~/.config/instinct-and-soul/<rel>
"""

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
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
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

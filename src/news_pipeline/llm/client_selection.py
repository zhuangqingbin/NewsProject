# src/news_pipeline/llm/client_selection.py
"""Helpers for routing LLM requests to the correct client.

Anthropic is optional: if the API key is absent or unconfigured, Tier-2 and
Tier-3 requests that would have targeted a ``claude-*`` model are automatically
rerouted to DashScope using the Tier-1 model.
"""
from news_pipeline.llm.clients.base import LLMClient


def is_anthropic_configured(api_key: str) -> bool:
    """Return True iff the key looks like a real Anthropic API key."""
    key = (api_key or "").strip()
    return bool(key) and key != "REPLACE_ME"


def pick_client_and_model(
    configured_model: str,
    *,
    anthropic_client: LLMClient | None,
    dashscope_client: LLMClient,
    tier1_fallback_model: str,
) -> tuple[LLMClient, str]:
    """Pick the LLM client and effective model for a configured model name.

    Rules:
    - If ``configured_model`` starts with ``"claude-"``:
        - Anthropic configured → use Anthropic + the configured model.
        - Anthropic NOT configured → fall back to DashScope + tier1_fallback_model.
    - Otherwise → use DashScope + the configured model (manual deepseek override).
    """
    if configured_model.startswith("claude-"):
        if anthropic_client is not None:
            return anthropic_client, configured_model
        return dashscope_client, tier1_fallback_model
    return dashscope_client, configured_model

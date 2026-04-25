# tests/unit/llm/test_client_selection.py
"""Tests for client_selection helpers."""
from unittest.mock import MagicMock

from news_pipeline.llm.client_selection import is_anthropic_configured, pick_client_and_model


class TestIsAnthropicConfigured:
    def test_empty_string_is_not_configured(self):
        assert is_anthropic_configured("") is False

    def test_replace_me_is_not_configured(self):
        assert is_anthropic_configured("REPLACE_ME") is False

    def test_whitespace_only_is_not_configured(self):
        assert is_anthropic_configured("   ") is False

    def test_real_key_is_configured(self):
        assert is_anthropic_configured("sk-ant-abc123") is True

    def test_replace_me_with_whitespace_is_not_configured(self):
        assert is_anthropic_configured("  REPLACE_ME  ") is False


class TestPickClientAndModel:
    def setup_method(self):
        self.anthropic_client = MagicMock(name="anthropic_client")
        self.dashscope_client = MagicMock(name="dashscope_client")
        self.tier1_model = "deepseek-v3"

    def test_pick_client_returns_anthropic_when_key_set(self):
        """Claude model + Anthropic configured → use Anthropic + configured model."""
        client, model = pick_client_and_model(
            "claude-haiku-4-5-20251001",
            anthropic_client=self.anthropic_client,
            dashscope_client=self.dashscope_client,
            tier1_fallback_model=self.tier1_model,
        )
        assert client is self.anthropic_client
        assert model == "claude-haiku-4-5-20251001"

    def test_pick_client_falls_back_when_key_missing(self):
        """Claude model + Anthropic NOT configured → fall back to DashScope + tier1 model."""
        client, model = pick_client_and_model(
            "claude-haiku-4-5-20251001",
            anthropic_client=None,
            dashscope_client=self.dashscope_client,
            tier1_fallback_model=self.tier1_model,
        )
        assert client is self.dashscope_client
        assert model == "deepseek-v3"

    def test_pick_client_with_explicit_deepseek_uses_dashscope(self):
        """Non-claude model → always DashScope, regardless of Anthropic availability."""
        for anthropic in (self.anthropic_client, None):
            client, model = pick_client_and_model(
                "deepseek-v3",
                anthropic_client=anthropic,
                dashscope_client=self.dashscope_client,
                tier1_fallback_model=self.tier1_model,
            )
            assert client is self.dashscope_client
            assert model == "deepseek-v3"

    def test_pick_client_sonnet_with_anthropic(self):
        """Claude Sonnet + Anthropic configured → use Anthropic."""
        client, model = pick_client_and_model(
            "claude-sonnet-4-6",
            anthropic_client=self.anthropic_client,
            dashscope_client=self.dashscope_client,
            tier1_fallback_model=self.tier1_model,
        )
        assert client is self.anthropic_client
        assert model == "claude-sonnet-4-6"

    def test_pick_client_sonnet_without_anthropic_falls_back(self):
        """Claude Sonnet + no Anthropic → fall back to DashScope + tier1."""
        client, model = pick_client_and_model(
            "claude-sonnet-4-6",
            anthropic_client=None,
            dashscope_client=self.dashscope_client,
            tier1_fallback_model=self.tier1_model,
        )
        assert client is self.dashscope_client
        assert model == "deepseek-v3"

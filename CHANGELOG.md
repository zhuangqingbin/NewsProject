# Changelog

## v0.1.2 (2026-04-25)

### Added
- Tier-2/Tier-3 LLM extractors now auto-fall-back to DashScope (Tier-1 model) when `anthropic_api_key` is not configured. WARN log on startup. Existing behavior preserved when Anthropic IS configured.
- Tier-2 extractor now sets `json_mode=True` (Anthropic ignores it; DashScope uses it for the fallback path).
- New helper `news_pipeline.llm.client_selection.pick_client_and_model` for routing Claude vs DashScope based on availability.

### Changed
- `extractors.py`: All 3 tier extractors gain optional `model_override: str | None = None` parameter (backwards compatible).
- `main.py`: Anthropic client is now optional (`None` when key not configured). Tier-2/3 routing determined at startup via `pick_client_and_model`.

### Tests
- New `tests/unit/llm/test_client_selection.py` (10 tests for `is_anthropic_configured` and `pick_client_and_model`).
- New `tests/unit/llm/test_tier2_dashscope_fallback.py` (2 tests: Tier-2 with DashScope client + `json_mode=True` assertion, backwards-compat without override).
- Total: 174 passed, 2 skipped.

## v0.1.1 (2026-04-25)

4 critical fixes on top of MVP: FeishuBitableClient tenant token, cost tracker concurrency, Telegram MarkdownV2 escaping, shutdown timeout.

## v0.1.0-mvp (2026-04-25)

Initial MVP release. 75 tasks, 12 phases. 9 scrapers, 4-tier LLM pipeline, 3 push platforms, 13-table SQLite, Feishu archive, charts, 11 bot commands, DR backup. See plan + spec docs.

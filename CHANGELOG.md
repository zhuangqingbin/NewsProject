# Changelog

## v0.1.3 (2026-04-25)

### Fixed / Improved
- **I5**: Replace deprecated `datetime.utcnow()` with `utc_now()` in `extractors.py` (Tier-1 and Tier-2 `extracted_at`) and `storage/models.py` (Entity/Relation `created_at` default_factory). Eliminates Python 3.12+ deprecation warnings.
- **I7**: Wrap `runner.shutdown()` in `asyncio.wait_for(timeout=30)` in `main.py`. On timeout, logs `shutdown_timeout` and proceeds to `db.close()` instead of hanging indefinitely.
- **I8**: `BurstSuppressor.should_send()` no longer appends to the bucket when suppressed. Fixes a bug where continuous suppressed attempts extended the window forever, making suppression permanent. Window now naturally releases once entries age out.
- **I10**: Enhanced anti-crawl detection for xueqiu and ths scrapers:
  - xueqiu: raises `AntiCrawlError` on non-JSON `Content-Type` and on `error_code != 0` in JSON payload.
  - ths: raises `AntiCrawlError` on empty body and on pages containing `登录` / `captcha`.
- **I3**: `Tier1Summarizer` now forwards `cache_segments` and `few_shot_examples` from the rendered prompt into `LLMRequest`, matching Tier-2 behaviour. Anthropic prompt caching will activate if Tier-1 model is ever swapped to Claude. (`tier1_summarize.v1.yaml` already had `cache_segments: [system]`.)
- **I4**: `CostTracker` is now thread-safe. Added `threading.Lock` guarding `_daily_total` mutations in `record()` and reads in `today_cost_cny()`.

### Tests
- `test_burst.py`: 2 new cases — window expiry releases suppression, continuous suppressed calls do not extend window (regression for I8 bug).
- `test_xueqiu.py`: 2 new cases — non-JSON content-type, error_code != 0.
- `test_ths.py`: 2 new cases — login page detection, empty body detection.
- `test_cost_tracker.py`: 1 new case — 1000 concurrent `record()` calls via `ThreadPoolExecutor` assert exact total.
- Total: 181 passed, 2 skipped.

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

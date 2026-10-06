# Changelog

## v0.7.0 (2026-10-06)

### Added

- 回看窗口抓取、原文 URL 幂等保存、来源健康/退避、心跳、系统日报与真实源冒烟。
- 事件与文章关联、结构化 Assessment、持久模型调用费用/预算/熔断、事务 Outbox、事件卡片和归纳摘要。
- legacy / shadow / v2 灰度模式，默认 legacy、LLM 关闭；影子新闻不发送，运维报告继续发送。
- 只读 rules/LLM 回放、完整输入响应缓存、人工审核样本导出和 8 个未审核已知案例 seed。
- 60/365 天原文保留、事件与投递保留、影子记录 30 天、LLM 调用 180 天及每月 VACUUM 任务。

### Changed

- 财联社、东财个股、巨潮、SEC 和华尔街见闻抓取使用明确合同与原文证据；失败不伪装成空列表。
- 规则区分主体、提及、人物和排除语境，按主体市场路由；重复、突发与旧闻降级摘要。
- 个股快照默认腾讯（Sina 可切换），东财全市场三次排序请求和板块分页，统一成交量单位与明确涨跌停价/量比。
- 摘要使用市场本地时区，失败不消费；多频道成功后才消费，最终飞书请求体有 20 KB 保护。
- 文档对齐 Docker Compose、`/opt/NewsProject`、配置拆分、备份/回滚与稳定门槛。

### Release gates

- 本条目记录实现变更，不代表生产发布或性能验收已经完成。
- B0 的 150 条人工标注、30 条留出验证和获授权模型 benchmark 尚未完成；8 个 seed 不作为 gold set 验收。
- shadow 需观察 2–3 个交易日；v2 稳定一周后才执行 C1/C2 旧模块/依赖删除（规划 v0.7.1），D 扩源至少等待两周稳定运行。
- 旧 Tier LLM、commands/charts、新闻 watchdog 与兼容配置仍保留；本次不宣称它们已经删除。

## v0.4.0 后已合入变更（未单独打发布 tag）

以下摘要来自 git 提交，不推断对应生产上线日期或补造 v0.5/v0.6 发布记录。

- 2026-06-13（`cf7d3d8`）：Compose 的 quote_watcher 命令改为直接运行 Python，移除运行阶段的 `uv run`。
- 2026-05-12（`35fa201`、`d6190a7`、`0ed6cec`）：配置拆为 common/news_pipeline/quote_watcher，新闻与盯盘使用独立飞书机器人，push secrets 按子系统嵌套。
- 2026-05-12（`40a435d`、`eae0abf`）：CurlError 归类为瞬态错误，Docker 构建下载并发恢复默认 8。
- 2026-05-09（`71e134c`、`c77af27`、`4aa7cfc`）：增加子系统入门/架构文档、MkDocs 导航入口并修复相对链接。

## v0.4.0 (2026-05-09)

本版本由实际 tag `v0.4.0` 和 Plan A/B 提交确认，不表示本次改造已再次上线。

- 增加独立 quote_watcher、Sina 个股快照、tick 缓存、表达式阈值、持仓/组合告警与飞书告警频道。
- 增加全市场扫描、板块异动、日 K 缓存和 MA/RSI/MACD 等指标告警。
- 增加 quotes.db Alembic 基线、alerts.yml watchdog reloader、历史规则预览 CLI 和子系统文档。

## v0.3.0 (2026-04-26)

### Added
- New `rules/` module: pluggable keyword-matching engine (Aho-Corasick default, MatcherProtocol for future extensions)
- `rules.enable` (default true) + `llm.enable` (default false) two-section watchlist
- Rules-only mode: zero LLM cost, < 1ms per article, deterministic matching
- `gray_zone_action`: configurable skip / digest / push for ambiguous cases
- Schema validators: at-least-one-enabled, ticker-unique, sector/macro ref validity
- `synth_enriched_from_rules()` — build EnrichedNews without LLM (body[:200] excerpt)
- `LLMPipeline.process_with_rules()` — skip Tier-0 when rules already classified
- `MessageBuilder.build_from_rules()` — push card with rules badges (tickers, sectors, macros, generic)
- `DispatchRouter.route(markets=...)` — multi-market routing for shared news (e.g., FOMC 影响 A 股)
- Migration script `scripts/migrate_watchlist_v0_3_0.py`
- Pre-flight check: `_word_boundary_ok` treats CJK chars as boundaries so 'FOMC加息' matches FOMC

### Breaking
- `WatchlistFile` schema changed: top-level `us/cn/macro/sectors` → `rules` + `llm` sections
- Old watchlist.yml format rejected at startup; run migration script first
- `WatchlistEntry` removed (replaced by `TickerEntry` with name/aliases/sectors/macro_links)

### Internal
- `ImportanceClassifier` accepts `verdict: RulesVerdict | None`, `gray_zone_action`, `llm_enabled`
- `process_pending` accepts `rules_engine`, `rules_enabled`, `llm_enabled` kwargs (default LLM-only behavior preserved)
- `LLMPipeline.__init__` accepts optional `first_party_sources` set
- Skip signal via `llm_reason='rules-only-grayzone-skip'` (avoids negative score that ScoredNews rejects)

### Performance
- Rules pipeline: ~350 patterns build in < 10ms, match in < 1ms per 1KB article
- Replaces LLM Tier-0 (1-2 seconds + DashScope token cost) for the common case

## v0.2.0 (2026-04-26)

### Added
- Comprehensive mkdocs documentation site under `docs/`
- mkdocs + mkdocs-material in dev deps
- 18 documentation pages organized into getting-started / components / operations / reference
- Mermaid diagrams for architecture, data flow, ER schema
- Glossary

### Notes
- Source code unchanged; this is documentation only
- Existing `docs/superpowers/` and `docs/runbook/` are linked / referenced from new pages

## v0.1.6 (2026-04-26)

### Removed
- Feishu self-built application integration (entire `archive/` module + `pushers/common/feishu_auth.py`)
- Feishu bitable archive (multidim table writeback)
- Feishu image upload via `im/v1/images` (chart embedding in Feishu cards)
- Helper scripts: diagnose_feishu / init_feishu_table / add_app_collaborator
- `lark-oapi` dependency

### Changed
- Feishu push now uses ONLY custom robot webhook + sign secret (no self-built app needed)
- TG sendPhoto for chart embedding still works (keeps `chart_image` field)
- Feishu chart embedding silently dropped (cards never include image)
- secrets.yml schema simplified: no `storage:` section

### Why
Feishu's permission model for self-built apps + bitable is hostile to single-developer
use. After 2+ hours debugging 91403 across 个人云 / 共享空间 / Wiki / advanced perms /
all OAuth scope combinations, decided to wholesale eliminate the surface area.
SQLite remains source of truth; browse via Datasette.

## v0.1.4 (2026-04-25)

### Removed
- WeCom (企业微信) channels — code kept for future re-enablement
- OSS (阿里云对象存储) for chart hosting — charts now embedded inline
- `chart_cache` table (migration 0003)
- `oss2` dependency from pyproject.toml

### Added
- Telegram `sendPhoto` API support for chart embedding (multipart/form-data)
- Feishu image upload via `im/v1/images` API; cards include `img_key` directly
- `news_pipeline.pushers.common.feishu_auth.FeishuTenantAuth` shared helper
  - Handles tenant_access_token caching with expiry tracking + asyncio.Lock
  - Used by both FeishuPusher (image upload) and FeishuBitableClient (archive)
  - Resolves review issue I1

### Changed
- `CommonMessage.chart_image: bytes | None` field (preferred over deprecated `chart_url`)
- `ChartFactory.render_kline()` returns `bytes` instead of OSS URL
- next-steps.md §1.9 rewritten with clearer cookie acquisition workflow
- §1.6 (企微) deleted; sections renumbered; §1.6 repurposed as OSS backup-only

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

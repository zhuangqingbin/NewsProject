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

以下为历史版本记录，不代表当前生产状态或当前默认能力。



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

---

## v0.1.7

Production stabilization. Current deployed version on 8.135.67.243.

---

## v0.1.6 (2026-04-26)

### Removed
- Feishu self-built application integration (entire `archive/` module + `pushers/common/feishu_auth.py`)
- Feishu bitable archive (multidim table writeback)
- Feishu image upload via `im/v1/images`
- `lark-oapi` dependency

### Changed
- Feishu push now uses **only** custom robot webhook + sign secret (no self-built app)
- TG sendPhoto for chart embedding still works
- Feishu chart embedding silently dropped
- `secrets.yml` schema simplified: no `storage:` section

### Why
Feishu's permission model for self-built apps + bitable is hostile to single-developer use.
After 2+ hours debugging error 91403 across all OAuth scope combinations, decided to wholly
eliminate the surface area. SQLite remains source of truth; browse via Datasette.

---

## v0.1.4 (2026-04-25)

### Removed
- WeCom (企业微信) channels
- OSS (阿里云对象存储) for chart hosting — charts now embedded inline
- `chart_cache` table (Alembic migration 0003)
- `oss2` dependency

### Added
- Telegram `sendPhoto` API for chart embedding (multipart/form-data)
- `CommonMessage.chart_image: bytes | None` field

---

## v0.1.3 (2026-04-25)

### Fixed
- Replace deprecated `datetime.utcnow()` with `utc_now()` everywhere
- Wrap `runner.shutdown()` in `asyncio.wait_for(timeout=30)`
- `BurstSuppressor.should_send()` no longer appends on suppressed calls (permanent suppression bug fix)
- Anti-crawl detection for xueqiu (non-JSON content-type, error_code != 0) and ths (empty body, login page)
- `Tier1Summarizer` now forwards `cache_segments` to `LLMRequest`
- `CostTracker` is now thread-safe (threading.Lock)

### Tests
- 181 passed, 2 skipped

---

## v0.1.2 (2026-04-25)

### Added
- Tier-2/Tier-3 auto-fallback to DashScope when `anthropic_api_key` is not configured
- `pick_client_and_model` helper for routing decisions
- WARN log `anthropic_not_configured_fallback_to_tier1` on startup

---

## v0.1.1 (2026-04-25)

4 critical fixes on top of MVP:
- FeishuBitableClient tenant token
- Cost tracker concurrency
- Telegram MarkdownV2 escaping
- Shutdown timeout

---

## v0.1.0-mvp (2026-04-25)

Initial MVP release. 75 tasks, 12 phases.

- 9 scrapers (5 enabled, 4 disabled due to API changes)
- 4-tier LLM pipeline (Tier-0/1/2/3)
- 3 push platforms (Telegram, Feishu, WeCom placeholder)
- 13-table SQLite schema
- Charts (mplfinance inline)
- 11 bot commands
- DR backup

See `docs/superpowers/specs/2026-04-25-news-pipeline-design.md` for original design spec.

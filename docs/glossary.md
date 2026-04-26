# Glossary

News Pipeline 中使用的术语表，按字母/拼音顺序排列。

---

## A

**akshare**
开源财经数据库（Python 包），提供 A 股行情、新闻等接口。本系统用 `ak.stock_news_em(ticker)` 抓取东方财富股票新闻。

**alembic**
Python 数据库迁移工具，与 SQLAlchemy 配合使用。本系统用 `uv run alembic upgrade head` 应用迁移。

**AntiCrawlError**
自定义异常类，在 scraper 检测到反爬信号（HTTP 401/403、非 JSON 响应、登录页等）时抛出。触发 source 暂停 30 分钟 + Bark 告警。

**APScheduler**
`apscheduler` 库，提供 `AsyncIOScheduler`。本系统用 `IntervalTrigger`（周期触发）和 `CronTrigger`（固定时刻触发）管理 13 个 job。

---

## B

**Bark**
iOS 推送应用，提供 HTTPS webhook。本系统作为独立告警通道（当 TG/飞书失效时仍能推到手机）。7 个触发点，15 分钟节流。

**burst suppression（Burst 抑制）**
防刷屏机制。同一 ticker 在 5 分钟滑动窗口内超过 3 条 immediate 推送，后续推送被丢弃（不进 digest）。见 `BurstSuppressor`。

---

## C

**ceiling（成本上限）**
`app.yml → runtime.daily_cost_ceiling_cny`，默认 ¥5/天。超限时 `CostTracker.check_async()` 抛出 `CostCeilingExceeded`，停止 LLM 处理当日文章。

**channel**
一个推送目标通道（如 `tg_us`、`feishu_cn`）。定义在 `channels.yml`，按 market 分组。

**CIK**
SEC 给每家上市公司分配的唯一标识符（Central Index Key）。本系统用于 SEC EDGAR scraper 构建 Atom feed URL。

**CommonMessage**
所有 pusher 共用的消息格式（Pydantic 模型），包含 title、summary、badges、chart_image 等字段。各 pusher 负责渲染为平台特定格式。

---

## D

**DashScope**
阿里云灵积模型服务，提供 DeepSeek-V3 等模型 API。本系统主要 LLM 服务商。

**dead letter（死信）**
处理失败且无法自动恢复的任务，写入 `dead_letter` 表，等待人工审查。分 `auto_retry_kinds`（自动重试）和 `notify_only_kinds`（只通知）。

**Datasette**
开源 SQLite 浏览器，提供 Web UI + SQL 查询界面。本系统用 Docker 在服务器上运行，通过 SSH 隧道远程访问。

**dedup（去重）**
两层去重：URL hash 精确匹配（SHA-1）+ SimHash 模糊标题匹配（汉明距离 ≤ 4）。24 小时窗口。

**DeepSeek-V3**
阿里云 DashScope 上的 DeepSeek 大语言模型。当前系统全程使用（Anthropic 未配置时 fallback）。输入 ¥0.5/M tokens，输出 ¥1.5/M tokens。

**digest**
汇总摘要推送。非 critical 新闻进入 `digest_buffer` 表，每天早晚各一次（A 股 + 美股共 4 次）被 cron job 消费并推送。

**digest_buffer**
存储待汇总新闻的数据库表。`scheduled_digest` 字段决定目标 bucket（`morning_cn`、`evening_us` 等）。

**DispatchRouter**
路由决策器，根据 `is_critical` 决定 immediate（实时）或 digest（汇总）推送，并按 market 分配目标 channels。

---

## E

**EnrichedNews**
Tier-1 或 Tier-2 LLM 提取的结构化结果（Pydantic 模型），包含 summary、event_type、sentiment、magnitude、entities、relations 等字段。

**entity_type**
实体类型枚举：`company`/`person`/`event`/`sector`/`policy`/`product`。

**event_type**
新闻事件类型枚举：`earnings`/`m_and_a`/`policy`/`price_move`/`downgrade`/`upgrade`/`filing`/`other`。

---

## F

**fallback（自动降级）**
当 Anthropic API key 未配置时，Tier-2 和 Tier-3 自动路由到 DashScope + DeepSeek-V3（tier1_model）。启动时打印 WARN 日志 `anthropic_not_configured_fallback_to_tier1`。

**first-party source（一手源）**
直接来自官方渠道的新闻源：`sec_edgar`（SEC 公告）、`juchao`（巨潮公告）、`caixin_telegram`（财联社）。这些源的文章直接路由到 Tier-2，跳过 Tier-0 分类。

**FTS5**
SQLite 内置全文搜索引擎（Full-Text Search version 5）。`news_fts` 虚拟表对 `raw_news` 的 title 和 body 建立全文索引。

---

## H

**hamming（汉明距离）**
两个整数的二进制表示中不同位的数量：`bin(a ^ b).count("1")`。用于 SimHash 相似度判断，距离越小越相似。

---

## I

**immediate（实时推送）**
`DispatchPlan.immediate=True` 时，新闻经过 BurstSuppressor 检查后立即发送到 pusher。对应 `is_critical=True` 的新闻。

**is_critical**
布尔字段（`news_processed.is_critical`），由 `ImportanceClassifier` 判定。`True` → immediate 推送 + 自动生成图表；`False` → digest 缓冲。

---

## L

**LLMJudge**
灰区（[40, 70) 分）时调用的 LLM 判定器，使用 tier1_model（DeepSeek-V3），返回 `(is_critical: bool, reason: str)`。

**LLMPipeline**
LLM 处理主管线，串联 Tier-0 分类 → LLMRouter 路由 → Tier-1/Tier-2 提取，并检查成本上限。

**LLMRouter**
路由决策器（`llm/router.py`），根据 source（一手源?）+ Tier-0 verdict（relevant? watchlist_hit? tier_hint?）决定 skip / tier1 / tier2。

---

## M

**magnitude**
新闻影响力量级枚举：`low`/`medium`/`high`。

**market**
市场标识枚举：`us`（美股）/`cn`（A 股）。用于 scraper 分组、digest 时刻选择、channel 路由。

---

## P

**predicate**
实体关系谓语枚举：`supplies`/`competes_with`/`owns`/`regulates`/`partners_with`/`mentions`。

**prompt cache**
Anthropic prompt caching 功能，将 system prompt 缓存在 Anthropic 服务器上，命中时输入 tokens 打 10% 折扣（节省 90%）。DeepSeek 不支持，无副作用。

**push_log**
记录每次推送操作的数据库表，包含 channel、status、http_status、response 等字段，用于推送失败统计和调试。

---

## R

**RawArticle**
scraper 输出的原始文章对象（Pydantic 模型），字段包括 source、market、url、url_hash、title、title_simhash、body、raw_meta。

**RuleEngine**
规则引擎，对 `EnrichedNews` 评估一组规则，输出 `RuleHit` 列表和总分（0-100）。分数决定是否进入灰区 LLM judge。

---

## S

**safe_event_type / safe_sentiment / safe_magnitude**
宽松枚举 coercion 辅助函数，LLM 返回非法枚举值时 fallback 到安全默认值而非 crash（`OTHER`/`NEUTRAL`/`LOW`）。

**ScoredNews**
`ImportanceClassifier` 的输出（Pydantic 模型），在 `EnrichedNews` 基础上增加 score、is_critical、rule_hits、llm_reason。

**sentiment**
新闻情绪枚举：`bullish`（看多）/`bearish`（看空）/`neutral`（中性）。

**simhash**
SimHash 是一种局部敏感哈希算法，相似文本生成接近的 64-bit 整数。本系统用字符 bigram 作为特征，对中英文均有效。

**source_id**
每个 scraper 的唯一标识符（如 `finnhub`、`sec_edgar`、`caixin_telegram`）。用于 `sources.yml` 配置、`raw_news.source` 字段、日志过滤。

**source_state**
记录每个 scraper 运行状态的数据库表（每源一行），包含 last_fetched_at、error_count、paused_until 等字段。

**structlog**
Python 结构化日志库，输出 JSON 格式。本系统通过 `get_logger(__name__)` 获取 logger，所有日志事件以 `event` 字段标识。

---

## T

**ticker**
股票代码。美股用字母代码（如 `NVDA`、`AAPL`）；A 股用 6 位数字（如 `600519`）。

**tier**
LLM 处理层级：Tier-0（标题分类）→ Tier-1（普通摘要）→ Tier-2（深度实体/关系抽取）→ Tier-3（深度分析，保留）。

**Tier0Verdict**
Tier-0 分类器的输出：`{relevant: bool, tier_hint: str, watchlist_hit: bool, reason: str}`。

---

## U

**url_hash**
`hashlib.sha1(url.encode()).hexdigest()`，40 位十六进制字符串。`raw_news.url_hash` 有 UNIQUE 约束，是第一层去重机制。

**uv**
Astral 开发的 Python 包管理器，极速安装预编译 wheel。本系统用 `uv sync --no-dev` 在生产服务器上安装依赖。

---

## W

**watchlist**
用户关注的股票/资产列表（`config/watchlist.yml`），US（美股）+ CN（A 股）+ macro（宏观事件）+ sectors（行业）。Tier-0 分类时用于检测 `watchlist_hit`，命中后路由到 Tier-2。

**webhook**
HTTP 回调接口。飞书自定义机器人和 Telegram Bot 都支持 webhook 推送消息。本系统的 Telegram webhook server（`commands/server.py`）已实现但未在生产中启用。

---

## 相关

- [Getting Started → Architecture](getting-started/architecture.md)
- [Components → LLM Pipeline](components/llm-pipeline.md)
- [Components → Storage](components/storage.md)

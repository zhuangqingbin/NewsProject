# Config Schema

这一页是 `AppConfig` Pydantic 模型的完整字段表，对应 `config/app.yml`。

---

## AppConfig 顶层结构

```python
class AppConfig:
    runtime: RuntimeCfg           # 运行时参数
    scheduler: SchedulerCfg       # 调度配置
    llm: LLMCfg                  # LLM 模型和 prompt 配置
    classifier: ClassifierCfg     # 重要性分类配置
    dedup: DedupCfg              # 去重配置
    charts: ChartsCfg            # 图表配置
    push: PushCfg                # 推送配置
    dead_letter: DeadLetterCfg   # 死信配置
    retention: RetentionCfg      # 数据保留配置
```

所有模型均使用 `extra="forbid"`（拒绝 YAML 中的未知字段，防止配置错误静默忽略）。

---

## RuntimeCfg

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `daily_cost_ceiling_cny` | float | 5.0 | LLM 日成本上限（CNY），超限停止 LLM 处理 |
| `hot_reload` | bool | true | 是否启用配置文件热加载（watchdog 监听 config/ 目录） |
| `timezone_display` | dict | `{us: ET, cn: CST}` | 日志和消息展示时区（不影响内部计算） |

---

## SchedulerCfg

### ScrapeIntervalsCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `market_hours_interval_sec` | int | 市场时段各 scraper 的默认抓取间隔（秒） |
| `off_hours_interval_sec` | int | 非市场时段间隔（当前未自动切换，所有 source 用固定间隔） |
| `caixin_interval_sec` | int | 财联社专用间隔（最频繁，默认 60s） |

### LLMIntervalCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `process_interval_sec` | int | LLM 处理 pending 文章的轮询间隔（默认 120s） |

### DigestTimesCfg

| 字段 | 格式 | 说明 |
|---|---|---|
| `morning_cn` | `"HH:MM"` | A 股早间 digest 时刻（CST） |
| `evening_cn` | `"HH:MM"` | A 股晚间 digest 时刻（CST） |
| `morning_us` | `"HH:MM"` | 美股早间 digest 时刻（CST） |
| `evening_us` | `"HH:MM"` | 美股晚间 digest 时刻（CST） |

---

## LLMCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `tier0_model` | str | Tier-0 分类模型（如 `deepseek-v3`） |
| `tier1_model` | str | Tier-1 摘要模型（DeepSeek fallback 目标） |
| `tier2_model` | str | Tier-2 深度抽取模型（如 `claude-haiku-4-5-20251001`，无 Anthropic key 时 fallback 到 tier1_model） |
| `tier3_model` | str | Tier-3 深度分析模型（如 `claude-sonnet-4-6`，当前未在主管线使用） |
| `prompt_versions` | dict[str, str] | prompt 版本 pin（`{tier0_classify: v1, ...}`） |
| `enable_prompt_cache` | bool | 是否启用 prompt cache（Anthropic 支持；DeepSeek 不支持，无副作用） |
| `enable_batch` | bool | 批处理模式（预留，当前未完整实现） |

---

## ClassifierCfg

### ClassifierRulesCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `price_move_critical_pct` | float | 价格涨跌幅阈值（预留，规则引擎当前未使用） |
| `sources_always_critical` | list[str] | 这些 source 的文章始终加 30 分（如 `[sec_edgar, juchao]`） |
| `sentiment_high_magnitude_critical` | bool | high magnitude + bullish/bearish → 加 40 分 |

### ClassifierCfg 自身

| 字段 | 类型 | 说明 |
|---|---|---|
| `rules` | ClassifierRulesCfg \| None | 规则配置，None 时使用代码内默认值 |
| `llm_fallback_when_score` | list[float] | 灰区范围 `[lo, hi]`，默认 `[40, 70]`，该区间内调用 LLM judge |

---

## DedupCfg

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `url_strict` | bool | true | 启用 URL hash 精确去重 |
| `title_simhash_distance` | int | 4 | SimHash 汉明距离阈值（≤ 此值视为重复），越小越严格 |

---

## ChartsCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `auto_on_critical` | bool | critical 新闻是否自动生成 K 线图 |
| `auto_on_earnings` | bool | earnings 事件是否自动生成 K 线图 |
| `cache_ttl_days` | int | 图表缓存有效期（预留，当前无 chart_cache 表） |

---

## PushCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `per_channel_rate` | str | 每 channel 速率限制（格式 `"N/min"`，如 `"30/min"`） |
| `same_ticker_burst_window_min` | int | Burst 抑制窗口（分钟） |
| `same_ticker_burst_threshold` | int | 窗口内同 ticker 最多推 N 条 |
| `digest_max_items_per_section` | int | 每次 digest 最多包含 N 条新闻 |

---

## DeadLetterCfg

| 字段 | 类型 | 说明 |
|---|---|---|
| `auto_retry_kinds` | list[str] | 自动重试的失败类型（如 `scrape`、`push_5xx`、`llm_timeout`） |
| `notify_only_kinds` | list[str] | 只通知不自动重试（如 `push_4xx`、`llm_validation`） |
| `weekly_summary_day` | str | 周报发送日（`monday`...`sunday`） |

---

## RetentionCfg

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `raw_news_hot_days` | int | 30 | raw_news 保留天数 |
| `news_processed_hot_days` | int | 365 | news_processed 保留天数 |
| `push_log_days` | int | 90 | push_log 保留天数 |

---

## 其他配置文件 Schema

### WatchlistFile

```python
class WatchlistEntry:
    ticker: str
    alerts: list[str] = []  # 告警类型（预留）

class WatchlistFile:
    us: list[WatchlistEntry] = []
    cn: list[WatchlistEntry] = []
    macro: list[str] = []      # 宏观事件关键词
    sectors: list[str] = []    # 行业关键词
```

### ChannelDef

```python
class ChannelDef:
    type: Literal["telegram", "feishu", "wecom"]
    enabled: bool = True
    market: Literal["us", "cn"]
    rate_limit: str = "30/min"
    options: dict[str, str] = {}   # 平台专用参数（key 名引用 secrets）
```

### SourceDef

```python
class SourceDef:
    enabled: bool = True
    interval_sec: int | None = None  # None → 使用 scheduler.scrape 默认值
    options: dict[str, str] = {}
```

---

## 相关

- [Operations → Configuration](../operations/configuration.md) — 配置文件实例
- [Reference → DB Schema](db-schema.md) — 数据库表结构

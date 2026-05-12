# news_pipeline 子系统

> 财经新闻自动化流水线：抓取 → 去重 → 规则匹配 → LLM 分层摘要 → 推送到飞书。
> 架构全貌见 `docs/architecture.md`(mkdocs 站内 nav 链 "整体架构")。

---

## 1. 它能做什么

- **多源抓取**：14 个新闻源（US + CN），各自独立 interval，互不阻塞
- **去重**：URL hash 严格去重 + simhash 标题模糊去重
- **规则匹配**：AhoCorasick 多模式匹配，支持 ticker / sector / macro 三类命中
- **LLM 分层路由**：Tier-0 分类 → Tier-1 摘要 → Tier-2 深度提取 → Tier-3 深度分析，按重要性按需升级
- **推送**：即时推 / 汇聚摘要 / 死信重试，推到飞书（US / CN 两个频道）

---

## 2. 数据流

```
scrapers(14 源) ─▶ raw_news(DB) ─▶ Dedup ─▶ RulesEngine
                                                │
                         ┌──────────────────────┘
                         │  score + rule_hits
                         ▼
                   LLM Pipeline
                   ├─ Tier-0: classify   (deepseek-v3)
                   ├─ Tier-1: summarize  (deepseek-v3)
                   ├─ Tier-2: extract    (claude-haiku)
                   └─ Tier-3: deep       (claude-sonnet) ← 仅 critical
                         │
                         ▼
                   Classifier ─▶ Router ─▶ Feishu Push
                   (importance)  (market)  (channel 选择)
                         │
                         ▼
                   news_processed(DB) + push_log(DB)
```

**灰度区(gray zone)**：score 在 `[40, 70]` 之间的新闻，由 `app.yml` 的 `gray_zone_action` 决定：`skip` / `digest`（汇总推）/ `push`（立即推）。

---

## 3. 必须的配置文件

### 3.1 `config/secrets.yml`

```yaml
llm:
  dashscope_api_key: sk-xxx       # DeepSeek-V3 必填；anthropic_api_key 留空则 Tier-2/3 降级
push:
  feishu_hook_us: https://...     # 美股频道 webhook URL
  feishu_sign_us: xxx             # 飞书签名(没开签名验证可留空)
  feishu_hook_cn: https://...     # A 股频道
  feishu_sign_cn: xxx
sources:
  finnhub_token: xxx              # 留空则 finnhub scraper 跳过
alert:
  bark_url: https://api.day.app/xxx  # 运维告警(可选)
```

### 3.2 `config/sources.yml`

控制哪些新闻源启用 + 抓取间隔：

| 源 | 市场 | 类型 | 默认 interval |
|---|---|---|---|
| `finnhub` | US | 公司新闻 API | 300s |
| `sec_edgar` | US | 官方公告 | 120s |
| `futu_global` | US/HK/A | 富途快讯 | 180s |
| `wallstreetcn` | US | 华尔街见闻 | 300s |
| `caixin_telegram` | CN | 财联社电报 | 60s |
| `eastmoney_global` | CN | 东财全球财经 | 180s |
| `ths_global` | CN | 同花顺财经直播 | 120s |
| `sina_global` | CN | 新浪财经全球 | 180s |
| `cjzc_em` | CN | 东财财经早餐 | 3600s |
| `cctv_news` | CN | 新闻联播 | 21600s |
| `kr36` | CN | 36氪 RSS | 600s |
| `akshare_news` | CN | 东财个股新闻 | 180s |
| `juchao` | CN | 巨潮官方公告 | 120s |

```yaml
# 关掉一个源：
finnhub: {enabled: false, interval_sec: 300}
```

### 3.3 `config/watchlist.yml`

双段架构：`rules` 段(关键词匹配) + `llm` 段(LLM watchlist)，至少一段 `enable: true`。

```yaml
rules:
  enable: true
  gray_zone_action: digest        # skip / digest / push
  us:
    - ticker: NVDA
      name: NVIDIA
      aliases: [英伟达, Jensen Huang]
      sectors: [semiconductor, ai]
      macro_links: [FOMC, CPI]
  cn:
    - ticker: "600519"
      name: 贵州茅台
      aliases: [茅台]
      sectors: [白酒]
      macro_links: [央行, MLF]
  keyword_list:
    us: [Powell, recession]
    cn: [证监会, 国常会]
  macro_keywords:
    us: [FOMC, CPI, NFP]
    cn: [央行, MLF, LPR]
  sector_keywords:
    us: [semiconductor, ai, ev]
    cn: [新能源, 半导体, 白酒]

llm:
  enable: false                   # 开启后按 LLM watchlist 做额外摘要
  us: [NVDA]
  cn: ["600519"]
```

**注意**：ticker 下的 `sectors` / `macro_links` 必须能在全局 `sector_keywords` / `macro_keywords` 找到，否则启动时报错。

### 3.4 `config/app.yml`

关键字段：

```yaml
llm:
  tier0_model: deepseek-v3         # 分类
  tier1_model: deepseek-v3         # 摘要
  tier2_model: claude-haiku-4-5-20251001  # 深度提取
  tier3_model: claude-sonnet-4-6   # 深度分析
  enable_prompt_cache: true        # 开启 Anthropic prompt cache(节省成本)

scheduler:
  scrape:
    market_hours_interval_sec: 180   # 市场开盘时间抓取间隔
    off_hours_interval_sec: 1800     # 非交易时段

push:
  per_channel_rate: "30/min"       # 每个 channel 限速
  same_ticker_burst_window_min: 5
  same_ticker_burst_threshold: 3   # 5 分钟内同股超过 3 条 → 合并 burst

runtime:
  daily_cost_ceiling_cny: 5.0      # 每日 LLM 成本上限(超过停止 LLM)
```

### 3.5 `config/channels.yml`

news_pipeline 推送到不含 `_alert` 后缀的频道（`feishu_cn` / `feishu_us`）；含 `_alert` 后缀的频道由 quote_watcher 独占。

```yaml
channels:
  feishu_us:
    type: feishu
    market: us
    options: {webhook_key: feishu_hook_us, sign_key: feishu_sign_us}
  feishu_cn:
    type: feishu
    market: cn
    options: {webhook_key: feishu_hook_cn, sign_key: feishu_sign_cn}
  # feishu_cn_alert / feishu_us_alert 由 quote_watcher 使用，news_pipeline 不会路由到这两个频道
```

`webhook_key` / `sign_key` 对应 `secrets.yml` 里的字段名。

---

## 4. 启动

### 4.1 本地

```bash
uv sync
cp config/secrets.yml.example config/secrets.yml && $EDITOR config/secrets.yml
uv run alembic upgrade head          # 初始化 news.db
uv run python -m news_pipeline.main
```

环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_LEVEL` | `INFO` | 日志级别(DEBUG 会打印每条抓取详情) |
| `TZ` | `Asia/Shanghai` | 摘要推送时区 |
| `NEWS_DB` | `data/news.db` | SQLite 数据库路径 |

### 4.2 Docker

```bash
docker compose up -d app
docker compose logs -f app
```

改了 `config/*.yml` 后：`docker compose restart app`（秒级，无需重建镜像）。
改了 `src/*.py` 后：`docker compose up -d --build`。

---

## 5. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 启动即崩溃，报 `watchlist validation error` | `sectors` / `macro_links` 字段引用了不在全局 keyword 表里的值 | 检查 `watchlist.yml`，确保 ticker 的 sectors/macro_links 都在全局列表里 |
| 新闻抓到但不推送 | score 低于阈值，被 skip 或进 digest 队列 | 调低 `gray_zone_action` 阈值，或检查 `push_log` 表的 `status` 字段 |
| LLM 报 `quota exceeded` | DashScope 额度或每日成本上限触发 | 检查 `app.yml` 的 `daily_cost_ceiling_cny`；检查 dashscope 控制台 |
| 推到飞书但格式异常 | 模板渲染问题或 `CommonMessage.kind` 未匹配 | 查 `push_log` 表 + 飞书 webhook 返回 code |
| 某个源没数据 | 源被 disable 或 cookie/token 失效 | 检查 `sources.yml` 的 `enabled`；检查 `secrets.yml` 对应 token |
| 死信队列持续增长 | 网络抖动或 LLM timeout | `dead_letter` 表查看 `kind`；`auto_retry_kinds` 会自动重试 scrape/push_5xx/llm_timeout |

---

## 6. 数据库（news.db）

主要表说明：

| 表名 | 内容 | 关键字段 |
|---|---|---|
| `raw_news` | 所有抓到的原始新闻(未去重前) | `source` / `url_hash` / `title_simhash` / `status` |
| `news_processed` | LLM 处理后的结果 | `summary` / `score` / `is_critical` / `push_status` / `model_used` |
| `push_log` | 每次推送记录 | `channel` / `pushed_at` / `ok` / `response_body` |
| `digest_buffer` | 待汇聚摘要队列 | `market` / `section` / `items` |
| `dead_letter` | 推送/LLM 失败条目 | `kind` / `retry_count` / `payload_summary` |
| `source_state` | 各数据源最后成功抓取时间 | `source` / `last_fetched_at` / `consecutive_errors` |
| `entities` | 实体表(ticker/公司名/别名) | `type` / `ticker` / `market` |
| `daily_metrics` | 每日统计指标 | `date` / `scraped_count` / `pushed_count` / `llm_cost_cny` |

常用查询：
```bash
# 看今天的 LLM 成本
sqlite3 data/news.db "SELECT date, llm_cost_cny FROM daily_metrics ORDER BY date DESC LIMIT 7;"

# 看哪些源出错
sqlite3 data/news.db "SELECT source, consecutive_errors, last_error FROM source_state WHERE consecutive_errors > 0;"
```

---

## 7. 进阶

### 加一个新闻源

参考 `src/news_pipeline/scrapers/cn/` 或 `scrapers/us/` 下的现有实现：
1. 新建 `scrapers/cn/my_source.py`，继承 `scrapers/base.py` 的 `BaseScraper`
2. 在 `scrapers/factory.py` 注册
3. 在 `config/sources.yml` 添加 `my_source: {enabled: true, interval_sec: 300}`

### 调 watchlist rules

编辑 `config/watchlist.yml` 后 `docker compose restart app` 即可热生效（无需重建）。

### 切换 LLM 模型

修改 `config/app.yml` 的 `llm.tier*_model` 字段：
- 成本优先：全部用 `deepseek-v3`
- 质量优先：Tier-2 改用 `claude-sonnet-4-6`
- 零 LLM：`watchlist.yml` 里 `llm.enable: false`，只跑规则匹配

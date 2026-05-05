# Configuration

这一页描述 5 个配置文件的结构、各字段含义，以及哪些改动需要重启、哪些可以热加载。

---

## 5 个配置文件

| 文件 | 用途 | 格式 |
|---|---|---|
| `config/app.yml` | 运行时参数：调度、LLM、去重、推送、保留策略 | YAML |
| `config/watchlist.yml` | 关注的 ticker 列表 + 告警规则 | YAML |
| `config/channels.yml` | 推送通道定义（TG / 飞书） | YAML |
| `config/sources.yml` | 抓取源启用/禁用 + 间隔 | YAML |
| `config/secrets.yml` | API keys / tokens / webhook URLs（gitignored） | YAML |

---

## app.yml — 核心运行参数

```yaml
runtime:
  timezone_display:
    us: America/New_York    # 日志/消息中显示的时区（仅展示）
    cn: Asia/Shanghai
  hot_reload: true          # 是否启用配置文件热加载（watchdog 监听）
  daily_cost_ceiling_cny: 5.0  # LLM 日成本上限（CNY）

scheduler:
  scrape:
    market_hours_interval_sec: 180   # 市场时段抓取间隔（秒）
    off_hours_interval_sec: 1800     # 非市场时段抓取间隔（秒）
    caixin_interval_sec: 60          # 财联社专用间隔
  llm:
    process_interval_sec: 120        # LLM 处理 pending 文章的间隔
  digest:
    morning_cn: "08:30"   # A 股早间 digest（CST）
    evening_cn: "21:00"   # A 股晚间 digest（CST）
    morning_us: "21:00"   # 美股早间 digest（CST，相当于 ET 盘前）
    evening_us: "04:30"   # 美股晚间 digest（CST，相当于 ET 盘后）

llm:
  tier0_model: deepseek-v3
  tier1_model: deepseek-v3
  tier2_model: claude-haiku-4-5-20251001   # 无 Anthropic key 时自动 fallback 到 tier1_model
  tier3_model: claude-sonnet-4-6
  prompt_versions:
    tier0_classify: v1
    tier1_summarize: v1
    tier2_extract: v1
    tier3_deep_analysis: v1
  enable_prompt_cache: true    # Anthropic prompt cache（DeepSeek 不支持，设置无副作用）
  enable_batch: true           # 批处理模式（当前未完整实现）

classifier:
  rules:
    price_move_critical_pct: 5.0                    # 预留字段（规则引擎当前未用）
    sources_always_critical: [sec_edgar, juchao]     # 这些源的文章始终得 30 分
    sentiment_high_magnitude_critical: true          # high magnitude + bullish/bearish → +40 分
  llm_fallback_when_score: [40, 70]                 # 灰区范围 [lo, hi)

dedup:
  url_strict: true
  title_simhash_distance: 4    # 汉明距离阈值（越小越严格）

charts:
  auto_on_critical: true       # critical 新闻自动生成 K 线图
  auto_on_earnings: true       # 财报新闻自动生成 K 线图
  cache_ttl_days: 30           # 预留（当前无 chart_cache）

push:
  per_channel_rate: "30/min"          # 每个 channel 的速率限制
  same_ticker_burst_window_min: 5     # Burst 窗口（分钟）
  same_ticker_burst_threshold: 3      # 窗口内同 ticker 最多推 N 条

dead_letter:
  auto_retry_kinds: [scrape, push_5xx, llm_timeout]
  notify_only_kinds: [push_4xx, llm_validation]
  weekly_summary_day: monday

retention:
  raw_news_hot_days: 30          # raw_news 保留 30 天
  news_processed_hot_days: 365   # news_processed 保留 1 年
  push_log_days: 90
```

---

## watchlist.yml — 关注标的

```yaml
us:
  - {ticker: NVDA, alerts: [price_5pct, earnings, downgrade, sec_filing]}
cn:
  - {ticker: "600519", alerts: [price_5pct, announcement]}
macro: [FOMC, CPI, NFP, 央行, MLF, LPR]
sectors: [semiconductor, ai, ev, 新能源, 半导体, 白酒]
```

- `ticker`：美股用股票代码（如 `NVDA`），A 股用 6 位代码（如 `600519`）
- `alerts`：预留字段，当前 Tier-0 classify 会检测 watchlist 命中，但 alert 类型未精细化处理
- `macro` / `sectors`：宏观事件和行业关键词，传给 Tier-0 分类 prompt

---

## channels.yml — 推送通道

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
```

`options` 中的 `*_key` 字段是 `secrets.yml → push` 中对应字段的键名（间接引用）。

---

## sources.yml — 抓取源

```yaml
sources:
  finnhub:        {enabled: true,  interval_sec: 300}
  sec_edgar:      {enabled: true,  interval_sec: 120}
  caixin_telegram: {enabled: true, interval_sec: 60}
  akshare_news:   {enabled: true,  interval_sec: 180}
  juchao:         {enabled: true,  interval_sec: 120}
  yfinance_news:  {enabled: false, interval_sec: 600}
  xueqiu:         {enabled: false, interval_sec: 300}
  ths:            {enabled: false, interval_sec: 300}
  tushare_news:   {enabled: false, interval_sec: 600}
```

---

## 哪些改动需要重启 vs 热加载

| 改动类型 | 热加载? | 说明 |
|---|---|---|
| `watchlist.yml` 增减 ticker | 是（如果 `hot_reload: true`） | watchdog 检测文件变化后重新加载 |
| `app.yml` 调整 `daily_cost_ceiling_cny` | 是 | 热加载 |
| `app.yml` 调整 scheduler 间隔 | **否** | APScheduler job 在启动时注册，改间隔需重启 |
| `sources.yml` 启用/禁用 source | **否** | scraper registry 在启动时构建 |
| `channels.yml` 增减 channel | **否** | pusher dispatcher 在启动时构建 |
| `secrets.yml` 更换 API key | **否** | secrets 在启动时读取 |
| `prompt_versions` 改版本 | **否** | prompt 在启动时加载 |

重启命令：
```bash
sudo systemctl restart news-pipeline
```

---

## 相关

- [Operations → Secrets](secrets.md) — secrets.yml 字段详解
- [Operations → Daily Ops](daily-ops.md) — 改 watchlist 的快捷方式

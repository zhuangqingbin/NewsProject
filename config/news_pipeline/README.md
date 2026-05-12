# config/news_pipeline — news_pipeline 子系统专用配置

仅 `news_pipeline` 读取；`quote_watcher` 不使用这里的文件。

---

## sources.yml

新闻源开关 + 轮询间隔。

### 字段格式

```yaml
sources:
  <source_id>:
    enabled: true          # bool — false 则完全跳过
    interval_sec: 180      # int — 轮询间隔（秒）；不填则用 app.yml scheduler.scrape 默认值
```

### 现有 14 个源

| source_id | 分类 | 说明 | 默认间隔 |
|---|---|---|---|
| `finnhub` | 美股 | Finnhub 财经新闻（需 `secrets.sources.finnhub_token`） | 300s |
| `sec_edgar` | 美股 | SEC EDGAR 官方公告（8-K / 10-K / 10-Q） | 120s |
| `futu_global` | 美/港/A | 富途快讯（US/HK/A 股混合） | 180s |
| `wallstreetcn` | 全球 | 华尔街见闻 global 频道 | 300s |
| `caixin_telegram` | A 股 | 财联社电报（速度最快，60s） | 60s |
| `eastmoney_global` | A 股 | 东财全球财经快讯 | 180s |
| `ths_global` | A 股 | 同花顺财经直播 | 120s |
| `sina_global` | 全球 | 新浪财经全球要闻 | 180s |
| `cjzc_em` | A 股 | 东财财经早餐（约 1 次 / 天） | 3600s |
| `cctv_news` | A 股 | 新闻联播（1 次 / 天） | 21600s |
| `kr36` | 科技/VC | 36氪 RSS | 600s |
| `akshare_news` | A 股 | 东财个股新闻（watchlist 中的 cn 股逐一拉取） | 180s |
| `juchao` | A 股 | 巨潮官方公告（公告级别最权威） | 120s |
| `yfinance_news` | 美股 | Yahoo Finance 新闻 | — |

### 如何添加新源

1. 在 `src/news_pipeline/scrapers/cn/` 或 `us/` 下新建 `<source_id>.py`，实现 `BaseScraper`
2. 在 `src/news_pipeline/scrapers/factory.py` 的 `build_registry()` 中注册
3. 在此文件中加一行：`<source_id>: {enabled: true, interval_sec: 300}`
4. 若需要 API key，在 `config/common/secrets.yml` 的 `sources` 块中加对应字段

---

## watchlist.yml

关注股/关键词列表。支持 **rules（规则引擎）** 和 **llm（LLM 筛选）** 两段双轨制：

```yaml
rules:
  enable: true                # bool — Aho-Corasick 关键词匹配（免费，速度快，推荐开）
  gray_zone_action: digest    # 灰区新闻处理：digest（汇总推送）/ skip
  matcher: aho_corasick       # 匹配器类型（目前只支持 aho_corasick）
  us: [...]                   # 美股关注列表
  cn: [...]                   # A 股关注列表

llm:
  enable: false               # bool — LLM 智能筛选（需 dashscope_api_key，会产生费用）
  us: [...]
  cn: [...]
  macro: [...]                # 宏观关键词（FOMC/CPI/加息等）
  sectors: [...]              # 行业关键词
```

### 每只股的字段

```yaml
- ticker: NVDA                # 必填 — 股票代码
  name: NVIDIA                # 必填 — 英文全称（用于显示）
  aliases: [英伟达, 老黄家]    # 推荐 — 中英文别名；Aho-Corasick 用这些词匹配新闻正文
  sectors: [semiconductor, ai] # 推荐 — 所属行业；用于匹配行业层面新闻
  macro_links: [FOMC, CPI]    # 选填 — 关联宏观关键词
  alerts: [price_5pct, earnings] # 选填 — 触发告警类型（当前为元数据，未来扩展用）
```

A 股 `market` 字段不用填（由 `quote_watchlist.yml` 管理盯盘用途）。

### 如何加新股

**US 股**：

```yaml
rules:
  us:
    - ticker: AAPL
      name: Apple
      aliases: [苹果, Tim Cook, 库克]
      sectors: [consumer, ai, hardware]
      macro_links: [FOMC, CPI]
```

**A 股**（6 位数字代码加引号）：

```yaml
rules:
  cn:
    - ticker: "600036"
      name: 招商银行
      aliases: [招商银行, 招行]
      sectors: [银行, 金融]
      macro_links: [央行, MLF, LPR]
```

### 详细设计说明

见 `docs/superpowers/specs/2026-04-26-watchlist-rules-design.md`

---

## prompts/

LLM 各 tier 的 prompt 模板目录。**不要随意改动**，字段与 schema 严格绑定。

```
prompts/
├── tier0_classify.v1.yaml       # tier-0：快速新闻分类（重要 / 不重要 / 灰区）
├── tier1_summarize.v1.yaml      # tier-1：摘要 + 实体提取（轻量）
├── tier2_extract.v1.yaml        # tier-2：深度实体抽取（用 Claude Haiku）
└── tier3_deep_analysis.v1.yaml  # tier-3：深度分析（预留）
```

使用的版本由 `app.yml` 的 `llm.prompt_versions` 字段控制。要修改 prompt，请先阅读 `docs/components/llm-pipeline.md`，再新建版本文件（如 `tier1_summarize.v2.yaml`），然后更新 `app.yml` 中对应的版本号。

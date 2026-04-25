# 财经新闻自动抓取 / 摘要 / 推送系统 — 设计文档

- **作者**：qingbin
- **日期**：2026-04-25
- **状态**：Draft (brainstorming approved, awaiting plan)
- **目标读者**：实施者（你 + 协作 LLM）
- **参考会话**：本设计经过 `superpowers:brainstorming` 流程逐节确认

---

## 0. 概述

### 0.1 一句话目标

把美股 + A 股的财经新闻**实时抓取、智能摘要、按重要度分级推送**到 Telegram / 飞书 / 企业微信三平台，并在飞书多维表格中自动归档以供复盘和二次分析。

### 0.2 范围

**MVP 范围（一次性交付，不分期）**：
- 多源抓取（美股 5 源、A 股 6 源）
- LLM 三层路由摘要（粗筛 + 摘要 + 深度抽取）
- 实体 + 关系抽取（关系数据按图论建模，预留 Neo4j 迁移路径）
- 三平台并行推送（含格式自适应）
- 飞书多维表格归档
- 按需图表生成（K 线 + 财报 + 情绪曲线）
- 双向命令交互（watchlist 管理、深度分析触发等）
- 配置驱动 + 热加载
- 死信队列 + Bark 告警

**显式不做**：
- 多用户隔离（仅自用）
- 实时图数据库（关系按图建模存关系表，迁移留接口）
- A/B 提示词框架（仅版本化）
- K8s / 消息队列（不需要这种规模）
- ELK / APM（结构化日志足够）

### 0.3 关键决策摘要

| 维度 | 决策 |
|---|---|
| 部署形态 | 阿里云轻量服务器 2c2g + Docker Compose 单容器 |
| 主语言 | Python 3.12 + asyncio |
| 调度 | APScheduler (进程内) |
| 主存储 | SQLite (WAL 模式) + 飞书多维表格 (归档/UI) |
| 文件存储 | 阿里云 OSS (图表图片) |
| LLM 路由 | DeepSeek-V3 (粗筛+摘要) → Claude Haiku 4.5 (深度抽取) → Sonnet 4.6 (手动深读) |
| 推送平台 | Telegram + 飞书 + 企业微信 (美股、A 股各一组共 6 个 channel) |
| 推送节奏 | 重大事件实时 + 早晚两次 digest |
| 告警 | Bark (iOS 推送, 独立链路) |
| 月成本预算 | LLM ¥30-100 + 服务器 ¥60 + OSS ≈¥1 |

---

## 1. 系统总览 + 数据流

### 1.1 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│  阿里云 轻量服务器 2c2g  /  单 Docker 容器                             │
│                                                                       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────┐  │
│  │ Scrapers    │──►│ Dedup +     │──►│ LLM Pipeline│──►│ Router  │  │
│  │ (US + CN)   │   │ Normalize   │   │ (DS / Haiku)│   │ (重大?) │  │
│  └─────────────┘   └─────────────┘   └─────────────┘   └────┬────┘  │
│         ▲                  │                  │              │       │
│         │           ┌──────▼──────┐           │       ┌──────▼─────┐ │
│         │           │  SQLite     │◄──────────┘       │  Pushers   │ │
│  ┌──────┴──────┐    │  主存储      │                   │  (TG/飞书/ │ │
│  │ APScheduler │    │             │                   │   企微)    │ │
│  │  调度        │    └──────┬──────┘                   └──────┬─────┘ │
│  └─────────────┘           │                                 │       │
│                            ▼                                 ▼       │
│                    ┌──────────────┐                 ┌────────────────┐│
│                    │ 飞书多维表格  │                 │ Chart Renderer ││
│                    │  归档(双写)  │                 │ (按需触发)      ││
│                    └──────────────┘                 └───────┬────────┘│
│                                                             │        │
│                                                     ┌───────▼──────┐ │
│                                                     │ 阿里云 OSS    │ │
│                                                     │ (图片托管)    │ │
│                                                     └──────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

外部依赖：
  阿里云 DashScope (DeepSeek-V3, Qwen)  |  Anthropic API (Claude Haiku 4.5 / Sonnet 4.6)
  Telegram Bot API  |  飞书自定义机器人 Webhook  |  企微群机器人 Webhook
  飞书多维表格 OpenAPI  |  阿里云 OSS SDK
  Bark Webhook (告警)
```

### 1.2 主数据流（一条新闻的一生）

```
[t=0]    Scheduler 触发某源轮询
[t=0.1s] Scraper 拉到 N 条新闻
[t=0.2s] Dedup: url_hash + title_simhash 去重
[t=0.3s] Normalize: 标准化 schema → RawArticle
[t=0.4s] 写入 SQLite raw_news, status=pending
[t=0.5s] LLM Pipeline 拉 pending → Tier-0 (DeepSeek) 标题分类
         ├─ relevant=False → 跳过, 仅入库
         └─ relevant=True  → Tier-1 (DeepSeek) 摘要 OR Tier-2 (Haiku) 深度抽取
[t=2s]   Tier-2 输出: {summary, related_tickers, event_type, sentiment,
                       magnitude, confidence, key_quotes, entities, relations}
[t=2.5s] Classifier: 规则 + LLM 兜底 → 算 score, 标 is_critical
[t=3s]   Router: 重大事件 → immediate; 普通事件 → digest_buffer
[t=3.5s] Pusher 三平台并行推送（异步 gather）
         ├─ Telegram: MarkdownV2 + InlineButton
         ├─ 飞书:    Card JSON + Action
         └─ 企微:    Markdown + 行内链接
[t=4s]   Archive Writer (异步) 写飞书多维表格一行
[t=4.5s] (可选) 重大事件触发 Chart Renderer → 上传 OSS → 第二条消息附图推送
```

### 1.3 调度时刻表

| 任务 | 频率 | 备注 |
|---|---|---|
| 抓取美股源（开市时段，ET 09:30-16:00 + 盘前盘后） | 5 min | |
| 抓取美股源（休市时段） | 30 min | |
| 抓取 A 股源（开市时段，CST 09:30-15:00） | 3 min | |
| 抓取 A 股源（休市时段） | 30 min | |
| 财联社电报抓取 | 1 min | 该源高频，不能漏 |
| 巨潮 / SEC EDGAR 公告 | 2 min | 一手公告时效要求高 |
| LLM 处理待处理队列 | 2 min | 滚动消费 |
| 推送 immediate 队列 | 实时（事件驱动） | |
| 推送早盘 digest | 每天 08:30 (CN) / 21:00 (CN, ≈US 盘前) | |
| 推送收盘 digest | 每天 15:30 (CN) / 04:30 (CN, US 收盘) | |
| 数据库 vacuum + 老数据归档 | 每周日凌晨 | 30 天前 raw_news 移到 OSS jsonl |
| 配置文件热加载检查 | 1 min (mtime check) | 改 YAML 不需重启 |
| SQLite 全量备份到 OSS | 每天 03:00 | 保留 30 天 |
| 周报推送（飞书） | 每周日 08:00 | 自动指标汇总 |

### 1.4 关键设计决策

1. **SQLite 是单一事实源**：所有业务查询/重试/统计都打 SQLite。飞书表格是"二级索引/UI 浏览"，写失败不影响主链路（异步 + 失败入死信）。
2. **OSS 是图片唯一托管点**：避免在数据库塞二进制；图片 30 天生命周期自动清。
3. **配置驱动 + 热加载**：watchlist、阈值、推送渠道都走 YAML，监听 mtime 变化，改文件不需重启。
4. **时区**：所有时间戳内部用 UTC，展示层按市场转时区（美股 ET，A 股 CST）。

---

## 2. 模块划分 + 接口契约

### 2.1 包结构

```
news_pipeline/
├── config/                 # YAML 加载 + Pydantic 校验 + 热加载
│   ├── loader.py
│   └── schema.py
├── scrapers/               # 抓取层（每个源一个文件）
│   ├── base.py            # ScraperProtocol
│   ├── common/            # http session, UA 池, 限流器, cookie 管理
│   ├── us/                # finnhub, sec_edgar, yfinance_news
│   └── cn/                # caixin_tel, akshare_news, xueqiu, ths, juchao, tushare_news
├── dedup/                  # url_hash 强去重 + simhash 弱去重
│   └── dedup.py
├── llm/                    # 模型路由 + 提示词 + 结构化抽取
│   ├── router.py          # DeepSeek vs Claude 路由
│   ├── prompts/           # 版本化提示词 (yaml)
│   ├── extractors.py      # pydantic 输出 schema
│   └── clients/           # dashscope.py, anthropic.py
├── classifier/             # 重大度判定（规则 + LLM 兜底）
│   ├── rules.py
│   ├── llm_judge.py
│   └── importance.py
├── router/                 # 决策：immediate vs digest, 哪些渠道
│   └── routes.py
├── pushers/                # 推送适配（每平台一个）
│   ├── base.py            # PusherProtocol
│   ├── common/            # 重试, 限流, CommonMessage 中间表示
│   ├── telegram.py
│   ├── feishu.py
│   └── wecom.py
├── charts/                 # 按需绘图
│   ├── kline.py           # mplfinance K线 + 新闻标记
│   ├── bars.py            # 财报/数据柱状
│   ├── sentiment.py       # 情绪曲线
│   └── uploader.py        # OSS 上传 + 公网 URL
├── archive/                # 飞书多维表格写入
│   ├── feishu_table.py
│   └── schema.py
├── storage/                # SQLite 层 (SQLModel + Alembic)
│   ├── models.py
│   ├── dao/
│   └── migrations/
├── scheduler/              # APScheduler 包装 + 任务定义
│   └── jobs.py
├── observability/          # logger, metrics, alert (Bark)
│   ├── log.py
│   └── alert.py
├── commands/               # 双向命令处理（TG/飞书 webhook）
│   └── handlers.py
├── common/                 # utils, time, hashing
└── main.py                 # 进程入口

tests/                     # 镜像源码结构
docker/                    # Dockerfile, compose.yml
config/                    # 实例配置 (gitignored secrets.yml + 公开 watchlist.yml 等)
docs/                      # 设计文档 + ADR
```

### 2.2 模块责任表

| 模块 | 单一职责 | 输入 | 输出 | 关键依赖 |
|---|---|---|---|---|
| config | 加载、校验、热加载 YAML | 文件路径 | `AppConfig`(pydantic) | pydantic, watchdog |
| scrapers | 把"某源在某时段的新内容"拉成 `RawArticle[]` | source 名 + 上次水位 | `list[RawArticle]` | httpx/playwright, feedparser, akshare, tushare, yfinance |
| dedup | 判断 RawArticle 是否新 | RawArticle + DB | bool | simhash, sqlite |
| llm.extractors | 摘要 + 抽实体/情绪/事件类型 | RawArticle | EnrichedNews | dashscope, anthropic SDK |
| llm.router | 选模型（标题级 → DS / 重大 → Claude） | RawArticle + tier | LLM 客户端实例 | — |
| classifier | 算重大度分数 + 是否触发 immediate | EnrichedNews + 配置 | ScoredNews | — |
| router | 决定推送哪些渠道 / 立即 vs digest | ScoredNews | list[DispatchPlan] | — |
| pushers.* | 把 CommonMessage 渲染成对应平台格式并发出 | CommonMessage + ChannelConfig | SendResult | httpx |
| charts | 按需出图 → 上传 OSS → 返回 URL | ChartRequest | ChartResult (URL) | mplfinance, matplotlib, oss2 |
| archive | 异步双写飞书多维表格 | EnrichedNews | 写入结果 | lark-oapi |
| storage | 持久化 + 查询 | ORM 调用 | ORM 对象 | SQLModel, Alembic |
| scheduler | 注册定时任务 + 触发 | 配置 | (副作用) | APScheduler |
| observability | 结构化日志 + 失败告警 | log/event | (副作用) | structlog, bark |
| commands | 处理 TG/飞书 入站命令 | webhook event | 命令响应 | python-telegram-bot, lark-oapi |

### 2.3 核心数据契约（pydantic）

```python
# common/contracts.py — 模块间协议

class RawArticle(BaseModel):
    source: SourceId
    market: Market                # "us" | "cn"
    fetched_at: datetime          # UTC
    published_at: datetime        # UTC
    url: HttpUrl
    url_hash: str                 # sha1(url)
    title: str
    body: str | None
    raw_meta: dict

class EnrichedNews(BaseModel):
    raw_id: int
    summary: str                  # 100-300 字
    related_tickers: list[str]
    sectors: list[str]
    event_type: EventType
    sentiment: Literal["bullish", "bearish", "neutral"]
    magnitude: Literal["low", "medium", "high"]
    confidence: float             # 0-1
    key_quotes: list[str]
    entities: list[Entity]        # 命名实体（图谱预留）
    relations: list[Relation]     # 实体间关系（图谱预留）
    model_used: str
    extracted_at: datetime

class ScoredNews(BaseModel):
    enriched: EnrichedNews
    score: float                  # 0-100 重大度
    is_critical: bool
    rule_hits: list[str]
    llm_reason: str | None

class CommonMessage(BaseModel):
    """平台无关消息中间表示"""
    title: str
    summary: str
    source_label: str
    source_url: HttpUrl
    badges: list[Badge]           # tickers, sentiment, event_type emoji
    chart_url: HttpUrl | None
    deeplinks: list[Deeplink]     # [(label, url)]
    market: Market

class DispatchPlan(BaseModel):
    message: CommonMessage
    channels: list[ChannelId]
    immediate: bool
```

### 2.4 边界设计原则

1. **插件化抓取源**：`ScraperProtocol` 只要求实现 `async def fetch(since: datetime) -> list[RawArticle]`。新增源 = 新增文件 + 注册到 source registry，不动其他模块。
2. **插件化推送平台**：`PusherProtocol` 只要求 `async def send(msg: CommonMessage, cfg: ChannelConfig) -> SendResult`。
3. **实体/关系字段为图谱预留**：MVP 存进 SQLite 的 entities/relations 表，但字段语义按 RDF 三元组建模，将来 `migrate_to_neo4j.py` 可一键导出。
4. **CommonMessage 是平台无关的**：渲染成各平台原生格式在各 pusher 内部完成，不支持的能力自动降级。
5. **archive 是异步的**：飞书表格 API 偶尔抽风，主链路不能等它，失败入死信重试 24 小时。

---

## 3. 数据模型

### 3.1 SQLite Schema（13 张表）

#### 业务核心 4 表

```sql
-- ① 原始新闻（去重后入库，处理前的事实）
CREATE TABLE raw_news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    market        TEXT NOT NULL,
    url           TEXT NOT NULL,
    url_hash      TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    title_simhash INTEGER NOT NULL,
    body          TEXT,
    raw_meta      TEXT,
    fetched_at    TIMESTAMP NOT NULL,
    published_at  TIMESTAMP NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    error         TEXT
);
CREATE INDEX idx_raw_status_pub ON raw_news(status, published_at);
CREATE INDEX idx_raw_market_pub ON raw_news(market, published_at);
CREATE INDEX idx_raw_simhash    ON raw_news(title_simhash);

-- ② 处理后新闻（LLM 抽取结果 + 评分）
CREATE TABLE news_processed (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id          INTEGER NOT NULL UNIQUE REFERENCES raw_news(id),
    summary         TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    sentiment       TEXT NOT NULL,
    magnitude       TEXT NOT NULL,
    confidence      REAL NOT NULL,
    key_quotes      TEXT,
    score           REAL NOT NULL,
    is_critical     INTEGER NOT NULL,
    rule_hits       TEXT,
    llm_reason      TEXT,
    model_used      TEXT NOT NULL,
    extracted_at    TIMESTAMP NOT NULL,
    push_status     TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX idx_proc_critical_extracted ON news_processed(is_critical, extracted_at);
CREATE INDEX idx_proc_push_status        ON news_processed(push_status, extracted_at);

-- ③ 全文搜索（FTS5，中英混合）
CREATE VIRTUAL TABLE news_fts USING fts5(
    title, summary, content='news_processed', content_rowid='id',
    tokenize='unicode61'
);
-- 触发器同步增删改
```

#### 图谱预留 3 表

```sql
-- ④ 实体（公司/人物/事件/板块/政策）
CREATE TABLE entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,    -- company|person|event|sector|policy|product
    name        TEXT NOT NULL,
    ticker      TEXT,
    market      TEXT,
    aliases     TEXT,             -- JSON
    metadata    TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_ent_type_name ON entities(type, name);
CREATE INDEX idx_ent_ticker           ON entities(ticker) WHERE ticker IS NOT NULL;

-- ⑤ 新闻 ↔ 实体（M:N，含角色和显著性）
CREATE TABLE news_entities (
    news_id     INTEGER NOT NULL REFERENCES news_processed(id),
    entity_id   INTEGER NOT NULL REFERENCES entities(id),
    role        TEXT NOT NULL,    -- subject|object|mentioned
    salience    REAL NOT NULL,    -- 0-1
    PRIMARY KEY (news_id, entity_id, role)
);
CREATE INDEX idx_ne_entity ON news_entities(entity_id, news_id);

-- ⑥ 实体间关系（RDF 三元组）
CREATE TABLE relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id      INTEGER NOT NULL REFERENCES entities(id),
    predicate       TEXT NOT NULL,  -- supplies|competes_with|owns|regulates|...
    object_id       INTEGER NOT NULL REFERENCES entities(id),
    source_news_id  INTEGER NOT NULL REFERENCES news_processed(id),
    confidence      REAL NOT NULL,
    valid_from      DATE,
    valid_until     DATE,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_rel_subject ON relations(subject_id, predicate);
CREATE INDEX idx_rel_object  ON relations(object_id, predicate);
```

> **图谱迁移路径**：上述 3 表（entities + news_entities + relations）即图模型。`migrate_to_neo4j.py` 把 entity 行 → 节点、relations 行 → 边、news_entities 行 → MENTIONED_IN 边。业务代码零改动。

#### 运维 / 状态 6 表

```sql
-- ⑦ 抓取源水位（增量拉取 + 反爬暂停）
CREATE TABLE source_state (
    source           TEXT PRIMARY KEY,
    last_fetched_at  TIMESTAMP,
    last_seen_url    TEXT,
    last_error       TEXT,
    error_count      INTEGER DEFAULT 0,
    paused_until     TIMESTAMP
);

-- ⑧ 推送日志（调试 + 审计）
CREATE TABLE push_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id      INTEGER NOT NULL REFERENCES news_processed(id),
    channel      TEXT NOT NULL,
    sent_at      TIMESTAMP NOT NULL,
    status       TEXT NOT NULL,
    http_status  INTEGER,
    response     TEXT,
    retries      INTEGER DEFAULT 0
);
CREATE INDEX idx_pushlog_news ON push_log(news_id);
CREATE INDEX idx_pushlog_sent ON push_log(sent_at);

-- ⑨ digest 缓冲池
CREATE TABLE digest_buffer (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id           INTEGER NOT NULL UNIQUE REFERENCES news_processed(id),
    market            TEXT NOT NULL,
    scheduled_digest  TEXT NOT NULL,
    added_at          TIMESTAMP NOT NULL,
    consumed_at       TIMESTAMP
);
CREATE INDEX idx_digest_pending ON digest_buffer(scheduled_digest, consumed_at);

-- ⑩ 死信队列
CREATE TABLE dead_letter (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,   -- scrape|llm|classify|push|archive|chart
    payload     TEXT NOT NULL,
    error       TEXT NOT NULL,
    retries     INTEGER NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    resolved_at TIMESTAMP
);

-- ⑪ 图表缓存
CREATE TABLE chart_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_hash  TEXT NOT NULL UNIQUE,
    ticker        TEXT NOT NULL,
    kind          TEXT NOT NULL,
    oss_url       TEXT NOT NULL,
    generated_at  TIMESTAMP NOT NULL,
    expires_at    TIMESTAMP NOT NULL
);

-- ⑫ 审计日志
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT,
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TIMESTAMP NOT NULL
);

-- ⑬ 指标（每日聚合，用于周报）
CREATE TABLE daily_metrics (
    metric_date     DATE NOT NULL,
    metric_name     TEXT NOT NULL,
    metric_value    REAL NOT NULL,
    dimensions      TEXT,            -- JSON
    PRIMARY KEY (metric_date, metric_name, dimensions)
);
```

### 3.2 飞书多维表格 Schema（归档/浏览层）

单表，每条新闻一行。表头：

| 字段 | 类型 | 说明 |
|---|---|---|
| news_id | 数字 | SQLite news_processed.id（外键） |
| published_at | 日期 | 北京时间 |
| market | 单选 | 美股 / A股 |
| source | 单选 | 财联社 / Finnhub / SEC / ... |
| tickers | 多选 | 关联股票 |
| event_type | 单选 | 财报/M&A/政策/异动/... |
| sentiment | 单选（带颜色） | 🟢看涨 / 🔴看跌 / ⚪中性 |
| magnitude | 单选 | 高/中/低 |
| score | 数字 | 重大度 0-100 |
| is_critical | 复选 | 是否实时推过 |
| title | 文本 | |
| summary | 长文本 | LLM 摘要 |
| key_quotes | 长文本 | 关键引述 |
| url | URL | 原文链接 |
| chart_url | URL（带预览） | 可选附图 |
| sent_to | 多选 | TG / 飞书 / 企微 |
| my_note | 长文本 | 手工标注 |
| my_action | 单选 | 已读/已操作/忽略/待跟踪 |

### 3.3 数据保留策略

| 表 | 热数据 | 冷归档 | 何时清 |
|---|---|---|---|
| raw_news | 30 天 | 压缩 jsonl 上传 OSS | 每周日凌晨 |
| news_processed | 1 年 | jsonl → OSS | 季度任务 |
| news_fts | 跟随 news_processed | — | 触发器 |
| entities | 永久 | — | 不清 |
| relations | 永久 | — | 不清 |
| push_log | 90 天 | — | 每周清理 |
| dead_letter | resolved 后 30 天清；未 resolved 永留 | — | 每周清理 |
| chart_cache | 30 天（OSS 同时过期） | — | 自动 |
| digest_buffer | consumed 后立即清 | — | 实时 |
| audit_log | 1 年 | — | 年度 |
| daily_metrics | 永久 | — | 不清（轻量） |

预估单文件大小：< 500 MB/年（含 raw_news；冷归档后核心 < 100 MB）。

### 3.4 关键查询示例

```sql
-- "NVDA 过去一周所有看跌新闻"
SELECT n.summary, n.published_at, r.url
FROM news_processed n
JOIN raw_news r ON r.id = n.raw_id
JOIN news_entities ne ON ne.news_id = n.id
JOIN entities e ON e.id = ne.entity_id
WHERE e.ticker = 'NVDA'
  AND n.sentiment = 'bearish'
  AND n.extracted_at > datetime('now', '-7 days');

-- "找出 NVDA 的所有上下游关系"
SELECT e1.name AS subject, r.predicate, e2.name AS object, r.confidence
FROM relations r
JOIN entities e1 ON e1.id = r.subject_id
JOIN entities e2 ON e2.id = r.object_id
WHERE e1.ticker = 'NVDA' OR e2.ticker = 'NVDA';

-- "全文搜索旧新闻"
SELECT * FROM news_fts WHERE news_fts MATCH '出口管制 OR export control';
```

### 3.5 关键设计决策

1. `url_hash` UNIQUE 是强去重；`title_simhash` 是弱去重（汉明距离 ≤ 4 视为重复）。
2. raw_news 与 news_processed 拆开：处理逻辑可重跑（重写 prompt 后批量重处理），原始数据不丢。
3. entities 用 (type, name) 唯一；公司同名异源（"英伟达" / "NVIDIA"）通过 aliases 字段 + entity_aliases.yml 归一化。
4. relations.source_news_id 必填：每条关系都有出处，可追溯、可置信度衰减。
5. digest_buffer 用独立表而非 status 字段：方便定时任务原子消费（select + update + delete in transaction），避免漏推。
6. OSS 不进 DB：chart_url 直接存 OSS 公网 URL；图片本身在 OSS。
7. **entities / news_entities / relations 仅由 Tier-2 填充**：Tier-1 普通摘要不抽实体/关系（成本考虑）。这意味着图谱视图自然只覆盖"重大新闻"网络——这是有意设计：图谱关注的本来就是值得追踪的事件，不是噪音。

---

## 4. LLM Pipeline

### 4.1 三层模型路由

```
                    ┌──────────────────────────────────────┐
                    │  raw_news 入站 (每条)                 │
                    └──────────────┬───────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │ Tier-0: Title Classifier (DeepSeek-V3)            │
        │ 输入: 标题 + ticker + source                       │
        │ 输出: {relevant, tier_hint, watchlist_hit}         │
        │ ~100 tokens, ¥0.0001/条                            │
        └──────────────┬───────────────────────────────────┘
                       │
              ┌────────┴────────┐
              │ relevant=False  │── skip (仅入库, 不入 LLM)
              │                 │
              │ relevant=True   │
              ▼                 ▼
   ┌─────────────────────┐ ┌────────────────────────────────┐
   │ Tier-1: Summarizer   │ │ Tier-2: Deep Extractor         │
   │ DeepSeek-V3          │ │ Claude Haiku 4.5               │
   │ 摘要 + 情绪 + 板块    │ │ 上述全部 + 实体抽取 + 关系     │
   │ ¥0.005/条            │ │ + 关键引述 (含 cache: ¥0.05/条) │
   └──────┬───────────────┘ └────────┬───────────────────────┘
          │                          │
          │ 普通新闻                 │ 重大新闻（规则命中 / Tier-0 hint）
          ▼                          ▼
                classifier (rules + LLM 兜底) → ScoredNews

         ┌────────────────────────────────────────┐
         │ Tier-3: Sonnet 4.6 (兜底/手动触发)      │
         │ - confidence < 0.6 escalate             │
         │ - /deep <news_id> 命令触发              │
         │ ¥0.3-1/条, 不走自动                     │
         └────────────────────────────────────────┘
```

### 4.2 路由决策表

| 条件 | 走哪一层 |
|---|---|
| 标题包含 watchlist ticker / 关键词 | Tier-0 → Tier-2 |
| 来自一手源（SEC, 巨潮, 财联社） | Tier-0 → Tier-2（强制） |
| 来自二手源 + 不命中 watchlist | Tier-0 → Tier-1 |
| Tier-0 标记 relevant=False | 丢弃 LLM，仅 raw_news 入库 |
| Tier-2 confidence < 0.6 | manual_review 队列（飞书表格标黄） |
| 用户 `/deep <id>` | Tier-3 |

### 4.3 月成本估算

前提：watchlist 50 只 + 宏观源；日均 raw_news ~800 条；DashScope DeepSeek-V3 `¥0.5/M in, ¥1.5/M out`；Anthropic Haiku 4.5 `$1/M in, $5/M out`，prompt cache 命中后输入降至 $0.10/M。

| 层 | 日调用 | 输入 tok | 输出 tok | 月成本（CNY） |
|---|---|---|---|---|
| Tier-0 (DS) | 800 | 100 | 30 | ¥2.3 |
| Tier-1 (DS) | 300 | 1500 | 300 | ¥10.8 |
| Tier-2 (Haiku, 缓存) | 50 | 2000 | 500 | ¥30 |
| Tier-3 (Sonnet, 手动) | 10/月 | 5000 | 1500 | ¥4 |
| **合计** | | | | **≈ ¥47/月** |

**硬上限熔断**：`daily_cost_ceiling_cny: 5.0`，超过立即停 LLM + Bark 告警，仅继续抓取入库；次日恢复。

### 4.4 提示词管理（版本化，不做 A/B）

```
prompts/
├── tier0_classify.v3.yaml
├── tier1_summarize.v5.yaml
├── tier2_extract.v7.yaml
└── tier3_deep_analysis.v2.yaml
```

每个 prompt 文件结构：

```yaml
name: tier2_extract
version: 7
model_target: claude-haiku-4-5-20251001
description: "深度抽取重大新闻的实体、关系、关键引述"
cache_segments: [system, few_shot_examples]   # Anthropic prompt cache

system: |
  你是金融新闻深度分析助手...
  输出严格遵守 JSON Schema。

output_schema: !include schemas/enriched_news.schema.json

few_shot_examples:
  - input: "..."
    output: { ... }

user_template: |
  ## 新闻
  来源: {source}
  时间: {published_at}
  标题: {title}
  正文: {body}

  ## 上下文（最近相关新闻）
  {recent_context}

  ## 任务
  按 schema 输出 JSON。

guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
  fallback_model: deepseek-v3
```

**版本管理规则**：
- prompt 改动必须升 version
- 代码显式 pin 版本：`PROMPTS["tier2_extract"] = "v7"`
- 升级前必须跑 eval（50 条 gold 集），新版指标不优于老版禁止上线

### 4.5 结构化输出与校验

```python
async def tier2_extract(article: RawArticle, context: list[EnrichedNews]) -> EnrichedNews:
    prompt = render(PROMPTS["tier2_extract"]["v7"], article=article, context=context)

    response = await claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        system=prompt.system,                              # cache_control
        messages=[{"role":"user","content":prompt.user}],
        tools=[{"name":"emit","input_schema":SCHEMA}],     # 强制 JSON 输出
        tool_choice={"type":"tool","name":"emit"},
        max_tokens=1000,
    )

    raw_json = response.content[0].input
    try:
        return EnrichedNews.model_validate(raw_json)
    except ValidationError as e:
        return await retry_with_error(article, prompt, e)  # 1 次重试
    # 还失败 → dead_letter("llm", payload, error)
```

关键技巧：
- **Anthropic 用 tool use** 而非 JSON mode（更稳，几乎 100% 合 schema）
- **DeepSeek 走 OpenAI-compatible JSON mode**（DashScope 兼容 `response_format={"type":"json_object"}`）
- Pydantic 二次校验
- 失败只重试 1 次，避免恶性循环烧钱

### 4.6 Prompt Cache 与 Batch

- **Anthropic Prompt Cache**：system + few-shot 打 `cache_control: {type:"ephemeral"}`，5 min TTL，命中输入降至 1/10
- **Batch API**：digest 提前 30 min 跑 batch，**便宜 50%**；is_critical 走同步实时

### 4.7 失败模式与降级链

| 失败 | 重试 | 降级 |
|---|---|---|
| 429 / 5xx | 指数退避 (2/4/8s + jitter), 3 次 | 入死信(自动重跑) |
| 4xx (非 429) | 不重试 | 立即死信(只通知) |
| Timeout (>30s) | 1 次, timeout=60s | 死信(自动重跑) |
| JSON schema 校验失败 | 1 次（错误塞回 prompt） | 死信(只通知) |
| Anthropic 整体不可用 | 跳过 | 降级 DeepSeek 跑 Tier-2 |
| DeepSeek 整体不可用 | 跳过 | 降级 Qwen-Plus（DashScope 内） |
| 月度成本超限 | 立即停 | 仅抓取入库, 次日恢复 |

### 4.8 关键设计决策

1. **Tier-0 是省钱核心**：99% 噪音在这层滤掉。Tier-0 误杀的兜底：来自 SEC/巨潮的全部公告无视分类直接走 Tier-2。
2. **关系抽取放 Tier-2 不放 Tier-1**：Tier-1 抽实体可以，关系（"NVDA supplies TSM"）质量飘忽，留给 Haiku。
3. **Confidence 是 LLM 自评**：用作 manual_review 触发器，不用作硬阈值丢弃。
4. **不依赖单一供应商**：DeepSeek + Claude 都不可用时降到 Qwen-Plus，至少摘要能跑。

---

## 5. Push & Rendering

### 5.1 渠道矩阵

```
                   ┌── tg_us       ── @你的美股 TG bot
                   ├── feishu_us   ── 飞书"美股新闻"机器人
        市场=US ───┼── wecom_us    ── 企微"美股新闻"群机器人
                   │
                   ├── tg_cn       ── @你的A股 TG bot
        市场=CN ───┼── feishu_cn   ── 飞书"A股新闻"机器人
                   └── wecom_cn    ── 企微"A股新闻"群机器人

        归档（不算"推送"）── feishu_archive_us / feishu_archive_cn
        告警（系统问题）── bark_alert
```

每个 channel 是一段独立配置，可单独 enable/disable。

### 5.2 渲染管线

```
ScoredNews → MessageBuilder → CommonMessage (平台无关)
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
   TelegramRenderer            FeishuRenderer              WecomRenderer
   (MarkdownV2 + Buttons)      (Card JSON + Action)        (Markdown 受限)
        │                            │                            │
        ▼                            ▼                            ▼
     Telegram API              飞书机器人 webhook            企微群机器人 webhook
```

Renderer 内部职责：
- 转义平台特殊字符
- 把 badges 渲染成视觉元素
- 不支持的能力自动降级（企微无按钮 → 行内链接）

### 5.3 消息样式

#### 实时推送（重大新闻）

**Telegram**:
```
🔴 NVDA -8% 盘后异动 ⚡

📌 *出口管制升级 — H100 销往中国受阻*
来源: Reuters · 2026-04-25 22:30 EST

> "新规将 H100/H800 列入实体清单，TSMC 同步暂停代工"

📊 影响: #半导体 #出口管制 #bearish [高]
🔗 关联: TSM ASML AMD

[原文]  [Yahoo Finance]  [📈 看 K 线]  [深度分析]
```

**飞书 Card**:
```
🔴 重大: NVDA 盘后 -8%
出口管制升级，H100 销往中国受阻
来源：Reuters | 2026-04-25 22:30 EST

[摘要框]
新规将 H100/H800 列入实体清单...

🏷  #半导体 #bearish #高
📊 关联标的: NVDA · TSM · ASML · AMD

[📰 原文]  [📈 K线]  [🔍 深度]  [✓ 已读]
```

**企微（受限）**:
```
🔴 **NVDA -8% 盘后**
**出口管制升级 — H100 销往中国受阻**

> 新规将 H100/H800 列入实体清单...

📊 #半导体 #bearish #高 | 关联: NVDA · TSM · ASML

[原文](url1) | [K线](url2) | [深度](url3)
```

#### Digest 推送（早晚总结，飞书 Card 折叠列表）

```
📋 美股早盘简报 · 2026-04-26 08:30 北京

重大事件 (3)
─────────────
🔴 NVDA -8%, 出口管制升级 [详情▼]
🟢 TSLA Q1 营收超预期 +5% [详情▼]
⚪ FOMC 维持利率不变 [详情▼]

行业/板块 (5)
─────────────
半导体: 整体回调 -3.2%
AI: Microsoft 宣布新合作
...

[打开归档表查看全部 23 条]
```

### 5.4 图表触发

| 场景 | 自动 | 用什么图 |
|---|---|---|
| 重大异动（涨跌 > 5%） | ✅ | K 线 + 新闻标记点（30 天） |
| 财报新闻 | ✅ | 财报数据柱状图（4 季度营收/利润） |
| Digest 总结 | ❌ | — |
| `/chart NVDA 1y` | ✅ | K 线 1 年 |
| `/sentiment NVDA 7d` | ✅ | 情绪曲线 7 天 |
| `/heatmap semiconductor` | ✅ | 板块热力图 |

生成与缓存：
```
ChartRequest → chart_cache 查 (30 天有效)
                ├─ 命中 → 返回 OSS URL
                └─ 未命中 → mplfinance 渲染 → OSS 上传 → 写 cache → URL
```

降级：
- OSS 上传失败 → base64 内嵌（飞书/TG 支持，企微跳过）
- 行情数据拉不到 → 跳过附图，文字推送照常

### 5.5 双向命令（Telegram + 飞书）

| 命令 | 用途 |
|---|---|
| `/watch NVDA` | 加自选股（写 watchlist.yml + 热加载） |
| `/unwatch NVDA` | 移除自选 |
| `/list` | 看当前 watchlist |
| `/chart NVDA [window]` | 出 K 线 |
| `/sentiment NVDA [days]` | 情绪曲线 |
| `/news NVDA` | 该股最近 10 条新闻 |
| `/deep <news_id>` | Tier-3 深度分析 |
| `/digest now` | 立即出一次 digest |
| `/health` | 系统健康检查 |
| `/cost` | 本月 LLM 消耗 |
| `/pause [source]` | 暂停某源 |

### 5.6 节流 / 防刷屏

| 规则 | 阈值 | 行为 |
|---|---|---|
| 单 channel 推送 | 30 条/分钟 | 排队（TG 官方限制） |
| 同 ticker 短时连推 | 5 min 内 ≥ 3 条 | 折叠为"NVDA 5min 3 连发" |
| 同事件多源 | 已识别为同事件（关系表） | 仅推首条，后续合并 thread |
| Digest 太长 | > 30 条 | 分两条推（重大 + 一般） |

### 5.7 关键设计决策

1. CommonMessage 真·平台无关，平台特定能力差异在 Renderer 内降级
2. 三平台同步并行 `asyncio.gather`，单失败不阻塞其他
3. 图表是异步附加：文字消息先发，图片后追发
4. 命令 MVP 实现 5 个核心（watch/list/chart/news/digest），其他 Phase 2 加
5. 企微作为穷人版兜底：不支持的能力静默降级

---

## 6. 配置 + 部署 + 监控 + 测试 + 运维

### 6.1 配置文件布局

```
config/
├── app.yml              # 主配置                          → 提交 git
├── watchlist.yml        # 自选股 + 板块订阅                → 提交 git
├── channels.yml         # 推送渠道开关 + 路由              → 提交 git
├── prompts/             # LLM 提示词 (版本化)              → 提交 git
├── entity_aliases.yml   # 实体归一化字典                   → 提交 git
├── sources.yml          # 各抓取源开关 + 限频              → 提交 git
└── secrets.yml          # API key / token / 密钥           → ❌ gitignored
```

#### `app.yml` 完整示例

```yaml
runtime:
  timezone_display:
    us: America/New_York
    cn: Asia/Shanghai
  hot_reload: true
  daily_cost_ceiling_cny: 5.0

scheduler:
  scrape:
    market_hours_interval_sec: 180
    off_hours_interval_sec: 1800
    caixin_interval_sec: 60
  llm:
    process_interval_sec: 120
  digest:
    morning_cn: "08:30"
    evening_cn: "21:00"
    morning_us: "21:00"
    evening_us: "04:30"

llm:
  tier0_model: deepseek-v3
  tier1_model: deepseek-v3
  tier2_model: claude-haiku-4-5-20251001
  tier3_model: claude-sonnet-4-6
  prompt_versions:
    tier0_classify: v3
    tier1_summarize: v5
    tier2_extract: v7
  enable_prompt_cache: true
  enable_batch: true

classifier:
  rules:
    price_move_critical_pct: 5.0
    sources_always_critical: [sec_edgar, juchao]
    sentiment_high_magnitude_critical: true
  llm_fallback_when_score: [40, 70]

dedup:
  url_strict: true
  title_simhash_distance: 4

charts:
  auto_on_critical: true
  auto_on_earnings: true
  cache_ttl_days: 30

push:
  per_channel_rate: "30/min"
  same_ticker_burst_window_min: 5
  same_ticker_burst_threshold: 3
  digest_max_items_per_section: 30

dead_letter:
  auto_retry_kinds: [scrape, push_5xx, llm_timeout]
  notify_only_kinds: [push_4xx, llm_validation]
  weekly_summary_day: monday

retention:
  raw_news_hot_days: 30
  news_processed_hot_days: 365
  push_log_days: 90
```

#### `watchlist.yml` 示例

```yaml
us:
  - {ticker: NVDA, alerts: [price_5pct, earnings, downgrade, sec_filing]}
  - {ticker: TSLA, alerts: [price_5pct, earnings, fda_news]}
  macro: [FOMC, CPI, NFP, jobless_claims]
  sectors: [semiconductor, ai, ev]
cn:
  - {ticker: "600519", alerts: [price_5pct, announcement]}
  - {ticker: "300750", alerts: [price_5pct, announcement]}
  macro: [央行, MLF, LPR, PMI]
  sectors: [新能源, 半导体, 白酒]
```

#### `secrets.yml` 示例（结构）

```yaml
llm:
  dashscope_api_key: sk-xxx
  anthropic_api_key: sk-ant-xxx
push:
  tg_bot_token_us: xxx
  tg_chat_id_us: xxx
  tg_bot_token_cn: xxx
  tg_chat_id_cn: xxx
  feishu_hook_us: https://...
  feishu_sign_us: xxx
  feishu_hook_cn: https://...
  feishu_sign_cn: xxx
  wecom_hook_us: https://...
  wecom_hook_cn: https://...
storage:
  feishu_app_id: cli_xxx
  feishu_app_secret: xxx
  feishu_table_us: tbl_xxx
  feishu_table_cn: tbl_xxx
oss:
  endpoint: oss-cn-hangzhou.aliyuncs.com
  bucket: news-charts
  access_key_id: LTAI...
  access_key_secret: xxx
sources:
  finnhub_token: xxx
  tushare_token: xxx
  xueqiu_cookie: xxx
  ths_cookie: xxx
alert:
  bark_url: https://api.day.app/xxxxx
```

**Secrets 规则**：
- `secrets.yml` 仅本地和服务器各一份，永不提交 git，文件权限 600
- `secrets.yml.example` 提交 git 当模板
- 后续可升级到阿里云 KMS / Vault；MVP 用文件足够

### 6.2 Docker Compose 部署

#### Dockerfile（multi-stage）

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY config/ ./config/
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "news_pipeline.main"]
```

#### compose.yml

```yaml
services:
  news_pipeline:
    build: .
    container_name: news_pipeline
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./config:/app/config:ro
      - ./secrets/secrets.yml:/app/config/secrets.yml:ro
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
      - LOG_LEVEL=INFO
    healthcheck:
      test: ["CMD", "python", "-m", "news_pipeline.healthcheck"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 1.5G
          cpus: '1.5'
```

#### 部署 / 升级流程

```bash
# 初次
ssh user@server
git clone <repo> /opt/news_pipeline && cd $_
cp config/secrets.yml.example secrets/secrets.yml && vim secrets/secrets.yml
docker compose up -d

# 升级（无停机）
git pull && docker compose build && docker compose up -d
```

### 6.3 监控 + 告警

#### 结构化日志

```python
log.info("scrape_done", source="finnhub", market="us",
         items_new=12, items_dup=43, duration_ms=1840)
log.error("llm_failed", model="claude-haiku-4-5", news_id=8842,
          error="timeout", retries=3)
```

JSON 行输出到 `logs/app.jsonl` + stdout，logrotate 每天切，保留 14 天。

#### 健康检查（每 5 min）

```python
checks = {
    "sqlite_writable":      try insert/delete in audit_log,
    "scrape_recent_15min":  raw_news 最近 15 min 有新数据,
    "llm_recent_30min":     news_processed 最近 30 min 有新数据,
    "push_recent_critical": 最近 critical news 有 push_log,
    "disk_free_gt_500MB":   df check,
    "dead_letter_unresolved_lt_50": count check,
    "today_cost_lt_ceiling": llm_cost.today() < 5,
}
```

任一 fail → Bark 告警（15 min 节流）。

#### 关键指标（写 daily_metrics 表）

| 指标 | 用途 |
|---|---|
| 每日 scrape 成功率（按源） | 反爬预警 |
| 每日 LLM 成本（按 tier） | 成本控制 |
| 每日 push 成功率（按 channel） | 渠道质量 |
| 每日 dead_letter 新增数 | 健康趋势 |
| 每日 critical news 数 | 业务反馈 |
| confidence 均值（按 event_type） | prompt 质量监控 |

每周日 08:00 → 飞书周报机器人自动发卡片。

#### Bark 告警策略

| 事件 | 等级 | 节流 |
|---|---|---|
| 健康检查失败 | 紧急 | 15 min 一次 |
| 反爬触发暂停 | 警告 | 1 小时一次 |
| 成本接近 ceiling 80% | 警告 | 一天一次 |
| 死信周报 | 信息 | 每周日 |
| 推送 4xx 反复失败 | 警告 | 半小时一次 |

### 6.4 测试策略

```
tests/
├── unit/                     # 纯函数 / 数据契约 / 渲染（~60）
├── integration/              # 真依赖 (sqlite, mock LLM) (~15)
├── eval/                     # LLM 输出质量 (50 条 gold)
└── live/                     # 真实外部 API (RUN_LIVE=1 gate)
```

**关键测试点**：
- pipeline_e2e：mock 一个源 → 走完去重/LLM(mock)/分类/路由/推送(mock) → 断言 SQLite 状态 + 推送队列正确
- renderer 快照测试：CommonMessage → 各平台 → 字符串快照对比，防格式回归
- schema 校验：所有 YAML 必须能被 pydantic 加载通过（CI 卡）
- eval 集：每改 prompt 跑一次，新版必须 ≥ 老版 F1

### 6.5 错误处理矩阵

| 模块 | 错误 | 处理 |
|---|---|---|
| scraper | 5xx / timeout | 退避重试 3 次 → 死信(自动重跑) |
| scraper | 反爬 (403) | 暂停该源 30 min + 告警 |
| scraper | parse 失败 | 死信(只通知) + 该条跳过 |
| dedup | simhash 异常 | 降级仅 url_hash + 告警 |
| llm | 429 / 5xx | 退避重试 3 次 → 死信(自动重跑) |
| llm | 4xx | 死信(只通知) |
| llm | schema 校验失败 | 重试 1 次 → 死信(只通知) |
| llm | 月成本超限 | 停 LLM + Bark + 仅入库 |
| classifier | 规则文件解析错误 | 沿用上次内存中规则 + 告警 |
| router | channel disabled | 跳过 |
| pusher | 401 / 403 | 死信(只通知, 通常 token 失效) |
| pusher | 429 | 入限流队列后台慢慢发 |
| pusher | 5xx | 重试 2 次 → 死信(自动重跑) |
| archive | 飞书 API 任意失败 | 死信(自动重跑 24h) |
| chart | 数据源失败 | 跳过附图, 文字照常 |
| chart | OSS 上传失败 | 降级 base64（企微跳过） |
| scheduler | job 异常 | APScheduler isolation, 不影响其他 |

### 6.6 备份与灾难恢复

| 资产 | 备份策略 |
|---|---|
| `data/news.db` (SQLite) | 每日 03:00 dump → OSS, 保留 30 天 |
| `secrets.yml` | 你本地 + 服务器 + 密码管理器三处 |
| `config/*` | git 版本控制 |
| `logs/` | 不备份, 14 天本地轮转 |
| 飞书表格 | 飞书自带版本历史 |
| OSS 图片 | 30 天生命周期自动清, 不备份 |

**DR**：服务器挂 → 新开轻量 + git clone + secrets + OSS 备份恢复 SQLite + `docker compose up`，**< 30 min 恢复**。SQLite 损坏 → 切前一天 OSS 备份，最多丢 1 天数据（且 raw_news 可重抓）。

### 6.7 本地开发工作流

```bash
# 一次性
uv sync
cp config/secrets.yml.example config/secrets.yml && vim $_
uv run alembic upgrade head

# 日常
uv run python -m news_pipeline.main --once
uv run python -m news_pipeline.cli scrape --source finnhub --dry
uv run pytest tests/unit
uv run pytest tests/integration
RUN_LIVE=1 uv run pytest tests/live

# 部署前
uv run pytest && uv run ruff check && uv run mypy src/
docker compose -f docker/compose.yml build
```

### 6.8 关键运维决策

1. 单容器单进程：不上 K8s，不上消息队列。健康检查 + restart=unless-stopped 兜底。
2. 配置全 YAML：除 secrets 外都进 git。改配置 = git commit，可追溯可回滚。
3. Bark 是唯一告警通道：避免推送系统挂了告警也发不出（独立链路）。
4. eval 集是 prompt 质量护城河：没有 eval 改 prompt 就是赌博。
5. 不上 APM/Tracing：个人项目过度。结构化 JSON 日志 + 周报指标够用。
6. OSS 备份 > 本地快照：服务器整体被回收的概率 > 数据库自己坏的概率。

---

## 7. 实施路线（高层）

> 详细任务和顺序由 writing-plans 阶段产出。这里只列大块，方便审视范围。

| 阶段 | 大块工作 | 验收 |
|---|---|---|
| **Foundation** | 仓库脚手架 + uv + ruff + mypy + pytest + docker + Alembic 初始 schema + config loader | `uv run pytest && docker compose up -d` 能起 |
| **Storage** | 13 表迁移 + DAO + dead_letter + audit_log | 所有表 CRUD 单测通过 |
| **Scrapers** | base + common + 美股 3 源 + A 股 5 源 + source_state 增量 + cookie/UA 池 | 每源 fetch 单测通过；本地能拉到真实数据 |
| **LLM Pipeline** | clients + router + 4 个 prompt + structured extractor + cost tracker + cache + batch | mock LLM 跑通 e2e；真 API smoke 通过 |
| **Classifier + Router** | 规则引擎 + LLM 兜底 + digest_buffer + immediate 路由 | 单测覆盖各类规则；e2e mock 通过 |
| **Pushers** | CommonMessage + 三平台 renderer + 节流 + 重试 | 三平台 smoke 各发一条 |
| **Charts** | mplfinance K线/bars/sentiment + OSS uploader + cache | `/chart NVDA` 能出图 |
| **Archive** | 飞书表格 schema + writer + 异步重试 | 写真表能看到行 |
| **Commands** | TG webhook + 飞书事件订阅 + 5 个核心命令 | 各命令真机调通 |
| **Observability** | structlog + healthcheck + daily_metrics 聚合 + 周报 + Bark | 健康检查全绿；Bark 收得到 |
| **DR / Backup** | 每日 OSS dump + 恢复脚本 | 模拟恢复演练通过 |
| **Eval Set** | 50 条 gold + 评测脚本 + CI 集成 | F1 ≥ 设定基线 |

---

## 8. 已知风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 雪球/财联社反爬升级 | 中 | 数据缺失 | UA/Cookie 轮换 + 失败暂停 + 多源冗余 |
| LLM 月成本暴涨（误判突发） | 低 | ¥300+ | daily ceiling 熔断 + 周成本告警 |
| 飞书表格写入瓶颈（速率） | 中 | 归档延迟 | 异步 + 批量写 + 队列控速 |
| Telegram 在国内访问中断 | 低 | TG 推送失败 | 飞书 + 企微作为冗余通道 |
| SQLite 单文件损坏 | 极低 | 数据丢失 | 每日 OSS 备份；WAL 模式 |
| 阿里云轻量服务器被回收 | 低 | 服务中断 | DR 流程 < 30 min；定期演练 |
| Cookie 过期（雪球/同花顺） | 高 | 该源数据缺失 | 监控 401/403 比例 + 告警 + 手动续 |
| Prompt 改动质量回退 | 中 | 摘要变差 | eval 集卡线，不达标禁上线 |

---

## 9. 显式不做（YAGNI 边界）

为避免范围蔓延，以下功能 **MVP 明确不做**，未来按需求决定是否纳入：

- 多用户隔离 / 账号体系
- Web 前端 / 仪表板（用飞书表格替代）
- 实时图数据库（Neo4j）—— 仅保留迁移路径
- A/B 提示词框架
- K8s / 消息队列（Kafka/Redis Stream）
- ELK / Prometheus / Grafana / APM
- 邮件推送通道
- 自动交易 / 触发下单
- 基本面财务数据深度分析（仅财报新闻摘要，不做 DCF 之类）
- 自定义订阅（其他用户可订阅你的关注组合）

---

## 附录 A — 词汇表

| 术语 | 含义 |
|---|---|
| RawArticle | 抓取后未处理的新闻 dataclass |
| EnrichedNews | LLM 抽取后的结构化新闻 |
| ScoredNews | 加上重大度评分后 |
| CommonMessage | 平台无关的推送消息中间表示 |
| DispatchPlan | 路由后决定送往哪些 channel 的计划 |
| critical / immediate | 重大事件，立即推送（不等 digest） |
| digest | 早晚定时简报（聚合普通事件） |
| Tier-0/1/2/3 | LLM 路由的四层（粗筛/摘要/深抽/手动深读） |
| 死信 (dead letter) | 反复失败、需要人工或定时重试的任务 |
| simhash | 局部敏感哈希，用于近重复检测 |
| watchlist | 自选股 + 关注板块 + 宏观订阅 |

## 附录 B — 配置驱动的扩展点

**新增抓取源**：
1. `scrapers/<market>/<source>.py` 实现 `ScraperProtocol`
2. `sources.yml` 加一段配置
3. `secrets.yml` 加 token（如有）

**新增推送平台**：
1. `pushers/<platform>.py` 实现 `PusherProtocol`
2. `channels.yml` 加 channel 定义
3. `secrets.yml` 加 webhook/token

**新增图表类型**：
1. `charts/<kind>.py` 实现 render 函数
2. `commands/handlers.py` 加新命令
3. （可选）触发规则配进 `app.yml charts:` 段

**升级 LLM 模型**：
1. `llm/clients/` 加新 client（如换供应商）
2. `app.yml llm:` 段改 model 字段
3. prompts 文件改 `model_target`
4. 跑 eval 验证质量


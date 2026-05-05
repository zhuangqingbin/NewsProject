# Architecture

这一页展示系统整体架构、数据流（一条新闻的一生），以及 7 个核心模块速览。

---

## 整体架构图

```mermaid
graph TB
    subgraph Sources["数据源层"]
        FH[Finnhub<br/>美股新闻]
        SE[SEC EDGAR<br/>美股公告]
        CX[财联社电报<br/>一手财经]
        AK[AkShare<br/>东财股票新闻]
        JC[巨潮<br/>A 股公告]
        D1[雪球 / 同花顺<br/>已暂停]
    end

    subgraph Ingest["采集层"]
        SC[ScraperRegistry<br/>9 个 Scraper]
        DD[Dedup<br/>URL hash + SimHash]
        RN[(raw_news)]
    end

    subgraph Process["处理层"]
        T0[Tier-0<br/>标题分类]
        LR[LLMRouter<br/>路由决策]
        T1[Tier-1<br/>摘要]
        T2[Tier-2<br/>深度抽取]
        IC[ImportanceClassifier<br/>规则 + LLM judge]
        NP[(news_processed)]
    end

    subgraph Dispatch["推送层"]
        DR[DispatchRouter<br/>immediate / digest]
        BS[BurstSuppressor<br/>防同 ticker 刷屏]
        DB[(digest_buffer)]
        PD[PusherDispatcher]
        FS[飞书 Webhook]
    end

    subgraph Observe["观测层"]
        CT[CostTracker<br/>¥5/天上限]
        BK[Bark iOS]
        DS[Datasette<br/>SQLite 浏览]
        LOG[structlog JSON]
    end

    Sources --> SC
    SC --> DD
    DD -->|is_new| RN
    RN -->|pending| T0
    T0 --> LR
    LR -->|skip| RN
    LR -->|tier1| T1
    LR -->|tier2| T2
    T1 --> IC
    T2 --> IC
    IC --> NP
    NP -->|is_critical=true| DR
    DR -->|immediate| BS
    BS --> PD
    DR -->|digest| DB
    DB -->|cron 4x/day| PD
    PD --> FS
    CT -.->|80% warn / 100% stop| BK
    NP -.-> DS
```

---

## 数据流：一条新闻的一生

```mermaid
sequenceDiagram
    participant S as Scraper
    participant D as Dedup
    participant T0 as Tier-0 LLM
    participant LR as LLMRouter
    participant T2 as Tier-2 LLM
    participant IC as Classifier
    participant DR as DispatchRouter
    participant FS as 飞书

    S->>D: RawArticle(url, title, body)
    D->>D: url_hash 精确匹配?
    alt 已存在
        D-->>S: is_new=False (丢弃)
    else 新文章
        D->>D: simhash 汉明距离 ≤ 4?
        alt 相似标题
            D-->>S: is_new=False (丢弃)
        else 真正新文章
            D->>D: INSERT raw_news (status=pending)
            Note over D: 等待 process_pending 轮询 (120s)
            D->>T0: classify(title, watchlist)
            T0-->>LR: Tier0Verdict(relevant, watchlist_hit, tier_hint)
            LR->>LR: 一手源? → tier2<br/>watchlist_hit? → tier2<br/>默认 → tier1
            LR->>T2: extract(title, body)
            T2-->>IC: EnrichedNews(entities, sentiment, event_type...)
            IC->>IC: RuleEngine 打分
            alt score ≥ 70
                IC-->>DR: is_critical=True (无需 LLM judge)
            else 40 ≤ score < 70
                IC->>T0: LLM judge 灰区判定
                T0-->>IC: (is_critical, reason)
            else score < 40
                IC-->>DR: is_critical=False
            end
            DR->>DR: is_critical? → immediate<br/>否则 → digest
            alt immediate
                DR->>FS: 实时推送
            else digest
                DR->>DR: 写入 digest_buffer<br/>等待早晚 cron
            end
        end
    end
```

---

## 7 个核心模块速览

| 模块 | 位置 | 职责 |
|---|---|---|
| **Scrapers** | `scrapers/` | 9 个数据源适配器，统一输出 `RawArticle` |
| **Dedup** | `dedup/` | URL hash 精确去重 + SimHash 模糊去重 |
| **LLM Pipeline** | `llm/` | Tier-0/1/2/3 四层 LLM，路由 + 提取 + 成本追踪 |
| **Classifier** | `classifier/` | 规则引擎打分 + LLM judge 灰区兜底，输出 `ScoredNews` |
| **DispatchRouter** | `router/` | 决定 immediate vs digest，按 market 分配 channel |
| **Pushers** | `pushers/` | 飞书 / WeCom 发送器，Burst 抑制，消息格式化 |
| **Storage** | `storage/` | SQLite 13 表，DAOs，Alembic 迁移 |

---

## 调度时序

系统启动后 APScheduler 维护以下 jobs（全部 UTC）：

| Job | 触发方式 | 间隔/时刻 |
|---|---|---|
| `scrape_finnhub` | interval | 每 300 秒 |
| `scrape_sec_edgar` | interval | 每 120 秒 |
| `scrape_caixin_telegram` | interval | 每 60 秒 |
| `scrape_akshare_news` | interval | 每 180 秒 |
| `scrape_juchao` | interval | 每 120 秒 |
| `process_pending` | interval | 每 120 秒 |
| `digest_morning_cn` | cron | 08:30 CST |
| `digest_evening_cn` | cron | 21:00 CST |
| `digest_morning_us` | cron | 21:00 CST (美股盘前) |
| `digest_evening_us` | cron | 04:30 CST (次日，美股盘后) |
| `push_failure_alert` | interval | 每 1800 秒 |
| `bark_heartbeat` | interval | 每 86400 秒 |
| `dlq_weekly_alert` | cron | 周一 08:00 CST |

---

## 相关

- [Components → LLM Pipeline](../components/llm-pipeline.md)
- [Components → Scrapers](../components/scrapers.md)
- [Components → Storage](../components/storage.md)
- [Components → Scheduler](../components/scheduler.md)

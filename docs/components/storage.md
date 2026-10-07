# Storage

两个子系统使用独立 SQLite：新闻 `data/news.db`，盯盘 `data/quotes.db`。Compose 持久挂载整个 `data` 目录；只读 Datasette 浏览新闻库。新闻库使用 WAL、外键和 `synchronous=NORMAL`，时间字段按 UTC 保存。

## 事件与投递表

| 表 | 用途 |
|---|---|
| `raw_news` | 原文、URL 唯一键、来源、发布时间与抓取时间；旧 `status` 和新 `v2_state` 独立 |
| `source_state` | 成功/条目时间、失败计数、健康转换、退避 |
| `events` | 主体事件、来源统计、规则、结构化评估、决策与摘要消费标记 |
| `event_articles` | 原始文章到事件关联；每篇文章只能归属一个事件 |
| `deliveries` | 按事件/期次/频道幂等的持久 outbox、尝试时间、状态、payload |
| `llm_calls` | 每次模型尝试的 token、费用、延迟、结果和 prompt 版本 |
| `daily_metrics` | 日级指标及预算告警去重等运行记录 |

`deliveries.event_ids` 是实际展示集合，`consumed_event_ids` 是成功摘要后要消费的全部预选候选，不能混为同一个计数。消费标记只有所有频道成功后和成功记录在同一事务提交；失败保留候选。

## legacy 表与图谱预留

`news_processed`、`digest_buffer`、`push_log` 已停止写入，历史数据只读保留。`entities`、`news_entities`、`relations`、`audit_log`、`dead_letter` 保留表结构，不作为新管线的知识图谱或死信方案。旧写入 DAO 已删除；本分支没有删表或破坏性迁移。生产发布仍须通过 [C1/C2 稳定门槛](../operations/staged-cleanup.md)。

## 索引与 FTS5 全文搜索

原始 URL 唯一键支持抓取幂等。0005 为 `v2_state IS NULL` 建待处理索引，并为事件决策、投递状态/重试时间和 LLM 费用时间建索引。迁移删除旧 `news_fts` 及其触发器，建立 `events_fts`，通过事件插入、更新、删除触发器维护标题和摘要搜索。

迁移前原始行初始化为 `v2_state='legacy'`；v2 处理只消费自己的状态列。旧 `title_simhash` 列保留，v2 入库写 0。

## 数据保留策略

每天北京时间 04:10 执行以下规则，并保护被事件或旧处理历史引用的原文：

| 数据 | 保留时间 |
|---|---|
| raw `skipped_rules` / `skipped_low` / `duplicate` / `seeded`，且无历史引用 | 60 天；识别旧 `status` 与新 `v2_state` |
| 其余 raw | 365 天；有历史引用时保留原文，避免外键断裂 |
| `events` / `event_articles` | 365 天；先删关联和相关投递，再删事件 |
| `deliveries` | 365 天；`shadow` 30 天 |
| `llm_calls` | 180 天 |

每月 1 日 04:30 在事务之外执行 VACUUM。执行前核对空闲磁盘足以容纳临时数据库。旧 `retention.*_hot_days` 配置已删除；上述保留策略由当前任务实现。

## 备份与 Datasette

WAL 库用 SQLite backup API 生成一致副本；不能仅复制活动 `.db`。部署备份步骤同时保存新闻库、盯盘库、配置和可回滚镜像，见 [部署指南](../getting-started/deployment-current.md)。

Datasette 仅暴露 `127.0.0.1:8001`，远程访问使用 SSH 隧道，不应将含原文与运营数据的库开放公网。

## 重要 SQL 查询

以下查询只读，可在 Datasette 中使用：

```sql
SELECT decision, decision_reason, COUNT(*) AS n
FROM events GROUP BY decision, decision_reason;

SELECT kind, status, COUNT(*) AS n
FROM deliveries GROUP BY kind, status;

SELECT model, prompt_version, SUM(cost_cny) AS cost_cny
FROM llm_calls WHERE created_at >= datetime('now', '-1 day')
GROUP BY model, prompt_version;
```

## 相关

- [事件合并](dedup.md) · [事务投递](dispatch-router.md) · [可观测性](observability.md)

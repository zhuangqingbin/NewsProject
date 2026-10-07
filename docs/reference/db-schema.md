# DB Schema

新闻库为 `data/news.db`，盯盘独立 `data/quotes.db`。实际字段以 `storage/models.py` 与 Alembic migrations 为准。0004 增加来源健康字段，0005 增加独立 v2 状态、事件、证据、投递、费用和事件 FTS。

## raw_news

原始新闻保留 source、market、url/url_hash、title/body/raw_meta、published_at/fetched_at。URL hash 唯一。旧 status 保留历史，新 v2_state 驱动事件处理；迁移前历史行置 legacy，避免补推。v2 停止标题 simhash 判重并写 0，旧列保留。

## source_state

源主键、首次/最近成功、最近条目时间、consecutive_failures、paused_until、health/reason/changed_at。健康转换是持久状态，不以新旧水位线推断上游仍活着。

## events 与 event_articles

events 保存时间、统一标题及特征、主体/标签/市场、文章与来源数、一手/源侧重要度、规则 decision/reason/rank、评估状态和结构化结果、最后决策以及 digest_delivery_id。

event_articles 使用 event_id/raw_id 关联，raw_id 唯一。追加证据的 article_count 用于阻止旧评估覆盖。repeat 合并重归原文而不是复制证据。

## deliveries

kind、event_id、market、channel、payload、status、attempts、attempt_timestamps、next_attempt_at、last_error、created_at/sent_at、digest_slot、event_ids、consumed_event_ids。事件投递 `(kind,event_id,channel)` 唯一，期次投递 `(kind,digest_slot,channel)` 唯一。

pending/sent/failed/expired/shadow/superseded 区分发送状态。shadow 与 legacy_digest/legacy_failed 是保留历史，不由当前 worker 发送。superseded 表示同事件已被旧路径成功发到该频道，不计作 v2 成功。展示 ids 与候选消费 ids 分开；摘要全部频道成功后消费与成功记录同事务提交。

## llm_calls 与 daily_metrics

llm_calls 逐尝试记录 purpose、event_id、模型、prompt 版本、token、费用、耗时、ok/error、时间；日预算按北京时间当日计算。daily_metrics 保存日级维度指标与告警去重记录。

## 历史表与 FTS

news_processed、digest_buffer、push_log 冻结为历史。entities/news_entities/relations/audit_log/dead_letter 保留表结构，旧写入 DAO 已删除，模型和迁移保留。0005 删除 news_fts 与旧触发器，events_fts 用触发器维护 headline/summary。

## 保留与查询

[Storage](../components/storage.md) 说明保留阈值、保护历史引用、事务顺序和 SQL 示例。[部署指南](../getting-started/deployment-current.md) 提供 WAL 一致备份。普通模式回滚不执行 downgrade 或删表。

# Events 与去重

保留 `dedup.md` 页面路径供旧链接使用。新版核心在 `ingest/store.py`、`events/similarity.py`、`events/clusterer.py` 和 `events/sent_cache.py`；旧 `dedup/` 模块暂留兼容，删除等待 v2 稳定一周。

## 第一层：URL Hash 精确匹配

URL hash 是原始新闻的唯一键。相同 URL 不重复写入；不同媒体 URL 是独立证据，不因为相似标题丢掉正文、来源或原文链接。

## 第二层：事件相似度

标题句先去快讯前缀、括号代码、空白与标点，提取字符二元组与关键数字。主体都非空而不相同时不合并。数字都非空且没有交集时，要求 Jaccard ≥ 0.9；一般 Jaccard ≥ 0.6 可合并。同一主体允许数字包含且 Jaccard ≥ 0.3，或标题包含度 ≥ 0.85 的变体。

聚类接受乱序证据，但距事件最近时间不超过 6 小时、整个事件跨度不超过 12 小时。索引保留前两篇和最近六篇的特征。巨潮同主体 high 公告另有 10 分钟、最多 5 份的合并条件。

## 事件与文章

`events` 存储统一标题、主体/标签、来源数、首次/最近时间、规则兜底和评估结果。`event_articles` 关联原始新闻，一篇文章只能归属一个事件。追加更强证据时，未即时推送的事件重新进入待评估；异步评估提交必须检查文章版本，不能用旧响应覆盖新证据。

模型 `novelty=repeat` 只有引用同标的最近 24 小时、最多 8 个有效事件 id 才成立；未知引用被清理。有效 repeat 可把文章重归到已有事件，不再独立推送。

## legacy / shadow / v2

| 模式 | 原始状态与去重 |
|---|---|
| legacy | URL 唯一；标题 simhash 重复仍入库标记；近期已推送事件特征防重复推送 |
| shadow | legacy 使用 `status`；新事件使用 `v2_state`，也处理不同 URL 的重复证据 |
| v2 | 标题 simhash 写 0；保留全部不同 URL 证据，由事件层合并 |

旧推送特征缓存从 `push_log`、`news_processed`、`raw_news` 重建，重启后继续去重。迁移前历史原始行标 `v2_state='legacy'`，防止启动时回放历史消息。

## 相关

- [抓取与保存](scrapers.md) · [规则](rules.md) · [存储](storage.md)
- [部署与灰度](../getting-started/deployment-current.md) · [后续清理](../operations/staged-cleanup.md)

# news_pipeline 子系统

新闻服务从回看窗口抓取原文，URL 幂等保存，规则召回候选。默认 legacy 规则路径、LLM 关闭；shadow/v2 使用事件聚类、可选结构化评估、事务决策、持久 Outbox 和摘要。

## 运行模式

| 模式 | 旧处理 | 新事件路径 |
|---|---|---|
| legacy（默认） | 发新闻与旧摘要 | 不运行 |
| shadow | 继续发送 | 完整计算但新闻/摘要只写 shadow |
| v2 | 不运行 | 实际投递，LLM 关闭/失败时规则兜底 |

系统日报和源冒烟是运维信号，在 shadow 仍发送。两条路径共享原文，分别用 `status` 与 `v2_state`。迁移前历史原文标 legacy，避免启动补推旧消息。

## 配置与存储

- `config/common/app.yml`：模式、LLM、新摘要时区、推送门槛、运维报告。
- `config/common/channels.yml`、`secrets.yml`：非 `_alert` 新闻频道和嵌套密钥。
- `config/news_pipeline/{sources,watchlist,scoring,first_party}.yml`：源、公司别名、评分词、一手分级。
- `data/news.db`：原文、源状态、事件、文章关联、投递与 LLM 调用；旧处理表保留兼容。

改变新闻配置后重启 `app`。旧 Tier-0/1/2/3、watchlist 双层 LLM 与 watchdog 字段不是新默认处理流程；commands/charts 没有被当前 main 启动。删除需通过稳定门槛。

## 入口

- [抓取](../components/scrapers.md) · [规则](../components/rules.md) · [事件](../components/dedup.md)
- [评估与回放](../components/llm-pipeline.md) · [投递与摘要](../components/dispatch-router.md)
- [部署、备份、灰度、回滚](../getting-started/deployment-current.md)
- [一周后的清理清单](../operations/staged-cleanup.md)

# news_pipeline 子系统

v0.7.1 仅支持 v2：回看窗口抓取 → URL 幂等保存 → 规则召回 → 事件聚类 → 可选结构化评估 → 事务决策与 Outbox → 即时卡片或摘要。LLM 默认关闭，跳过或失败时使用规则。

本分支提前完成 C1/C2 开发；发布须先在保留的 v0.7.0 完成 B0、2–3 个交易日 shadow 和一周 v2 稳定观察。legacy/shadow 配置不被本版本接受。

## 配置与存储

- config/common/app.yml：v2、LLM、新摘要时区、推送门槛与运维报告。
- config/common/channels.yml、secrets.yml：新闻频道与嵌套密钥。
- config/news_pipeline/{sources,watchlist,scoring,first_party}.yml：源、别名、评分词与一手分级。
- data/news.db：原文、源状态、事件、文章关联、投递与 LLM 调用。

新闻配置修改后重启 app；新闻不监听 YAML。盯盘 alerts reloader 保留。旧多层 LLM、commands/charts、classifier/router 和 simhash 路径已删除。历史表、旧列与 migrations 0001–0005 保留；旧处理记录停止写入。

## 阅读入口

[抓取](../components/scrapers.md) · [规则](../components/rules.md) · [事件](../components/dedup.md) · [评估](../components/llm-pipeline.md) · [Outbox](../components/dispatch-router.md)

[部署与回滚](../getting-started/deployment-current.md) · [清理记录](../operations/staged-cleanup.md)

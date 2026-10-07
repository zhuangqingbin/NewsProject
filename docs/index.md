# NewsProject

新闻与 A 股盯盘独立运行，共用飞书发送、配置、交易日历和心跳。本分支为 v0.7.1 清理候选：新闻仅支持 v2，LLM 默认关闭，事件聚类、持久投递与摘要使用规则兜底。生产发布仍等待 v0.7.0 灰度和稳定观察。

## 阅读入口

| 目标 | 页面 |
|---|---|
| 部署、备份、灰度与回滚 | [Current Deployment](getting-started/deployment-current.md) |
| 了解数据流 | [架构](architecture.md) |
| 新闻源与规则 | [Scrapers](components/scrapers.md) · [Rules](components/rules.md) |
| 事件与可选模型 | [Events](components/dedup.md) · [Assessment](components/llm-pipeline.md) |
| 消息投递与摘要 | [Outbox](components/dispatch-router.md) · [Pushers](components/pushers.md) |
| 心跳、源状态、日报和冒烟 | [Observability](components/observability.md) |
| 一周后的代码清理 | [稳定门槛与删除清单](operations/staged-cleanup.md) |

## 发布状态与待完成验证

本次实现不代表已部署上线。B0 的 150 条真实样本已准备，人工标注和付费模型评测尚未完成，8 条 seed 不作为质量验收。v0.7.0 shadow 需要 2–3 个交易日观察，v2 稳定一周后才发布本清理版本，稳定至少两周后逐项评估 D 扩源。真实源可用性、行情单位和线上推送效果仍需从部署服务器验证。

历史组件页面路径保留以维护旧链接。Tier-0/1/2/3、旧双层 LLM 配置、commands/charts 和新闻 watchdog 已删除；旧历史表及迁移仍保留。

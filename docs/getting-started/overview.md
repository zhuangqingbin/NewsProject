# Overview

NewsProject 提供财经新闻与 A 股盯盘两个独立子系统。新闻默认使用规则，LLM 默认关闭；v0.7.0 提供事件聚类、可选模型评估、持久投递与归纳摘要。飞书自定义机器人按 US/CN 新闻及 CN 告警分流。

## 当前配置默认值

`pipeline.mode: legacy` 和 `llm.enabled: false`。启用候选源、默认模型名称或单元测试通过都不是线上可用性、模型质量或实际费用的结论。8 条已知案例是未审核 seed；150 条人工标注与付费 benchmark 尚未完成。

## 开始使用

先看 [部署指南](deployment-current.md)，填写真实密钥和 SEC 联系 User-Agent，检查源与频道开关，再启动 Compose。默认规则运行不需要 LLM key；启用 LLM 前需完成 B0 和实际正数单价配置。

新闻改配置后重启，盯盘 alerts 支持专用 reloader。系统心跳、源状态与发送结果是三类独立监控。影子观察 2–3 个交易日后才能评估切 v2；一周/两周的后续门槛见 [清理清单](../operations/staged-cleanup.md)。

## 阅读路径

- [架构](architecture.md) · [数据源](../components/scrapers.md) · [规则](../components/rules.md)
- [事件](../components/dedup.md) · [Assessment](../components/llm-pipeline.md) · [Outbox](../components/dispatch-router.md)
- [日常操作](../operations/daily-ops.md) · [可观测性](../components/observability.md)

# Classifier 历史入口

v0.7.1 已删除旧 classifier、LLMJudge 和灰区评分配置。规则召回见 [Rules](rules.md)，单次模型评估见 [Assessment](llm-pipeline.md)，最终推送门槛见 [决策与 Outbox](dispatch-router.md)。

旧 news_processed.is_critical/score 仅作为历史数据保留，不驱动当前事件处理。历史设计保存在 docs/superpowers/specs/2026-04-25-news-pipeline-design.md。

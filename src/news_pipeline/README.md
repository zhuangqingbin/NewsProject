# news_pipeline

v0.7.1 清理候选，仅支持 v2：回看抓取 → URL 幂等保存 → 规则召回 → 事件聚类 → 可选 Assessment → 事务决策与 Outbox → 飞书即时卡片或摘要。LLM 默认关闭；旧 Tier 路由、simhash、commands/charts 和旧写入 DAO 已删除，历史表与迁移保留。

生产发布仍须先在保留的 v0.7.0 完成 B0、shadow 观察和一周 v2 稳定运行。回滚使用 v0.7.0 镜像和配置。

- [子系统说明](../../docs/subsystems/news_pipeline.md)
- [配置](../../config/news_pipeline/README.md) · [共用配置与密钥模板](../../config/common/README.md)
- [部署、备份与回滚](../../docs/getting-started/deployment-current.md)
- [事件](../../docs/components/dedup.md) · [Assessment](../../docs/components/llm-pipeline.md) · [Outbox](../../docs/components/dispatch-router.md)
- [源冒烟与监控](../../docs/components/observability.md) · [C1/C2 发布门槛](../../docs/operations/staged-cleanup.md)

新闻配置位于 config/common 与 config/news_pipeline，修改后重启 app。真实密钥从 config/common/secrets.yml.example 复制至同目录 secrets.yml，不提交版本库。启动前使用部署指南完成数据库迁移与源/频道配置；NEWS_PIPELINE_ONCE 也可能真实发送消息。

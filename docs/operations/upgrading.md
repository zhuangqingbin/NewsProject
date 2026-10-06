# Upgrading

完整发布命令、SQLite backup API 备份和回滚方案见 [Current Deployment](../getting-started/deployment-current.md)。本页保留旧操作入口。

先停新闻与盯盘写入，保留旧镜像、配置和两份一致数据库备份。只有 app 启动时迁移新闻库；不要让 quote_watcher 重复执行迁移。0004/0005 迁移保留旧处理历史，0005 将旧全文索引换为事件索引。

保持默认 legacy/LLM false 验证阶段 A。B0 完成 150 条人工标注及获授权模型选型后，shadow 观察 2–3 个交易日，再评估 v2。阶段 B 回滚改 legacy、关闭 LLM、重启；不删新表。

v2 稳定一周后才执行 C1/C2 代码与依赖删除，规划 v0.7.1；该阶段回滚需保留的 v0.7.0 镜像与配置。D 扩源至少等两周稳定后逐源验证。细项见 [清理门槛](staged-cleanup.md)。这些步骤是要求，不是已完成上线记录。

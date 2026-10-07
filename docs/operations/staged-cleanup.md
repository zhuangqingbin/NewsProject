# C1/C2 清理与发布门槛

本分支为提前开发的 v0.7.1 清理候选。C1/C2 的代码、配置和依赖删除已实现；生产发布门槛尚未满足。保留的 v0.7.0 分支继续支持 legacy/shadow 与配置回滚，不将本清理分支提前合入上线分支。

两个分支的提交、验证与待完成验收见 [开发交付记录](../superpowers/reviews/2026-10-07-development-delivery.md)。

## 发布条件

先完成 B0 的 150 条人工标注、获授权模型评测和最终留出集验收，再用 v0.7.0 观察 2–3 个交易日 shadow。切 v2 后连续稳定运行至少一周，保存逐源服务器冒烟、日报、重试/消费、预算与回滚证据，才能发布 v0.7.1。等待期不能用离线通过数代替。

阶段 D 仍须等待至少两周稳定运行，再按覆盖缺口与来源质量逐项选择。

## 已实现的清理

| 范围 | 结果 |
|---|---|
| 旧链路 | 删除 commands/charts、四层 LLM、classifier/router、标题 simhash、旧摘要/处理任务及旧新闻配置监听 |
| 旧数据访问 | 删除 entities/relations/audit_log/dead_letter/news_processed/digest_buffer/push_log 的写入 DAO；历史模型和迁移保留 |
| 停用抓取器 | 删除 akshare_news、caixin_telegram、kr36、ths、xueqiu、tushare_news、yfinance_news 及旧 cookies/ratelimit |
| 共用层 | 删除旧 MessageBuilder 和每周死信周报，保留通用 WeCom 与盯盘能力 |
| 配置 | mode 仅 v2；删除旧 tier、classifier/dedup/charts/dead_letter/runtime、旧 scheduler 与双层 watchlist 字段；未知字段拒绝解析 |
| 依赖 | 移除 14 项不再使用的直接依赖，删除 Docker fonts-noto-cjk；保留 watchdog 和 akshare，后者锁定升级到 1.19.1 |
| 检查 | 保留配置叶子的消费方检查区分段与完整路径，排除 schema、迁移和测试自身 |

beautifulsoup4 仍是 akshare 的传递依赖，不能把直接依赖删除说成环境里完全不存在该包。

## 数据兼容与回滚

不删 entities、news_entities、relations、audit_log、dead_letter、news_processed、digest_buffer、push_log 等历史表。raw_news.title_simhash 旧值不重写，新入库统一写 0。保留任务继续保护被历史 news_processed 引用的原文。

历史 shadow 投递保持 shadow，不会因只剩 v2 而自动发出。待发即时投递仍核对历史成功推送，避免从 v0.7.0 恢复后重复发送。

回滚需要保留的 v0.7.0 镜像和配置；本分支不接受 legacy/shadow。没有新增破坏性迁移，不执行删表或 Alembic downgrade。备份与操作顺序见 [部署指南](../getting-started/deployment-current.md)。

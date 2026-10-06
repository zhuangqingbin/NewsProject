# Architecture

完整图示见 [整体架构](../architecture.md)。本页保留旧文档入口。

新闻：回看抓取 → URL 幂等原文 → 规则候选 → shadow/v2 事件聚类 → 可选 Assessment → 事务决策/Outbox → 即时卡片或摘要。默认 legacy 仍运行旧规则处理，LLM 关闭；新评估失败不阻塞规则兜底。

盯盘：腾讯个股 + 东财全市场/行业扫描 → 缓存与表达式规则 → CN `_alert` 频道。Sina 个股源可切换，日 K 缓存保留 akshare。

持久数据分别位于 news.db 与 quotes.db；心跳各自独立。共用层只提供通用契约与发送，新闻内容构建在新闻子系统。

旧四层 LLM、commands、charts、新闻 watchdog 仅迁移兼容，不作为新默认入口。v2 稳定一周后才按 [C1/C2 清单](../operations/staged-cleanup.md) 删除；部署流程见 [Current Deployment](deployment-current.md)。

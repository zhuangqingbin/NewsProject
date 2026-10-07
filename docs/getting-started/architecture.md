# Architecture

完整图示见 [整体架构](../architecture.md)。本页保留旧文档入口。

新闻：回看抓取 → URL 幂等原文 → 规则候选 → v2 事件聚类 → 可选 Assessment → 事务决策/Outbox → 即时卡片或摘要。LLM 默认关闭；评估失败使用规则兜底。

盯盘：腾讯个股 + 东财全市场/行业扫描 → 缓存与表达式规则 → CN `_alert` 频道。Sina 个股源可切换，日 K 缓存保留 akshare。

持久数据分别位于 news.db 与 quotes.db；心跳各自独立。共用层只提供通用契约与发送，新闻内容构建在新闻子系统。

v0.7.1 已删除旧四层 LLM、commands、charts 和新闻 watchdog，仅支持 v2。它是独立的清理候选分支，生产仍需先用 v0.7.0 完成灰度和一周稳定观察；见 [清理门槛](../operations/staged-cleanup.md) 与 [部署指南](deployment-current.md)。

# shared 共用层

新闻与盯盘共用通用消息契约、UTC 时间与交易日历、日志、Bark、心跳及飞书/WeCom 发送实现。抓取、规则、评估和持久投递由各自子系统负责。

旧 MessageBuilder 与每周死信报告已删除；共用层不反向依赖新闻业务模型。新闻卡片在 news_pipeline/deliver/cards.py。盯盘的 BurstSuppressor 与 alerts reloader 保留。

[共用层说明](../../docs/subsystems/shared.md) · [Pushers](../../docs/components/pushers.md) · [可观测性](../../docs/components/observability.md)

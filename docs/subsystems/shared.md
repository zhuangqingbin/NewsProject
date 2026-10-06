# shared 共用层

共用通用数据契约、时间与中国交易日历、日志、心跳、Bark、飞书/WeCom pusher、dispatcher 和频道 factory。业务抓取、规则、LLM 与新闻卡片归各自子系统。

## 模块

`shared/common` 提供 CommonMessage、Badge、DigestItem、Deeplink、Market、UTC 时间与 MarketCalendar。`shared/observability` 提供 structlog、Bark 和原子心跳文件。`shared/push` 将通用消息渲染并发送，使用嵌套 secrets 路径解析频道。

新闻卡片在 news_pipeline/deliver/cards.py；持久状态/重试在新闻 Outbox。旧 shared MessageBuilder 对新闻契约的反向引用为 legacy 兼容，等待 C1/C2 删除，不能当作新业务代码示例。旧每周死信报告同样不由当前 main 启动。

## 边界与兼容

新共用代码不引入新闻或盯盘业务 DAO。旧 news_pipeline.common 时间/枚举 shim 保留兼容，新代码直接使用 shared。WeCom 代码保留但默认无频道启用。watchdog 在盯盘 AlertsReloader 仍被实际使用，不因新闻配置监听删除而移除。

详见 [Pushers](../components/pushers.md)、[可观测性](../components/observability.md) 和 [清理门槛](../operations/staged-cleanup.md)。

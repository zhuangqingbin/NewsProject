# Pushers 与新闻卡片

共用发送层在 `shared/push`；新闻内容在 `news_pipeline/deliver/cards.py` 构建。当前配置使用飞书自定义机器人 webhook，新闻 US/CN 与盯盘 CN 告警频道分开。WeCom 实现保留但默认没有频道使用。Telegram、命令服务器和图表代码是待清理兼容模块，不是当前默认功能。

## CommonMessage 消息结构

通用消息包含 title、summary、来源标签/URL、badge、deeplink、market 和可选 digest_items。它不包含新闻 DAO 或模型客户端依赖。消息持久化到 `Delivery.payload` 时使用 JSON 模式，worker 恢复模型后交给 dispatcher。

## 即时卡片

事件卡片显示 summary（最多 60 字）、加粗的 so_what、事件类型、实质性与星级、来源数、首次时间和原文链接。未评估成功时标“规则”；SEC/一手公告有独立标记。优先链接一手原文，否则链接正文最长的文章。ticker deeplink 指向行情页面。

同主体 high 巨潮公告按 10 分钟、最多 5 份合并成“公司 发布 N 份公告”，列出每份标题与原文 URL。普通事件仍使用其单独标题。`push.color_scheme` 默认 `us`（利好绿、利空红），`cn` 反转颜色。

## 飞书 Pusher（自定义机器人 Webhook）

`config/common/channels.yml` 的 `webhook_key` 和 `sign_key` 使用 dotted secret 路径，例如 `news_pipeline.feishu_hook_cn`。值从 `config/common/secrets.yml` 的 `push.news_pipeline` 查找；旧 flat secrets 仅用于兼容迁移。

开启签名时，用 `timestamp + "\n" + secret` 作为 HMAC-SHA256 key，对空消息签名后 Base64 编码。不要把设备 key、webhook 或 sign secret 写进日志与版本库。飞书卡片无需自建应用或图片上传权限，当前新闻卡片不生成图表。

## PusherDispatcher

`dispatch(message, channels=[...])` 返回按频道索引的 `SendResult`。发送层汇报成功/失败，事件路径的状态持久化、重试与消费由 outbox 管理。HTTP 200 不能独自代表业务成功，还要检查平台响应。缺失频道结果不能当成功。

## 速率与体积限制

新闻新 outbox 每频道 1 秒间隔、20 次尝试/分钟；旧 `push.per_channel_rate` 不是新 worker 的配置入口。卡片和摘要在渲染后按 UTF-8 字节裁剪，计入签名余量，确保最终体积不超过飞书 20 KB 限制；摘要显示“另有 N 条未展示”。共享 pusher 的底层 HTTP 重试不替代持久 outbox。

## 相关

- [决策与 Outbox](dispatch-router.md) · [可观测性](observability.md)
- [部署与密钥](../getting-started/deployment-current.md) · [后续清理](../operations/staged-cleanup.md)

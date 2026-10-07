# Observability

心跳回答进程和调度器是否活着；源健康回答上游是否可用；投递状态回答消息是否发出。三者分开监控，不用“最近有新闻”代替进程健康。

## structlog JSON 日志

默认 JSON 日志。`httpx` 和 `httpcore` logger 至少为 WARNING，避免 INFO 请求 URL 泄露飞书 webhook 或 Bark key。错误使用可辨识的异常类别或 repr，不把空列表当作所有故障的统一结果。

```bash
docker compose logs --tail=100 app quote_watcher
docker compose logs -f app
```

抓取日志关注 `scrape_failed`、`scrape_done`；评估关注 `event_assess_failed`、`assess_input_truncated`；行情关注 `quote_feed_ok`、`ticker_loop_failed` 与启动探测。旧 Tier 与每周死信链路已删除。

## 源健康状态机

`source_state` 保存首次/最近成功、最新条目时间、连续失败、暂停时间、健康状态和变更时间。连续 5 次失败进入 down/failing；成功但超过配置静默阈值进入 down/silent。北京时间交易日 09:00–23:00 使用 `max_silence_min`，其他时段用 `max_silence_off_min`；交易日历处理周末与中国节假日。

抓取失败指数退避封顶 30 分钟。Bark 仅在状态转换时告警：down 发失效，恢复发中断时长，不再每次解析错误都紧急提醒。新闻日报仍逐源展示状态，down 排在前面。

## 行情源监控

`QUOTE_FEED=tencent` 是个股默认源，`sina` 是切换选项。启动时分别探测个股、全市场、行业板块，任一路失败发 Bark。交易时段连续 5 分钟没有成功个股快照告警一次，首次恢复再通知；成功记录 `quote_feed_ok`。休市不积累无快照故障时间。

## 健康检查

`shared/observability/heartbeat.py` 每 60 秒写 `data/heartbeat_news_pipeline.json` 或 `data/heartbeat_quote_watcher.json`，包含当前时间与各 job 完成时间。写入使用临时文件替换。healthcheck 要求文件在最近 3 分钟更新；两个子系统有各自的 Compose healthcheck。

```bash
docker compose exec app python -m news_pipeline.healthcheck
docker compose exec quote_watcher python -m news_pipeline.healthcheck --subsystem quote_watcher
```

healthy 不意味着所有源正常，也不代表当前新闻已经发送成功。

## 系统日报

每天北京时间 08:20 向 `ops.report_channel`（默认 `feishu_cn`）发送系统卡片：逐源过去 24 小时入库/状态、候选、即时推送、去重/突发/新鲜度拦截、摘要期数/展示条数、投递失败、数据库与 WAL 大小、LLM 次数/费用/失败/规则兜底。

当前日报只读取 v2 指标。历史旧处理与 legacy_digest 审计保留在库中。摘要展示数使用 `event_ids`；`consumed_event_ids` 是预选消费范围，不能代替展示条数。同一期多个频道不能重复计作多个事件。

新旧影子对比随旧路径删除而移除。历史 shadow 事件/摘要不会自动发送。日报本身也走持久投递；未收到日报时检查调度心跳与 outbox。

## 漏抓抽检与源冒烟

```bash
docker compose exec app python -m news_pipeline.health.leak_check
docker compose exec app python -m news_pipeline.health.smoke --no-report
```

手工 smoke 默认输出 JSON 并向 ops 频道发送卡片，数据库始终只读、不插入新闻；`--no-report` 仅输出 JSON，`--report` 是默认行为的显式别名。启动和每周日 20:00 北京时间自动冒烟经 outbox 排队卡片；包含结构错误与 checked / present / missing / missing_urls。发布超过 15 分钟仍不在 URL hash 中的条目作为漏抓候选，不再运行标题 simhash 检查。失败与漏抓是不同指标，源能返回列表也可能漏新闻。

## 相关

- [部署与回滚](../getting-started/deployment-current.md) · [调度](scheduler.md)
- [投递](dispatch-router.md) · [模型预算](llm-pipeline.md)

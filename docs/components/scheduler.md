# Scheduler

新闻调度入口是 `main.register_jobs`，封装在 `scheduler/runner.py`。interval/cron job 使用 `max_instances=1`、coalesce 和异常记录；完成时更新各自心跳。旧“固定 13 个任务”与固定北京时间美股 digest 的描述不适用于当前入口。

## Interval Jobs

| 任务 | 频率 | 模式 |
|---|---|---|
| `scrape_<source>` | 每源 `interval_sec`，带 jitter | v2 |
| `cluster_events`、`assess_events` | 各 30 秒 | v2 |
| `decide_events` | 10 秒 | v2 |
| `deliver_outbox` | 10 秒，单 worker | v2；历史 shadow 项不发 |
| `source_health` | 300 秒 | v2 |
| `heartbeat` | 60 秒 | v2 |

同一 job 不重入不等于不同 job 不并发。聚类、评估、决策和投递要依靠版本检查与事务保持一致，不能依赖调度顺序。

## Cron Jobs

| 任务 | 时刻与时区 |
|---|---|
| A 股 digest | 08:27、20:57，`Asia/Shanghai` |
| 美股 digest | 08:27、16:27，`America/New_York` |
| 系统日报 | `ops.report_at`，默认 08:20 北京时间 |
| 数据保留 | 每天 04:10 北京时间 |
| VACUUM | 每月 1 日 04:30 北京时间 |
| 每周源冒烟 | 周日 20:00 北京时间 |

## 时区说明

数据库保存 UTC，展示按市场本地时区。摘要 schedule 每项显式包含 `at` 和 `tz`，美股随纽约夏令时自动换算，不写死北京时间。避开整点和半点减少平台限流风险。

```yaml
scheduler:
  digest:
    cn: [{at: '08:27', tz: Asia/Shanghai}, {at: '20:57', tz: Asia/Shanghai}]
    us: [{at: '08:27', tz: America/New_York}, {at: '16:27', tz: America/New_York}]
```

## Digest Key 选择逻辑

当前 `digest_slot` 包含市场、计划时刻和该市场本地日期，作为频道幂等键的一部分；所有频道同事务入队，成功消费独立于触发时刻。

`NEWS_PIPELINE_ONCE=1` 是一次性抓取/处理入口，会处理 v2 并运行一次 outbox。它可能发送消息，不是 smoke --no-report 或 rules replay 的替代。

## 配置修改与旧任务

每源抓取间隔来自 `sources.yml`。旧 `scheduler.scrape.*`、`scheduler.llm` 与新闻 hot_reload 字段已删除；改配置后重启 `app`。旧命令服务器、图表、死信周报与多层 LLM 任务已删除。

## 相关

- [抓取](scrapers.md) · [Outbox](dispatch-router.md) · [心跳与日报](observability.md)
- [保留任务](storage.md) · [部署](../getting-started/deployment-current.md)

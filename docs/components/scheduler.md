# Scheduler

这一页描述 APScheduler 的 13 个 job、调度时刻表，以及时区处理。

---

## 调度器基础

使用 `APScheduler AsyncIOScheduler`，运行在同一个 asyncio event loop 中：

```python
class SchedulerRunner:
    def __init__(self) -> None:
        self._sched = AsyncIOScheduler(timezone="UTC")  # 调度器内部时区: UTC
```

每个 job 都设置 `max_instances=1`（防止上次未完成时重叠触发）和 `coalesce=True`（错过的触发合并为一次）。

---

## 13 个 Jobs 完整列表

### Interval Jobs（按间隔触发）

| Job ID | 间隔 | 说明 | jitter |
|---|---|---|---|
| `scrape_finnhub` | 300s | 抓取 Finnhub 美股新闻 | 10s |
| `scrape_sec_edgar` | 120s | 抓取 SEC EDGAR 公告 | 10s |
| `scrape_caixin_telegram` | 60s | 抓取财联社 | 10s |
| `scrape_akshare_news` | 180s | 抓取东财股票新闻 | 10s |
| `scrape_juchao` | 120s | 抓取巨潮 A 股公告 | 10s |
| `process_pending` | 120s | LLM 处理 pending 文章（批量 25 条） | — |
| `push_failure_alert` | 1800s | 检查推送失败率，发 Bark 告警 | — |
| `bark_heartbeat` | 86400s | 每日心跳（24h 未见 → 异常） | — |

所有 scrape job 加了 10s jitter，避免多个 scraper 同时发请求。

### Cron Jobs（固定时刻触发）

| Job ID | 触发时刻 | 说明 |
|---|---|---|
| `digest_morning_cn` | 08:30 CST | A 股早间摘要 |
| `digest_evening_cn` | 21:00 CST | A 股晚间摘要 |
| `digest_morning_us` | 21:00 CST | 美股早间摘要（美东时间盘前） |
| `digest_evening_us` | 04:30 CST (次日) | 美股晚间摘要（美东时间盘后） |
| `dlq_weekly_alert` | 周一 08:00 CST | 周报：未处理的 dead letter 汇总 |

---

## 时区说明

!!! note "调度器 vs 展示时区"
    - **调度器内部**：全部 UTC（`AsyncIOScheduler(timezone="UTC")`）
    - **Cron 触发**：用 `CronTrigger(hour=..., timezone="Asia/Shanghai")` 指定 CST
    - **日志显示**：`runtime.timezone_display` 控制展示时区（us: ET，cn: CST）
    - **数据库存储**：全部 naive UTC datetime（SQLite 无时区类型）

时区转换辅助函数：
```python
# common/timeutil.py
def utc_now() -> datetime:
    return datetime.now(UTC)

def ensure_utc(dt: datetime) -> datetime:
    """确保 datetime 有 UTC tzinfo（处理 naive + aware 混合问题）"""
    ...

def to_market_local(dt_utc: datetime, market: Market) -> datetime:
    """转换为市场本地时间，用于 Digest key 判断"""
    ...
```

---

## 调度时间线可视化

```
UTC 时间轴（24h）
00:00  01:00  02:00  ...  08:00  ...  13:00  ...  21:00
  |      |      |           |           |           |
 美股              美股                         A股
盘后              收盘                          早盘
摘要            摘要(UTC)                      摘要
 US               US                           CN
evening          morning                       evening

CST 对应：
00:30(CST)     21:00(CST)    digest_morning_us
04:30(CST次日) 20:00(CST)    digest_evening_us
08:30(CST)                   digest_morning_cn
21:00(CST)                   digest_evening_cn
```

---

## Digest Key 选择逻辑

```python
def _choose_digest_key(market: Market, now_utc: datetime) -> str:
    local = to_market_local(now_utc, market)
    period = "morning" if local.hour < 12 else "evening"
    return f"{period}_{market.value}"
```

文章处理时，根据市场本地时间决定进入哪个 digest bucket：
- A 股新闻在 08:00–11:59 CST 处理 → `morning_cn`
- A 股新闻在 12:00–23:59 CST 处理 → `evening_cn`

---

## 查看运行中的 Jobs

服务启动时会记录所有 job ID：

```
{"event": "scheduler_started", "jobs": ["scrape_finnhub", "scrape_sec_edgar", ...]}
```

查看 APScheduler 状态（通过日志）：
```bash
sudo journalctl -u news-pipeline --since "1 hour ago" | grep scheduler
```

---

## 相关

- [Components → Scrapers](scrapers.md) — scrape job 实现
- [Components → Dispatch Router](dispatch-router.md) — digest buffer
- [Operations → Daily Ops](../operations/daily-ops.md) — 手动触发 digest

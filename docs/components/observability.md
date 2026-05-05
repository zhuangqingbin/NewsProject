# Observability

这一页描述日志系统（structlog）、Bark 告警的 7 个触发点、周报机制，以及健康检查。

---

## structlog JSON 日志

```python
# observability/log.py
import structlog

def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),  # JSON 格式输出
        ],
        ...
    )
```

日志格式（JSON，每行一条）：

```json
{"timestamp": "2026-04-25T09:30:00Z", "level": "info", "event": "scrape_done", "source": "finnhub", "new": 3, "total": 15}
{"timestamp": "2026-04-25T09:30:01Z", "level": "warning", "event": "anticrawl", "source": "xueqiu", "error": "xueqiu blocked"}
```

### 关键日志事件

| event | level | 含义 |
|---|---|---|
| `scheduler_started` | info | 调度器启动，列出所有 job |
| `scrape_done` | info | 单次抓取完成，含 new/total 计数 |
| `anticrawl` | warning | 反爬触发，source 已暂停 |
| `scrape_transient_error` | warning | 网络超时等临时错误 |
| `scrape_structural_error` | error | 解析 bug 等结构性错误 |
| `llm_skip` | debug | Tier-0 判断无关，跳过 |
| `llm_failed` | error | LLM 调用异常，文章进 dead letter |
| `push_suppressed_burst` | info | Burst 抑制，未推送 |
| `scraper_probe_ok` | info | 启动时连通性探测成功 |
| `scraper_probe_failed` | warning | 启动时连通性探测失败 |
| `anthropic_not_configured_fallback_to_tier1` | warning | Anthropic 未配，已 fallback DeepSeek |
| `shutdown_signal` | info | 收到 SIGTERM/SIGINT |
| `shutdown_complete` | info | 优雅退出完成 |

### 查看日志

```bash
# systemd journal（生产）
sudo journalctl -u news-pipeline -f --no-pager

# 只看 error
sudo journalctl -u news-pipeline -p err --since "1 hour ago"

# 过滤特定 event（jq 解析 JSON）
sudo journalctl -u news-pipeline --since today | jq 'select(.event == "scrape_done")'
```

---

## Bark iOS 告警

Bark 是一个轻量 iOS 推送应用，提供 HTTPS webhook，一次调用 → iPhone 系统通知。

当 TG 或飞书 token 失效时，Bark 作为独立告警通道。

### 配置

```yaml
# config/secrets.yml
alert:
  bark_url: https://api.day.app/<YOUR_BARK_KEY>
```

### 7 个触发点

| 告警 ID | 触发时机 | 级别 |
|---|---|---|
| C-1 | `AntiCrawlError` → source 暂停 30min | WARN |
| C-2 | 今日 LLM 成本 >= ceiling × 80%（每天只发一次） | WARN |
| C-3 | 今日 LLM 成本 >= ceiling（每次超限都发） | URGENT |
| C-4 | 某 channel 最近 60min 失败次数 >= 3 | WARN |
| C-5 | `scraper_probe_failed`（启动时连通性探测失败） | WARN |
| C-6 | 每日心跳（24h 间隔，证明服务存活） | INFO |
| C-7 | 周一 08:00 CST，DLQ 未处理任务汇总 | INFO |

### 告警节流

`BarkAlerter` 内置节流（默认 15 分钟同一告警 key 不重复发送）：

```python
class BarkAlerter:
    def __init__(self, base_url: str, throttle_seconds: int = 900):
        self._throttle = throttle_seconds  # 900s = 15min
        self._last_sent: dict[str, float] = {}

    async def send(self, title: str, body: str, level: AlertLevel) -> bool:
        key = f"{level}:{title}"
        if (now - last_sent[key]) < self._throttle:
            return False  # 节流，不发
        ...
```

---

## 健康检查

`healthcheck.py` 实现了一个简单的健康端点，用于 Docker HEALTHCHECK 或外部监控：

```python
# healthcheck.py
# 检查：数据库连通性 + 最近 N 分钟有无新数据
```

```bash
# 本地检查
uv run python -c "from news_pipeline.healthcheck import check; import asyncio; asyncio.run(check())"
```

---

## 周报（DLQ Summary）

每周一 08:00 CST，`_weekly_dlq_alert` job 查询未处理的 dead letter 并通过 Bark 发送汇总：

```python
async def build_dlq_summary(*, dlq: DeadLetterDAO) -> str:
    # 查询 resolved_at IS NULL 的死信
    # 按 kind 分组统计
    # 返回摘要字符串，如: "scrape: 2, push_4xx: 1"
```

---

## daily_metrics 表

每次抓取/LLM/推送后，`MetricsDAO.increment()` 更新 `daily_metrics`：

| metric_name | dimensions | 含义 |
|---|---|---|
| `scrape_new` | `source=finnhub` | 新抓取文章数 |
| `scrape_dup` | `source=finnhub` | 去重丢弃数 |
| `llm_cost_cny` | — | 今日 LLM 花费（CNY） |
| `push_ok` | `channel=feishu_us` | 推送成功数 |
| `push_failed` | `channel=feishu_us` | 推送失败数 |

查询示例：
```sql
SELECT metric_date, metric_name, dimensions, metric_value
FROM daily_metrics
WHERE metric_date >= date('now', '-7 days')
ORDER BY metric_date DESC, metric_name;
```

---

## 相关

- [Operations → Monitoring](../operations/monitoring.md) — 看日志 / 看成本 / Datasette 访问
- [Operations → Troubleshooting](../operations/troubleshooting.md) — 常见问题处理

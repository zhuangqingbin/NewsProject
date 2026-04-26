# Monitoring

这一页说明如何看日志、查成本、通过 Datasette 远程访问数据，以及 Bark 告警渠道。

---

## 日志监控

服务日志输出为 JSON，由 systemd journal 收集。

```bash
# 实时日志
sudo journalctl -u news-pipeline -f

# 只看 error + critical
sudo journalctl -u news-pipeline -p err -f

# 用 jq 过滤特定事件
sudo journalctl -u news-pipeline --since "1 hour ago" -o cat | \
  python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        if d.get('event') in ('scrape_done','anticrawl','llm_failed'):
            print(json.dumps(d, ensure_ascii=False))
    except: pass
"
```

### 关键日志模式

| 正常状态 | 异常状态 |
|---|---|
| 每 2 分钟出现 `process_pending` | 超过 10 分钟无 `process_pending` → 调度器挂了 |
| `scrape_done` 含 `new > 0` | 持续 `new: 0` → scraper 可能被反爬或 API 挂了 |
| 无 `llm_failed` | `llm_failed` 出现 → LLM API 错误或成本超限 |
| 无 `anticrawl` | `anticrawl` 出现 → cookie 需要更新 |

---

## 成本监控

```bash
# Bot 命令（最快）
/cost

# SQL 查询（最近 7 天）
sqlite3 /opt/news_pipeline/data/news.db "
SELECT metric_date, printf('%.4f CNY', metric_value) as cost
FROM daily_metrics
WHERE metric_name = 'llm_cost_cny'
ORDER BY metric_date DESC LIMIT 7;"
```

### 成本超限处理

当 Bark 发 `llm_cost_exceeded` 告警时：

1. 确认当日成本：`/cost`
2. 查哪个 tier 消耗最多（通过 `model_used` 字段）：
   ```sql
   SELECT model_used, count(*) cnt
   FROM news_processed
   WHERE date(extracted_at) = date('now')
   GROUP BY model_used;
   ```
3. 临时提高 ceiling 度过当天（不推荐）或等第二天自动重置
4. 根本原因：Tier-2 被触发次数过多 → 考虑调紧 watchlist 或提高 tier2 路由门槛

---

## Datasette — 远程浏览数据库

### SSH 隧道（推荐）

```bash
# 本机执行（保持 terminal 开着）
ssh -L 8001:localhost:8001 ubuntu@8.135.67.243

# 浏览器打开
http://localhost:8001
```

Datasette 提供：
- 每个表的可视化浏览（分页、过滤、排序）
- SQL 查询界面（`/news.db?sql=SELECT...`）
- CSV 导出
- FTS5 全文搜索

### 关键页面速查

| 用途 | Datasette URL |
|---|---|
| 今日 critical 新闻 | `http://localhost:8001/news/news_processed?is_critical=1&_sort_desc=extracted_at` |
| 所有 source 状态 | `http://localhost:8001/news/source_state` |
| 推送失败记录 | `http://localhost:8001/news/push_log?status=failed&_sort_desc=sent_at` |
| 死信列表 | `http://localhost:8001/news/dead_letter?_where=resolved_at+is+null` |
| 日常成本 | `http://localhost:8001/news/daily_metrics?metric_name=llm_cost_cny&_sort_desc=metric_date` |

---

## Bark 告警渠道

Bark 是独立于 TG/飞书的告警通道，在主推送渠道失效时仍能到达你的 iPhone。

7 个触发点见 [Components → Observability](../components/observability.md)。

主要关注：
- `URGENT: llm_cost_exceeded` → 今日 LLM 成本已超限，停止处理
- `WARN: anti_crawl_<source>` → source 被反爬，已暂停 30min
- `WARN: push_fail_<channel>` → 推送失败率过高
- `INFO: heartbeat` → 每天收到代表服务正常

如果超过 25 小时没收到心跳：
```bash
sudo systemctl status news-pipeline
sudo journalctl -u news-pipeline --since "2 hours ago"
```

---

## 健康检查

```bash
# 检查服务进程
sudo systemctl is-active news-pipeline
# → active

# 检查数据库（最近 30 分钟是否有新数据）
sqlite3 /opt/news_pipeline/data/news.db "
SELECT count(*) FROM raw_news WHERE fetched_at > datetime('now', '-30 minutes');"
# 应该 > 0（取决于市场时段）

# 检查数据库文件大小（增长说明有数据写入）
ls -lh /opt/news_pipeline/data/news.db
```

---

## 推送成功率

```sql
-- 最近 24 小时推送成功率
SELECT
  channel,
  sum(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok,
  sum(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM push_log
WHERE sent_at > datetime('now', '-24 hours')
GROUP BY channel;
```

---

## 相关

- [Components → Observability](../components/observability.md) — structlog 和 Bark 详解
- [Operations → Troubleshooting](troubleshooting.md) — 问题排查
- [Operations → Daily Ops](daily-ops.md) — 日常操作命令

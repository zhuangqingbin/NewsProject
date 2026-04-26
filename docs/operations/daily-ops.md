# Daily Ops

这一页是日常运维的快速参考：systemctl 命令、sqlite3 查数据、改 watchlist、调阈值。

---

## 服务管理

```bash
# 查状态
sudo systemctl status news-pipeline

# 重启
sudo systemctl restart news-pipeline

# 查最近 200 行日志
sudo journalctl -u news-pipeline -n 200 --no-pager

# 实时跟踪日志
sudo journalctl -u news-pipeline -f

# 只看 error 级别
sudo journalctl -u news-pipeline -p err --since "1 hour ago"

# 查今天所有日志
sudo journalctl -u news-pipeline --since today
```

---

## 查数据（sqlite3）

```bash
# 进入 sqlite3 交互模式
sqlite3 /opt/news_pipeline/data/news.db

# 或直接执行 SQL
sqlite3 /opt/news_pipeline/data/news.db "SQL 语句"
```

### 常用查询

```sql
-- 各源今日抓取量
SELECT source, count(*) cnt
FROM raw_news
WHERE date(fetched_at) = date('now')
GROUP BY source ORDER BY cnt DESC;

-- 今日 critical 新闻列表
SELECT rn.title, np.score, np.event_type, np.is_critical, np.extracted_at
FROM news_processed np JOIN raw_news rn ON rn.id = np.raw_id
WHERE date(np.extracted_at) = date('now') AND np.is_critical = 1
ORDER BY np.extracted_at DESC;

-- 最近 30 分钟有无新数据（检查 scraper 是否工作）
SELECT source, count(*) cnt
FROM raw_news
WHERE fetched_at > datetime('now', '-30 minutes')
GROUP BY source;

-- 查看暂停状态的 source
SELECT source, paused_until, last_error, error_count
FROM source_state
WHERE paused_until > datetime('now');

-- 今日 LLM 成本
SELECT metric_date, metric_value as cost_cny
FROM daily_metrics
WHERE metric_name = 'llm_cost_cny'
ORDER BY metric_date DESC LIMIT 7;

-- 推送成功率
SELECT channel, status, count(*) cnt
FROM push_log
WHERE sent_at > datetime('now', '-24 hours')
GROUP BY channel, status;

-- 死信列表
SELECT kind, error, retries, created_at
FROM dead_letter WHERE resolved_at IS NULL
ORDER BY created_at DESC;
```

---

## 改 Watchlist

方式一：直接编辑文件（服务会热加载）

```bash
vim /opt/news_pipeline/config/watchlist.yml
# 添加或删除 ticker，保存
# hot_reload=true 时 watchdog 自动检测变化，无需重启
```

方式二：通过 Bot 命令（推荐）

```
/watch TSLA
/unwatch AAPL
/list
```

---

## 解除 Source 暂停

Source 被反爬检测后自动暂停 30 分钟。手动解除：

```bash
# 方式一：直接清除 paused_until
sqlite3 /opt/news_pipeline/data/news.db \
  "UPDATE source_state SET paused_until = NULL, error_count = 0 WHERE source = 'xueqiu';"

# 方式二：Bot 命令
/resume xueqiu
```

---

## 调整 LLM 成本上限

```bash
vim /opt/news_pipeline/config/app.yml
# 修改: daily_cost_ceiling_cny: 10.0  （改为 ¥10/天）
# 保存后热加载（无需重启）
```

!!! tip "Anthropic 配置后需要上调 ceiling"
    DeepSeek 单日成本很难超过 ¥5，但启用 Anthropic Haiku 后每日成本可能达到 ¥15–20。
    上调 ceiling 前先观察 `/cost` 几天。

---

## 查 Cost

Bot 命令：
```
/cost
# → 今日 LLM 成本: 1.23 CNY / ceiling 5.00 CNY
```

SQL 查询（最近 7 天）：
```bash
sqlite3 /opt/news_pipeline/data/news.db "
SELECT metric_date, printf('%.4f', metric_value) as cost_cny
FROM daily_metrics
WHERE metric_name = 'llm_cost_cny'
ORDER BY metric_date DESC LIMIT 7;"
```

---

## 触发 Digest

```bash
# Bot 命令（立即触发当前市场的 digest）
/digest now

# 或手动触发 Python 代码（在服务器上）
cd /opt/news_pipeline
uv run python -c "
import asyncio
from news_pipeline.main import _amain
# 不推荐直接调用 _amain，用 Bot 命令更安全
"
```

---

## 手动生成图表

```bash
# Bot 命令
/chart NVDA 30d
/chart 600519 90d
```

---

## Datasette 远程访问

```bash
# 本地 SSH 隧道
ssh -L 8001:localhost:8001 ubuntu@8.135.67.243
# 然后浏览器打开 http://localhost:8001
```

---

## 上传更新代码

```bash
# 从本地推到服务器（不改 secrets）
rsync -avz --exclude='.venv' --exclude='__pycache__' \
  --exclude='config/secrets.yml' --exclude='data/' \
  ./ ubuntu@8.135.67.243:/opt/news_pipeline/

# 服务器上
ssh ubuntu@8.135.67.243
cd /opt/news_pipeline
uv sync --no-dev
uv run alembic upgrade head
sudo systemctl restart news-pipeline
```

---

## 相关

- [Operations → Monitoring](monitoring.md) — 深度监控
- [Operations → Upgrading](upgrading.md) — 升级流程
- [Operations → Troubleshooting](troubleshooting.md) — 问题排查

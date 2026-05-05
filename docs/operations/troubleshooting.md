# Troubleshooting

这一页是实战痛点合集，基于真实部署经验。每个问题都给出根本原因和具体修复步骤。

---

## 飞书 bitable 91403 错误

**症状**：飞书 API 返回 `{"code": 91403, "msg": "..."}`，归档写入失败。

**根本原因**：飞书自建应用 + bitable 在个人云空间（非企业空间）的权限模型极其复杂。
91403 = 没有权限访问 bitable。需要：Space 权限 + App 权限 + 协作者身份 + OAuth scope —— 四重限制叠加，对单人开发者几乎无解。

**解决方案**：v0.1.6 已**完全移除飞书自建应用和 bitable 归档**。使用 Datasette 浏览 SQLite 数据。

```bash
# 远程访问数据库
ssh -L 8001:localhost:8001 ubuntu@8.135.67.243
# 浏览器 http://localhost:8001
```

如果你在 v0.1.5 以前遇到此问题，升级到 v0.1.6+ 即可彻底解决。

---

## 飞书 Webhook 签名错

**症状**：飞书机器人推送返回 HTTP 400，响应含 `"sign check failed"` 或 `"verification failed"`。

**根本原因**：飞书 webhook 签名算法为 `HMAC-SHA256(timestamp + "\n" + sign_secret)`，base64 编码后传入 `sign` 字段。

**调试步骤**：

```bash
# 手动计算签名（Python）
python3 -c "
import hmac, hashlib, base64, time
timestamp = str(int(time.time()))
sign_secret = 'YOUR_SIGN_SECRET'
sign_str = timestamp + '\n' + sign_secret
sig = base64.b64encode(
    hmac.new(sign_str.encode(), digestmod=hashlib.sha256).digest()
).decode()
print(f'timestamp={timestamp}, sign={sig}')
"

# 用 curl 测试 webhook
curl -X POST 'https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_HOOK' \
  -H 'Content-Type: application/json' \
  -d '{
    "timestamp": "TIMESTAMP_FROM_ABOVE",
    "sign": "SIGN_FROM_ABOVE",
    "msg_type": "text",
    "content": {"text": "test"}
  }'
```

常见错误：
- `feishu_sign_*` 填错（多了空格或换行）→ 检查 `secrets.yml`
- 飞书 webhook URL 过期 → 重新在飞书群创建机器人

---

## LLM 返回 `'xxx' is not a valid EventType`

**症状**（历史）：`EnrichedNews` 创建失败，日志中有 `ValidationError`，提示某个枚举值不合法。

**根本原因**：LLM 偶尔返回枚举定义外的字符串（如 `"market_analysis"`、`"neutral_to_positive"`）。

**状态**：v0.1.0-mvp 已通过 `safe_*` coercion 函数修复，不会再出现此 crash。

```python
# 现在的行为：宽松 fallback 而非 crash
def safe_event_type(value: str | None) -> EventType:
    try:
        return EventType(value.lower())
    except (ValueError, AttributeError):
        return EventType.OTHER  # 安全回退
```

如果日志里仍出现 `llm_failed` + ValidationError，检查是否在 `EnrichedNews` 构造时有未走 `safe_*` 的字段。

---

## DeepSeek 返回 markdown fenced JSON

**症状**（历史）：LLM 响应不是裸 JSON，而是 ```json ... ``` 代码块包裹，导致 JSON 解析失败。

**根本原因**：DeepSeek 有时即使在 `json_mode=True` 下也会输出 markdown 格式的 JSON。

**状态**：已在 DashScope client 中通过 `parse_json_or_none()` 修复——自动提取 fenced code block 内的 JSON。

如果再次遇到：

```bash
# 查 llm_failed 日志，看原始 payload
sudo journalctl -u news-pipeline | grep llm_failed | tail -5
```

---

## 时区比较错误

**症状**（历史）：抓取时报 `TypeError: can't compare offset-naive and offset-aware datetimes`。

**根本原因**：SQLite 存储 naive UTC datetime，读取后没有 tzinfo，和带 `UTC` tzinfo 的 datetime 比较报错。

**状态**：v0.1.3 I5 已修复，`ensure_utc()` 统一处理：

```python
def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
```

所有从数据库读取后参与时间比较的地方都调用 `ensure_utc()`。

---

## Cookie 过期（xueqiu / ths）

**症状**：日志中 `anticrawl` 事件，source 暂停；或 source 一直返回空数据。

**处理流程**：

```bash
# 1. 暂停该 source（防止反复触发告警）
/pause xueqiu 120

# 2. 获取新 cookie（浏览器开发者工具 → Network → 找到目标请求 → 复制 Cookie 请求头）

# 3. 更新 secrets.yml
vim /opt/news_pipeline/config/secrets.yml
# 修改 sources.xueqiu_cookie / sources.ths_cookie

# 4. 重启服务（secrets.yml 变更需要重启）
sudo systemctl restart news-pipeline

# 5. 确认 scraper_probe_ok
sudo journalctl -u news-pipeline -n 30 | grep probe
```

Cookie 有效期通常 7-30 天，需要定期更新。

---

## 成本超限（CostCeilingExceeded）

**症状**：Bark 告警 `llm_cost_exceeded`；日志中大量 `llm_failed` 且 error 含 `CostCeilingExceeded`；`/cost` 显示已达上限。

**处理流程**：

```bash
# 1. 查今日成本
/cost

# 2. 查哪个模型消耗最多
sqlite3 /opt/news_pipeline/data/news.db "
SELECT model_used, count(*) cnt
FROM news_processed
WHERE date(extracted_at) = date('now')
GROUP BY model_used;"

# 3. 临时提高上限（让当天继续处理）
vim /opt/news_pipeline/config/app.yml
# 改 daily_cost_ceiling_cny: 10.0
# 热加载，无需重启

# 4. 明天成本自动重置
# 或根本原因分析：为什么 Tier-2 被触发过多？
```

---

## 服务挂了（进程退出）

**症状**：systemctl status 显示 `failed` 或 `inactive`；收不到 Bark 心跳。

```bash
# 1. 查状态
sudo systemctl status news-pipeline

# 2. 查最近日志
sudo journalctl -u news-pipeline -n 50 --no-pager

# 3. 常见退出原因
# - ValidationError（配置文件格式错）
# - ImportError（依赖未安装）
# - OSError（data/ 目录不存在或权限不对）
# - 端口冲突

# 4. 修复后重启
sudo systemctl start news-pipeline

# 5. 如果频繁 crash-loop，查 RestartSec 是否太短
sudo journalctl -u news-pipeline --since "1 hour ago" | grep -E "started|stopped|failed"
```

---

## 抓取一直为空（各源 new=0）

**症状**：日志中所有 `scrape_done` 的 `new` 均为 0，watchlist 没有推送。

**排查顺序**：

```bash
# 1. 是否所有 source 都为 0？
sudo journalctl -u news-pipeline | grep scrape_done | tail -20

# 2. 是否有 source 被暂停？
sqlite3 /opt/news_pipeline/data/news.db "
SELECT source, paused_until FROM source_state WHERE paused_until > datetime('now');"

# 3. 是否 dedup 太激进（全部命中 simhash）？
sqlite3 /opt/news_pipeline/data/news.db "
SELECT source, count(*) FROM raw_news
WHERE fetched_at > datetime('now', '-1 hour')
GROUP BY source;"

# 4. API 是否真的没有新内容（非高峰时间段属正常）
# 美股在非交易时段（09:30-16:00 ET）新闻量少是正常的
```

---

## 相关

- [Components → Scrapers](../components/scrapers.md) — 各源详解
- [Operations → Monitoring](monitoring.md) — 日志查看
- [Operations → Daily Ops](daily-ops.md) — 常用操作

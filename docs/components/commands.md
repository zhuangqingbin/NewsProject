# Bot Commands

这一页列出 11 个 Bot 命令、使用方式，以及 Webhook 配置说明（当前未启用）。

---

## 命令列表

| 命令 | 参数 | 说明 |
|---|---|---|
| `/watch` | `<TICKER>` | 添加到 watchlist |
| `/unwatch` | `<TICKER>` | 从 watchlist 移除 |
| `/list` | — | 显示当前 watchlist |
| `/pause` | `<source> [minutes]` | 暂停指定 source N 分钟（默认 60） |
| `/resume` | `<source>` | 解除 source 暂停 |
| `/digest` | `now` | 立即触发当前市场 digest |
| `/cost` | — | 显示今日 LLM 成本 |
| `/chart` | `<TICKER> [window]` | 生成 K 线图（默认 30d） |
| `/status` | — | 显示各 source 状态（启用/暂停/错误） |
| `/dlq` | — | 显示 dead letter 未解决数量 |
| `/help` | — | 显示命令帮助 |

---

## 命令实现架构

```python
# commands/dispatcher.py
class CommandDispatcher:
    def register(self, name: str) -> Callable:
        """装饰器方式注册命令处理函数"""
        ...

    async def handle_text(self, text: str, *, ctx: dict) -> str | None:
        """解析 /cmd arg1 arg2 格式，路由到对应 handler"""
        # 文本不以 / 开头 → 返回 None（忽略）
        # 未知命令 → 返回 "未知命令: /xxx"
```

每个命令 handler 是一个 `async def handler(args: list[str], ctx: dict) -> str` 函数，返回字符串作为回复内容。

---

## 常用命令示例

```
# 添加 watchlist
/watch NVDA
/watch TSMC

# 查看 watchlist
/list
# → 回复: US: NVDA, TSMC | CN: 600519

# 暂停反爬触发的 source
/pause xueqiu 60
# → 回复: xueqiu 已暂停 60 分钟

# 恢复
/resume xueqiu

# 查今日成本
/cost
# → 回复: 今日 LLM 成本: 1.23 CNY / ceiling 5.00 CNY

# 生成 K 线图
/chart NVDA 30d
/chart NVDA 1y

# 查 source 状态
/status
# → 回复: finnhub: OK | sec_edgar: OK | caixin_telegram: OK | ...

# 立即触发 digest
/digest now
```

---

## Webhook 配置（未启用）

`commands/server.py` 实现了接收 Telegram / 飞书 Webhook 的 FastAPI 应用：

```python
# FastAPI endpoints（当前未启动）
POST /webhook/tg/us     # Telegram US bot webhook
POST /webhook/tg/cn     # Telegram CN bot webhook
POST /webhook/feishu/us # 飞书 US webhook
POST /webhook/feishu/cn # 飞书 CN webhook
```

### 安全验证

**Telegram**：
```python
# 验证 X-Telegram-Bot-Api-Secret-Token header
# 与 secrets.yml → push.tg_secret_token_us 对比
```

**飞书**：
```python
# 验证 token 字段（飞书经典 verification token 方案）
# 与 secrets.yml → push.feishu_verification_token 对比
```

### 将来启用的步骤

1. 在 systemd unit 中启动 FastAPI server（或用 uvicorn）：
   ```bash
   ExecStart=/opt/news_pipeline/.venv/bin/uvicorn news_pipeline.commands.server:app --host 0.0.0.0 --port 8080
   ```

2. Nginx 反代（建议加 HTTPS）：
   ```nginx
   location /webhook/ {
       proxy_pass http://127.0.0.1:8080;
   }
   ```

3. 注册 Telegram webhook：
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<domain>/webhook/tg/us" \
     -d "secret_token=<tg_secret_token_us>"
   ```

4. 飞书自定义机器人暂不支持 webhook 回调（飞书机器人是单向推送）。

!!! note "当前状态"
    v0.1.7 中命令通过 Telegram Bot polling 或直接 API 调用处理，
    webhook server 未在 systemd 中启动。

---

## 相关

- [Operations → Daily Ops](../operations/daily-ops.md) — 日常运维命令使用
- [Operations → Secrets](../operations/secrets.md) — secret token 配置
- [Components → Pushers](pushers.md) — webhook 安全配置

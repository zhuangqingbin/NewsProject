# Pushers

这一页描述 Telegram 和飞书两个推送通道：消息渲染格式、发送方式，以及 webhook 配置说明。

---

## 推送通道一览

| channel_id | 类型 | market | 配置方式 |
|---|---|---|---|
| `tg_us` | Telegram Bot | us | bot_token + chat_id |
| `tg_cn` | Telegram Bot | cn | bot_token + chat_id |
| `feishu_us` | 飞书自定义机器人 | us | webhook URL + sign secret |
| `feishu_cn` | 飞书自定义机器人 | cn | webhook URL + sign secret |

---

## CommonMessage 消息结构

所有 pusher 共用同一个 `CommonMessage` 对象，各自渲染：

```python
class CommonMessage:
    title: str                    # 新闻标题
    summary: str                  # LLM 生成的摘要
    source_label: str             # 如 "Finnhub"、"SEC EDGAR"
    source_url: HttpUrl           # 原文链接
    badges: list[Badge]           # 标签（sentiment、magnitude、event_type）
    chart_url: HttpUrl | None     # 已废弃，用 chart_image
    chart_image: bytes | None     # PNG 字节，用于 TG sendPhoto
    deeplinks: list[Deeplink]     # 相关链接
    market: Market                # us | cn
```

---

## Telegram Pusher

### 文字消息

使用 `sendMessage` API，格式为 **MarkdownV2**：

- 标题加粗：`*NVDA 财报超预期*`
- 特殊字符（`.`、`(`、`)`、`-` 等）需要转义（`\.`）
- Badges 用 Emoji 区分：`📈` bullish / `📉` bearish / `➡️` neutral
- 末尾附原文链接

```
*NVDA 财报超预期*
📈 bullish | HIGH | earnings

英伟达 Q3 EPS $4.02，超预期 $3.65。数据中心营收同比+122%。

[阅读原文](https://...)  |  [SEC Filing](https://...)
来源：Finnhub  |  2026-04-25 09:30 ET
```

### 图表嵌图

当 `CommonMessage.chart_image` 不为 None 时，使用 `sendPhoto`（multipart/form-data）：

```python
# TG sendPhoto 流程
files = {"photo": ("chart.png", chart_bytes, "image/png")}
data = {"chat_id": chat_id, "caption": text}
await client.post(f"{BASE_URL}/sendPhoto", files=files, data=data)
```

图片直接嵌入消息，不需要 OSS 或其他图床。

!!! note "v0.1.4 改动"
    v0.1.4 前用阿里云 OSS 存图片 URL。v0.1.4 起改为 inline 嵌图（`chart_image: bytes`），
    移除了 `oss2` 依赖，简化了配置。

---

## 飞书 Pusher（自定义机器人 Webhook）

使用飞书**自定义机器人**（不是飞书自建应用）。

### Webhook 签名

飞书自定义机器人支持签名校验（推荐开启）：

```python
# 签名算法：timestamp + "\n" + sign_secret → HMAC-SHA256 → base64
timestamp = str(int(time.time()))
sign_str = f"{timestamp}\n{sign_secret}"
signature = base64.b64encode(
    hmac.new(sign_str.encode(), digestmod=hashlib.sha256).digest()
).decode()
```

请求体：
```json
{
  "timestamp": "1714039812",
  "sign": "base64_hmac...",
  "msg_type": "interactive",
  "card": { ... }
}
```

### 卡片渲染（Card JSON）

飞书消息使用 Interactive Card：

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"content": "NVDA 财报超预期", "tag": "plain_text"},
    "template": "red"
  },
  "elements": [
    {"tag": "div", "text": {"content": "摘要内容...", "tag": "lark_md"}},
    {"tag": "note", "elements": [
      {"tag": "plain_text", "content": "来源: Finnhub | 2026-04-25 09:30 ET"}
    ]},
    {"tag": "action", "actions": [
      {"tag": "button", "text": {"content": "阅读原文", "tag": "plain_text"},
       "url": "https://..."}
    ]}
  ]
}
```

!!! warning "v0.1.6 移除飞书自建应用"
    v0.1.6 彻底移除了飞书自建应用集成（`feishu_auth.py`、`bitable archive`、
    飞书图片上传）。飞书推送现在**只用自定义机器人 webhook**，无需任何 OAuth 配置。

---

## PusherDispatcher

```python
class PusherDispatcher:
    async def dispatch(
        self, msg: CommonMessage, *, channels: list[str]
    ) -> dict[str, PushResult]:
        results = {}
        for ch in channels:
            pusher = self._pushers[ch]
            result = await pusher.send(msg)
            results[ch] = result
        return results
```

每条消息并发发送到所有目标 channel（`asyncio.gather`）。

---

## 速率限制

```yaml
# config/app.yml
push:
  per_channel_rate: "30/min"   # 每个 channel 每分钟最多 30 条
```

由 `aiolimiter` 实现的令牌桶算法，防止触发 Telegram / 飞书 API 限流。

---

## Bot 命令 Webhook（未启用）

`commands/server.py` 实现了一个 FastAPI webhook server，支持接收 Telegram 和飞书的 Webhook 回调，处理 `/watch`、`/list` 等命令。

当前**未在生产中启用**（webhook server 未被 systemd 拉起）。命令通过轮询（polling）或手动调用实现。

配置 Telegram webhook（将来启用时）：
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://<server>/webhook/tg/us" \
  -d "secret_token=<tg_secret_token_us>"
```

---

## 相关

- [Components → Bot Commands](commands.md) — 11 个命令详解
- [Operations → Secrets](../operations/secrets.md) — webhook URL 和 sign secret 配置
- [Operations → Troubleshooting](../operations/troubleshooting.md) — 签名错误调试

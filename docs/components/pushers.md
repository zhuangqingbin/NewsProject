# Pushers

这一页描述飞书推送通道（以及可选的 WeCom）：消息渲染格式、发送方式，以及 webhook 配置说明。

---

## 推送通道一览

| channel_id | 类型 | market | 配置方式 |
|---|---|---|---|
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
    chart_image: bytes | None     # PNG 字节（飞书暂不支持图片推送）
    deeplinks: list[Deeplink]     # 相关链接
    market: Market                # us | cn
```

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

由 `aiolimiter` 实现的令牌桶算法，防止触发飞书 API 限流。

---

## 相关

- [Components → Bot Commands](commands.md) — 11 个命令详解
- [Operations → Secrets](../operations/secrets.md) — webhook URL 和 sign secret 配置
- [Operations → Troubleshooting](../operations/troubleshooting.md) — 签名错误调试

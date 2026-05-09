# shared/ 共用层

> news_pipeline 和 quote_watcher 共用的基础设施。不直接对外提供业务功能，只被两个子系统 import。

---

## 1. 这是什么

`shared/` 解决两个子系统重叠的基础需求：推送到同一批飞书 webhook、使用同一套结构化日志、以及共享跨子系统的数据契约（`CommonMessage`、`Market` 枚举等）。

它是两个 bounded context 之间的**最小公共基础设施**，不含任何业务逻辑（scrapers / 规则 / LLM 都不在这里）。

---

## 2. 内容速查

| 模块 | 干啥 | 主要导出 |
|---|---|---|
| `shared/push/` | 飞书 / 企微推送实现 | `FeishuPusher`, `WecomPusher`, `PusherDispatcher`, `build_pushers`, `BurstSuppressor` |
| `shared/observability/` | structlog 日志 + Bark 运维告警 | `configure_logging`, `get_logger`, `BarkAlerter`, `AlertLevel` |
| `shared/common/` | 跨子系统数据契约 + 类型 | `CommonMessage`, `Badge`, `Deeplink`, `DigestItem`, `Market`, `utc_now`, `ensure_utc` |

### push/

```
shared/push/
├── feishu.py      # 飞书 webhook，支持签名验证
├── wecom.py       # 企微 webhook
├── dispatcher.py  # PusherDispatcher — asyncio.gather 并发发送到多个 channel
├── factory.py     # build_pushers(config) — 从 channels.yml + secrets.yml 构造 pusher 注册表
└── base.py        # PusherProtocol(Protocol) + SendResult(ok/response_body)
```

### observability/

```
shared/observability/
├── log.py          # configure_logging(level, json=True) + get_logger(name)
├── alert.py        # BarkAlerter(url).send(msg, level=AlertLevel.ERROR)
└── weekly_report.py # build_dlq_summary(dead_letters) → 格式化周报
```

### common/

```
shared/common/
├── contracts.py   # CommonMessage / Badge / Deeplink / DigestItem (pydantic v2)
├── enums.py       # Market(StrEnum): us / cn
└── timeutil.py    # utc_now() / ensure_utc(dt) — 统一时区处理
```

---

## 3. 重要约定

### CommonMessage.kind 字段

推送层根据 `kind` 选不同模板：

| kind | 来源 | 飞书渲染 |
|---|---|---|
| `news` | news_pipeline 即时推送 | 标题 + 摘要 + badge + deeplink |
| `alert` | quote_watcher 单条告警 | 规则 ID + 触发值 + severity |
| `alert_burst` | quote_watcher burst 合并 | 多条规则合并为一条 |
| `market_scan` | quote_watcher 全市场榜单 | 涨跌幅/量比 Top-N 列表 |
| `digest` | news_pipeline 汇聚推送 | 多条新闻 bullet 列表 |

### re-export shim

`news_pipeline.common.enums` 和 `news_pipeline.common.timeutil` 是 shim 模块，内容直接 re-export 自 `shared.common.*`，保持向后兼容。新代码**直接 import `shared.common.*`**。

---

## 4. 不要做什么

- **不要**从 `shared/` 反向 import `news_pipeline` 或 `quote_watcher` 的任何模块
- **不要**在 `shared/` 里加业务逻辑（scrapers、规则引擎、LLM 客户端都不该在这）
- **不要**在 `shared/` 里加子系统特有的配置读取逻辑

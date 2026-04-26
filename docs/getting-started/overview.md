# Overview

这一页说明 News Pipeline 能做什么、不能做什么、以及适合哪类用户。

---

## 系统能做什么

- **持续抓取**：从 9 个财经数据源（美股 + A 股）按分钟级间隔获取最新新闻，目前 5 个已启用
- **去重**：URL 精确匹配 + 标题 SimHash 模糊匹配，24 小时窗口内消除重复
- **LLM 结构化提取**：四层管线 — 标题分类 → 普通摘要 → 深度实体/关系抽取（一手源直达深度层）
- **重要性评分**：规则引擎 + LLM judge 灰区兜底，判定 `is_critical`
- **分级推送**：
  - 关键新闻：立即实时推送到 Telegram / 飞书
  - 普通新闻：进入 Digest 缓冲区，早晚各一次汇总推送
- **Bot 命令**：通过 Telegram / 飞书 发 `/watch NVDA`、`/cost`、`/chart NVDA 30d` 等 11 个命令
- **图表**：关键新闻自动附 K 线图（mplfinance 生成，TG sendPhoto inline 嵌图）
- **告警**：Bark iOS 推送 — 反爬触发 / 成本超限 / 推送失败 / 日常心跳
- **备份**：每日 SQLite → 阿里云 OSS，脚本保留 30 天

---

## 系统不能做什么

- **不是实时行情**：抓取间隔最快 60 秒（财联社），大多数源 3-5 分钟，不能替代 Level-2 行情
- **不做交易决策**：只做新闻推送和摘要，没有信号生成和下单能力
- **不支持多用户**：单人部署，watchlist 统一，没有用户权限体系
- **不能抓付费墙内容**：雪球、同花顺需要登录 cookie，且当前禁用；Tushare 新闻需要更高积分
- **图表不实时**：K 线数据来自 akshare，延迟 T+1

---

## 适合谁

| 用户画像 | 适合度 |
|---|---|
| 个人投资者，想第一时间收到持仓股的重要新闻 | 非常适合 |
| 想把 A 股公告 + 美股 SEC 文件都汇聚到一个频道 | 适合 |
| 需要搭建团队共用的新闻系统 | 需要二次开发（多用户 / 权限） |
| 需要毫秒级行情数据 | 不适合 |

---

## 技术栈速览

| 层 | 技术 |
|---|---|
| 语言 | Python 3.12 + asyncio |
| 抓取 | httpx + feedparser + akshare + BeautifulSoup |
| LLM | DashScope (DeepSeek-V3) / Anthropic (Claude) |
| 存储 | SQLite + SQLModel + Alembic |
| 调度 | APScheduler (AsyncIO 模式) |
| 推送 | python-telegram-bot + httpx (飞书 webhook) |
| 图表 | mplfinance + matplotlib |
| 监控 | structlog (JSON) + Bark |
| 部署 | uv + systemd (生产) / Docker Compose (Datasette) |

---

## 相关

- [Architecture](architecture.md) — 系统全貌和数据流
- [Deployment](deployment-current.md) — 当前生产部署方式
- [Components → LLM Pipeline](../components/llm-pipeline.md) — LLM 四层管线详解

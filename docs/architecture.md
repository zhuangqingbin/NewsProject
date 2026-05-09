# NewsProject 全栈架构教程

> 面向第一次克隆本项目的开发者。读完这篇，你能理解整个系统在干什么、为什么这样设计、以及怎么把它跑起来。

---

## 0. 这是什么项目？

这是一个**个人投资自动化工具**，包含 2 个独立子系统，统一推送到飞书 webhook：

```
                      ┌─────────────────────────────────┐
                      │         NewsProject              │
                      │                                  │
  多路新闻源 ──────▶  │  news_pipeline   ─────────────▶ │──▶ 飞书(US频道)
                      │  (新闻抓取+摘要)                  │
  Sina行情 ──────────▶ │  quote_watcher   ─────────────▶ │──▶ 飞书(CN频道)
                      │  (实时盯盘+告警)                  │
                      └─────────────────────────────────┘
```

- **news_pipeline**：定时抓取财经新闻 → 去重 → 规则/LLM 判断重要性 → 推送摘要到飞书
- **quote_watcher**：每 5 秒 poll A 股行情 → 4 类规则触发 → 即时告警到飞书

两个子系统**完全独立**：可以只跑其中一个，互不影响。

---

## 1. 顶层目录布局

```
NewsProject/
├── config/                    # 单一配置目录(所有 yaml 都在这)
│   ├── secrets.yml            # API key + webhook(不入 git)
│   ├── app.yml                # 调度参数 + LLM 模型选择
│   ├── channels.yml           # 飞书推送渠道路由
│   ├── sources.yml            # 新闻源 enable/interval
│   ├── watchlist.yml          # 新闻 rules + LLM watchlist
│   ├── quote_watchlist.yml    # 盯盘股列表 + 全市场扫描参数
│   ├── alerts.yml             # 4 类告警规则
│   ├── holdings.yml           # 持仓(composite 规则用)
│   └── prompts/               # LLM prompt 模板
├── data/                      # SQLite 数据文件(bind mount，重启不丢)
│   ├── news.db                # news_pipeline 数据库
│   └── quotes.db              # quote_watcher 数据库
├── src/
│   ├── news_pipeline/         # 子系统 1：新闻流水线
│   ├── quote_watcher/         # 子系统 2：实时盯盘
│   └── shared/                # 共用层(push + observability + 数据契约)
├── tests/                     # pytest 测试套件
├── docs/                      # 文档(本文件所在)
├── docker-compose.yml         # 3 个 service：app + quote_watcher + datasette
├── pyproject.toml             # Python 项目定义 + 依赖
└── Dockerfile                 # 单镜像，两个 service 共用
```

**设计原则**：
- 单一 `config/` 目录让运维只需关注一个地方
- 单一 Docker image，两个 service 用不同 `command` 启动不同入口
- `data/` bind mount 到宿主机，容器重建不丢数据

---

## 2. 两个子系统对比

| 维度 | news_pipeline | quote_watcher |
|---|---|---|
| **功能定位** | 财经新闻抓取、去重、摘要、推送 | A 股实时行情盯盘、规则触发告警 |
| **输入来源** | 14 个新闻源(Finnhub/SEC/财联社/东财等) | Sina 5s poll + akshare 60s 扫描 + 板块数据 |
| **处理过程** | 去重 → 规则匹配 → LLM 分层处理 → 分类路由 | AlertEngine 4 类规则评估 → cooldown 去重 → burst 合并 |
| **输出动作** | 推飞书(即时 / 摘要 / 深度分析) | 推飞书告警 |
| **数据库** | `news.db` (SQLite) | `quotes.db` (SQLite) |
| **启动命令** | `python -m news_pipeline.main` | `python -m quote_watcher.main` |
| **Docker service** | `app` | `quote_watcher` |
| **内存限制** | 1.5 GB | 512 MB |
| **配置文件** | `sources.yml` `watchlist.yml` `app.yml` | `quote_watchlist.yml` `alerts.yml` `holdings.yml` |

---

## 3. 数据流

### 3.1 news_pipeline 数据流

```
┌──────────────────────────────────────────────────────────────┐
│  scrapers (14 个源，各自 interval)                            │
│  finnhub / sec_edgar / futu_global / wallstreetcn            │
│  caixin_telegram / eastmoney_global / ths_global / sina      │
│  juchao / akshare_news / kr36 / cctv_news / ...             │
└─────────────────────┬────────────────────────────────────────┘
                      │ RawNews → news.db raw_news
                      ▼
              ┌───────────────┐
              │  Dedup 去重    │  url_hash 严格去重 + simhash 标题模糊去重
              └───────┬───────┘
                      │ pending → processing
                      ▼
              ┌───────────────┐
              │  RulesEngine  │  AhoCorasick 关键词匹配
              │  (watchlist)  │  ticker / sector / macro 命中
              └───────┬───────┘
                      │ rule_hits → score
                      ▼
              ┌───────────────────────────────────────┐
              │  LLM Pipeline (分层路由)               │
              │  Tier-0: deepseek-v3 classify         │ ← 判断是否值得继续
              │  Tier-1: deepseek-v3 summarize        │ ← 生成摘要
              │  Tier-2: claude-haiku deep extract    │ ← 关键事件 + 报价提取
              │  Tier-3: claude-sonnet deep analysis  │ ← 深度分析(仅 critical)
              └───────┬───────────────────────────────┘
                      │ news_processed
                      ▼
              ┌───────────────┐
              │  Classifier   │  重要性分级(critical / standard / digest)
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │  Router       │  market 路由 → 选 channel
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │  Feishu Push  │  即时推 / 汇聚摘要 / 死信队列
              └───────────────┘
```

### 3.2 quote_watcher 数据流

```
┌─────────────────────────────────────────────────────┐
│  feeds (并行采集)                                     │
│  sina.py     — 每 5s poll watchlist ticker 行情      │
│  market_scan — 每 60s akshare 全 A 股快照             │
│  sector.py   — 每 60s 板块涨跌幅                      │
│  calendar.py — 启动时拉 250 天日 K (indicator 预热)   │
└──────────────────┬──────────────────────────────────┘
                   │ 原始行情数据
                   ▼
          ┌─────────────────────────────────────────┐
          │  AlertEngine                             │
          │  ├── threshold  数值阈值规则              │
          │  ├── indicator  技术指标规则(MA/RSI/MACD) │
          │  ├── event      涨跌停 / 板块异动          │
          │  └── composite  持仓风控 / 组合浮亏        │
          └──────────────┬──────────────────────────┘
                         │ 触发 → cooldown 检查
                         ▼
                ┌──────────────────┐
                │  BurstSuppressor  │  同股多规则合并 alert_burst
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │  Feishu Push     │  立即推送
                └──────────────────┘
```

---

## 4. 共用层(shared/)

**为什么要有 shared？**

news_pipeline 和 quote_watcher 是两个独立的 bounded context，业务逻辑完全分开。但它们都需要：
1. 推送到同一批飞书 webhook
2. 用同一套结构化日志 + Bark 告警
3. 共享 `CommonMessage` 数据契约和 `Market` 枚举

把这些放进 `shared/` 既避免重复，又不破坏各子系统的独立性。

```
shared/
├── push/               # 推送层
│   ├── feishu.py       # 飞书 webhook 实现
│   ├── wecom.py        # 企微 webhook 实现
│   ├── dispatcher.py   # PusherDispatcher — 并发 dispatch 到多 channel
│   ├── factory.py      # build_pushers(config) 工厂函数
│   └── base.py         # PusherProtocol + SendResult
├── observability/      # 可观测性
│   ├── log.py          # configure_logging / get_logger (structlog)
│   ├── alert.py        # BarkAlerter + AlertLevel
│   └── weekly_report.py# 死信队列周报摘要
└── common/             # 跨子系统数据契约
    ├── contracts.py    # CommonMessage / Badge / Deeplink / DigestItem
    ├── enums.py        # Market(us/cn)
    └── timeutil.py     # utc_now / ensure_utc
```

**重要约定**：
- `news_pipeline.common.{enums,timeutil}` 是 re-export shim，指向 `shared.common.*`，保持向后兼容
- `shared/` 只被两个子系统 import，**绝不**反向 import 任何业务模块

---

## 5. 配置文件全表

所有配置文件都在 `config/` 目录下。

| 文件 | 使用者 | 必须 | 内容摘要 |
|---|---|---|---|
| `secrets.yml` | 两边都用 | ✅ | 飞书 webhook/sign、dashscope/anthropic key、finnhub token、Bark URL |
| `app.yml` | news_pipeline | ✅ | 调度间隔、LLM 模型(tier0~3)、去重参数、推送速率、数据保留策略 |
| `channels.yml` | 两边都用 | ✅ | 推送渠道定义(`feishu_us` / `feishu_cn`)+ market 路由 |
| `sources.yml` | news_pipeline | ✅ | 14 个新闻源的 `enabled` 开关和 `interval_sec` |
| `watchlist.yml` | news_pipeline | ✅ | `rules` 段(AhoCorasick 关键词) + `llm` 段(LLM watchlist 股票) |
| `quote_watchlist.yml` | quote_watcher | ✅ | 盯盘股列表(cn/us) + `market_scans` 全市场扫描参数 |
| `alerts.yml` | quote_watcher | ✅ | 4 类规则定义(threshold/indicator/event/composite) |
| `holdings.yml` | quote_watcher | ⚠️ 可选 | 持仓列表 + 组合总资金(只有 composite 规则需要) |
| `prompts/` | news_pipeline | ✅ | LLM prompt 模板，按 tier 和版本组织 |
| `entity_aliases.yml` | news_pipeline | 可选 | 实体别名映射(如 "NVIDIA Corp" → "NVDA") |
| `secrets.yml.example` | — | — | 模板，复制后改成真实值 |

### 关键字段速查

**`secrets.yml`**（必填项）：
```yaml
llm:
  dashscope_api_key: sk-xxx        # DeepSeek-V3 走 DashScope
push:
  feishu_hook_us: https://...      # 对应 channels.yml feishu_us
  feishu_sign_us: xxx
  feishu_hook_cn: https://...
  feishu_sign_cn: xxx
alert:
  bark_url: https://api.day.app/<key>   # 运维告警(可选)
```

**`app.yml`** LLM 模型配置：
```yaml
llm:
  tier0_model: deepseek-v3         # 分类(便宜快)
  tier1_model: deepseek-v3         # 摘要
  tier2_model: claude-haiku-4-5-20251001  # 深度提取
  tier3_model: claude-sonnet-4-6   # 深度分析(仅 critical)
```

---

## 6. 第一次启动

### 6.1 本地开发模式（推荐先用这个验证）

```bash
# Step 1: 克隆 + 进目录
git clone <repo_url>
cd NewsProject

# Step 2: 安装依赖(需要 uv，没有就 pip install uv)
uv sync

# Step 3: 填写密钥
cp config/secrets.yml.example config/secrets.yml
# 至少填: feishu_hook_cn / feishu_hook_us + dashscope_api_key
$EDITOR config/secrets.yml

# Step 4: 初始化数据库
uv run alembic upgrade head

# Step 5: 起 news_pipeline
uv run python -m news_pipeline.main
# 等 2-3 分钟，看日志出现 "push_ok" 字样
# 验证：飞书频道收到第一条新闻推送

# Step 6(可选): 另开终端起 quote_watcher
uv run python -m quote_watcher.main
# 验证：日志出现 "kline_warmup_ok" + "poll_tick"
```

**如果不通，看这里排查：**

| 现象 | 看哪里 |
|---|---|
| news_pipeline 没推 | `src/news_pipeline/README.md` § 故障排查 |
| quote_watcher 指标不触发 | `docs/quote_watcher/getting_started.md` § 4 故障排查 |
| 推送格式异常 | `src/shared/README.md` + `data/news.db push_log` 表 |
| LLM 报错 | 检查 `secrets.yml` 的 `dashscope_api_key` |

### 6.2 最简模式（零 LLM 成本）

编辑 `config/watchlist.yml`，保持 `rules.enable: true` 且 `llm.enable: false`：
- 只做关键词匹配，不调 LLM
- 不需要 `dashscope_api_key`

---

## 7. 部署 — Docker

```bash
# 首次部署(构建镜像 5-10 分钟)
docker compose up -d

# 看日志
docker compose logs -f app
docker compose logs -f quote_watcher

# 只起盯盘，不起新闻
docker compose up -d quote_watcher

# 重启(改了 config/*.yml 后)
docker compose restart app

# 改了 src/*.py 后需要重建
docker compose up -d --build
```

三个 Docker service：

| Service | 入口 | 内存限制 | 说明 |
|---|---|---|---|
| `app` | `news_pipeline.main` | 1.5 GB | 新闻流水线 |
| `quote_watcher` | `quote_watcher.main` | 512 MB | 实时盯盘 |
| `datasette` | Datasette web UI | 256 MB | 浏览 news.db，地址 http://127.0.0.1:8001 |

数据持久化（bind mount，`docker compose down` 不删除）：

| 宿主机路径 | 容器内路径 | 内容 |
|---|---|---|
| `./config/` | `/app/config` (只读) | yaml 配置 |
| `./data/` | `/app/data` | SQLite 数据库 |
| `./logs/` | `/app/logs` | structlog JSON 日志 |

---

## 8. 看数据（仪表盘）

### 8.1 Datasette Web UI

```
http://127.0.0.1:8001
```

浏览 `news.db` 所有表，支持 SQL 查询。

### 8.2 常用 SQLite 查询

```bash
# 最近 20 条已推送的新闻
sqlite3 data/news.db "
  SELECT r.source, r.title, p.is_critical, p.push_status
  FROM news_processed p JOIN raw_news r ON p.raw_id = r.id
  ORDER BY p.extracted_at DESC LIMIT 20;"

# 今日推送统计(按来源)
sqlite3 data/news.db "
  SELECT r.source, count(*) as cnt
  FROM push_log l JOIN raw_news r ON l.raw_id = r.id
  WHERE date(l.pushed_at) = date('now')
  GROUP BY r.source ORDER BY cnt DESC;"

# 死信队列(推送失败)
sqlite3 data/news.db "
  SELECT kind, payload_summary, created_at, retry_count
  FROM dead_letter ORDER BY created_at DESC LIMIT 10;"

# quote_watcher 今日触发的规则
sqlite3 data/quotes.db "
  SELECT rule_id, ticker, datetime(last_triggered_at,'unixepoch','+8 hours') as last_at,
         trigger_count_today
  FROM alert_state ORDER BY last_triggered_at DESC LIMIT 20;"
```

---

## 9. 接下来读哪里

按需深入：

| 你想了解 | 读这里 |
|---|---|
| 新闻流水线完整配置 + 启动 + 排查 | [news_pipeline 子系统](subsystems/news_pipeline.md) |
| 实时盯盘配置 + 4 类规则 + 排查 | [quote_watcher 子系统](subsystems/quote_watcher.md) |
| 4 类规则详细字段参考 | [Quote Watcher Getting Started](quote_watcher/getting_started.md) |
| 共用层(push/observability/common) | [shared 共用层](subsystems/shared.md) |
| 系统设计决策(深入) | `docs/superpowers/specs/`(直接 git 树查看) |
| 日常运维命令速查 | 顶层 `README.md` § 日常运维 |

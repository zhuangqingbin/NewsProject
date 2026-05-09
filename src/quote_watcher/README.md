# quote_watcher 子系统

> 实时盯盘 + 规则告警：Sina 5s poll → AlertEngine → 飞书即时推送。
> 架构全貌见 [`docs/architecture.md`](../../docs/architecture.md)。

---

## 1. 它能做什么

| 功能 | 数据来源 | 间隔 | 说明 |
|---|---|---|---|
| watchlist 盯盘 | Sina 行情 API | 5s | 最多 50 只股实时 poll，触发立即推 |
| 全市场扫描 | akshare 快照 | 60s | 全 A 股涨跌幅 / 量比榜，超阈值推 digest |
| 板块异动 | akshare 板块数据 | 60s | 板块涨跌幅触发告警 |
| 日 K 预热 | akshare 历史数据 | 启动一次 | 拉 250 天日 K，供 indicator 规则使用 |
| 持仓风控 | `holdings.yml` + Sina | 随盯盘 | 持仓浮亏 + 组合浮亏告警 |

---

## 2. 数据流

```
┌─────────────────────────────────────────────────────┐
│  feeds(并行)                                         │
│  sina.py        ── 5s  ──▶ watchlist ticker 行情     │
│  market_scan.py ── 60s ──▶ 全 A 股快照              │
│  sector.py      ── 60s ──▶ 板块涨跌幅                │
│  calendar.py    ── 启动 ──▶ 250天日K(indicator预热)  │
└──────────────────┬──────────────────────────────────┘
                   │ 行情数据
                   ▼
          ┌─────────────────────────────────────────┐
          │  AlertEngine                             │
          │  ├── threshold  数值阈值(价格/量比/涨跌幅) │
          │  ├── indicator  技术指标(MA/RSI/MACD)     │
          │  ├── event      涨跌停 / 板块异动事件      │
          │  └── composite  持仓风控 / 组合浮亏        │
          └──────────────┬──────────────────────────┘
                         │ 规则触发
                         ▼
                ┌─────────────────────────┐
                │  cooldown 检查           │ ← per-rule cooldown_min
                └────────────┬────────────┘
                             │ 通过
                             ▼
                ┌─────────────────────────┐
                │  BurstSuppressor        │ ← 同股多规则 → alert_burst
                └────────────┬────────────┘
                             │
                             ▼
                ┌─────────────────────────┐
                │  Feishu Push            │ → 飞书 CN 频道
                └─────────────────────────┘
                       alert_history(DB)
```

---

## 3. 配置文件

### 3.1 `config/quote_watchlist.yml`

```yaml
cn:
  - ticker: "600519"
    name: 贵州茅台
    market: SH              # SH = 上交所, SZ = 深交所
  - ticker: "300750"
    name: 宁德时代
    market: SZ
us: []                      # 暂不支持 US ticker 盯盘

market_scans:
  cn:
    top_gainers_n: 50       # 内部取前 N 排序
    top_losers_n: 50
    top_volume_ratio_n: 50
    push_top_n: 5           # 只推前 5 条
    only_when_score_above: 8.0  # 涨跌幅 ≥ 8% 或量比 ≥ 8 才推
```

详细字段参考见 [`docs/quote_watcher/getting_started.md`](../../docs/quote_watcher/getting_started.md) § 1.1。

### 3.2 `config/alerts.yml`

每条规则一个 `kind`，支持 4 类（详见下方 § 5 速查表）：

```yaml
alerts:
  - id: maotai_drop_3pct
    kind: threshold
    ticker: "600519"
    name: 贵州茅台
    expr: "pct_change_intraday <= -3.0"
    cooldown_min: 30
    severity: warning
```

**热加载**：直接编辑保存后，quote_watcher 自动检测并重载规则，无需重启。

详细字段参考见 [`docs/quote_watcher/getting_started.md`](../../docs/quote_watcher/getting_started.md) § 1.2。

### 3.3 `config/holdings.yml`（可选）

仅 `composite` 规则需要：

```yaml
holdings:
  - ticker: "600519"
    name: 贵州茅台
    qty: 100
    cost_per_share: 1850.0

portfolio:
  total_capital: 200000
  base_currency: CNY
```

详细字段参考见 [`docs/quote_watcher/getting_started.md`](../../docs/quote_watcher/getting_started.md) § 1.3。

---

## 4. 启动

### 4.1 本地

```bash
uv sync
cp config/secrets.yml.example config/secrets.yml && $EDITOR config/secrets.yml
# 确保 feishu_hook_cn 已填
uv run python -m quote_watcher.main
```

环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QUOTE_WATCHER_DB` | `data/quotes.db` | SQLite 数据库路径 |
| `QUOTE_POLL_INTERVAL_SEC` | `5` | Sina ticker poll 间隔(秒) |
| `QUOTE_SCAN_INTERVAL_SEC` | `60` | 全市场扫描间隔(秒) |
| `QUOTE_SECTOR_INTERVAL_SEC` | `60` | 板块异动扫描间隔(秒) |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### 4.2 Docker

```bash
docker compose up -d quote_watcher
docker compose logs -f quote_watcher
```

改了 `config/alerts.yml`：quote_watcher 会自动热加载，**无需任何操作**。
改了 `config/quote_watchlist.yml` 后需要重启：`docker compose restart quote_watcher`。

---

## 5. 4 类规则速查

| kind | 适用场景 | 必填字段 | 示例 expr |
|---|---|---|---|
| `threshold` | 价格/涨跌幅/量比等实时数值 | `ticker` `expr` `cooldown_min` | `pct_change_intraday <= -3.0` |
| `indicator` | 技术指标(MA/RSI/MACD/交叉) | `ticker` `expr` `cooldown_min` | `ma5 > ma20` / `rsi(14) < 25` |
| `event` | 涨跌停、板块异动等离散事件 | `target_kind`(`ticker`/`sector`) `expr` | `is_limit_up` / `sector_pct_change >= 3.0` |
| `composite` | 持仓风控、组合浮亏 | `holding`(单股) 或 `portfolio: true` | `pct_change_from_cost <= -8.0` |

**threshold 可用变量**：`price_now / price_open / high_today / low_today / prev_close / pct_change_intraday / volume_today / volume_avg5d / volume_ratio / bid1 / ask1 / is_limit_up / is_limit_down / now_hhmm`

**indicator 额外变量**：`ma5/10/20/60/120` / `macd_dif/dea/hist` / `rsi(n)` / `cross_above(a,b)` / `highest_n_days(n)`

完整变量列表见 [`docs/quote_watcher/getting_started.md`](../../docs/quote_watcher/getting_started.md) § 1.2。

---

## 6. 进阶

### preview_rules — 先 dry-run 再上线

新规则上线前在历史数据上测试触发频率：

```bash
uv run python -m quote_watcher.tools.preview_rules \
    --tickers 600519,300750 \
    --since 2026-04-01 --until 2026-05-08
```

如果一条规则一周触发 50 次，先调高 `cooldown_min` 或收紧阈值再部署。

### 热加载 alerts.yml

直接编辑 `config/alerts.yml` 并保存，quote_watcher 会在下一个 tick 检测文件变化并自动 swap 规则，无需重启。

### 数据库迁移（quotes.db）

新版本有 schema 变更时：

```bash
# 本地
uv run alembic -n quote upgrade head

# Docker 容器内
docker compose exec quote_watcher uv run alembic -n quote upgrade head
```

---

## 7. 完整字段参考

见 [`docs/quote_watcher/getting_started.md`](../../docs/quote_watcher/getting_started.md)，包含：
- § 1 所有配置文件完整字段说明
- § 2 启动详细步骤
- § 3 preview_rules 调试说明
- § 4 故障排查（含 `quotes.db` 常用查询）
- § 5 数据表说明（`quote_bars_daily` / `alert_state` / `alert_history`）

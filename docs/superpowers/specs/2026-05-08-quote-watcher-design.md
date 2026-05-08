# Quote Watcher — 实时盯盘子系统设计

- **作者**：qingbin
- **日期**：2026-05-08
- **状态**：Draft（brainstorming approved，待 implementation plan）
- **目标版本**：v0.4.0
- **关系**：与 `news_pipeline` 平级的全新子系统；通过 `shared/` 共用基础设施

---

## 0. 一句话目标

在已有的新闻推送能力之上加一个独立的 **A 股实时盯盘**子系统：基于免费数据源（Sina 行情 HTTP poll + akshare/tushare 日 K 历史），对 watchlist + 全市场 + 持仓三个维度做 4 类规则匹配（数值阈值 / 技术指标 / 事件板块 / 持仓+组合），命中后通过共用的飞书 webhook 推送，自带去重和冷却。

## 0.1 解决的痛点

当前 `news_pipeline` 只能基于**新闻文本**做关键词匹配，无法响应"价格本身的异动"。

- 茅台盘中跳水 -3% 没有新闻：news_pipeline 静默
- 寒武纪量比放大 5 倍异动：news_pipeline 静默
- 持仓股浮亏到止损线：news_pipeline 静默
- 半导体板块整体下跌：news_pipeline 静默

新增 `quote_watcher` 子系统补齐这块，与 news_pipeline 解耦，互不影响。

## 0.2 关键决策（来自 brainstorming）

| 决策 | 选择 | 理由 |
|---|---|---|
| 用途 | 盘中决策辅助 + 全市场扫描 + 持仓风控 | 跳过 tick 级/打板/T+0 流派 |
| 市场覆盖 | Phase 1 = A 股 only，US 后续 | A 股交易为主，US 后续 |
| 数据源 | Sina HTTP poll 5s（盯盘）+ Sina 全市场快照 1min（扫描）+ akshare/tushare 日 K（指标）| 全部免费 |
| 规则类型 | 4 类全做：数值阈值 / 技术指标 / 事件板块 / 持仓+组合 | 覆盖大部分实操需求 |
| 架构形态 | 与 `news_pipeline` 平级的独立子系统 | News 和 Quote 是两个 bounded context，不该嵌套 |
| 共享内容 | 仅共享 push、observability、common 数据契约 | watchlist 各管各的，避免双向耦合 |
| 表达式语法 | `asteval` 沙箱 Python 表达式 | 工程师友好、可热加载、安全隔离 |
| 去重策略 | 二层叠加：AlertState cooldown（规则级）+ BurstSuppressor（同股多规则合并）| 各自防各自的"刷屏" |

---

## 1. 架构

### 1.1 顶层目录布局

```
NewsProject/
├── config/                                  # 单一 config 目录（运维方便）
│   ├── app.yml          channels.yml        # 共用
│   ├── watchlist.yml    sources.yml         # news_pipeline 用（不动）
│   ├── quote_watchlist.yml                  # ← 新：盯盘股票列表
│   ├── alerts.yml                           # ← 新：4 类规则定义
│   └── holdings.yml                         # ← 新：持仓表
│
├── data/
│   ├── news.db                              # news_pipeline 数据（不动）
│   └── quotes.db                            # ← 新：quote_watcher 自己的库
│
├── docker-compose.yml
│   # 两个 service:
│   #   news_pipeline (现有)
│   #   quote_watcher (新)
│
├── src/
│   ├── news_pipeline/                       # 子系统 1（现有，仅改 imports）
│   │   ├── scrapers/  dedup/  rules/  llm/  classifier/
│   │   ├── router/  scheduler/  storage/  main.py
│   │   └── （删除：pushers/, observability/, common/* 中的共享部分）
│   │
│   ├── quote_watcher/                       # 子系统 2（全新）
│   │   ├── feeds/                           # 报价采集
│   │   ├── store/                           # 行情本地存储
│   │   ├── alerts/                          # 规则引擎
│   │   ├── state/                           # 触发状态机
│   │   ├── emit/                            # AlertVerdict → CommonMessage
│   │   ├── scheduler/                       # APScheduler 任务
│   │   ├── storage/                         # quote_bars / alert_state 表 + DAO
│   │   └── main.py                          # 独立入口
│   │
│   └── shared/                              # 共用基础设施（从 news_pipeline 抽出）
│       ├── push/                            # ← 整目录从 news_pipeline/pushers/ 迁出
│       ├── observability/                   # ← 整目录从 news_pipeline/observability/ 迁出
│       └── common/                          # ← 抽 enums/timeutil/contracts 公共部分
│
└── tests/
    ├── unit/
    │   ├── news_pipeline/                   # 现有（部分子目录改名）
    │   ├── quote_watcher/                   # ← 新
    │   └── shared/                          # ← 新（从 news_pipeline/ 迁出）
    └── integration/
        ├── news_pipeline/                   # 现有
        └── quote_watcher/                   # ← 新
```

部署模型：

```
docker-compose
├── news_pipeline   service（现有，独立进程）
└── quote_watcher   service（新，独立进程）
        │                 │
        └─── 共用 ───→ shared/push → 飞书 webhook
                       config/channels.yml + secrets.yml
```

### 1.2 quote_watcher 内部数据流

```
[Sina HTTP /list=...]  (每 5 秒，盘中)
      │
      ▼
  feeds/sina.py  ──┐
                   │
[akshare 全市场]   │
  (每 60 秒)       │
      │            ▼
  feeds/sina_market.py
                   │
                   ▼
            QuoteSnapshot
                   │
                   ▼
            store/tick.py   (内存 ring buffer)
            store/bar.py    (1min K 落 SQLite)
                   │
                   ▼
            alerts/engine.py
              ├─ threshold matcher
              ├─ indicator matcher  ←─ store/daily_kline.py（昨日及之前的日 K）
              ├─ event matcher
              └─ composite matcher  ←─ holdings.yml + asteval ctx
                   │
                   ▼
            state/tracker.py（cooldown 检查）
                   │
                   ▼
            emit/message.py（AlertVerdict → CommonMessage）
                   │
                   ▼
            shared/push/dispatcher.py
              ├─ shared/push/burst.py（同 ticker N 秒合并）
              └─ shared/push/feishu.py
                   │
                   ▼
                 飞书
```

---

## 2. 数据采集层（feeds/）

### 2.1 数据源策略

| 数据 | 来源 | 频率 | 实现 |
|---|---|---|---|
| watchlist 实时报价 | Sina `hq.sinajs.cn/list=sh600519,sz000001,...` 一次拉所有 | 5s（盘中），关闭（休市） | aiohttp 单连，~3KB/次 |
| 全市场快照 | akshare `stock_zh_a_spot_em` 或东财批量接口 | 60s（盘中） | ~5000 行，内存计算 top N |
| 日 K 历史（指标用） | akshare `stock_zh_a_hist` 或 tushare `pro_bar` | 收盘后 1 次/天 | watchlist 范围内每股 250 天 |
| 板块信息 + 资金流（事件类规则） | 东财 `bk_quotation` API | 60s | Phase 1.6 |

### 2.2 QuoteSnapshot 数据契约

```python
@dataclass(frozen=True)
class QuoteSnapshot:
    ticker: str                  # "600519"
    market: str                  # "SH" | "SZ" | "BJ"
    name: str                    # 股票名（来自 quote_watchlist.yml，feed 不解析）
    ts: datetime                 # 数据时间（北京时区 aware）
    price: float                 # 当前价（last）
    open: float
    high: float
    low: float
    prev_close: float
    volume: int                  # 当日累计成交量（手）
    amount: float                # 当日累计成交额（元）
    bid1: float
    ask1: float
    pct_change: float            # 当日涨跌幅 %（= (price - prev_close) / prev_close * 100）
```

### 2.3 MarketCalendar

```python
class MarketCalendar:
    def is_open(self, now: datetime) -> bool: ...
    def session(self, now: datetime) -> Literal["pre", "morning", "noon_break", "afternoon", "post", "closed"]: ...
```

- A 股交易时段：周一到周五 09:30-11:30 / 13:00-15:00（北京时间）
- 节假日用 `chinese_calendar` 库
- 非交易时段：feed 任务直接 return（不报错），alerts 同步停跑

### 2.4 异常处理

| 场景 | 行为 |
|---|---|
| 单次请求超时 | retry 1 次（2s 间隔），失败 log warn |
| 连续 5 次失败 | 退避 30s，bark warn 1 次（不刷屏） |
| HTTP 5xx / 空 body / 反爬 | 视为失败，进入退避 |
| 节假日整天没数据 | calendar 已 skip，不进 retry 循环 |
| 个股停牌（price 为 0 或某股不在响应中）| 该股本轮跳过，不报错 |

---

## 3. 行情存储（store/）

### 3.1 三层存储

| 层 | 介质 | 容量 | 用途 |
|---|---|---|---|
| tick ring | 内存（dict[ticker, deque(maxlen=1000)]） | ~80KB × 50 股 = 4MB | 当日 tick 序列，重启即失（可接受）|
| 1min K | SQLite `quote_bars_1min` 表 | ~5KB/股/日 × 50 股 × 30 天 = ~7.5MB | 量比 / 短期波动 / 重启恢复 |
| 日 K | SQLite `quote_bars_daily` 表 | ~250 行/股 × 50 股 = 12,500 行 | 技术指标计算（MA/MACD/RSI）|

### 3.2 SQLite schema（`storage/models.py`）

```python
class QuoteBar1min(Base):
    __tablename__ = "quote_bars_1min"
    id: int (PK)
    ticker: str
    bar_start: datetime              # 北京时间，分钟边界
    open / high / low / close: float
    volume: int
    amount: float
    __table_args__ = (
        UniqueConstraint("ticker", "bar_start"),
        Index("idx_ticker_ts", "ticker", "bar_start"),
    )

class QuoteBarDaily(Base):
    __tablename__ = "quote_bars_daily"
    id: int (PK)
    ticker: str
    trade_date: date
    open / high / low / close / prev_close: float
    volume: int
    amount: float
    __table_args__ = (UniqueConstraint("ticker", "trade_date"),)

class AlertState(Base):
    __tablename__ = "alert_state"
    rule_id: str (PK part)
    ticker: str (PK part)
    last_triggered_at: int           # unix sec
    last_value: float | None         # 触发时 expr 评估值
    trigger_count_today: int = 1     # 每天 00:00 重置
    __table_args__ = (
        PrimaryKeyConstraint("rule_id", "ticker"),
        Index("idx_alert_state_ticker", "ticker"),
    )

class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: int (PK)
    rule_id: str
    ticker: str
    triggered_at: datetime
    snapshot_json: str               # 触发时的 QuoteSnapshot dump
    pushed: bool                     # 是否进入推送（false = 被 burst 折叠）
    push_message_id: str | None      # 关联 push_log
```

### 3.3 数据库分库

quote_watcher 用 `data/quotes.db`（独立于 `data/news.db`），避免高频写 quote_bars_1min 时给 news 表加写锁。两个进程也可分别配置 SQLite WAL。

### 3.4 数据清理

- `quote_bars_1min`：保留 30 天，每天 00:00 删除
- `quote_bars_daily`：保留 365 天
- `alert_state.trigger_count_today`：每天 00:00 重置为 0
- `alert_history`：保留 90 天

---

## 4. 规则引擎（alerts/）

### 4.1 配置 schema：`config/alerts.yml`

4 类规则统一成一个数据结构，按 `kind` 分派：

```yaml
alerts:
  # ─── 数值阈值类 ───
  - id: maotai_drop_3pct
    kind: threshold
    ticker: "600519"
    name: 贵州茅台
    expr: "pct_change_intraday <= -3.0"
    cooldown_min: 30
    severity: warning

  - id: catl_volume_spike
    kind: threshold
    ticker: "300750"
    expr: "volume_ratio >= 2.0"
    cooldown_min: 60

  - id: maotai_break_resistance
    kind: threshold
    ticker: "600519"
    expr: "price_high_today > 1800 and price_high_today_yday <= 1800"
    cooldown_min: 240

  # ─── 技术指标类 ───
  - id: byd_ma_golden_cross
    kind: indicator
    ticker: "002594"
    expr: "cross_above(ma5, ma20)"
    cooldown_min: 1440
    needs: [daily_kline_60d]

  - id: smic_rsi_oversold
    kind: indicator
    ticker: "688981"
    expr: "rsi(14) < 25"
    cooldown_min: 240

  # ─── 事件 / 板块类 ───
  - id: cambricon_limit_up
    kind: event
    ticker: "688256"
    expr: "is_limit_up"
    cooldown_min: 1440

  - id: semi_sector_surge
    kind: event
    target_kind: sector              # ← 不是个股，是板块
    sector: 半导体
    expr: "sector_pct_change >= 3.0"
    cooldown_min: 60

  # ─── 持仓 + 组合类 ───
  - id: maotai_position_alert
    kind: composite
    holding: "600519"                # ← 引用 holdings.yml
    expr: |
      pct_change_from_cost <= -8
      and volume_ratio >= 1.5
    cooldown_min: 60

  - id: total_pnl_alert
    kind: composite
    portfolio: true                  # ← 整个组合
    expr: "total_unrealized_pnl_pct <= -3"
    cooldown_min: 240
```

### 4.2 Pydantic schema（`config/schema.py`，新增）

```python
class AlertKind(StrEnum):
    THRESHOLD = "threshold"
    INDICATOR = "indicator"
    EVENT = "event"
    COMPOSITE = "composite"


class AlertRule(_Base):
    id: str
    kind: AlertKind
    expr: str
    cooldown_min: int = 30
    severity: Literal["info", "warning", "critical"] = "warning"

    # threshold / indicator / event 三类用 ticker，event sector 用 sector，composite 用 holding/portfolio
    ticker: str | None = None
    name: str | None = None
    target_kind: Literal["ticker", "sector"] = "ticker"
    sector: str | None = None
    holding: str | None = None
    portfolio: bool = False
    needs: list[str] = []

    @model_validator(mode="after")
    def validate_target_consistency(self): ...    # 见 §4.3


class AlertsFile(_Base):
    alerts: list[AlertRule]

    @model_validator(mode="after")
    def unique_ids(self): ...
    @model_validator(mode="after")
    def expr_syntax_ok(self): ...                # 启动时 asteval 干跑一遍语法
```

### 4.3 启动校验

| 校验 | 失败行为 |
|---|---|
| `alerts[].id` 唯一 | 拒启动 |
| `kind=threshold/indicator` 必须有 `ticker` | 拒启动 |
| `kind=event` 必须有 `ticker`（target_kind=ticker）或 `sector`（target_kind=sector） | 拒启动 |
| `kind=composite` 必须有 `holding` 或 `portfolio=true` | 拒启动 |
| `holding` 引用必须存在于 `holdings.yml` | 拒启动 |
| `portfolio=true` 但 `holdings.yml.portfolio.total_capital` 缺失 | 拒启动 |
| `expr` asteval 干跑解析报错 | 拒启动，日志指出哪条规则 |
| `ticker` 不在 `quote_watchlist.yml` | warn（不 fail，feed 仍会 poll，规则不会被触发） |

### 4.4 表达式上下文变量

注入到 asteval Interpreter 的变量（按规则类型分组）：

**所有 kind 共有**：
| 变量 | 类型 | 含义 |
|---|---|---|
| `price_now` | float | 当前价 |
| `price_open / high_today / low_today / prev_close` | float | 当日 OHLC 与昨收 |
| `price_high_today_yday / low_today_yday` | float | 昨日同字段（用于"突破" 判断）|
| `pct_change_intraday` | float | 当日涨跌幅 % |
| `volume_today / amount_today` | int / float | 当日累计 |
| `volume_avg5d / volume_avg20d` | float | 历史均量 |
| `volume_ratio` | float | volume_today / volume_avg5d |
| `bid1 / ask1` | float | 买一卖一价 |
| `is_limit_up / is_limit_down` | bool | 启发式（涨跌停板价 + 卖一/买一为 0） |
| `now_hhmm` | int | 当前北京时间 HHMM（如 1430） |

**kind=indicator 额外**（依赖 `daily_kline_*d` 历史）：
| 变量 / 函数 | 含义 |
|---|---|
| `ma5 / ma10 / ma20 / ma60 / ma120` | 当前各均线值（含今天 price_now）|
| `ma5_yday / ma10_yday / ma20_yday / ma60_yday` | 昨日均线（用于交叉检测） |
| `rsi(N)` | RSI(N) 函数 |
| `macd_dif / macd_dea / macd_hist` | MACD 三线 |
| `cross_above(a, b)` | a 上穿 b（昨日 a<=b 且今日 a>b） |
| `cross_below(a, b)` | a 下穿 b |
| `highest_n_days(N) / lowest_n_days(N)` | 过去 N 日最高/最低收盘价 |

**kind=composite + holding 额外**：
| 变量 | 含义 |
|---|---|
| `cost_per_share` | 持仓成本（来自 holdings.yml） |
| `qty` | 持仓数量 |
| `pct_change_from_cost` | (price_now - cost_per_share) / cost_per_share * 100 |
| `unrealized_pnl` | (price_now - cost_per_share) * qty |
| `unrealized_pnl_pct` | unrealized_pnl / (cost_per_share * qty) * 100 |

**kind=composite + portfolio 额外**：
| 变量 | 含义 |
|---|---|
| `total_unrealized_pnl` | 全部持仓汇总浮盈亏（元） |
| `total_unrealized_pnl_pct` | 全部持仓汇总浮亏 / total_capital * 100 |
| `holding_count_in_loss` | 浮亏的持仓数 |

**kind=event + target_kind=sector 额外**：
| 变量 | 含义 |
|---|---|
| `sector_pct_change` | 板块当日涨跌幅 |
| `sector_volume_ratio` | 板块整体量比 |

### 4.5 引擎调度（`alerts/engine.py`）

```python
class AlertEngine:
    def __init__(self, rules: list[AlertRule], state: StateTracker, indicators: IndicatorContext):
        self._rules = rules
        self._state = state
        self._indicators = indicators

    async def evaluate_for_snapshot(self, snap: QuoteSnapshot) -> list[AlertVerdict]:
        verdicts = []
        # 找到所有 target=this ticker 的规则（threshold + indicator + event-ticker + composite-holding）
        applicable = [r for r in self._rules if self._matches_target(r, snap)]
        for rule in applicable:
            ctx = self._build_context(rule, snap)
            interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
            try:
                result = bool(interp(rule.expr))
            except Exception as e:
                log.warning("rule_eval_failed", rule=rule.id, error=str(e))
                continue
            if not result:
                continue
            if self._state.is_in_cooldown(rule.id, snap.ticker):
                self._state.bump_count(rule.id, snap.ticker)
                continue
            verdicts.append(AlertVerdict(rule=rule, snapshot=snap, ctx_dump=ctx))
            self._state.mark_triggered(rule.id, snap.ticker, value=ctx.get("price_now"))
        return verdicts

    async def evaluate_market_scan(self, snapshots_all: list[QuoteSnapshot]) -> list[AlertVerdict]: ...
    async def evaluate_portfolio(self) -> list[AlertVerdict]: ...
    async def evaluate_sector(self, sector: str, ctx: dict) -> list[AlertVerdict]: ...
```

### 4.6 调用时机

| 时机 | 调用 |
|---|---|
| 5s Sina poll 完一轮 | `evaluate_for_snapshot(snap)` × N（每股一次） + `evaluate_portfolio()` × 1 |
| 60s 全市场扫描 | `evaluate_market_scan(snapshots_all)` |
| 60s 板块快照 | `evaluate_sector(sector, ctx)` × M（每板块一次） |
| 收盘后日 K 拉取 | refresh `IndicatorContext`（次日生效） |

---

## 5. 状态机（state/）

### 5.1 三种状态

| 状态 | 说明 |
|---|---|
| 未触发 | `alert_state` 表中不存在该 (rule_id, ticker) 行 |
| 已触发-冷却中 | 存在行，且 `now - last_triggered_at < cooldown_min * 60` |
| 已触发-可重发 | 存在行，且 `now - last_triggered_at >= cooldown_min * 60` |

### 5.2 触发流程

```
满足 expr → state.is_in_cooldown(rule.id, ticker)?
              ├─ Yes → state.bump_count() → 返回 None（静默）
              └─ No  → state.mark_triggered() → 写 alert_history → emit verdict
```

### 5.3 冷却结束后

下一次 expr 满足 → 重新触发，写新一行 `alert_history`。`alert_state` 行原地更新 `last_triggered_at`，`trigger_count_today += 1`。

### 5.4 与 BurstSuppressor 的二层叠加

```
verdicts: [V1, V2, V3]  (同一 ticker，3 条规则同时触发)
    │
    ▼
emit/message.py
    │
    ├─ if len(verdicts_for_ticker) > 1:
    │     合并为单条 CommonMessage（kind="alert_burst"）
    │     title="贵州茅台 (600519) 多规则触发"
    │     body=每条规则一行 ✓
    │
    └─ if len(verdicts_for_ticker) == 1:
          单规则 CommonMessage（kind="alert"）
    │
    ▼
shared/push/burst.py（BurstSuppressor）
    │
    ├─ same_ticker_burst_window 内已发过相似消息 → 折叠/丢弃
    │
    └─ 推 shared/push/dispatcher.py → 飞书
```

合并逻辑在 `emit/message.py` 内（quote 自己的同 ticker 多规则合并），BurstSuppressor 是后置的"全局降噪兜底"。

---

## 6. 配置 schema 补全

### 6.1 `config/quote_watchlist.yml`

```yaml
cn:
  - ticker: "600519"
    name: 贵州茅台
    market: SH
  - ticker: "300750"
    name: 宁德时代
    market: SZ
  - ticker: "688256"
    name: 寒武纪
    market: SH
  - ticker: "002594"
    name: 比亚迪
    market: SZ
  - ticker: "688981"
    name: 中芯国际
    market: SH
  # 推荐规模：30-50 只

us: []                                   # Phase 1 不实装，Phase 1.x 再加

market_scans:
  cn:
    top_gainers_n: 50
    top_losers_n: 50
    top_volume_ratio_n: 50
    push_top_n: 5
    only_when_score_above: 8.0           # 阈值（涨幅 % 或量比，由 scan 自定义）
```

### 6.2 `config/holdings.yml`

```yaml
holdings:
  - ticker: "600519"
    name: 贵州茅台
    qty: 100
    cost_per_share: 1850.0
  - ticker: "300750"
    qty: 200
    cost_per_share: 220.0

portfolio:
  total_capital: 200000
  base_currency: CNY
```

### 6.3 Pydantic schemas（新增）

```python
class QuoteTickerEntry(_Base):
    ticker: str
    name: str
    market: Literal["SH", "SZ", "BJ"]


class MarketScansCfg(_Base):
    top_gainers_n: int = 50
    top_losers_n: int = 50
    top_volume_ratio_n: int = 50
    push_top_n: int = 5
    only_when_score_above: float = 8.0


class QuoteWatchlistFile(_Base):
    cn: list[QuoteTickerEntry] = []
    us: list[QuoteTickerEntry] = []
    market_scans: dict[str, MarketScansCfg] = {}

    @model_validator(mode="after")
    def cn_tickers_unique(self): ...


class HoldingEntry(_Base):
    ticker: str
    name: str | None = None
    qty: int
    cost_per_share: float


class PortfolioCfg(_Base):
    total_capital: float | None = None
    base_currency: str = "CNY"


class HoldingsFile(_Base):
    holdings: list[HoldingEntry] = []
    portfolio: PortfolioCfg = Field(default_factory=PortfolioCfg)
```

---

## 7. 推送消息样式（emit/）

### 7.1 复用与扩展

`CommonMessage` 数据契约从 `news_pipeline/common/contracts.py` 抽到 `shared/common/contracts.py`。新增字段：

```python
class CommonMessage(_Base):
    # 现有字段保留：title, summary, source_label, source_url, badges, chart_url, chart_image,
    #              deeplinks, market, digest_items
    kind: Literal["news", "alert", "alert_burst", "market_scan", "digest"] = "news"  # ← 新
```

### 7.2 单股单规则触发

```
🔻 贵州茅台 (600519) 盘中跳水

⚡ 触发: 跌幅 -3.2%（规则 maotai_drop_3pct）
当前价: 1789.50 (-3.2%)
今日量: 28万手  量比: 2.1

📈 [东财 K 线]  [雪球 600519]
⏱ 14:30:25
🏷 #600519 #白酒  alert
```

### 7.3 单股多规则触发（同 ticker burst 合并）

```
⚡ 贵州茅台 (600519) 多规则触发

✓ 跌幅 -3.2%             (maotai_drop_3pct)
✓ 量比 2.1（放量）         (maotai_volume_spike)
✓ 跌破 MA20（1790.5）      (maotai_below_ma20)

当前价: 1789.50  ⏱ 14:30:25

📈 [东财 K 线]  [雪球]
🏷 #600519 #白酒  alert
```

### 7.4 全市场扫描（每分钟最多 1 条 digest 式）

```
📊 A 股 14:30 异动榜

🚀 涨幅 top 5:
1. 寒武纪 +9.2%   2. 中芯国际 +8.5%
3. 北方华创 +6.8%  4. 海光信息 +5.9%
5. 韦尔股份 +5.3%

📈 量比异动 top 3（量比 ≥ 3）:
• 寒武纪 量比 5.2（放天量）
• 比亚迪 量比 3.8

🏷 #market_scan
```

### 7.5 持仓风控触发

```
⚠️ 持仓告警: 贵州茅台 (600519)

成本: 1850.0  现价: 1700.0
浮亏: -8.1%  浮亏额: -¥15,000
触发规则: maotai_position_alert

⏱ 14:30:25
🏷 #持仓 #600519  alert
```

### 7.6 与 news_pipeline 推送的视觉区分

| 维度 | news | alert |
|---|---|---|
| 左上 emoji | 🟢/🔴/🟡（情绪极性）| ⚡/🔻/⚠️（动作 / 方向）|
| 底部 badge | 含 `news` / `rules` 标签 | 含 `alert` 标签 |
| deeplinks 优先级 | 原文 > 行情 | 行情 > 原文 |
| 标题前缀 | 来源名（"财联社"等） | ticker 名（"贵州茅台"等） |

---

## 8. 重构（shared/ 抽离）

### 8.1 重构动作清单（5 步，每步独立 commit）

| # | 动作 | imports 影响 | tests 影响 |
|---|---|---|---|
| R1 | `git mv src/news_pipeline/pushers/ src/shared/push/` | grep 替换 `from news_pipeline.pushers` → `from shared.push`，约 ~15 处 | `tests/unit/pushers/` → `tests/unit/shared/push/` |
| R2 | `git mv src/news_pipeline/observability/ src/shared/observability/` | grep 替换 ~12 处 | 同上 |
| R3 | 拆 `news_pipeline/common/contracts.py`：`CommonMessage / Badge / Deeplink / DigestItem` → `shared/common/contracts.py`；新闻特有的 `RawArticle / EnrichedNews / ScoredNews` 留 news_pipeline | ~30 处细粒度 import 变更 | 拆 `tests/unit/common/test_contracts.py` |
| R4 | `news_pipeline/common/timeutil.py / hashing.py / enums.py`（共用部分）→ `shared/common/`；news 特有的留下 | ~25 处 | 类似 |
| R5 | 跑全部 tests + ruff + mypy + pre-commit；确认 0 regression | — | — |

### 8.2 回滚机制

每步独立 commit + tag（`refactor-step-1` / `-2` / ...），出问题 `git revert <tag>` 单步回滚。

### 8.3 import 命名

```python
# Before
from news_pipeline.pushers.feishu import FeishuPusher
from news_pipeline.observability.log import get_logger
from news_pipeline.common.contracts import CommonMessage, Badge

# After
from shared.push.feishu import FeishuPusher
from shared.observability.log import get_logger
from shared.common.contracts import CommonMessage, Badge

# 新闻特有保留
from news_pipeline.common.contracts import RawArticle, EnrichedNews
```

### 8.4 不拆的部分

- `news_pipeline/config/loader.py` 不抽到 shared/。原因：news 和 quote 各自的配置 schema 完全不同（watchlist.yml vs quote_watchlist.yml），共用 loader 抽象只会引入无意义的间接层。
- `news_pipeline/common/timeutil.py` 中的 `utc_now` 等通用函数抽到 shared/，但 news_pipeline 自己的 `from news_pipeline.common.timeutil` 仍可调用（保留薄 re-export，避免一次性改太多）。

---

## 9. 错误处理 + 边界情况

| 场景 | 行为 | 实现位置 |
|---|---|---|
| 盘休时段 | `MarketCalendar.is_open()` → poll job 直接 return（log "market_closed"） | `feeds/calendar.py` |
| 节假日 | `chinese_calendar` 库判断 | 同上 |
| Sina 单次超时 | retry 1 次（2s 间隔），仍失败 log warn | `feeds/sina.py` |
| Sina 反爬 / 5xx | 退避 30s 后重试；连续 5 次 → bark warn 1 次后退避 5min | 同上 |
| 个股停牌 | feed 返回的 snapshot 中该 ticker 缺失 → 跳过该轮 | `alerts/engine.py` |
| 冷启动指标计算缺数据 | startup hook 一次性拉 watchlist 的 250 天日 K + 5/20 日均量预热，加载完才开 alert engine | `quote_watcher/main.py` |
| holdings.yml 缺失 | 启动校验：composite-portfolio / composite-holding 规则会拒启动 | `config/schema.py` validator |
| 规则 expr 语法错 | asteval 启动期干跑 → 拒启动 | 同上 |
| 单条规则 eval 运行期错 | log warn，该规则本次跳过，不影响其他规则 | `alerts/engine.py` |
| SQLite 写锁 | quote_watcher 用 quotes.db，独立于 news.db | 设计就分开 |
| 服务器内存压力 | tick ring 限制 1000 条/股 × 50 股 = ~4MB；indicator context 缓存按 LRU 100 项 | `store/tick.py` |
| 重启数据丢失 | tick 内存丢失（当日数据），1min K + 日 K + alert_state 都在 SQLite 持久 | 设计就这样 |
| 时间偏移 | 所有时间戳以北京时间存（A 股一个市场，避免 timezone 杂耍） | 全局约定 |
| 同一 tick 重复评估 | snapshot 比对 ts，如 ts == last_evaluated_ts 直接 skip | `alerts/engine.py` |
| asteval 注入 | asteval 默认禁 import / open，规则只能用注入的变量与函数 | asteval 默认行为 |

---

## 10. 测试策略

### 10.1 单元测试

| 文件 | 覆盖 |
|---|---|
| `tests/unit/quote_watcher/feeds/test_sina.py` | Sina 字符串解析（正常/停牌/退市/复牌当日）|
| `tests/unit/quote_watcher/feeds/test_calendar.py` | 交易时段判断 + 节假日 |
| `tests/unit/quote_watcher/store/test_tick_ring.py` | ring buffer 满后 FIFO |
| `tests/unit/quote_watcher/store/test_bar_aggregation.py` | tick → 1min bar 聚合 |
| `tests/unit/quote_watcher/alerts/test_threshold.py` | 数值阈值 4 子类型 |
| `tests/unit/quote_watcher/alerts/test_indicator.py` | MA/MACD/RSI 各 + cross_above |
| `tests/unit/quote_watcher/alerts/test_event.py` | 涨跌停启发式 + 板块异动 |
| `tests/unit/quote_watcher/alerts/test_composite.py` | 持仓 + portfolio + AND/OR |
| `tests/unit/quote_watcher/alerts/test_asteval_safety.py` | asteval 沙箱（禁 import os 等）|
| `tests/unit/quote_watcher/state/test_cooldown.py` | cooldown 状态机三种状态转移 |
| `tests/unit/quote_watcher/emit/test_message.py` | AlertVerdict → CommonMessage 各 kind |
| `tests/unit/quote_watcher/emit/test_burst_merge.py` | 同 ticker 多规则合并 |
| `tests/unit/shared/push/*` | 现有 push 测试整体迁移（仅改 import） |
| `tests/unit/shared/common/test_contracts.py` | CommonMessage 字段 + kind |
| `tests/unit/config/test_alerts_schema.py` | alerts.yml 校验 + asteval 干跑 |
| `tests/unit/config/test_holdings_schema.py` | holdings.yml 校验 |

### 10.2 集成测试

| 文件 | 覆盖 |
|---|---|
| `tests/integration/quote_watcher/test_e2e_threshold.py` | 假 Sina 响应 → threshold 触发 → mock 飞书验消息 |
| `tests/integration/quote_watcher/test_e2e_indicator.py` | 假日 K + 假 tick → 金叉触发 → 推 |
| `tests/integration/quote_watcher/test_e2e_burst.py` | 同股 3 规则同时触发 → 合并为 1 条 |
| `tests/integration/quote_watcher/test_calendar_skip.py` | 周末时段 poll job 不调 |
| `tests/integration/test_news_pipeline_unchanged.py` | news_pipeline 在重构后行为完全不变（重要！） |

### 10.3 Eval

`tests/eval/quote_watcher/test_rule_replay.py`：用一周历史 Sina 数据 replay，统计 4 类规则触发次数，确认在合理范围（每股每周不超过 N 次的健康线）。

### 10.4 手动验证

- **首周观察**：`alert_state.trigger_count_today` 分布 — 单条规则一天触发 > 50 次 → 太松，需调阈值或加 cooldown
- **每天早盘前**：`uv run python -m quote_watcher.tools.preview_rules` 干跑前一日 → 看会触发多少
- **真实灰度**：先用 alerts.yml 里 2-3 条规则跑 1 周，确认推送质量后再加规则

---

## 11. Phase 1 内部 Sprint 切分

| Sprint | 内容 | 估时 |
|---|---|---|
| **S0：重构** | §8 五步，push/observability/common 抽到 shared/，0 行为变化 | 1.5 天 |
| **S1：骨架 + Sina poll** | quote_watcher 框架 + Sina feed + tick ring + market calendar + 1 个最简规则（单股跌幅阈值）端到端通飞书 | 2 天 |
| **S2：数值阈值组完整** | 涨跌幅 / 量比 / 价格突破 / N 日新高低 + cooldown + BurstSuppressor 接入 + watchlist 全跑 | 2 天 |
| **S3：持仓风控 + 组合规则** | holdings.yml + composite + asteval + 浮亏告警 | 1.5 天 |
| **S4：全市场扫描** | Sina/akshare 全市场快照 + 涨跌幅榜 / 量比榜 + 1min digest 推送 | 2 天 |
| **S5：技术指标组** | 日 K 持久化 + MA / MACD / RSI 计算 + cross_above 函数 + 一组指标规则 | 3 天 |
| **S6：事件 / 板块组** | 涨跌停启发式 + 板块异动（东财 API） | 2.5 天 |
| **S7：观测 + 文档** | preview tool + dry-run replay + alert_state 监控 + README | 1 天 |

**总计 ~15.5 天**。S0 → S1 → S2 → S3 走完（~7 天）即可上一个能用版本，S4-S6 边用边加。

---

## 12. 显式不做（YAGNI）

| 不做 | 原因 |
|---|---|
| Tick 级 / websocket | 5s poll 已选定，够用 |
| Level-2（逐笔成交、十档）| 免费拿不到，付费太贵 |
| 龙虎榜 | 数据源反爬严重 |
| US 实时（Phase 1） | 后续 Phase 1.x 再做 |
| 自动交易 / 下单 | 跟 news_pipeline 一样明确不做 |
| Web UI / dashboard | 飞书消息已经是终端 |
| 多用户 / 多 portfolio | 单人单组合 |
| Backtesting 框架 | preview tool 历史 replay 够用，不做完整回测 |
| 自学习规则 | 规则手动维护 |
| 跨子系统的"超级规则"（quote 触发 → 翻 news）| 两个子系统通过推送解耦，不互相调用 |
| K 线图直接渲染推送 | charts 模块能做，但 alert 类不附图（保持消息精简），deeplink 跳东财即可 |

---

## 13. 决策记录（ADR）

| ADR | 决策 | 理由 |
|---|---|---|
| 1 | quote_watcher 与 news_pipeline 平级（不嵌套） | 两个 bounded context 不同，硬嵌套会让依赖混乱 |
| 2 | 仅共享 push / observability / common contracts | watchlist 各管各的，避免双向耦合 |
| 3 | 数据源选 Sina HTTP poll 5s + akshare/tushare 日 K | 全部免费，5s 延迟足够覆盖 -3% 触发场景 |
| 4 | SQLite 分库（quotes.db / news.db） | 高频写 quote_bars_1min 不会给 news 表加锁 |
| 5 | 4 类规则统一为一个 schema，按 `kind` 分派 | 配置文件单一，引擎统一调度 |
| 6 | 表达式语法选 asteval | 工程师直觉、可热加载、沙箱安全 |
| 7 | 二层去重：AlertState cooldown + BurstSuppressor | 各防各的：规则级冷却 + 同股多规则合并 |
| 8 | tick 用内存 ring buffer，不持久化 | 重启即失可接受，性能优先 |
| 9 | 北京时间为唯一时区基准 | A 股单市场，避免 timezone 复杂度 |
| 10 | docker-compose 双 service 而非单进程多 task | 进程隔离，崩了一边不影响另一边，重启独立 |

---

## 14. 后续扩展（v0.4.x+ 候选）

- **US 实时**：Finnhub websocket（free 50 symbols）作为 `feeds/finnhub_ws.py`，与 Sina 同接 `QuoteSnapshot`
- **指标更全**：BOLL / KDJ / OBV / VWAP
- **更复杂事件**：连续 N 日缩量上涨、跳空缺口检测
- **板块联动规则**：板块强势 + 个股弱势（相对强弱）
- **告警升级机制**：同一规则连续 3 次触发 → 升级为 critical
- **Discord / 企业微信** 推送（shared/push 已经预留 wecom.py）
- **alert_history 周报**：每周一汇总上周触发分布、最频繁规则

---

## 附录 A — 配置 vs 行为对照速查

| 你想 | 配置 |
|---|---|
| 加一只盯盘股 | `config/quote_watchlist.yml` 加一项 |
| 加一条跌幅告警 | `config/alerts.yml` 加 `kind: threshold` 项 + expr |
| 调全市场扫描频率 | `config/quote_watchlist.yml` 的 `market_scans.cn.push_top_n` |
| 加持仓 | `config/holdings.yml` 加 `holdings[]` 项 |
| 临时禁用某规则 | 删除/注释 `alerts.yml` 中该项（hot reload 自动生效） |
| 规则触发太频繁 | 调高 `cooldown_min` 或调严 `expr` 阈值 |
| 节假日不要 poll | 自动（chinese_calendar） |

## 附录 B — 与 news_pipeline 的契约

- 两子系统**只通过共享的 push 通道交互**，不直接互相调用、不共享数据库
- `config/channels.yml` 由两边共用（飞书 webhook 配置）
- `config/secrets.yml` 由两边共用（飞书 token、bark 等）
- `data/news.db` 与 `data/quotes.db` 完全独立
- 飞书消息上 `alert` badge 与 `news` / `rules` badge 区分来源

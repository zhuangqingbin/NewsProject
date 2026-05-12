# config/quote_watcher — quote_watcher 子系统专用配置

仅 `quote_watcher` 读取；`news_pipeline` 不使用这里的文件。

---

## quote_watchlist.yml

盯盘股列表 + 全市场扫描参数。

### 字段结构

```yaml
cn:                        # A 股盯盘列表
  - ticker: "600519"       # 必填 — 股票代码（6 位字符串，需加引号）
    name: 贵州茅台           # 必填 — 股票名称（用于显示）
    market: SH             # 必填 — 交易所（见下表）

us: []                     # 美股盯盘列表（当前暂未接入实时报价）

market_scans:              # 全市场扫描配置
  cn:
    top_gainers_n: 50      # 拉取涨幅前 N 只
    top_losers_n: 50       # 拉取跌幅前 N 只
    top_volume_ratio_n: 50 # 拉取量比前 N 只
    push_top_n: 5          # 每次推送前 N 只（超过此数不推送）
    only_when_score_above: 8.0  # 综合评分阈值，低于此值不推送
```

### market 字段规则

| market | 适用代码前缀 | 说明 |
|---|---|---|
| `SH` | 60xxxx、68xxxx | 上交所主板 + 科创板 |
| `SZ` | 00xxxx、30xxxx | 深交所主板 + 创业板 |
| `BJ` | 8xxxxx、4xxxxx、9xxxxx | 北交所 |

### 如何加新股

```yaml
cn:
  - ticker: "000858"
    name: 五粮液
    market: SZ
```

代码前两位判断交易所：`00/30` → SZ，`60/68` → SH，`8/4/9` → BJ。

### 推荐规模

核心盯盘：30-50 只以内（过多会增加 Sina 接口压力）。可把持仓股全部加入，配合 `holdings.yml` 使用 composite 规则监控盈亏。

---

## alerts.yml

告警规则配置。`quote_watcher` 支持热加载：**保存文件后下一个 tick（默认 5 秒）自动生效，无需重启**。

### 4 种规则类型

#### 1. threshold — 数值阈值（最常用）

```yaml
alerts:
  - id: maotai_drop_3pct          # 唯一 ID（同 id 的告警有冷却去重）
    kind: threshold
    ticker: "600519"
    name: 贵州茅台                  # 可选，用于推送显示
    expr: "pct_change_intraday <= -3.0"   # asteval 表达式
    cooldown_min: 30               # 同一规则两次触发的最短间隔（分钟）
    severity: warning              # info / warning / critical（可选，默认 info）
```

#### 2. indicator — 技术指标（需要日 K 数据）

```yaml
  - id: maotai_ma_breakout
    kind: indicator
    ticker: "600519"
    expr: "ma5 > ma20"             # 均线金叉
    cooldown_min: 1440             # 1 天冷却
```

```yaml
  - id: catl_rsi_oversold
    kind: indicator
    ticker: "300750"
    expr: "rsi(14) < 25"           # RSI 超卖
    cooldown_min: 240
```

> indicator 规则依赖日 K 缓存，启动时会自动预热 250 天数据。如果数据库是空的，首次启动可能需要几秒。

#### 3. event — 事件触发

```yaml
  - id: maotai_limit_up
    kind: event
    ticker: "600519"
    event_type: limit_up           # limit_up / limit_down / sector_surge
    cooldown_min: 1440
```

#### 4. composite — 持仓组合规则（需配合 holdings.yml）

```yaml
  - id: maotai_loss_alert
    kind: composite
    holding: "600519"              # 匹配 holdings.yml 中的 ticker
    expr: "pct_change_from_cost <= -5.0"   # 从持仓成本算起的亏损比例
    cooldown_min: 60
    severity: critical
```

### asteval 表达式可用变量（threshold / composite）

| 变量 | 说明 |
|---|---|
| `price` | 当前价格 |
| `prev_close` | 昨日收盘价 |
| `pct_change_intraday` | 今日涨跌幅（%） |
| `volume_ratio` | 量比（当前量 / 过去 N 日平均量） |
| `bid1` / `ask1` | 买一 / 卖一价 |
| `pct_change_from_cost` | 从持仓成本算起的涨跌幅（仅 composite 可用） |
| `ma5` / `ma10` / `ma20` / `ma60` | N 日均线（仅 indicator 可用） |
| `rsi(N)` | RSI 指标（仅 indicator 可用） |

完整变量列表和更多示例见 `docs/quote_watcher/getting_started.md` § 1.2。

---

## holdings.yml

持仓表。仅 `composite` 类告警规则需要此文件；若不使用 composite 规则，此文件可以保持空列表。

### 字段结构

```yaml
holdings:
  - ticker: "600519"           # A 股代码（字符串）
    name: 贵州茅台               # 可选，用于显示
    qty: 100                   # 持仓数量（股）
    cost_per_share: 1850.0     # 持仓成本价（元/股）

  - ticker: "300750"
    name: 宁德时代
    qty: 200
    cost_per_share: 220.0

portfolio:
  total_capital: 200000        # 总资金量（元）；用于计算仓位比例（预留字段，当前未强制使用）
  base_currency: CNY
```

### 无持仓时

```yaml
holdings: []
portfolio:
  total_capital: 0
  base_currency: CNY
```

### 更新持仓

直接编辑此文件并保存。`quote_watcher` 会在下一次 `ConfigLoader.load()` 时读取最新值（触发条件是文件系统事件 + 500ms debounce）。

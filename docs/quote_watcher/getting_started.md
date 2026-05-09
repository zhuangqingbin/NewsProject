# Quote Watcher 入门

> 假设你已经把 news_pipeline 跑起来了(参见根 README).quote_watcher 复用同一份 `secrets.yml + channels.yml`,只是多了几个自己的配置文件.

## 1. 准备配置

### 1.1 `config/quote_watchlist.yml`

盯盘的股票列表 + 全市场扫描参数:

```yaml
cn:
  - ticker: "600519"
    name: 贵州茅台
    market: SH
  - ticker: "300750"
    name: 宁德时代
    market: SZ

market_scans:
  cn:
    top_gainers_n: 50          # 涨幅榜 top N(内部排序)
    top_losers_n: 50
    top_volume_ratio_n: 50
    push_top_n: 5              # 推送时只取前 N 条
    only_when_score_above: 8.0 # 只关注涨跌幅 ≥ 8% 或量比 ≥ 8 的
```

### 1.2 `config/alerts.yml`

规则定义.每条规则一个 `kind`:

#### threshold(数值阈值)

```yaml
- id: maotai_drop_3pct
  kind: threshold
  ticker: "600519"
  name: 贵州茅台
  expr: "pct_change_intraday <= -3.0"
  cooldown_min: 30
  severity: warning
```

可用变量:`price_now / price_open / high_today / low_today / prev_close / pct_change_intraday / volume_today / volume_avg5d / volume_ratio / bid1 / ask1 / is_limit_up / is_limit_down / now_hhmm`.

#### indicator(技术指标)

```yaml
- id: maotai_ma_breakout
  kind: indicator
  ticker: "600519"
  expr: "ma5 > ma20"
  cooldown_min: 1440

- id: catl_rsi_oversold
  kind: indicator
  ticker: "300750"
  expr: "rsi(14) < 25"
  cooldown_min: 240
```

可用变量(threshold 那些 + 这些):
- `ma5 / ma10 / ma20 / ma60 / ma120` 当前均线
- `ma5_yday / ...` 昨日均线
- `macd_dif / macd_dea / macd_hist`
- `rsi(n)`(callable,默认 14)
- `cross_above(a, b, yday_a=, yday_b=)` / `cross_below(...)`
- `highest_n_days(n)` / `lowest_n_days(n)`

注意:indicator 规则需要 `data/quotes.db` 里有日 K 历史.启动时会从 akshare 自动预拉 250 天.

#### event(事件)

```yaml
- id: cambricon_limit_up
  kind: event
  target_kind: ticker
  ticker: "688256"
  expr: "is_limit_up"
  cooldown_min: 1440

- id: semi_sector_surge
  kind: event
  target_kind: sector
  sector: 半导体
  expr: "sector_pct_change >= 3.0"
  cooldown_min: 60
```

board sector 规则的可用变量:`sector_pct_change / sector_volume_ratio / sector_turnover_rate`.

#### composite(持仓 / 组合)

```yaml
- id: maotai_pos_alert
  kind: composite
  holding: "600519"
  expr: "pct_change_from_cost <= -8.0 and volume_ratio >= 1.5"
  cooldown_min: 60

- id: total_pnl_alert
  kind: composite
  portfolio: true
  expr: "total_unrealized_pnl_pct <= -3.0"
  cooldown_min: 240
```

per-holding 可用变量:threshold 那些 + `cost_per_share / qty / pct_change_from_cost / unrealized_pnl / unrealized_pnl_pct`.

portfolio 可用变量:`total_unrealized_pnl / total_unrealized_pnl_pct / holding_count_in_loss`.

### 1.3 `config/holdings.yml`(只在用 composite 规则时需要)

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

## 2. 启动

### 2.1 本地

```bash
uv run python -m quote_watcher.main
```

环境变量:
- `QUOTE_WATCHER_DB`(默认 `data/quotes.db`)
- `QUOTE_POLL_INTERVAL_SEC`(默认 5,Sina ticker poll)
- `QUOTE_SCAN_INTERVAL_SEC`(默认 60,全市场扫描)
- `QUOTE_SECTOR_INTERVAL_SEC`(默认 60,板块异动)
- `LOG_LEVEL`(默认 INFO)

### 2.2 Docker

`docker-compose.yml` 里已经有 `quote_watcher` service.

```bash
docker compose up -d quote_watcher
docker compose logs -f quote_watcher
```

## 3. 调试新规则

新加规则前先用 preview tool 在历史数据上 dry-run:

```bash
uv run python -m quote_watcher.tools.preview_rules \
    --tickers 600519,300750 \
    --since 2026-04-01 --until 2026-05-08
```

输出告诉你哪些规则在哪些天会触发——如果一个规则一周触发 50 次,先调 cooldown 或调严阈值再上线.

## 4. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `kline_warmup_failed` 启动告警 | akshare 网络问题 | 系统自动降级跑(没指标规则就不影响),晚点重试 |
| 启动时 `alerts_reload_failed` | yaml 语法错或 expr 语法错 | 看日志详细信息修配置 |
| 推到飞书但格式怪 | `shared/push/feishu.py` 模板渲染问题 | 看 `push_log` 表 + 飞书 webhook 返回 |
| 一只股推不停刷屏 | cooldown 太短 OR Burst 没生效 | 调高 `cooldown_min` 或检查 `same_ticker_burst_*` 配置 |
| indicator 规则不触发 | quotes.db 没日 K | `kline_warmup_ok` 在日志里能看到吗?或手动 `uv run python -m quote_watcher.tools.preview_rules --since ... --until ...` |

## 5. 看数据

`quotes.db` 主要表:
- `quote_bars_daily` — 日 K 历史
- `quote_bars_1min` — 1 分钟 K(暂未启用,未来功能)
- `alert_state` — 每条规则当前 cooldown 状态
- `alert_history` — 历史触发记录

```bash
sqlite3 data/quotes.db "SELECT rule_id, ticker, datetime(last_triggered_at,'unixepoch','+8 hours'), trigger_count_today FROM alert_state ORDER BY last_triggered_at DESC LIMIT 20;"
```

## 6. 进阶

- `config/alerts.yml` 是**热加载**的——编辑文件保存后,quote_watcher 自动检测并 swap 规则,不用重启
- 想要新加一只股:在 `quote_watchlist.yml` 加一行,然后 `quote_watcher` 自动 poll 它(下个 5 秒 tick)
- 想关停整个 quote_watcher 但保留 news_pipeline:`docker compose stop quote_watcher`(news_pipeline 不动)

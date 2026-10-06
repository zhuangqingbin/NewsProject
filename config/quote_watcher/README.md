# config/quote_watcher — 盯盘配置

盯盘为独立 A 股子系统，使用 `data/quotes.db` 和 `_alert` 新闻之外的飞书频道。新闻的 legacy/shadow/v2 开关不改变盯盘告警。

## quote_watchlist.yml

```yaml
cn:
  - ticker: '600519'
    name: 贵州茅台
    market: SH
us: []
market_scans:
  cn:
    top_gainers_n: 50
    top_losers_n: 50
    top_volume_ratio_n: 50
    push_top_n: 5
    only_when_score_above: 8.0
```

交易所：SH 包含 60/68 前缀，SZ 包含 00/30，BJ 包含北交所代码。当前不提供美股实时盯盘。列表改变后重启 `quote_watcher`。

默认 `QUOTE_FEED=tencent`，可切 `sina` 并重建容器环境。腾讯成交量统一为股：主板与创业板原始手数 ×100，688/689 科创板原始股数保持；成交额使用人民币元。全市场与行业板块分别使用东财 clist 排序/分页请求，不扫描整个全 A 表。交易时段真实单位校验仍是发布验收的一部分。

## alerts.yml

只有此文件使用现有 `AlertsReloader` 监听并替换规则，无需重启。其他配置不承诺热加载。规则类型是 threshold、indicator、event、composite；表达式由 asteval 执行，冷却按 id 保持。

```yaml
alerts:
  - id: maotai_drop_3pct
    kind: threshold
    ticker: '600519'
    expr: 'pct_change_intraday <= -3.0'
    cooldown_min: 30
    severity: warning
```

常用变量：price、prev_close、pct_change_intraday、volume_ratio、bid1、ask1；持仓规则另有 pct_change_from_cost。indicator 使用日 K 缓存和 ma5/ma20/rsi 等函数，冷缓存网络预热耗时随上游而变，不能保证几秒完成。

量比优先采用源返回 `volume_ratio`，缺失才使用现有均量计算。涨跌停优先采用明确 `limit_up/limit_down` 价格，允许 0.005 元容差；无字段才使用旧比例估算。源值缺失与值为 0 不应混淆。

## holdings.yml

```yaml
holdings:
  - ticker: '600519'
    name: 贵州茅台
    qty: 100
    cost_per_share: 1850.0
portfolio:
  total_capital: 200000
  base_currency: CNY
```

仅持仓/组合规则需要。无持仓可保留空 holdings；修改后重启 `quote_watcher`，alerts reloader 不重新加载 holdings。

## 运维

个股、全市场与板块启动探测，任一路失败 Bark 提醒。交易时段个股连续 5 分钟无成功快照只告警一次，恢复再提醒。healthcheck 读取独立心跳文件，不以是否有新闻判断盯盘存活。

详见 [部署指南](../../docs/getting-started/deployment-current.md) 和 [可观测性](../../docs/components/observability.md)。配置受版本管理，真实机器人和 Bark 密钥只写共用 secrets。

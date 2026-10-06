# quote_watcher 子系统

独立 A 股盯盘：腾讯个股快照（默认）与东财全市场/行业扫描 → tick/日 K 缓存 → 规则 → CN `_alert` 飞书频道。新闻 legacy/shadow/v2 开关不改变盯盘。

## 取数与规则

`QUOTE_FEED=tencent|sina` 选择个股源。腾讯 GBK 响应提供量比与明确涨跌停价，成交量统一为股：主板/创业板手数乘 100，688/689 科创板股数保留。全市场请求涨幅降序、涨幅升序、量比降序三榜再去重；板块按总数分页。日 K 仍用 akshare 缓存，交易时段需真实校验单位。

threshold、indicator、event、composite 四类规则由 AlertEngine 执行，带冷却与告警记录。持仓组合使用 holdings 配置。当前不提供美股实时盯盘。

## 配置与存储

`config/quote_watcher/{quote_watchlist,alerts,holdings}.yml`，共用 channels/secrets 位于 `config/common`。只有 alerts.yml 使用 watchdog AlertsReloader；持仓与盯盘列表修改后重启。数据在 data/quotes.db，心跳在独立 heartbeat_quote_watcher.json。

启动个股/全市场/板块探测，任一路失败 Bark 告警。交易时段 5 分钟无成功个股快照告警一次，首次恢复再通知。心跳与行情源成功分开监控。

## 入门与运维

- [规则示例](../quote_watcher/getting_started.md)
- [部署与环境变量](../getting-started/deployment-current.md)
- [心跳与源监控](../components/observability.md)

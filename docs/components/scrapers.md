# Scrapers

抓取器返回统一 `RawArticle`；保存与调度分别在 `ingest/store.py` 和 `scheduler/jobs.py`。当前源开关以 `config/news_pipeline/sources.yml` 为准，启用配置不等于已经完成服务器上的可用性验收。

## 数据源总览

| source_id | 实现与默认间隔 | 配置要点 |
|---|---|---|
| `sina_global` / `futu_global` / `eastmoney_global` | 全球快讯，180 秒 | 使用实际源市场作为无主体新闻的路由兜底 |
| `ths_global` | 同花顺快讯，120 秒 | 与停用的个股 `ths` 抓取器不同 |
| `cls_telegraph` | 财联社直连接口，60 秒 | 替代旧 `caixin_telegram` |
| `wallstreetcn` | 华尔街见闻直连接口，120 秒 | 解析结构变化抛合同异常 |
| `finnhub` | 美股公司新闻，300 秒 | `secrets.sources.finnhub_token` |
| `em_stock_news` | 东财个股新闻直连，300 秒 | 按自选 A 股取新闻，替代旧 `akshare_news` |
| `juchao` | 巨潮公告，300 秒 | 初始化 orgId；不按公告时间过滤；一手源分级 |
| `sec_edgar` | SEC submissions，120 秒 | 初始化 CIK、真实联系 User-Agent、一手表单分级 |
| `cjzc_em` / `cctv_news` | 财经早餐 / 新闻联播，3600 / 21600 秒 | 低频内容不要求每次抓取都非空 |
| `kr36` | 默认关闭 | 扩源与替换等阶段 D 再评估 |

旧 `caixin_telegram`、`akshare_news`、雪球/个股同花顺等文件暂留兼容，不是新 factory 的默认路径。删除条件见 [C1/C2 清单](../operations/staged-cleanup.md)。

## 抓取与保存

每次取 `now - lookback_min`，不用上轮发布时间当排他水位线。晚出现的旧条目仍能进入回看窗口。`ArticleStore` 先查 URL hash：同 URL 不重复插入；不同 URL 的同标题证据在 legacy/shadow 标为 `duplicate` 入库并记录 `dup_of`，不是丢弃。v2 停止标题 simhash 判重，由事件层合并文章。

源第一次成功抓取的内容作为 `seeded` 基线，避免初始化历史列表全部推送。抓取外层有 `fetch_timeout_sec`，成功/失败、最新条目时间和退避写入 `source_state`。失败退避为 interval 的指数倍，封顶 30 分钟。

```yaml
sources:
  cls_telegraph:
    enabled: true
    interval_sec: 60
    lookback_min: 360
    max_silence_min: 60
    max_silence_off_min: 240
    fetch_timeout_sec: 30
```

## 错误契约

网络失败和响应结构不合法必须抛异常，不能伪装成空列表。`SourceContractError` 表示结构失败；真正没有新条目才返回空列表。数值、时间和列表结构校验在抓取器边界完成，调度器记录错误并交给源健康状态机。

## SEC 与巨潮初始化

SEC 使用自选美股的 CIK，巨潮使用自选 A 股的 orgId。未知配置 ticker 是启动配置错误；网络初始化失败会记录，后续抓取可以重试。SEC `options.user_agent` 或新闻主进程的 `SEC_USER_AGENT` 必须含真实联系信息，部署方法见 [部署指南](../getting-started/deployment-current.md)。公告原文链接和一手元数据应保留供分级、卡片与核对使用。

## 启动连通性探测

启动和每周日 20:00 北京时间调用 `health.smoke`，逐源真实抓取、验证结构、高频源非空，并核对发布超过 15 分钟的条目是否在库。probe 不插入新闻。服务器 IP 的测试结果才是部署验收证据，录制响应测试不能代替它。

```bash
docker compose exec app python -m news_pipeline.health.smoke --no-report
docker compose exec app python -m news_pipeline.health.leak_check
```

手工 smoke 默认同时向系统日报频道发送结果卡片；上面的 `--no-report` 是仅 JSON 的只读检查。数据库不写入；启动和每周自动报告经 outbox 发送。

## 相关

- [事件与去重](dedup.md) · [源健康与日报](observability.md)
- [调度](scheduler.md) · [部署与回滚](../getting-started/deployment-current.md)

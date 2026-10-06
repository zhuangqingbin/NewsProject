# Configuration

配置拆为 `config/common`（app/channels/secrets）、`config/news_pipeline`（sources/watchlist/scoring/first_party）和 `config/quote_watcher`（quote_watchlist/alerts/holdings）。非密钥配置受版本管理；真实 `config/common/secrets.yml` 与旧 `config/secrets.yml` 被忽略。

## 修改与生效

新闻启动时读取一次配置，修改后 `docker compose restart app`。旧 `runtime.hot_reload` 不表示主进程正在监听文件。盯盘仅 `alerts.yml` 有专用 `AlertsReloader`；其他配置修改后重启盯盘。

## 模式与 LLM

默认 legacy、LLM false。新模型配置为 `llm.assess/digest`，实际单价位于 `llm.pricing.<model>.input/output`，单位人民币 / 百万 token，两项须为正数；控制台核对及 B0 完成前不要启用。日预算使用 `llm.daily_cost_ceiling_cny`，旧 tier/runtime 预算字段仅兼容。

SEC `sources.sec_edgar.options.user_agent` 应包含真实联系人和邮箱，主进程可用 SEC_USER_AGENT 覆盖；当前 Compose 从宿主 export 或 `.env` 自动注入它，环境修改后用 `docker compose up -d app` 重建容器。sources 每源定义 interval/lookback/timeout/静默阈值，不能只改旧全局 scrape 字段。

## 进一步说明

- [部署与配置示例](../getting-started/deployment-current.md)
- [规则与别名校验](../components/rules.md) · [调度](../components/scheduler.md)
- [新旧字段删除门槛](staged-cleanup.md)

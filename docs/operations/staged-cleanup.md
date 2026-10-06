# 稳定门槛与清理清单

本清单是 C1/C2 的后续工作，不表示这些文件或依赖已经删除。v0.7.0 保留旧路径支持 `legacy`/`shadow` 和配置回滚。部署顺序、备份与回滚见 [部署指南](../getting-started/deployment-current.md)。

## 执行门槛

完成 B0 的 150 条人工标注与获授权的模型评测，影子模式观察 2–3 个交易日，切 v2 后连续稳定运行至少一周。稳定证据包括逐源真实冒烟、每日系统报告、新旧事件对比、失败重试与摘要消费验证、持久预算控制以及可用的备份和 v0.7.0 回滚镜像。尚未达到门槛时保留下面的旧代码和依赖。

C1/C2 清理规划为 v0.7.1；阶段 D 扩源至少等 v2 稳定两周后逐项评估。等待期不是自动批准，验收证据必须实际记录，不能用离线通过数代替线上观察。

## C1：旧文件和路径删除候选

| 删除对象 | 替代与检查 |
|---|---|
| `src/news_pipeline/commands/`、`tests/unit/commands/` | 飞书 webhook 不提供命令回调，当前 main 不启动命令服务器 |
| `src/news_pipeline/charts/`、`tests/unit/charts/` | 当前新闻卡片不生成图表；保留盯盘 `store/kline.py` 和指标功能 |
| `src/news_pipeline/llm/`、`config/news_pipeline/prompts/`、相应旧 LLM 测试 | `assess/` 负责新事件评估和摘要调用 |
| `src/news_pipeline/classifier/`、`router/`、相应旧测试 | `rules/`、`deliver/policy.py` 与新卡片路由替代 |
| `src/news_pipeline/dedup/`、`common/hashing.py` 的 `title_simhash`、相应旧测试 | `ingest/store.py` URL 去重、`events/similarity.py` 事件合并；保留 URL hash 函数与数据库旧列 |
| `scrapers/cn/{akshare_news,caixin_telegram,kr36,ths,xueqiu,tushare_news}.py`、`scrapers/us/yfinance_news.py` | 已替换或停用；先查 factory、CLI 与测试引用 |
| `scrapers/common/{cookies,ratelimit}.py` | 新抓取器不再引用后删除 |
| `storage/dao/{entities,relations,audit_log,dead_letter,news_processed,digest_buffer,push_log}.py` | 新路径改用事件与投递 DAO；旧表本身保留 |
| `shared/observability/weekly_report.py` 与旧每周死信任务 | 系统日报替代 |
| `shared/push/common/message_builder.py` | `news_pipeline/deliver/cards.py` 替代，解除 shared 对新闻子系统的反向依赖 |
| `PipelineRuntime` 的 legacy/shadow 分支、`scheduler/jobs.py` 的 `process_pending` 和旧摘要路径 | 只剩 v2 后删除；同步移除兼容测试与旧入口 |
| 新闻 `ConfigLoader.start_watching` 与新闻配置监听 | 新闻改配置后重启；保留盯盘 `AlertsReloader` |

删除前逐项用引用搜索确认依赖，更新 factory、导出接口、配置加载与文档，运行剩余完整测试和真实源冒烟。不能只删目录而留下运行时 import。

## C2：配置与依赖清理候选

旧配置候选：`scheduler.scrape.*`、`scheduler.llm`、`llm.tier0_model` 至 `tier3_model`、`llm.prompt_versions`、`llm.enable_prompt_cache`、`llm.enable_batch`、`classifier.*`、`dedup.*`、`charts.*`、`push.per_channel_rate`、`push.digest_max_items_per_section`、`dead_letter.*`、`runtime.hot_reload`、watchlist 的旧 `llm:` 段。旧 `runtime.daily_cost_ceiling_cny` 不控制新预算，新预算使用 `llm.daily_cost_ceiling_cny`；旧保留项不能覆盖新的固定保留任务。

依赖删除候选为 `python-telegram-bot`、`fastapi`、`uvicorn`、`tushare`、`yfinance`、`mplfinance`、`matplotlib`、`tenacity`、`dashscope`、`beautifulsoup4`、`aiolimiter`、`simhash`、`anthropic`、`feedparser`。逐个确认剩余源码不再 import 后再移除并重建 lock。`watchdog` 仍被盯盘的 `AlertsReloader` 使用，不能随新闻监听一起删除。

移除新闻图表后再删 Docker 运行层的 `fonts-noto-cjk`。保留 `akshare`：部分新闻源和盯盘日 K 仍使用它；升级版本需从服务器 IP 逐源冒烟确认返回列和单位。`httpx`、SQLite/Alembic、APScheduler、规则匹配、表达式和交易日历依赖也继续使用。

新增配置引用检查，确保保留下来的配置叶子有实际消费方；这项检查应区分两个子系统和兼容字段，避免把只存在于 schema 的名称当作有效消费。

## 表与兼容数据

不删 `entities`、`news_entities`、`relations`、`audit_log`、`dead_letter` 空表。`news_processed`、`digest_buffer`、`push_log` 在 v2 停止写入，作为历史只读保留。`raw_news.title_simhash` 旧列保留，v2 入库写 0。保留 `shared/push/wecom.py` 的通用实现。数据保留和 VACUUM 属于单独任务，不借代码清理做破坏性删表。

C1/C2 完成后回滚必须使用保留的 v0.7.0 镜像与配置。门槛通过和清理完成应分别记录，不要把这份计划标为已执行。

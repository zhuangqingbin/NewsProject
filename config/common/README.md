# config/common — 共用配置

两个子系统读取此目录。默认 `pipeline.mode: legacy`、`llm.enabled: false`；配置加载不等于线上验收完成。新闻改配置后重启 `app`，不使用旧新闻 watchdog 热加载。

## secrets.yml

```bash
umask 077
cp config/common/secrets.yml.example config/common/secrets.yml
chmod 600 config/common/secrets.yml
```

真实 `config/common/secrets.yml` 与旧 `config/secrets.yml` 被 `.gitignore` 排除；示例、app、channels、watchlist 和 sources 配置受版本管理，不能把所有配置目录当作已忽略。

| 路径 | 用途 |
|---|---|
| `push.news_pipeline.feishu_hook_us / feishu_sign_us` | 美股新闻机器人 |
| `push.news_pipeline.feishu_hook_cn / feishu_sign_cn` | A 股新闻机器人 |
| `push.quote_watcher.feishu_hook_cn / feishu_sign_cn` | A 股盯盘机器人 |
| `llm.dashscope_api_key` | 新评估/摘要开启后才需要，默认规则运行可留未配置 |
| `sources.finnhub_token` | 启用 Finnhub 时需要 |
| `alert.bark_url` | 源失效/恢复、模型控制和行情告警 |

只启用已经填好密钥的源与频道。旧 flat push、Anthropic key 和 cookie 字段暂留兼容，不是新默认依赖。真实密钥不得提交或写入日志。

## app.yml

| 字段 | 默认 / 含义 |
|---|---|
| `pipeline.mode` | legacy / shadow / v2，默认 legacy |
| `llm.enabled` | false；新评估与归纳摘要的总开关 |
| `llm.assess` / `llm.digest` | 模型、max_tokens、prompt_version；默认 qwen-plus 不是选型结论 |
| `llm.pricing.<model>.input / output` | 人民币 / 百万 token；开启时两个实际模型都必须有正数单价 |
| `llm.daily_cost_ceiling_cny` | 5.0；评估和摘要共享的持久日预算 |
| `push.max_age_min` / `dedup_window_hours` | 90 分钟新鲜度、6 小时近期推送去重 |
| `push.same_ticker_burst_window_min / threshold` | 5 分钟 / 3 次；主体键突发降级 |
| `push.push_min_materiality / push_min_materiality_macro` | 公司 4、宏观/行业 5 |
| `push.digest_min_materiality / min_confidence` | 3 / 0.5 |
| `push.quiet_hours` | 默认关闭；北京时间 00:30–07:30 的可选静默策略 |
| `push.color_scheme` | us 默认，或 cn |
| `digest.max_items / max_age_hours` | 列表兜底 20 条、24 小时 |
| `scheduler.digest.cn / us` | 每项显式 at/tz；中国 08:27、20:57，美国纽约 08:27、16:27 |
| `ops.report_at / report_channel` | 北京时间 08:20 / feishu_cn |

先保留 `enabled: false, pricing: {}`。获授权完成模型评测、从真实控制台核对并填入两个模型的正数单价后，才开启 LLM；缺价、零价和负价会拒绝启动。不提供伪装成实际报价的示例单价。

旧 `runtime.hot_reload`、`runtime.daily_cost_ceiling_cny`、`scheduler.scrape.*`、`scheduler.llm`、`llm.tier*`/旧 prompt/cache/batch、classifier/charts、旧 push rate 和 retention 字段为迁移兼容，不能据此推断新入口行为。新保留任务使用 60/365/30/180 天规则，见存储文档。删除这些字段等待 v2 稳定一周。

## channels.yml

新闻只选匹配 market 且不以 `_alert` 结尾的启用频道；盯盘只选 cn 且以 `_alert` 结尾的频道。默认 `feishu_us`、`feishu_cn`、`feishu_cn_alert`，分别对应独立密钥。

```yaml
channels:
  feishu_cn:
    type: feishu
    market: cn
    enabled: true
    options:
      webhook_key: news_pipeline.feishu_hook_cn
      sign_key: news_pipeline.feishu_sign_cn
```

更多说明见 [部署](../../docs/getting-started/deployment-current.md)、[Assessment](../../docs/components/llm-pipeline.md) 和 [清理门槛](../../docs/operations/staged-cleanup.md)。

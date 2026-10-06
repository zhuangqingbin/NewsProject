# Config Schema

Schema 定义位于 `src/news_pipeline/config/schema.py`，当前示例配置在 `config/common`、`config/news_pipeline`、`config/quote_watcher`。新运行入口与兼容字段分开说明；旧字段仍能解析不意味着会生效。

## AppConfig 顶层结构

| 段 | 当前用途 |
|---|---|
| pipeline | mode：legacy（默认）、shadow、v2 |
| llm | enabled（默认 false）、base_url、assess/digest、pricing、日预算 |
| scheduler.digest | cn/us 每项 at/tz；旧时段字段暂留兼容 |
| push | 新鲜度、近期去重、主体突发、静默、实质性/置信度、颜色与一手底线 |
| digest | max_items=20、max_age_hours=24 |
| ops | 北京时间 report_at=08:20、report_channel=feishu_cn |
| runtime/classifier/dedup/charts/dead_letter/retention 旧字段 | 部分 legacy 兼容，不能当作新入口配置能力 |

## LLMCfg

默认 assess 为 qwen-plus / 400 tokens / assess_v1，digest 为 qwen-plus / 1500 tokens / digest_v1；模型名不是已验收选型。预算 `llm.daily_cost_ceiling_cny` 默认 5.0。`pricing.<model>.input/output` 单位人民币 / 百万 token，实际使用的两个模型在 enabled=true 时均须有正数价格。零/负值或缺失会拒绝开启。

## 推送与摘要

默认公司 push materiality 4、市场/行业 5、digest 3、min_confidence 0.5；一手底线 tier:high=4、tier:normal=3。新鲜度 max_age_min=90，dedup_window_hours=6，突发 5 分钟/3 次。quiet_hours 默认关闭，时区 Asia/Shanghai；color_scheme 为 us 或 cn。

摘要默认中国 08:27/20:57（Asia/Shanghai），美国 08:27/16:27（America/New_York）。新 Outbox 限速是持久 1 秒间隔及 20 次尝试/分钟，不读取旧 push.per_channel_rate。

## 其他配置文件 Schema

SourceDef 包含 enabled、interval_sec、lookback_min、fetch_timeout_sec、max_silence_min/max_silence_off_min 与 options。SEC user_agent 使用真实联系信息；巨潮和 SEC 初始化公司标识。

TickerEntry 包含 ticker、name、aliases、people、exclude、sectors、macro_links；短中文别名显式许可，跨公司冲突拒绝。旧 llm watchlist 双层开关不控制新 EventAssessor。

ChannelDef 包含 type、market、enabled 与 options。webhook_key/sign_key 是 nested secrets 路径；新闻使用非 _alert，盯盘使用 CN _alert。

## 兼容字段与后续删除

旧 Tier-0/1/2/3、旧 scheduler.scrape/llm、runtime.hot_reload、watchlist.llm、图表/死信设置保留到稳定门槛。新闻不进行 YAML 热加载，修改后重启；盯盘 alerts reloader 保留。详细候选字段见 [C1/C2 清单](../operations/staged-cleanup.md)。

## 相关

- [部署和生效方式](../getting-started/deployment-current.md)
- [规则](../components/rules.md) · [Assessment](../components/llm-pipeline.md) · [调度](../components/scheduler.md)

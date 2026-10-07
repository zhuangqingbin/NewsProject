# Assessment 与模型评测

保留 `llm-pipeline.md` 页面路径。新路径使用 `assess/{client,prompts,schema,assessor}.py`，每个事件一次结构化评估，摘要单独调用。旧四层 Tier-0/1/2/3、双层 rules/llm watchlist、Anthropic 路由和 YAML prompt 文件已删除。

## 默认关闭与配置

仓库默认 `llm.enabled: false`、`pricing: {}`。v2 在 LLM 关闭时仍可按规则抓取、即时推送和发摘要。启用新 LLM 前必须配置 API key、经过授权的模型选型，以及评估/摘要模型的实际正数 input/output 单价（人民币 / 百万 token）；缺价或零价会拒绝启动。

```yaml
llm:
  enabled: false
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  assess: {model: qwen-plus, max_tokens: 400, prompt_version: assess_v1}
  digest: {model: qwen-plus, max_tokens: 1500, prompt_version: digest_v1}
  daily_cost_ceiling_cny: 5.0
  pricing: {}
```

模型名是配置默认值，不是已完成 benchmark 的推荐。旧 `llm.tier*` 与 `runtime.daily_cost_ceiling_cny` 已从 schema 删除，不能带入新配置。

## 哪些事件送评估

每批最多 20 个待评估事件，共享最多 4 个并发请求。被公司标签命中、一手源、或源侧重要度 ≥ 2 的候选可以送评估；其余跳过并使用规则。正文选最长文章，超过 1500 字保留前 1000 和后 500 字。输入含持仓清单、一手来源/来源数、主体标题和相同标的最近 24 小时最多 8 个事件，帮助识别重复与更新。

## 输出校验

`event_type`、`scope`、`holdings` 关系与方向使用枚举；`materiality` 是 1–5 整数，`confidence` 在 0–1 内。summary 校验后截到 60 字；未知 ticker 从 holdings 删除，未知近期引用清空，错误 repeat 不沿用。新闻正文中的指令只作为数据，不得改变系统规则。

JSON 或 schema 不合法时带上错误信息重试一次，仍失败则 `assess_status='failed'`，决策使用规则。评估写入检查事件 `article_count` 和待评估状态，避免聚类追加证据期间写入旧响应。

## HTTP、预算与熔断

复用 OpenAI-compatible `AsyncClient`，默认超时 30 秒。网络错误、429、5xx、超时最多重试 2 次，等待 2 秒与 6 秒；其他 4xx 不重试。每次调用尝试的模型、prompt 版本、token、费用、耗时与错误写入 `llm_calls`。

评估与摘要共享预算、并发和熔断。预算按北京时间当天持久记录计算，并为在途请求预留保守成本，避免并发越限；上限后停止新调用，规则兜底，并一天告警一次。连续 10 次终态调用失败熔断 10 分钟，开断与恢复各告警一次。

## B0：模型选型不是已完成验收

先从三周样本导出 150 个事件：push 50、digest_hi 50、提及 30、宏观 20。人工修正预填 label/tickers，保留 30 条只做最终验证。`tests/eval/gold_events.jsonl` 目前只有 8 个未审核 seed，不是 150 条已审核 gold set。

付费对比在明确授权后才能运行；尚未进行付费 benchmark，不能引用虚构精度或生产费用。目标线是精度 ≥ 0.70、必推召回 ≥ 0.90、认错公司率 ≤ 2%、JSON 合法率 ≥ 99%、p95 ≤ 8 秒。

## 只读回放

```bash
uv run python -m news_pipeline.tools.replay --db /path/to/read-only-copy.db --from 2026-09-14 --to 2026-10-06 --mode rules --export data/review-events.csv
```

SQLite 用只读 URI 打开，不迁移或修改来源库。导出样本标为 unreviewed；规则/模型回放输出日推送候选数、合并倍数和已知案例，不等于线上发送成功数。`--eval --mode rules` 不调用模型，输出样本审核状态（seed 为 seed_unreviewed），不能把未审核指标当验收。取得授权、完成标注并配置真实单价后，才使用 `--mode llm`；`--eval --model ID` 未显式给 mode 时也自动选 llm，会触发付费调用。响应缓存哈希含完整输入、模型、prompt 版本和供应商，重复缓存命中不再次计为新调用费用。

## 相关

- [规则兜底](rules.md) · [决策与摘要](dispatch-router.md)
- [灰度与回滚](../getting-started/deployment-current.md) · [运维报告](observability.md)

# B0 样本审核与模型验收

B0 必须使用真实三周新闻、150 条人工审核事件及独立的 30 条留出集。仓库里的八条 `seed_unreviewed` 只用于回归，不是已审核样本。当前默认仍是 `legacy`、LLM 关闭；完成以下准备不会切换生产模式。

2026-10-07 已只读提取 9/14–10/6 的 60,832 条真实原始新闻，并准备好包含八类案例、50/50/30/20 分层的 150 条待审核 CSV。本地文件位于工作区 `data/b0/2026-09-14_2026-10-06/review-150.csv`，不提交原始新闻到 Git。150 条目前全部是 `unreviewed`；具体来源、哈希、选择方法与验证见[本轮记录](../superpowers/reviews/2026-10-07-rollout-hardening-verification.md)。

## 导出与人工审核

先用 SQLite backup API 取得一致的数据库副本，或在单个只读事务中提取所需 `raw_news` 窗口并在本地重建样本库；后者不包含完整备份所需的其他表。按实际样本窗口修改日期。回放以只读方式打开数据库，不执行迁移、不写入事件、不发送消息。

```bash
uv run python -m news_pipeline.tools.replay \
  --db /path/to/news-backup.db --from 2026-09-14 --to 2026-10-06 \
  --mode rules --export data/review-150.csv
```

导出按 push 50、digest_hi 50、mention 30、macro 20 抽样。某层不足时不从其他层补齐；JSON 输出中的 `export_shortfall` 和 `exported_strata` 说明缺口，需扩展真实样本范围后重新导出到新文件。已有 CSV 不会被覆盖。

CSV 保留稳定 `id`、原回放 `event_id`、来源、市场、发布时间、URL 和 `raw_meta`。`sources`、`tickers` 是 JSON 数组，`raw_meta` 是 JSON 对象。保持这些证据完整，逐行核对正文并修正 `label` 和 `tickers`；`label` 只允许 `must_push`、`digest`、`drop`。只有实际完成审核后，才把对应行的 `annotation_status` 改成 `reviewed`。规则预填标签不是人工结论。

在 `case` 列标记八类已知案例：`nvda_buyback`、`tesla_target`、`tesla_fitch`、`meta_big_move`、`amd_acquisition`、`avgo_roundup`、`yaoming_junuo`、`ningde_city`。自动回放只聚合规则候选，因此药明巨诺、宁德市等已经被正确丢弃的反例可能不在抽样 CSV 中；需从真实原始新闻补入并替换同层样本，保留真实来源证据、唯一标识和总分层数量。不要为 seed 示例编造发布时间或 URL。未收集齐这些案例时，验收验证会明确报告缺口。

## 导入与冻结留出集

```bash
uv run python -m news_pipeline.tools.gold import \
  --csv data/review-150.csv --output data/gold-reviewed-v1.jsonl
uv run python -m news_pipeline.tools.gold validate \
  data/gold-reviewed-v1.jsonl --acceptance
```

导入拒绝未审核行、错误 JSON 字段、重复标识、无时区时间及缺失证据，且不覆盖已有输出。它按稳定 ID 固定每层的 train/holdout 成员：训练集 40/40/24/16，留出集 10/10/6/4，共 120/30 条。划分不依据标签或 ticker；不要通过改 ID、替换样本或反复调换成员来改变留出结果。

导入可以保存不足 150 条的已审核回归集，但只有完整的 150 条、50/50/30/20 分层、八类案例、全员审核、正确固定拆分同时满足时，`acceptance_ready` 才为 true。`validate --acceptance` 不满足时退出码为 1；格式错误退出码为 2。`dataset_hash` 标识包含证据、标签与拆分的整个数据集，重排文件行不会改变哈希。

## 调参与最终评测

先运行不花费模型额度的规则基线：

```bash
uv run python -m news_pipeline.tools.replay \
  --eval data/gold-reviewed-v1.jsonl --mode rules --split train
```

真实模型评测前，必须先确定候选模型、核实对应供应商的每百万 token 输入/输出人民币价格、估算本轮费用，并取得付费调用确认。公开价格与一轮估算见 [B0 模型准备](b0-model-proposal.md)。将价格填入 `llm.pricing`，配置真实 API key。下面的 `MODEL_ID` 只是命令占位符；准备流程没有自动执行这些请求。

```bash
uv run python -m news_pipeline.tools.replay \
  --eval data/gold-reviewed-v1.jsonl --model MODEL_ID --split train \
  --cache-dir data/replay-cache > data/model-train-report.json
# 仅在提示词与模型已固定后运行保留的最终集合：
uv run python -m news_pipeline.tools.replay \
  --eval data/gold-reviewed-v1.jsonl --model MODEL_ID --split holdout \
  --cache-dir data/replay-cache > data/model-holdout-report.json
```

存在固定拆分的数据集不指定 `--split` 时默认只评测 train；最终验收必须显式选择 holdout。小型 seed 回归集默认评测全部，仍显示 `not_eligible`。显式 `--mode rules` 始终不创建模型客户端，即使同时指定了 `--model`。

报告包含数据集哈希、所选集合、模型、供应商、提示词版本、缓存命中、实际新增费用和预算降级数量。缓存键涵盖完整请求与提示词版本，命中不重复计入新增费用。本次回放以 `llm.daily_cost_ceiling_cny` 作为新增费用上限，阻止超预算请求；各 CLI 进程之间不共享当天额度，运行多模型时须合计费用。降级不是成功模型输出。

只有完整已审核数据集上的 30 条 holdout 的 LLM 报告可取得验收结果。五项门槛必须同时满足：push precision ≥ 0.70、must-push recall ≥ 0.90、错 ticker 比例 ≤ 0.02、JSON 合法率 ≥ 0.99、P95 延迟 ≤ 8000 ms。结果为 `pass`、`fail` 或 `not_eligible`，每项显示实际值与门槛；规则基线和训练集不会被标为模型验收通过。

通过 B0 后，仍需部署 IP 的上游检查、交易时段行情单位核对及 2–3 个交易日 shadow。C1/C2 删除等一周 v2 稳定后执行，D 扩源等两周稳定及明确选择后执行，见[部署指南](../getting-started/deployment-current.md)与[清理清单](staged-cleanup.md)。

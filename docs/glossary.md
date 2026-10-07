# Glossary

| 术语 | 当前含义 |
|---|---|
| RawArticle | 抓取器输出的原始文章；URL hash 用于幂等保存 |
| Event | 聚合多个来源文章的同一事件，保留独立原文证据 |
| Assessment | 一次结构化评估：类型、标的关系、实质性、方向、摘要与重复引用 |
| materiality | 1–5 的实质性评分，用于即时与摘要门槛 |
| fallback | LLM 关闭、跳过或失败时使用规则决策 |
| Outbox | 与决策同事务保存的待发消息；持久重试、限速与成功状态 |
| digest | 按市场本地时区触发的事件摘要；全部目标频道成功后消费候选 |
| v2_state | 原始新闻的事件处理状态，与保留的旧 status 独立 |
| source_state | 每源成功、失败、退避、最新条目与健康转换状态 |
| heartbeat | 进程与任务活性记录，独立于上游健康及发送结果 |
| CIK / orgId | SEC / 巨潮公司标识，初始化时查询，不按 ticker 推导 |
| akshare | 全球快讯、财经早餐、新闻联播及盯盘日 K 的上游库 |
| Bark | 独立运维告警；来源仅在健康状态转换时告警 |
| FTS5 | SQLite 全文索引；当前 events_fts 索引事件标题与摘要 |
| gold set | 真实样本经人工复核、固定训练/留出成员后的评测数据 |
| shadow | v0.7.0 灰度模式；本 v0.7.1 清理分支已删除其运行入口 |

旧 Tier-0/1/2/3、LLMJudge、simhash 与 bot commands 不属于当前运行能力。历史设计保留在 superpowers/specs 下。

[架构](architecture.md) · [存储](components/storage.md) · [Assessment](components/llm-pipeline.md)

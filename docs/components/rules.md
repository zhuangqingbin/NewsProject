# Rules Engine

`rules/` 的职责是召回候选并提供可独立运行的兜底决策。v0.7.1 仅支持 v2，LLM 默认关闭；评估失败、预算耗尽或熔断时同样使用规则。

## 配置

`config/news_pipeline/watchlist.yml` 定义公司 ticker、正式名称、`aliases`、`people`、`exclude`、行业；`scoring.yml` 定义事件词与通用召回词；`first_party.yml` 定义巨潮标题和 SEC 表单分级。

```yaml
rules:
  us:
    - ticker: NVDA
      name: NVIDIA
      aliases: [英伟达]
      people: [Jensen Huang]
      exclude: []
      sectors: [semiconductor]
  cn: []
```

两字中文别名必须显式列入 `short_alias_allow`；别名不能跨公司冲突。英文名称使用词边界。先移除 `exclude` 语境，再匹配公司；人物名字单独记录，不直接等同于公司主体。A 股 ticker 用带引号的六位字符串。旧 watchlist `llm:` 段、双层 enable 和 macro_links 已删除；模型总开关是 `app.yml` 的 `llm.enabled`。

## 标题句与判定

原标题太短或只是“市场消息”时，从正文取首个有信息的标题句。标题句命中的公司是 `subject_tickers`；正文和人物语境可补充 `tagged_tickers`。主体、靠前事件词、明确金额和涨跌幅用于分级；行情名单或只在背景提及的公司不会自动即时推送。市场由主体所属市场决定，主体为空再取标签，仍为空用文章市场。

`RulesVerdict` 的新核心字段是 `decision`（push / digest_hi / digest_lo / drop）、`reason`、主体/标签、市场、源侧重要度和 `rank_score`。它不是 LLM 的实质性评分。旧评分入口已删除。

## 一手源

巨潮公告用标题规则分 high / normal / low；SEC 用表单类型分级。低等级噪声直接过滤。相同公司、同轮抓取、10 分钟内的 high 巨潮公告最多合并 5 份，卡片保留每份标题与原文链接；不能把普通媒体报道都当一手公告。

## 与评估和推送的关系

v2 把候选聚成事件，再做可选评估。评估完成后，政策默认要求公司主体或交易对手关系、实质性 ≥ 4、置信度 ≥ 0.5；市场/行业即时推送要求实质性 ≥ 5。规则判 push 而模型评分低时降为摘要，防止增强层直接丢掉规则的重要候选。旧 `gray_zone_action` 与 Tier-0/1/2/3 配置已删除。

修改词表后先跑录制样本和 [只读回放](llm-pipeline.md)，再核对当前事件与原文证据。不存在本次发布已经达到线上精度门槛的结论。

## 相关

- [事件与去重](dedup.md) · [Assessment](llm-pipeline.md)
- [决策与 Outbox](dispatch-router.md) · [清理门槛](../operations/staged-cleanup.md)

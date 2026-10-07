# config/news_pipeline — 新闻配置

仅新闻子系统使用。修改后执行 `docker compose restart app`。本清理分支仅支持 v2，LLM 默认关闭；开关位于 `config/common/app.yml`。旧 watchlist 的 `llm` 段已删除。

## sources.yml

每源配置 `enabled`、`interval_sec`、`lookback_min`、`fetch_timeout_sec`、`max_silence_min`、`max_silence_off_min` 与可选 `options`。抓取回看窗口不使用排他水位线。失败指数退避最多 30 分钟，静默阈值区分交易日白天和其他时段。

当前源包括新浪、富途、东财与同花顺全球快讯、`cls_telegraph`、华尔街见闻、Finnhub、`em_stock_news`、巨潮、SEC、财经早餐与新闻联播；旧 `kr36` 已删除。旧 `caixin_telegram` 与 `akshare_news` 由直连新源替代，不应重新打开旧名称。

```yaml
sources:
  sec_edgar:
    enabled: true
    interval_sec: 120
    lookback_min: 4320
    options:
      user_agent: 'NewsProject operator operator@example.org'
```

用自己的真实联系人与邮箱替换示例。当前 Compose 会从宿主 export 或仓库 `.env` 注入 `SEC_USER_AGENT`，新闻主进程用它覆盖文件设置；环境变更后用 `docker compose up -d app` 重建容器。不要原样保留 `<你的邮箱>`。SEC 会初始化 CIK，巨潮初始化 orgId；未知自选代码会拒绝初始化，网络失败由抓取重试。巨潮不按不可靠公告时间过滤。

## watchlist.yml

rules 的每只股票包含 ticker、name、aliases、people、exclude、sectors。A 股代码加引号。人物单独放 people；同名公司语境放 exclude。短中文别名须列入 `short_alias_allow`，跨公司别名冲突会启动报错。

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

标题命中决定主体，全文命中补标签；路由优先主体市场，无主体时使用标签，再使用文章市场。旧双层 rules/llm enable、gray_zone_action、macro_links 和旧通用词表已删除；新评估器使用同一份 rules 持仓清单。

## scoring.yml 与 first_party.yml

`scoring.yml` 管理事件词、标题位置、明确金额/涨跌幅和宏观/政策/行业召回词。`first_party.yml` 管理巨潮公告标题 high/normal/low 与 SEC 表单等级，并定义巨潮合并窗口和条数限制。词表变更先做录制样本、只读回放和影子观察，不凭关键词命中就宣称投资重要性。

## Prompt 版本

旧 Tier-0/1/2/3 YAML 模板与 prompts/ 目录已删除。新 prompt 在 `src/news_pipeline/assess/prompts.py`，`app.yml` 的 assess/digest `prompt_version` 记录其版本。不要把旧模板或旧 tier 字段带入新配置。

详见 [抓取源](../../docs/components/scrapers.md)、[规则](../../docs/components/rules.md)、[评测门槛](../../docs/components/llm-pipeline.md) 和 [清理清单](../../docs/operations/staged-cleanup.md)。这些非密钥配置受版本管理，只有真实 secrets 文件被忽略。

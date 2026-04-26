# Watchlist 重设计 — Rules + LLM 双段架构

- **作者**：qingbin
- **日期**：2026-04-26
- **状态**：Draft（brainstorming approved，待 implementation plan）
- **目标版本**：v0.3.0
- **取代**：v0.1.7 的扁平 `watchlist.yml`（us / cn / macro / sectors 顶层数组）

---

## 0. 一句话目标

把单层关键词 watchlist 改成 **rules（规则匹配，免费快速）+ llm（LLM 智能筛选，可选）** 双段，rules 默认开、llm 默认关。rules 用 Aho-Corasick 算法对 ticker / 别名 / 板块 / 宏观关键词做多模式匹配，匹配方法**可插拔**（未来可换 TF-IDF / embedding / regex / composite）。

## 0.1 解决的痛点

当前（v0.1.7）watchlist 只能配 ticker 列表，全靠 LLM Tier-0 做语义判定 watchlist_hit：

- **慢**：每条新闻 1-2 秒 LLM 调用
- **贵**：累积消耗 DashScope token
- **不可控**：LLM 偶尔漏判、过判
- **死路一条**：想加复杂关联（NVDA 关联 TSMC、半导体板块）只能在 prompt 里塞，不可枚举不可调试

新方案：
- **绝大多数情况**走 rules（毫秒级、零成本、可解释）
- **只在 rules 没覆盖到的场景**用 LLM（用户主动 enable）
- 配置可枚举：所有 ticker / alias / 板块 / 宏观关键词都明文写在 yml，可审计可单测

---

## 1. 架构 + 数据流

### 1.1 模块布局

```
src/news_pipeline/
├── rules/                          # ← 全新模块
│   ├── __init__.py
│   ├── matcher.py                  # MatcherProtocol + AhoCorasickMatcher
│   ├── engine.py                   # RulesEngine: 编译 patterns + 反向索引 + match()
│   ├── verdict.py                  # RulesVerdict 数据契约
│   └── factory.py                  # build_matcher(name, options) 工厂
│
├── classifier/importance.py        # ← 接收 RulesVerdict 参数
├── llm/pipeline.py                 # ← 加 process_with_rules() 跳过 Tier-0
├── pushers/common/message_builder.py # ← 加 build_from_rules()
├── scheduler/jobs.py               # ← process_pending 加 rules 前置
├── config/schema.py                # ← WatchlistFile 重构
└── main.py                         # ← wiring
```

### 1.2 数据流（4 种 enable 组合下）

| `rules.enable` | `llm.enable` | 行为 |
|---|---|---|
| **true / false（默认）** | rules.match → 命中走 `synth_enriched_from_rules`（无 LLM）→ classifier → router → push。**不命中：mark_status='skipped_rules' 丢弃。** |
| true / true | rules.match → 命中走 `LLMPipeline.process_with_rules`（跳过 Tier-0，直接 Tier-1 或 Tier-2 拿摘要）→ ...。**不命中：丢弃**（rules 仍是 gate） |
| false / true | 跳过 rules，走原有 LLM 全流程（Tier-0 → Tier-1/2 → ...） |
| false / false | **启动报错**（schema 校验阻止） |

详细流程图见 §4.2。

---

## 2. 配置 Schema

### 2.1 完整 YAML

```yaml
# config/watchlist.yml

rules:
  enable: true
  gray_zone_action: digest      # 'skip' | 'digest'（默认） | 'push'
  
  us:
    - ticker: NVDA
      name: NVIDIA
      aliases: [英伟达, 老黄家, Jensen Huang, GPU 龙头]
      sectors: [semiconductor, ai]
      macro_links: [FOMC, CPI]
    - ticker: TSLA
      name: Tesla
      aliases: [特斯拉, Elon Musk, 马斯克]
      sectors: [ev, autonomous driving]
      macro_links: [FOMC]
  
  cn:
    - ticker: "600519"
      name: 贵州茅台
      aliases: [茅台, 飞天茅台]
      sectors: [白酒]
      macro_links: [央行, MLF, LPR]
    - ticker: "300750"
      name: 宁德时代
      aliases: [CATL]
      sectors: [新能源, 锂电池]
      macro_links: [央行, LPR]
  
  keyword_list:                 # 通用关键词，命中即 relevant，不绑特定 ticker
    us: [Powell, Yellen, recession, soft landing, AI bubble]
    cn: [证监会, 国常会, 中央经济工作会议]
  
  macro_keywords:               # 宏观关键词，被 ticker.macro_links 引用
    us: [FOMC, CPI, NFP, 美联储, 加息, 降息, PCE, jobless claims]
    cn: [央行, MLF, LPR, 降准, 降息, PMI, 社融, 政治局会议]
  
  sector_keywords:              # 板块关键词，被 ticker.sectors 引用
    us: [semiconductor, AI chip, GPU, autonomous driving, biotech, ev]
    cn: [白酒, 新能源, 半导体, 储能, 锂电池, 光伏]

llm:
  enable: false
  us: [NVDA, TSLA, AAPL]
  cn: ["600519", "300750"]
  macro: [FOMC, CPI]
  sectors: [semiconductor]
```

### 2.2 Pydantic Schema (`config/schema.py`)

```python
class TickerEntry(_Base):
    ticker: str
    name: str
    aliases: list[str] = []
    sectors: list[str] = []
    macro_links: list[str] = []
    alerts: list[str] = []           # 兼容旧字段，仅 LLM 使用


class MarketKeywords(_Base):
    us: list[str] = []
    cn: list[str] = []


class RulesSection(_Base):
    enable: bool = True
    gray_zone_action: Literal["skip", "digest", "push"] = "digest"
    matcher: str = "aho_corasick"            # 算法名（工厂选）
    matcher_options: dict[str, Any] = {}     # 算法特定配置
    us: list[TickerEntry] = []
    cn: list[TickerEntry] = []
    keyword_list: MarketKeywords = Field(default_factory=MarketKeywords)
    macro_keywords: MarketKeywords = Field(default_factory=MarketKeywords)
    sector_keywords: MarketKeywords = Field(default_factory=MarketKeywords)


class LLMSection(_Base):
    enable: bool = False
    us: list[str] = []
    cn: list[str] = []
    macro: list[str] = []
    sectors: list[str] = []


class WatchlistFile(_Base):
    rules: RulesSection = Field(default_factory=RulesSection)
    llm: LLMSection = Field(default_factory=LLMSection)
    
    @model_validator(mode="after")
    def at_least_one_enabled(self) -> "WatchlistFile":
        if not self.rules.enable and not self.llm.enable:
            raise ValueError(
                "watchlist.yml: rules.enable AND llm.enable both False — "
                "at least one must be enabled"
            )
        return self
    
    @model_validator(mode="after")
    def ticker_unique(self) -> "WatchlistFile":
        for market in ("us", "cn"):
            tickers = [t.ticker for t in getattr(self.rules, market)]
            if len(tickers) != len(set(tickers)):
                dups = {t for t in tickers if tickers.count(t) > 1}
                raise ValueError(f"rules.{market}: duplicate tickers {dups}")
        return self
    
    @model_validator(mode="after")
    def sector_macro_refs_valid(self) -> "WatchlistFile":
        for market in ("us", "cn"):
            sectors_set = set(getattr(self.rules.sector_keywords, market))
            macros_set = set(getattr(self.rules.macro_keywords, market))
            for entry in getattr(self.rules, market):
                bad_sectors = set(entry.sectors) - sectors_set
                bad_macros = set(entry.macro_links) - macros_set
                if bad_sectors:
                    raise ValueError(
                        f"{market} ticker {entry.ticker}: "
                        f"sectors {bad_sectors} not in sector_keywords.{market}"
                    )
                if bad_macros:
                    raise ValueError(
                        f"{market} ticker {entry.ticker}: "
                        f"macro_links {bad_macros} not in macro_keywords.{market}"
                    )
        return self
```

### 2.3 启动校验汇总

| 校验 | 失败行为 |
|---|---|
| 至少一个 enable=true | 拒启动（raise ValueError） |
| 同 market 内 ticker 唯一 | 拒启动 |
| ticker.sectors 引用了不存在的 sector_keyword | 拒启动 |
| ticker.macro_links 引用了不存在的 macro_keyword | 拒启动 |
| keyword_list / macro_keywords / sector_keywords 内重复关键词 | warn 不 fail |
| 同一关键词同时出现在 us 和 cn | warn 不 fail |

---

## 3. 算法（Aho-Corasick）

### 3.1 库

[`pyahocorasick>=2.1`](https://pyahocorasick.readthedocs.io/) — C 扩展，多模式串匹配标准库。

### 3.2 Pattern 数据结构

```python
class PatternKind(StrEnum):
    TICKER = "ticker"
    ALIAS = "alias"
    SECTOR = "sector"
    MACRO = "macro"
    GENERIC = "generic"


@dataclass(frozen=True)
class Pattern:
    text: str             # 关键词（lowercase）
    is_english: bool      # True = 全 ASCII，需 word boundary 校验
    kind: PatternKind
    market: Market        # us / cn
    owner: str            # TICKER/ALIAS → ticker code; 其他 → keyword 自身


@dataclass(frozen=True)
class Match:
    pattern: Pattern
    start: int
    end: int
    matched_text: str
```

### 3.3 MatcherProtocol（可插拔）

```python
class MatcherProtocol(Protocol):
    def rebuild(self, patterns: list[Pattern]) -> None: ...
    def find_all(self, text: str) -> list[Match]: ...


class AhoCorasickMatcher(MatcherProtocol):
    """Default: O(N+M) multi-pattern keyword search."""
    
    def __init__(self) -> None:
        self._auto: ahocorasick.Automaton | None = None
    
    def rebuild(self, patterns: list[Pattern]) -> None:
        auto = ahocorasick.Automaton()
        # 多个 Pattern 可能共享同一文本（不同 market / kind），用 list payload
        grouped: dict[str, list[Pattern]] = {}
        for p in patterns:
            grouped.setdefault(p.text, []).append(p)
        for text, group in grouped.items():
            auto.add_word(text, group)
        auto.make_automaton()
        self._auto = auto
    
    def find_all(self, text: str) -> list[Match]:
        text_lc = text.lower()
        out: list[Match] = []
        for end_idx, payloads in self._auto.iter(text_lc):
            for p in payloads:
                start_idx = end_idx - len(p.text) + 1
                if p.is_english and not _word_boundary_ok(text_lc, start_idx, end_idx):
                    continue
                out.append(Match(p, start_idx, end_idx, text_lc[start_idx:end_idx + 1]))
        return out


def _word_boundary_ok(text: str, start: int, end: int) -> bool:
    """英文 pattern 必须前后是非字母数字字符。
    防止 'NVDA' 误命中 'ENVDAQ'。中文不需要。
    """
    left_ok = (start == 0) or not text[start - 1].isalnum()
    right_ok = (end == len(text) - 1) or not text[end + 1].isalnum()
    return left_ok and right_ok


# 工厂
def build_matcher(name: str, options: dict[str, Any]) -> MatcherProtocol:
    if name == "aho_corasick":
        return AhoCorasickMatcher(**options)
    raise ValueError(f"unknown matcher: {name}")
```

### 3.4 RulesEngine

```python
class RulesEngine:
    def __init__(
        self,
        watchlist: RulesSection,
        matcher: MatcherProtocol,
    ) -> None:
        patterns, sector_to_tickers, macro_to_tickers = _compile(watchlist)
        matcher.rebuild(patterns)
        self._matcher = matcher
        self._sector_to_tickers = sector_to_tickers   # dict[str, set[str]]
        self._macro_to_tickers = macro_to_tickers     # dict[str, set[str]]
    
    def match(self, art: RawArticle) -> RulesVerdict:
        text = f"{art.title}  {art.body or ''}"
        matches = self._matcher.find_all(text)
        
        if not matches:
            return RulesVerdict(matched=False)
        
        tickers: set[str] = set()
        sectors: set[str] = set()
        macros: set[str] = set()
        generics: list[str] = []
        markets: set[str] = set()
        related_tickers: set[str] = set()
        
        for m in matches:
            p = m.pattern
            markets.add(p.market.value)
            if p.kind in (PatternKind.TICKER, PatternKind.ALIAS):
                tickers.add(p.owner)
            elif p.kind == PatternKind.SECTOR:
                sectors.add(p.text)
                related_tickers.update(self._sector_to_tickers.get(p.text, []))
            elif p.kind == PatternKind.MACRO:
                macros.add(p.text)
                related_tickers.update(self._macro_to_tickers.get(p.text, []))
            elif p.kind == PatternKind.GENERIC:
                generics.append(p.text)
        
        return RulesVerdict(
            matched=True,
            tickers=sorted(tickers),
            related_tickers=sorted(related_tickers - tickers),
            sectors=sorted(sectors),
            macros=sorted(macros),
            generic_hits=generics,
            markets=sorted(markets),
            score_boost=_compute_boost(tickers, sectors, macros),
        )


def _compute_boost(tickers, sectors, macros) -> float:
    boost = 0.0
    if tickers:           boost += 50.0
    if sectors:           boost += 20.0
    if macros:            boost += 15.0
    return min(boost, 100.0)


def _compile(rules: RulesSection) -> tuple[list[Pattern], dict, dict]:
    """从 RulesSection 构建 Pattern 列表 + 反向索引。"""
    patterns: list[Pattern] = []
    sector_to_tickers: dict[str, set[str]] = {}
    macro_to_tickers: dict[str, set[str]] = {}
    
    for market_str in ("us", "cn"):
        market = Market(market_str)
        for entry in getattr(rules, market_str):
            patterns.append(Pattern(
                text=entry.ticker.lower(),
                is_english=entry.ticker.isascii(),
                kind=PatternKind.TICKER,
                market=market,
                owner=entry.ticker,
            ))
            patterns.append(Pattern(
                text=entry.name.lower(),
                is_english=entry.name.isascii(),
                kind=PatternKind.ALIAS,
                market=market,
                owner=entry.ticker,
            ))
            for alias in entry.aliases:
                patterns.append(Pattern(
                    text=alias.lower(),
                    is_english=alias.isascii(),
                    kind=PatternKind.ALIAS,
                    market=market,
                    owner=entry.ticker,
                ))
            for sec in entry.sectors:
                sector_to_tickers.setdefault(sec.lower(), set()).add(entry.ticker)
            for mac in entry.macro_links:
                macro_to_tickers.setdefault(mac.lower(), set()).add(entry.ticker)
        
        # SECTOR / MACRO / GENERIC patterns
        for kw in getattr(rules.sector_keywords, market_str):
            patterns.append(Pattern(
                text=kw.lower(), is_english=kw.isascii(),
                kind=PatternKind.SECTOR, market=market, owner=kw,
            ))
        for kw in getattr(rules.macro_keywords, market_str):
            patterns.append(Pattern(
                text=kw.lower(), is_english=kw.isascii(),
                kind=PatternKind.MACRO, market=market, owner=kw,
            ))
        for kw in getattr(rules.keyword_list, market_str):
            patterns.append(Pattern(
                text=kw.lower(), is_english=kw.isascii(),
                kind=PatternKind.GENERIC, market=market, owner=kw,
            ))
    
    return patterns, sector_to_tickers, macro_to_tickers
```

### 3.5 性能特征

| 指标 | 数值 |
|---|---|
| 总 patterns（50 stocks 配置） | ~350 |
| 自动机构建时间 | < 10 ms（启动 + 配置热加载时一次） |
| 单条新闻 (1 KB 文本) 匹配 | < 1 ms |
| 1 天 1000 条新闻总开销 | < 1 秒 |
| 内存 | ~5 MB |

对比当前 LLM Tier-0：每条 1-2 秒 + ¥0.0001 → **rules 快 1000x，零成本**。

---

## 4. Pipeline 集成

### 4.1 RulesVerdict 数据契约

```python
@dataclass(frozen=True)
class RulesVerdict:
    matched: bool
    tickers: list[str] = field(default_factory=list)
    related_tickers: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    generic_hits: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    score_boost: float = 0.0
```

### 4.2 `scheduler/jobs.py:process_pending` 改动

```python
async def process_pending(
    *, raw_dao, llm, rules_engine, importance, proc_dao,
    msg_builder, router, dispatcher, push_log, digest_dao,
    burst, rules_enabled: bool, llm_enabled: bool,
    batch_size: int = 25,
) -> int:
    pending = await raw_dao.list_pending(limit=batch_size)
    processed = 0
    for raw in pending:
        art = _raw_to_article(raw)
        
        # === 1. Rules 阶段 ===
        verdict = rules_engine.match(art) if rules_enabled else None
        
        if rules_enabled and not verdict.matched:
            # rules 是 gate，不命中直接丢
            await raw_dao.mark_status(raw.id, "skipped_rules")
            continue
        
        # === 2. EnrichedNews 来源 ===
        if llm_enabled:
            try:
                if verdict is not None and verdict.matched:
                    enriched = await llm.process_with_rules(art, verdict, raw_id=raw.id)
                else:
                    enriched = await llm.process(art, raw_id=raw.id)
            except Exception as e:
                await raw_dao.mark_status(raw.id, "dead", error=str(e))
                continue
            if enriched is None:
                await raw_dao.mark_status(raw.id, "skipped")
                continue
        else:
            # rules-only mode: 不调 LLM，直接构造 EnrichedNews
            enriched = synth_enriched_from_rules(art, verdict, raw_id=raw.id)
        
        # === 3. classifier ===
        scored = await importance.score_news(enriched, source=raw.source, verdict=verdict)
        proc_id = await proc_dao.insert(...)
        await raw_dao.mark_status(raw.id, "processed")
        
        # === 4. 路由 + 推 ===
        msg = (
            msg_builder.build_from_rules(art, scored, verdict)
            if not llm_enabled
            else msg_builder.build(art, scored, chart_url=None)
        )
        plans = router.route(scored, msg, markets=verdict.markets if verdict else None)
        
        for p in plans:
            if p.immediate:
                if not burst.should_send(enriched.related_tickers):
                    continue
                results = await dispatcher.dispatch(p.message, channels=p.channels)
                for ch, r in results.items():
                    await push_log.write(...)
            else:
                # gray zone or non-critical → digest
                await digest_dao.enqueue(
                    news_id=proc_id, market=art.market.value,
                    scheduled_digest=_choose_digest_key(art.market, utc_now()),
                )
        
        processed += 1
    return processed
```

### 4.3 `synth_enriched_from_rules` 函数

```python
def synth_enriched_from_rules(
    art: RawArticle, verdict: RulesVerdict, *, raw_id: int
) -> EnrichedNews:
    """Rules-only mode：不调 LLM 时构造 EnrichedNews。
    summary = 标题 + 正文前 200 字截取（无 LLM 摘要）。
    """
    body_excerpt = (art.body or "")[:200].rstrip()
    summary = body_excerpt or art.title
    
    related = list(set(verdict.tickers + verdict.related_tickers))
    
    return EnrichedNews(
        raw_id=raw_id,
        summary=summary,
        related_tickers=related,
        sectors=verdict.sectors,
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.LOW,
        confidence=0.0,                 # 标记为非 LLM 推断
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="rules-only",        # push_log 区分
        extracted_at=utc_now().replace(tzinfo=None),
    )
```

### 4.4 `LLMPipeline.process_with_rules`

```python
async def process_with_rules(
    self, art: RawArticle, verdict: RulesVerdict, *, raw_id: int
) -> EnrichedNews | None:
    """rules + llm 模式：rules 已判 relevant，跳过 Tier-0。
    根据 verdict 决定走 Tier-1 还是 Tier-2。
    """
    self._cost.check()
    
    # 直接 ticker 命中 OR 来自一手源 → Tier-2 深度抽取
    if verdict.tickers or art.source in self._first_party_sources:
        return await self._tier2.extract(art, raw_id=raw_id, recent_context="")
    # 否则 Tier-1 摘要
    return await self._tier1.summarize(art, raw_id=raw_id)
```

### 4.5 `classifier/importance.py` 改动

```python
async def score_news(
    self, enriched: EnrichedNews, *,
    source: str,
    verdict: RulesVerdict | None = None,
) -> ScoredNews:
    rule_hits = self._rules.evaluate(enriched, source=source)
    score = float(self._rules.score(rule_hits))
    
    # 加 verdict score_boost
    if verdict is not None and verdict.matched:
        score += verdict.score_boost
        rule_hits.append(RuleHit(
            f"rules_{','.join(verdict.markets)}", int(verdict.score_boost)
        ))
    score = min(100.0, score)
    
    if score >= self._hi:
        return ScoredNews(
            enriched=enriched, score=score, is_critical=True,
            rule_hits=[h.name for h in rule_hits], llm_reason=None,
        )
    if score < self._lo:
        return ScoredNews(
            enriched=enriched, score=score, is_critical=False,
            rule_hits=[h.name for h in rule_hits], llm_reason=None,
        )
    
    # 灰区：根据 gray_zone_action 决定
    if not self._llm_enabled:
        # rules-only 灰区行为：根据 RulesSection.gray_zone_action 决定
        action = self._gray_zone_action  # 'skip' | 'digest' | 'push'
        if action == "push":
            is_crit = True
        elif action == "skip":
            is_crit = False
            score = -1   # 特殊标记，让 router 不入 digest 也不推
        else:  # digest
            is_crit = False
        return ScoredNews(
            enriched=enriched, score=score, is_critical=is_crit,
            rule_hits=[h.name for h in rule_hits],
            llm_reason=f"rules-only-grayzone-{action}",
        )
    
    # llm.enable=True：调 LLM judge
    is_crit, reason = await self._judge.judge(enriched, watchlist_tickers=self._wl)
    return ScoredNews(...)
```

### 4.6 `pushers/common/message_builder.py` 改动

```python
def build_from_rules(
    self, art: RawArticle, scored: ScoredNews, verdict: RulesVerdict, *,
    chart_url: str | None = None,
) -> CommonMessage:
    """Rules-only mode 消息构造。"""
    e = scored.enriched
    badges = []
    for t in (verdict.tickers + verdict.related_tickers)[:5]:
        badges.append(Badge(text=t, color="blue"))
    for s in verdict.sectors[:2]:
        badges.append(Badge(text=f"#{s}", color="gray"))
    if verdict.macros:
        badges.append(Badge(text=f"📊 {verdict.macros[0]}", color="yellow"))
    if verdict.generic_hits:
        badges.append(Badge(text=f"🔖 {verdict.generic_hits[0]}", color="gray"))
    badges.append(Badge(text="rules", color="green"))   # 标记规则匹配
    
    deeplinks = [Deeplink(label="原文", url=str(art.url))]
    for t in (verdict.tickers + verdict.related_tickers)[:3]:
        if art.market == Market.US:
            deeplinks.append(Deeplink(
                label=f"Yahoo {t}",
                url=f"https://finance.yahoo.com/quote/{t}",
            ))
        else:
            deeplinks.append(Deeplink(
                label=f"东财 {t}",
                url=f"https://quote.eastmoney.com/{('sh' if t.startswith('6') else 'sz')}{t}.html",
            ))
    
    return CommonMessage(
        title=art.title,
        summary=e.summary,                # = body[:200] 截取
        source_label=self._labels.get(art.source, art.source),
        source_url=str(art.url),
        badges=badges,
        chart_url=chart_url,
        chart_image=None,
        deeplinks=deeplinks,
        market=art.market,
    )
```

### 4.7 `router/routes.py` 改动（多 market 路由）

```python
def route(
    self, scored: ScoredNews, msg: CommonMessage, *,
    markets: list[str] | None = None,    # 新参数；None 时回退到 msg.market
) -> list[DispatchPlan]:
    """rules 命中可能涉及多 market（'美联储加息影响 A 股'）→ 推多份。"""
    target_markets = markets or [msg.market.value]
    plans = []
    for mkt in target_markets:
        channels = self._by_market.get(mkt, [])
        if not channels:
            continue
        plans.append(DispatchPlan(
            message=msg, channels=channels, immediate=scored.is_critical,
        ))
    return plans
```

---

## 5. 推送内容示例

### 5.1 Rules-only 模式（默认）

**Telegram MarkdownV2**:
```
🟢 NVDA 异动 ⚡

📌 NVIDIA reports record Q1 revenue
来源: finnhub · 2026-04-26 13:30 EST

NVIDIA reported quarterly revenue of $26 billion, up 262% year-over-year, 
driven by data center demand for AI chips. The company also announced...
（前 200 字截取）

📊 #NVDA #semiconductor #ai `rules`

[原文]  [Yahoo NVDA]
```

**飞书 Card**:
```
🟢 异动: NVDA
NVIDIA reports record Q1 revenue
来源: finnhub | 2026-04-26 13:30

[摘要]
NVIDIA reported quarterly... (200 字截取)

🏷 #NVDA #semiconductor #ai
⚙️ rules

[📰 原文]  [📈 Yahoo]
```

**关键差异 vs LLM 模式**：
- 摘要是原文截取（不是 LLM 生成）
- sentiment color 默认中性
- 多一个 `rules` badge 标记数据来源

### 5.2 Rules + LLM 模式

跟当前 LLM 模式视觉一致，区别只在跳过 Tier-0：
- 有 LLM 生成的摘要 ✅
- 有 sentiment color / magnitude ✅
- 走 Tier-1（普通）或 Tier-2（命中 ticker / 一手源）

### 5.3 命中标签规则

| 命中类型 | 推送显示 |
|---|---|
| 直接 ticker | `#NVDA` |
| ticker + sector 联合命中 | `#NVDA #semiconductor` |
| ticker + macro 联合命中 | `#NVDA 📊 FOMC` |
| 仅 sector_keywords 命中 | `#sector_us:semiconductor` |
| 仅 macro_keywords 命中 | `📊 macro_us:CPI` |
| 仅 keyword_list 命中 | `🔖 generic_us:Powell` |
| Rules-only 模式 | 额外 `rules` badge |

---

## 6. 行为约束 + Edge Cases

### 6.1 同一新闻多 market 命中

新闻"美联储加息冲击 A 股"——同时命中 us（FOMC, 美联储）和 cn（A 股相关板块）。

**行为**（按用户决策 OR）：
- 推 us 和 cn 各一份消息
- 各自走自己 market 的 channels
- dedup 不会去重（不同 channel 是不同 push_log 行）

### 6.2 灰区行为（rules-only 模式）

`gray_zone_action` 决定：

| 值 | 行为 |
|---|---|
| `skip` | 灰区新闻完全丢弃（不进 digest 也不推） |
| `digest`（默认） | 进 digest_buffer，等早晚定时推 |
| `push` | 灰区当 critical 直接立即推 |

### 6.3 Burst suppression

继承当前行为：同 ticker 5 min 内 ≥ 3 条 → 折叠/抑制。Rules-only 模式仍然适用。

### 6.4 Hot reload

`config/loader.py` 的 watchdog 检测到 `watchlist.yml` 变更 → ConfigLoader 重新加载 → 重新构建 `RulesEngine`（自动机重建 < 10 ms）→ 新 patterns 立即生效，无需重启。

### 6.5 LLM cost ceiling

跟当前一样：每个 LLM 调用 `cost.record()`；超 ceiling → `CostCeilingExceeded` 抛出 → 仅当 `llm.enable=True` 时可能触发。Rules-only 模式不调 LLM，不受影响。

---

## 7. 迁移路径

### 7.1 从 v0.1.7 watchlist.yml 迁移

旧格式（v0.1.7）：
```yaml
us:
  - {ticker: NVDA, alerts: [price_5pct, earnings, downgrade, sec_filing]}
cn:
  - {ticker: "600519", alerts: [price_5pct, announcement]}
macro: [FOMC, CPI, NFP, 央行, MLF, LPR]
sectors: [semiconductor, ai, ev, 新能源, 半导体, 白酒]
```

新格式（v0.3.0）：参见 §2.1。

### 7.2 一次性迁移脚本

`scripts/migrate_watchlist_v0_3_0.py`：

```python
"""Auto-migrate watchlist.yml from v0.1.7 flat format to v0.3.0 rules + llm format.

逻辑:
- 顶层 us/cn → 移到 rules.us/cn 下，每只股加 name/aliases/sectors/macro_links 占位
- 顶层 macro → 拆到 rules.macro_keywords.us 和 .cn (启发式：中文进 cn，英文进 us)
- 顶层 sectors → 拆到 rules.sector_keywords.us 和 .cn (同上)
- 添加 rules.enable=true, llm.enable=false（默认）
- alerts 字段保留
- 备份原文件到 watchlist.yml.v0_1_7.bak
"""
```

用户运行：
```bash
uv run python scripts/migrate_watchlist_v0_3_0.py
# 然后手动补 name/aliases/sectors/macro_links（这些字段是迁移脚本无法自动填的）
```

### 7.3 兼容性

- **新 schema 不向前兼容**：v0.3.0 启动时如果 watchlist.yml 是旧格式 → schema 校验报错（`rules` / `llm` 段缺失）
- **LLMPipeline 老路径保留**：rules.enable=False 时跟当前完全一致
- **classifier 老调用兼容**：`score_news(enriched, source=)` 不传 verdict 也工作（向后兼容）

---

## 8. 测试策略

### 8.1 单元测试

| 测试文件 | 覆盖 |
|---|---|
| `tests/unit/rules/test_matcher.py` | AhoCorasickMatcher：基本命中、word boundary、中英混合、case insensitive、空 patterns |
| `tests/unit/rules/test_engine.py` | RulesEngine.match()：返回 verdict 正确、反向索引正确、score_boost 公式、空配置 |
| `tests/unit/rules/test_compile.py` | `_compile()`：从 RulesSection 生成 patterns 正确、所有 PatternKind 都覆盖 |
| `tests/unit/config/test_watchlist_schema.py` | 新 WatchlistFile 校验：3 种合法 enable 组合、非法引用拒绝、ticker 唯一 |
| `tests/unit/scheduler/test_process_pending_rules.py` | process_pending 在 4 种 enable 组合下行为正确 |
| `tests/unit/classifier/test_importance_with_verdict.py` | score_news 接受 verdict、score_boost 正确加分、灰区 action 三种 |
| `tests/unit/pushers/test_message_builder_rules.py` | build_from_rules 输出 CommonMessage 字段正确 |
| `tests/unit/router/test_routes_multi_market.py` | route 接受 markets 参数，多 market 时返回多个 plan |

### 8.2 集成测试

- `tests/integration/test_rules_pipeline_e2e.py` — 假新闻命中 NVDA → 完整走通到 push_log

### 8.3 Eval

`tests/eval/test_rules_recall_precision.py`：用 50 条 gold 新闻测 rules 召回率（预期 ≥ 85%）+ 精度（预期 ≥ 90%）。

### 8.4 手动验证

部署后第一周观察：
- `news_processed.model_used = "rules-only"` 占多少
- `raw_news.status = "skipped_rules"` 占多少（高 = rules 太严，应加关键词）
- `push_log` 实际推送量是否符合预期

---

## 9. 显式不做（YAGNI）

- **TF-IDF / embedding matcher**：架构预留 Protocol，本期只实现 AhoCorasickMatcher
- **关系图遍历（NVDA 关联 TSMC）**：现有 `relations` 表可在未来扩 RulesEngine 用，本期不做
- **per-ticker enable 开关**：每只股单独 enable，本期 watchlist 整体 enable 即可
- **OR/AND 复合规则**：本期纯关键词命中 = relevant，无复杂布尔
- **自动学习别名**（从历史 LLM 抽取的 entities 反推）：本期手工维护

---

## 10. 实施风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Aho-Corasick 中文边界处理不当（"AI" 匹配 "main"） | 中 | rules 推噪音 | 用户写关键词时注意；boundary 校验 + 上线后看 metrics 调 |
| 用户配置漏写 alias，rules 漏判 | 高 | 漏新闻 | 提供 LLM fallback 模式（`rules.enable=true + llm.enable=true`）兜底 |
| 启动校验过严，用户 yaml 写错字拒启动 | 中 | 上线失败 | 错误信息清楚指出哪个 ticker / sector 引用问题，便于改 |
| 迁移脚本 macro/sectors 拆分错（中文判进 cn，英文判进 us 太粗） | 中 | 用户得手动修 | 迁移脚本输出 warning + 显式列出每个移动决策，用户审 |
| Hot reload 期间新旧 patterns 不一致 | 低 | 几秒钟 race | acceptable；ConfigLoader 已有 atomic snapshot |

---

## 11. 后续扩展

### 11.1 v0.3.x 候选

- TfidfMatcher：当 keyword 命中量大时，按 TF-IDF 排序结果（解决"NVDA 在新闻里出现 1 次 vs 30 次"的相关度差别）
- `enabled_per_ticker`：每只股单独开关
- 别名自动建议：从 v0.1.x 的 LLM 抽取 entities 表中找出 ticker 的高频实体，提示用户加入 aliases

### 11.2 v0.4.0+ 候选

- EmbeddingMatcher：sentence-transformers 计算新闻 vs 用户描述（"AI 半导体相关"）的余弦相似度
- CompositeMatcher：rules + embedding 加权合并
- 关系图触发：news 抽出的 relations 自动加进 rules 候选（半自动维护）

---

## 12. 决策记录（ADR）

| ADR | 决策 | 理由 |
|---|---|---|
| 1 | 选 Aho-Corasick 而非 regex/flashtext | C 扩展最快、API 干净、生态成熟 |
| 2 | 启用 word boundary 仅对英文 | 中文 substring 匹配是预期行为（"茅台" ⊂ "贵州茅台"） |
| 3 | rules 是 gate（不命中即丢） | 用户明确选 D 选项；最省钱、最快、最可控 |
| 4 | 启动校验严格（拒非法引用） | "好的拼写错误"应当在配置时被发现，不是部署后才发现漏推 |
| 5 | 多 market 命中各推一份 | 同事件不同 market 视角，dedup 自然处理 |
| 6 | gray_zone_action 三选 | 用户控制噪音 vs 召回的滑块 |
| 7 | model_used="rules-only" 标记 | push_log + 归档可一眼区分数据来源 |
| 8 | matcher 协议化预留扩展 | 未来加 TF-IDF/embedding 不用动下游代码 |

---

## 附录 A — 配置 vs 行为对照速查

| 你想 | 配置 |
|---|---|
| 完全规则模式（默认）| `rules.enable=true, llm.enable=false` |
| 规则命中再用 LLM 拿摘要 | `rules.enable=true, llm.enable=true` |
| 仍用 LLM 全流程（保留兼容） | `rules.enable=false, llm.enable=true` |
| 加新股 NVDA | `rules.us` 加一项 + 写 name/aliases/sectors/macro_links |
| 加新板块"游戏" | `rules.sector_keywords.us` 加 'gaming' + 哪些股 sectors 引用它 |
| 灰区不要刷屏 | `rules.gray_zone_action=skip` |
| 灰区都进早晚 digest | `rules.gray_zone_action=digest`（默认） |

# src/news_pipeline/config/schema.py
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


# --- app.yml ---


class PipelineCfg(_Base):
    mode: Literal["v2"] = "v2"


class DigestSchedule(_Base):
    at: str
    tz: str


class DigestTimesCfg(_Base):
    cn: list[DigestSchedule] = Field(
        default_factory=lambda: [
            DigestSchedule(at="08:27", tz="Asia/Shanghai"),
            DigestSchedule(at="20:57", tz="Asia/Shanghai"),
        ]
    )
    us: list[DigestSchedule] = Field(
        default_factory=lambda: [
            DigestSchedule(at="08:27", tz="America/New_York"),
            DigestSchedule(at="16:27", tz="America/New_York"),
        ]
    )


class SchedulerCfg(_Base):
    digest: DigestTimesCfg = Field(default_factory=DigestTimesCfg)


class LLMTaskCfg(_Base):
    model: str = "qwen-plus"
    max_tokens: int = Field(default=400, gt=0)
    prompt_version: str = "assess_v1"


class ModelPricing(_Base):
    input: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    output: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class LLMCfg(_Base):
    enabled: bool = False
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assess: LLMTaskCfg = Field(default_factory=LLMTaskCfg)
    digest: LLMTaskCfg = Field(
        default_factory=lambda: LLMTaskCfg(max_tokens=1500, prompt_version="digest_v1")
    )
    daily_cost_ceiling_cny: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    pricing: dict[str, ModelPricing] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enabled_models_have_prices(self) -> "LLMCfg":
        if self.enabled:
            for model in {self.assess.model, self.digest.model}:
                price = self.pricing.get(model)
                if price is None or price.input <= 0 or price.output <= 0:
                    raise ValueError(
                        f"llm.pricing: enabled model {model!r} needs positive input/output prices"
                    )
        return self


class QuietHoursCfg(_Base):
    enabled: bool = False
    start: str = "00:30"
    end: str = "07:30"
    tz: str = "Asia/Shanghai"
    allow_reasons: list[str] = Field(default_factory=lambda: ["big_move", "tier:high"])


class PushCfg(_Base):
    max_age_min: int = Field(default=90, gt=0)
    quiet_hours: QuietHoursCfg = Field(default_factory=QuietHoursCfg)
    color_scheme: Literal["us", "cn"] = "us"
    push_min_materiality: int = Field(default=4, ge=1, le=5)
    push_min_materiality_macro: int = Field(default=5, ge=1, le=5)
    digest_min_materiality: int = Field(default=3, ge=1, le=5)
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    quiet_min_materiality: int = Field(default=5, ge=1, le=5)
    first_party_floor: dict[str, int] = Field(
        default_factory=lambda: {
            "tier:high": 4,
            "tier:normal": 3,
        }
    )
    same_ticker_burst_window_min: int = Field(default=5, gt=0)
    same_ticker_burst_threshold: int = Field(default=3, gt=0)


class DigestCfg(_Base):
    max_items: int = Field(default=20, gt=0)
    max_age_hours: int = Field(default=24, gt=0)


class OpsCfg(_Base):
    report_at: str = "08:20"
    report_channel: str = "feishu_cn"


class AppConfig(_Base):
    pipeline: PipelineCfg = Field(default_factory=PipelineCfg)
    scheduler: SchedulerCfg = Field(default_factory=SchedulerCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    push: PushCfg = Field(default_factory=PushCfg)
    digest: DigestCfg = Field(default_factory=DigestCfg)
    ops: OpsCfg = Field(default_factory=OpsCfg)


# --- watchlist.yml ---
class TickerEntry(_Base):
    """One stock under rules.us or rules.cn."""

    ticker: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)

    @field_validator("aliases", "people", "exclude", mode="after")
    @classmethod
    def lowercase_aliases(cls, values: list[str]) -> list[str]:
        return [value.lower() for value in values]


class RulesSection(_Base):
    short_alias_allow: list[str] = Field(default_factory=list)
    us: list[TickerEntry] = Field(default_factory=list)
    cn: list[TickerEntry] = Field(default_factory=list)


class WatchlistFile(_Base):
    rules: RulesSection = Field(default_factory=RulesSection)

    @model_validator(mode="after")
    def ticker_unique(self) -> "WatchlistFile":
        for market in ("us", "cn"):
            tickers = [t.ticker for t in getattr(self.rules, market)]
            if len(tickers) != len(set(tickers)):
                dups = sorted({t for t in tickers if tickers.count(t) > 1})
                raise ValueError(f"rules.{market}: duplicate tickers {dups}")
        return self

    @model_validator(mode="after")
    def aliases_valid(self) -> "WatchlistFile":
        owners: dict[str, str] = {}
        allow = {alias.lower() for alias in self.rules.short_alias_allow}
        for entry in [*self.rules.us, *self.rules.cn]:
            strong = {entry.ticker.lower(), entry.name.lower(), *entry.aliases}
            for alias in strong:
                if re.fullmatch(r"[\u4e00-\u9fff]{1,2}", alias) and alias not in allow:
                    raise ValueError(f"alias {alias!r}: add to rules.short_alias_allow")
            for alias in strong | set(entry.people):
                owner = owners.setdefault(alias, entry.ticker)
                if owner != entry.ticker:
                    raise ValueError(
                        f"alias {alias!r} belongs to two tickers: {owner}, {entry.ticker}"
                    )
            for excluded in entry.exclude:
                if not any(alias in excluded for alias in strong):
                    raise ValueError(f"{entry.ticker}: exclude {excluded!r} must contain own alias")
        return self

    def effective_us(self) -> list[str]:
        """US ticker scope is defined by the rules watchlist."""
        return [entry.ticker for entry in self.rules.us]

    def effective_cn(self) -> list[str]:
        """CN ticker scope is defined by the rules watchlist."""
        return [entry.ticker for entry in self.rules.cn]


# --- scoring.yml / first_party.yml ---
class ScoringKeywords(_Base):
    macro: list[str] = Field(
        default_factory=lambda: [
            "美联储",
            "鲍威尔",
            "FOMC",
            "降息",
            "加息",
            "非农",
            "CPI",
            "PCE",
            "PPI",
            "PMI",
            "GDP",
            "降准",
            "LPR",
            "MLF",
            "逆回购",
            "社融",
            "国债收益率",
            "中国央行",
            "人民银行",
            "re:(?<![一-龥])央行",
        ]
    )
    policy: list[str] = Field(
        default_factory=lambda: [
            "证监会",
            "国常会",
            "财政部",
            "发改委",
            "工信部",
            "商务部",
            "关税",
            "出口管制",
            "制裁",
            "re:(?<![一-龥])国务院",
        ]
    )
    sector: list[str] = Field(
        default_factory=lambda: [
            "半导体",
            "芯片",
            "存储",
            "光模块",
            "CPO",
            "光通信",
            "晶圆",
            "封测",
            "人工智能",
            "算力",
            "数据中心",
            "大模型",
            "机器人",
            "液冷",
            "创新药",
            "CRO",
            "锂电池",
            "储能",
            "新能源车",
            "电动车",
            "自动驾驶",
        ]
    )
    en: list[str] = Field(
        default_factory=lambda: [
            "Fed",
            "Powell",
            "FOMC",
            "tariff",
            "rate cut",
            "rate hike",
            "export control",
            "sanction",
            "semiconductor",
            "chip",
        ]
    )

    @field_validator("macro", "policy", "sector", "en", mode="after")
    @classmethod
    def lowercase_keywords(cls, values: list[str]) -> list[str]:
        out = [value.lower() for value in values]
        for word in out:
            if word.startswith("re:"):
                try:
                    re.compile(word[3:])
                except re.error as error:
                    raise ValueError(
                        f"invalid keyword regular expression {word!r}: {error}"
                    ) from error
        return out


class ScoringConfig(_Base):
    big_move_pct: float = Field(default=5.0, gt=0)
    lead_window_chars: int = Field(default=12, gt=0)
    strong_events: list[str] = Field(
        default_factory=lambda: [
            "回购",
            "增持",
            "减持",
            "目标价",
            "评级",
            "首次覆盖",
            "财报",
            "业绩",
            "营收",
            "净利",
            "指引",
            "预增",
            "预减",
            "预亏",
            "扭亏",
            "快报",
            "预告",
            "收购",
            "并购",
            "重组",
            "分拆",
            "要约",
            "私有化",
            "定增",
            "配股",
            "可转债",
            "中标",
            "召回",
            "调查",
            "处罚",
            "罚款",
            "诉讼",
            "起诉",
            "禁令",
            "制裁",
            "出口管制",
            "停牌",
            "复牌",
            "涨停",
            "跌停",
            "辞职",
            "离职",
            "裁员",
            "问询",
            "立案",
            "解禁",
            "质押",
            "分红",
            "派息",
            "拆股",
            "历史新高",
            "上调",
            "下调",
            "涨价",
            "降价",
            "提价",
        ]
    )
    lead_events: list[str] = Field(
        default_factory=lambda: [
            "订单",
            "大单",
            "合同",
            "协议",
            "入股",
            "建厂",
            "扩产",
            "投产",
            "量产",
            "交付",
            "获批",
            "批准",
            "许可",
            "任命",
            "接任",
        ]
    )
    amount_events: list[str] = Field(default_factory=lambda: ["投资", "融资", "发债", "发行"])
    roundup_words: list[str] = Field(
        default_factory=lambda: [
            "要闻",
            "一览",
            "速递",
            "早知道",
            "早报",
            "晚报",
            "收评",
            "午评",
            "开盘",
            "收盘",
            "盘中",
            "异动",
            "概念",
            "板块",
            "普涨",
            "普跌",
            "跟涨",
            "跟跌",
            "领涨",
            "领跌",
            "etf",
            "净申购",
            "资金流",
            "龙虎榜",
            "多头持仓",
            "空头持仓",
            "持仓比例",
            "持股比例",
            "成交额",
            "涨幅榜",
            "跌幅榜",
            "周报",
            "日报",
            "提醒",
            "日历",
            "盘前",
            "盘后",
            "夜盘",
            "期指",
            "指数",
            "三大股指",
            "热门股",
            "科技股",
            "中概股",
            "七姐妹",
            "金股",
            "融资买入",
            "融资融券",
            "融资余额",
            "居首",
            "主力资金",
            "北向资金",
            "南向资金",
            "获买入",
            "暗盘",
        ]
    )
    keywords: ScoringKeywords = Field(default_factory=ScoringKeywords)

    @field_validator("strong_events", "lead_events", "amount_events", "roundup_words", mode="after")
    @classmethod
    def lowercase_words(cls, values: list[str]) -> list[str]:
        return [value.lower() for value in values]


class JuchaoTiers(_Base):
    low: list[str] = Field(
        default_factory=lambda: [
            "法律意见书|核查意见|独立财务顾问|自查表|合规性说明",
            "管理办法|实施细则|工作细则|议事规则|工作制度|章程",
            "会议资料|H股公告|港股公告|翌日披露报表|月报表|证券变动",
        ]
    )
    high: list[str] = Field(
        default_factory=lambda: [
            "业绩预告|业绩快报|季度报告|半年度报告|年度报告",
            "回购|增持|减持|权益分派|利润分配|分红",
            "重大合同|中标|收购|出售|重组|对外投资|签订.*协议|受让|转让",
            "诉讼|仲裁|处罚|立案|问询函|关注函|监管函",
            "停牌|复牌|异常波动|澄清|更正|终止",
            "股权激励.*草案|限制性股票.*草案|员工持股计划.*草案",
            "质押|解除质押|实际控制人|控股股东.*变更",
            "辞职|聘任|选举.*董事长",
        ]
    )
    merge_window_min: int = Field(default=10, gt=0)
    merge_max_items: int = Field(default=5, gt=0)


class SECHighTier(_Base):
    forms: list[str] = Field(
        default_factory=lambda: [
            "10-Q",
            "10-K",
            "20-F",
            "SC 13D",
            "SCHEDULE 13D",
            "S-1",
            "424B1",
            "424B2",
            "424B3",
            "424B4",
            "424B5",
        ]
    )
    items_8k: list[str] = Field(
        default_factory=lambda: [
            "1.01",
            "1.02",
            "2.01",
            "2.02",
            "2.05",
            "2.06",
            "3.01",
            "4.01",
            "4.02",
            "5.02",
        ]
    )
    doc_name_6k: list[str] = Field(default_factory=lambda: ["revenue"])


class SECLowTier(_Base):
    forms: list[str] = Field(default_factory=lambda: ["3", "4", "5", "144", "13F-HR"])


class SECTiers(_Base):
    high: SECHighTier = Field(default_factory=SECHighTier)
    low: SECLowTier = Field(default_factory=SECLowTier)
    item_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "1.01": "签订重大协议",
            "1.02": "终止重大协议",
            "2.01": "完成资产收购或处置",
            "2.02": "经营业绩与财务状况",
            "2.03": "新增重大债务",
            "2.05": "重组或裁撤相关成本",
            "2.06": "重大减值",
            "3.01": "退市或不符合上市标准的通知",
            "4.01": "更换审计机构",
            "4.02": "此前财报不可依赖",
            "5.02": "董事或高管变动",
            "5.07": "股东大会表决结果",
            "7.01": "Reg FD 披露",
            "8.01": "其他事项",
            "9.01": "财务报表及附件",
        }
    )


class FirstPartyConfig(_Base):
    juchao: JuchaoTiers = Field(default_factory=JuchaoTiers)
    sec: SECTiers = Field(default_factory=SECTiers)


# --- channels.yml ---
class ChannelDef(_Base):
    type: Literal["feishu", "wecom"]
    enabled: bool = True
    market: Literal["us", "cn"]
    rate_limit: str = "30/min"
    # platform-specific opaque fields go in 'options'; secrets resolved separately
    options: dict[str, str] = Field(default_factory=dict)


class ChannelsFile(_Base):
    channels: dict[str, ChannelDef]


# --- sources.yml ---
class SourceDef(_Base):
    enabled: bool = True
    interval_sec: int | None = None
    lookback_min: int = Field(default=360, gt=0)
    fetch_timeout_sec: int = Field(default=45, gt=0)
    max_silence_min: int | None = Field(default=None, gt=0)
    max_silence_off_min: int | None = Field(default=None, gt=0)
    options: dict[str, str] = Field(default_factory=dict)


class SourcesFile(_Base):
    sources: dict[str, SourceDef]


# --- secrets.yml ---
class SecretsFile(_Base):
    """Secrets loaded from secrets.yml.

    ``push`` accepts two layouts during the migration window:

    *New (nested)*::

        push:
          news_pipeline:
            feishu_hook_cn: xxx
          quote_watcher:
            feishu_hook_cn: yyy

    *Legacy (flat)*::

        push:
          feishu_hook_cn: xxx
          feishu_hook_cn_alert: yyy

    Both are stored as ``dict[str, Any]``; the factory's ``_lookup_push``
    handles dotted-path resolution for both shapes.
    """

    llm: dict[str, str] = Field(default_factory=dict)
    push: dict[str, str | dict[str, str]] = Field(default_factory=dict)
    storage: dict[str, str] = Field(default_factory=dict)
    oss: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)
    alert: dict[str, str] = Field(default_factory=dict)


# --- quote_watchlist.yml ---
class QuoteTickerEntry(_Base):
    ticker: str
    name: str
    market: Literal["SH", "SZ", "BJ"]


class MarketScansCfg(_Base):
    top_gainers_n: int = 50
    top_losers_n: int = 50
    top_volume_ratio_n: int = 50
    push_top_n: int = 5
    only_when_score_above: float = 8.0


class QuoteWatchlistFile(_Base):
    cn: list[QuoteTickerEntry] = Field(default_factory=list)
    us: list[QuoteTickerEntry] = Field(default_factory=list)
    market_scans: dict[str, MarketScansCfg] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _tickers_unique(self) -> "QuoteWatchlistFile":
        for market_attr in ("cn", "us"):
            seen: set[str] = set()
            for e in getattr(self, market_attr):
                if e.ticker in seen:
                    raise ValueError(f"duplicate ticker {e.ticker} in {market_attr}")
                seen.add(e.ticker)
        return self


# --- holdings.yml ---
class HoldingEntry(_Base):
    ticker: str
    name: str | None = None
    qty: int = Field(gt=0)
    cost_per_share: float = Field(gt=0)


class PortfolioCfg(_Base):
    total_capital: float | None = None
    base_currency: str = "CNY"


class HoldingsFile(_Base):
    holdings: list[HoldingEntry] = Field(default_factory=list)
    portfolio: PortfolioCfg = Field(default_factory=PortfolioCfg)

    @model_validator(mode="after")
    def _unique_holdings(self) -> "HoldingsFile":
        seen: set[str] = set()
        for h in self.holdings:
            if h.ticker in seen:
                raise ValueError(f"duplicate holding: {h.ticker}")
            seen.add(h.ticker)
        return self

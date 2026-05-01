# src/news_pipeline/config/schema.py
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- app.yml ---
class RuntimeCfg(_Base):
    daily_cost_ceiling_cny: float = 5.0
    hot_reload: bool = True
    timezone_display: dict[str, str] = Field(
        default_factory=lambda: {"us": "America/New_York", "cn": "Asia/Shanghai"}
    )


class ScrapeIntervalsCfg(_Base):
    market_hours_interval_sec: int
    off_hours_interval_sec: int
    caixin_interval_sec: int


class LLMIntervalCfg(_Base):
    process_interval_sec: int


class DigestTimesCfg(_Base):
    morning_cn: str
    evening_cn: str
    morning_us: str
    evening_us: str


class SchedulerCfg(_Base):
    scrape: ScrapeIntervalsCfg
    llm: LLMIntervalCfg
    digest: DigestTimesCfg


class LLMCfg(_Base):
    tier0_model: str
    tier1_model: str
    tier2_model: str
    tier3_model: str
    prompt_versions: dict[str, str]
    enable_prompt_cache: bool
    enable_batch: bool


class ClassifierRulesCfg(_Base):
    price_move_critical_pct: float
    sources_always_critical: list[str]
    sentiment_high_magnitude_critical: bool


class ClassifierCfg(_Base):
    rules: ClassifierRulesCfg | None = None
    llm_fallback_when_score: Annotated[list[float], Field(min_length=2, max_length=2)]


class DedupCfg(_Base):
    url_strict: bool = True
    title_simhash_distance: int = 4


class ChartsCfg(_Base):
    auto_on_critical: bool
    auto_on_earnings: bool
    cache_ttl_days: int


class PushCfg(_Base):
    per_channel_rate: str
    same_ticker_burst_window_min: int
    same_ticker_burst_threshold: int
    digest_max_items_per_section: int


class DeadLetterCfg(_Base):
    auto_retry_kinds: list[str]
    notify_only_kinds: list[str]
    weekly_summary_day: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]


class RetentionCfg(_Base):
    raw_news_hot_days: int
    news_processed_hot_days: int
    push_log_days: int


class AppConfig(_Base):
    runtime: RuntimeCfg = Field(default_factory=RuntimeCfg)
    scheduler: SchedulerCfg
    llm: LLMCfg
    classifier: ClassifierCfg
    dedup: DedupCfg = Field(default_factory=DedupCfg)
    charts: ChartsCfg
    push: PushCfg
    dead_letter: DeadLetterCfg
    retention: RetentionCfg


# --- watchlist.yml ---
class TickerEntry(_Base):
    """One stock under rules.us or rules.cn."""

    ticker: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    macro_links: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)  # legacy, LLM-only


class MarketKeywords(_Base):
    """A keyword list split by market."""

    us: list[str] = Field(default_factory=list)
    cn: list[str] = Field(default_factory=list)


class RulesSection(_Base):
    enable: bool = True
    gray_zone_action: Literal["skip", "digest", "push"] = "digest"
    matcher: str = "aho_corasick"
    matcher_options: dict[str, Any] = Field(default_factory=dict)
    us: list[TickerEntry] = Field(default_factory=list)
    cn: list[TickerEntry] = Field(default_factory=list)
    keyword_list: MarketKeywords = Field(default_factory=MarketKeywords)
    macro_keywords: MarketKeywords = Field(default_factory=MarketKeywords)
    sector_keywords: MarketKeywords = Field(default_factory=MarketKeywords)


class LLMSection(_Base):
    enable: bool = False
    us: list[str] = Field(default_factory=list)
    cn: list[str] = Field(default_factory=list)
    macro: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)


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
                dups = sorted({t for t in tickers if tickers.count(t) > 1})
                raise ValueError(f"rules.{market}: duplicate tickers {dups}")
        return self

    def effective_us(self) -> list[str]:
        """Tickers in scope for US. When rules.enable=True the rules section is
        the single source of truth (llm.us is ignored, even if llm.enable=True);
        otherwise fall back to llm.us."""
        if self.rules.enable:
            return [t.ticker for t in self.rules.us]
        return list(self.llm.us)

    def effective_cn(self) -> list[str]:
        """Tickers in scope for CN. Same precedence rule as effective_us."""
        if self.rules.enable:
            return [t.ticker for t in self.rules.cn]
        return list(self.llm.cn)

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
                        f"sectors {sorted(bad_sectors)} not in "
                        f"sector_keywords.{market}"
                    )
                if bad_macros:
                    raise ValueError(
                        f"{market} ticker {entry.ticker}: "
                        f"macro_links {sorted(bad_macros)} not in "
                        f"macro_keywords.{market}"
                    )
        return self


# --- channels.yml ---
class ChannelDef(_Base):
    type: Literal["telegram", "feishu", "wecom"]
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
    options: dict[str, str] = Field(default_factory=dict)


class SourcesFile(_Base):
    sources: dict[str, SourceDef]


# --- secrets.yml ---
class SecretsFile(_Base):
    llm: dict[str, str] = Field(default_factory=dict)
    push: dict[str, str] = Field(default_factory=dict)
    storage: dict[str, str] = Field(default_factory=dict)
    oss: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)
    alert: dict[str, str] = Field(default_factory=dict)

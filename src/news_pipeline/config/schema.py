# src/news_pipeline/config/schema.py
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


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
class WatchlistEntry(_Base):
    ticker: str
    alerts: list[str] = Field(default_factory=list)


class WatchlistFile(_Base):
    us: list[WatchlistEntry] = Field(default_factory=list)
    cn: list[WatchlistEntry] = Field(default_factory=list)
    macro: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)


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

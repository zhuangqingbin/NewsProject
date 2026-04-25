# src/news_pipeline/common/contracts.py
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from news_pipeline.common.enums import (
    EntityType,
    EventType,
    Magnitude,
    Market,
    Predicate,
    Sentiment,
)


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class RawArticle(_Base):
    source: str
    market: Market
    fetched_at: datetime
    published_at: datetime
    url: HttpUrl
    url_hash: str
    title: str
    title_simhash: int = 0
    body: str | None = None
    raw_meta: dict[str, object] = Field(default_factory=dict)


class Entity(_Base):
    type: EntityType
    name: str
    ticker: str | None = None
    market: Market | None = None
    aliases: list[str] = Field(default_factory=list)


class Relation(_Base):
    subject: Entity
    predicate: Predicate
    object: Entity
    confidence: Annotated[float, Field(ge=0, le=1)]


class EnrichedNews(_Base):
    raw_id: int
    summary: str
    related_tickers: list[str]
    sectors: list[str]
    event_type: EventType
    sentiment: Sentiment
    magnitude: Magnitude
    confidence: Annotated[float, Field(ge=0, le=1)]
    key_quotes: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    model_used: str
    extracted_at: datetime


class ScoredNews(_Base):
    enriched: EnrichedNews
    score: Annotated[float, Field(ge=0, le=100)]
    is_critical: bool
    rule_hits: list[str] = Field(default_factory=list)
    llm_reason: str | None = None


class Badge(_Base):
    text: str
    color: str = "gray"  # gray|green|red|yellow|blue


class Deeplink(_Base):
    label: str
    url: HttpUrl


class CommonMessage(_Base):
    title: str
    summary: str
    source_label: str
    source_url: HttpUrl
    badges: list[Badge]
    chart_url: HttpUrl | None  # deprecated: prefer chart_image
    # PNG bytes for inline embedding (TG sendPhoto / Feishu img_key)
    chart_image: bytes | None = None
    deeplinks: list[Deeplink]
    market: Market


class DispatchPlan(_Base):
    message: CommonMessage
    channels: list[str]
    immediate: bool

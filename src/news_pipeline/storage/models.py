from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

SQLModelBase = SQLModel


class RawNews(SQLModel, table=True):
    __tablename__ = "raw_news"
    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_raw_url_hash"),
        Index("idx_raw_status_pub", "status", "published_at"),
        Index("idx_raw_market_pub", "market", "published_at"),
        Index("idx_raw_simhash", "title_simhash"),
    )
    id: int | None = Field(default=None, primary_key=True)
    source: str
    market: str
    url: str
    url_hash: str
    title: str
    title_simhash: int = 0
    body: str | None = None
    raw_meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fetched_at: datetime
    published_at: datetime
    status: str = "pending"
    error: str | None = None


class NewsProcessed(SQLModel, table=True):
    __tablename__ = "news_processed"
    __table_args__ = (
        UniqueConstraint("raw_id", name="uq_proc_raw"),
        Index("idx_proc_critical_extracted", "is_critical", "extracted_at"),
        Index("idx_proc_push_status", "push_status", "extracted_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    raw_id: int = Field(foreign_key="raw_news.id")
    summary: str
    event_type: str
    sentiment: str
    magnitude: str
    confidence: float
    key_quotes: list[str] | None = Field(default=None, sa_column=Column(JSON))
    score: float
    is_critical: bool
    rule_hits: list[str] | None = Field(default=None, sa_column=Column(JSON))
    llm_reason: str | None = None
    model_used: str
    extracted_at: datetime
    push_status: str = "pending"


class Entity(SQLModel, table=True):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("type", "name", name="uq_ent_type_name"),
        Index("idx_ent_ticker", "ticker"),
    )
    id: int | None = Field(default=None, primary_key=True)
    type: str
    name: str
    ticker: str | None = None
    market: str | None = None
    aliases: list[str] | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict[str, Any] | None = Field(
        default=None, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NewsEntity(SQLModel, table=True):
    __tablename__ = "news_entities"
    news_id: int = Field(foreign_key="news_processed.id", primary_key=True)
    entity_id: int = Field(foreign_key="entities.id", primary_key=True)
    role: str = Field(primary_key=True)
    salience: float


class Relation(SQLModel, table=True):
    __tablename__ = "relations"
    __table_args__ = (
        Index("idx_rel_subject", "subject_id", "predicate"),
        Index("idx_rel_object", "object_id", "predicate"),
    )
    id: int | None = Field(default=None, primary_key=True)
    subject_id: int = Field(foreign_key="entities.id")
    predicate: str
    object_id: int = Field(foreign_key="entities.id")
    source_news_id: int = Field(foreign_key="news_processed.id")
    confidence: float
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SourceState(SQLModel, table=True):
    __tablename__ = "source_state"
    source: str = Field(primary_key=True)
    last_fetched_at: datetime | None = None
    last_seen_url: str | None = None
    last_error: str | None = None
    error_count: int = 0
    paused_until: datetime | None = None


class PushLog(SQLModel, table=True):
    __tablename__ = "push_log"
    __table_args__ = (
        Index("idx_pushlog_news", "news_id"),
        Index("idx_pushlog_sent", "sent_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(foreign_key="news_processed.id")
    channel: str
    sent_at: datetime
    status: str
    http_status: int | None = None
    response: str | None = None
    retries: int = 0


class DigestBuffer(SQLModel, table=True):
    __tablename__ = "digest_buffer"
    __table_args__ = (
        UniqueConstraint("news_id", name="uq_digest_news"),
        Index("idx_digest_pending", "scheduled_digest", "consumed_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(foreign_key="news_processed.id")
    market: str
    scheduled_digest: str
    added_at: datetime
    consumed_at: datetime | None = None


class DeadLetter(SQLModel, table=True):
    __tablename__ = "dead_letter"
    id: int | None = Field(default=None, primary_key=True)
    kind: str
    payload: str
    error: str
    retries: int
    created_at: datetime
    resolved_at: datetime | None = None


class ChartCache(SQLModel, table=True):
    __tablename__ = "chart_cache"
    __table_args__ = (
        UniqueConstraint("request_hash", name="uq_chart_req_hash"),
    )
    id: int | None = Field(default=None, primary_key=True)
    request_hash: str
    ticker: str
    kind: str
    oss_url: str
    generated_at: datetime
    expires_at: datetime


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    actor: str | None = None
    action: str
    detail: str | None = None
    created_at: datetime


class DailyMetric(SQLModel, table=True):
    __tablename__ = "daily_metrics"
    metric_date: str = Field(primary_key=True)
    metric_name: str = Field(primary_key=True)
    dimensions: str = Field(default="", primary_key=True)
    metric_value: float

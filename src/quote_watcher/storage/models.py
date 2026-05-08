"""SQLAlchemy models for data/quotes.db."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QuoteBar1min(Base):
    __tablename__ = "quote_bars_1min"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("ticker", "bar_start", name="uq_bar1min_ticker_start"),
        Index("idx_bar1min_ticker_ts", "ticker", "bar_start"),
    )


class QuoteBarDaily(Base):
    __tablename__ = "quote_bars_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    prev_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_bardaily_ticker_date"),
    )


class AlertState(Base):
    __tablename__ = "alert_state"
    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    last_triggered_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_count_today: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (Index("idx_alert_state_ticker", "ticker"),)


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    pushed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlmodel import col

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.events.similarity import Features, features, same_event, within_event_window
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.headline import headline
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Delivery, EventArticle, NewsProcessed, PushLog, RawNews
from shared.common.timeutil import ensure_utc, utc_now


class SentEventCache:
    def __init__(
        self, db: Database, *, window_hours: int = 6, rules: RulesEngine | None = None
    ) -> None:
        self._db = db
        self._rules = rules
        self._hours = window_hours
        self._sent: list[tuple[Features, datetime]] = []

    async def rebuild(self) -> None:
        cutoff = (utc_now() - timedelta(hours=self._hours)).replace(tzinfo=None)
        async with self._db.session() as session:
            result = await session.execute(
                select(RawNews, col(PushLog.sent_at))
                .join(NewsProcessed, col(NewsProcessed.raw_id) == col(RawNews.id))
                .join(PushLog, col(PushLog.news_id) == col(NewsProcessed.id))
                .where(col(PushLog.status) == "ok", col(PushLog.sent_at) >= cutoff)
            )
            v2_result = await session.execute(
                select(RawNews, col(Delivery.sent_at))
                .join(EventArticle, col(EventArticle.raw_id) == col(RawNews.id))
                .join(Delivery, col(Delivery.event_id) == col(EventArticle.event_id))
                .where(
                    col(Delivery.kind) == "immediate",
                    col(Delivery.status) == "sent",
                    col(Delivery.sent_at) >= cutoff,
                )
            )
            rows: list[tuple[RawNews, datetime]] = [(raw, sent_at) for raw, sent_at in result.all()]
            rows.extend((raw, sent_at) for raw, sent_at in v2_result.all() if sent_at is not None)
            self._sent = [
                (
                    features(
                        headline(raw.title, raw.body),
                        self._subjects(raw),
                        ensure_utc(raw.published_at),
                    ),
                    ensure_utc(sent_at),
                )
                for raw, sent_at in rows
            ]

    def duplicate(self, feature: Features) -> bool:
        now = utc_now()
        self._sent = [(f, at) for f, at in self._sent if now - at <= timedelta(hours=self._hours)]
        return any(
            within_event_window(feature.at, f.at, f.at) and same_event(feature, f)
            for f, _ in self._sent
        )

    def record(self, feature: Features) -> None:
        self._sent.append((feature, utc_now()))

    def _subjects(self, raw: RawNews) -> list[str]:
        if self._rules is None:
            return []
        article = RawArticle(
            source=raw.source,
            market=Market(raw.market),
            url=raw.url,
            url_hash=raw.url_hash,
            title=raw.title,
            body=raw.body,
            raw_meta=raw.raw_meta or {},
            fetched_at=raw.fetched_at,
            published_at=raw.published_at,
        )
        return self._rules.match(article).subject_tickers

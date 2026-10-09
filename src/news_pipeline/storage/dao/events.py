from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Event, EventArticle, RawNews
from shared.common.timeutil import utc_now


class EventsDAO:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, event_id: int) -> Event | None:
        async with self.db.session() as session:
            return await session.get(Event, event_id)

    async def list_recent(self, hours: int = 12, *, now: datetime | None = None) -> list[Event]:
        reference = now or utc_now()
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        cutoff = (reference.astimezone(UTC) - timedelta(hours=hours)).replace(tzinfo=None)
        async with self.db.session() as session:
            result = await session.execute(
                select(Event).where(Event.last_seen_at >= cutoff).order_by(Event.id)
            )
            return list(result.scalars())

    async def list_pending(self, limit: int = 20) -> list[Event]:
        async with self.db.session() as session:
            result = await session.execute(
                select(Event)
                .where(Event.assess_status == "pending")
                .order_by(Event.id)
                .limit(limit)
            )
            return list(result.scalars())

    async def recent_repeat_ids(self, hours: int = 12) -> set[int]:
        cutoff = (utc_now() - timedelta(hours=hours)).replace(tzinfo=None)
        async with self.db.session() as session:
            result = await session.execute(
                select(Event.id).where(
                    Event.decision_reason == "repeat", Event.last_seen_at >= cutoff
                )
            )
            return set(result.scalars())

    async def list_undecided(self, limit: int = 200) -> list[Event]:
        async with self.db.session() as session:
            result = await session.execute(
                select(Event)
                .where(Event.decision.is_(None), Event.assess_status != "pending")
                .order_by(Event.id)
                .limit(limit)
            )
            return list(result.scalars())

    async def articles(self, event_id: int) -> list[RawNews]:
        async with self.db.session() as session:
            result = await session.execute(
                select(RawNews)
                .join(EventArticle, EventArticle.raw_id == RawNews.id)
                .where(EventArticle.event_id == event_id)
                .order_by(RawNews.published_at, RawNews.id)
            )
            return list(result.scalars())

    async def update(self, event_id: int, **values: Any) -> None:
        async with self.db.session() as session:
            await session.execute(update(Event).where(Event.id == event_id).values(**values))
            await session.commit()

    async def merge_repeat(
        self, event_id: int, target_id: int, *, expected_article_count: int | None = None
    ) -> bool:
        async with self.db.session() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            source = await session.get(Event, event_id)
            if source is None:
                return False
            if expected_article_count is not None and (
                source.article_count != expected_article_count
                or source.assess_status == "pending"
                or source.decision is not None
                or source.novelty != "repeat"
                or source.same_as_event_id != target_id
            ):
                return False
            # The original target may have been reparented while this assessment ran.
            resolved_id = target_id
            visited = {event_id}
            target = None
            while resolved_id not in visited:
                visited.add(resolved_id)
                candidate = await session.get(Event, resolved_id)
                if candidate is None:
                    break
                if candidate.decision != "drop":
                    target = candidate
                    break
                if candidate.decision_reason != "repeat" or candidate.same_as_event_id is None:
                    break
                resolved_id = candidate.same_as_event_id
            if target is None:
                source.assess_status = "pending"
                source.novelty = "new"
                source.same_as_event_id = None
                source.decision = source.decision_reason = source.decided_at = None
                await session.commit()
                return False
            await session.execute(
                update(EventArticle)
                .where(EventArticle.event_id == event_id)
                .values(event_id=resolved_id)
            )
            target.article_count += source.article_count
            target.sources = sorted(set(target.sources) | set(source.sources))
            target.source_count = len(target.sources)
            target.tagged_tickers = sorted(set(target.tagged_tickers) | set(source.tagged_tickers))
            target.first_seen_at = min(target.first_seen_at, source.first_seen_at)
            target.last_seen_at = max(target.last_seen_at, source.last_seen_at)
            target.subject_tickers = sorted(
                set(target.subject_tickers) | set(source.subject_tickers)
            )
            target.markets = sorted(set(target.markets) | set(source.markets))
            target.rank_score = max(target.rank_score, source.rank_score)
            if source.first_party and not target.first_party:
                target.headline = source.headline
                target.norm_headline = source.norm_headline
                target.key_numbers = source.key_numbers
            target.first_party |= source.first_party
            strength = {"drop": 0, "digest_lo": 1, "digest_hi": 2, "push": 3}
            if strength[source.rule_decision] > strength[target.rule_decision]:
                target.rule_decision, target.rule_reason = source.rule_decision, source.rule_reason
            if source.first_party and source.rule_reason == "tier:high":
                target.rule_reason = source.rule_reason
            if target.decision != "push":
                target.decision = None
                target.assess_status = "pending"
            target.importance_hint = max(target.importance_hint, source.importance_hint)
            source.article_count = 0
            source.decision = "drop"
            source.decision_reason = "repeat"
            source.same_as_event_id = resolved_id
            source.decided_at = utc_now().replace(tzinfo=None)
            await session.commit()
            return True

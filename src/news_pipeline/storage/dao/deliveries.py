"""Transactional delivery queue and durable per-channel attempt reservations."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Delivery, Event, EventArticle, NewsProcessed, PushLog

RETRY_SECONDS = (10, 30, 120, 600, 1800)


def naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


class DeliveryDAO:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, delivery_id: int) -> Delivery | None:
        async with self.db.session() as session:
            return await session.get(Delivery, delivery_id)

    async def enqueue(self, delivery: Delivery) -> int:
        async with self.db.session() as session:
            delivery_id = await self.enqueue_session(session, delivery)
            await session.commit()
            return delivery_id

    @staticmethod
    async def enqueue_session(session: AsyncSession, delivery: Delivery) -> int:
        values = delivery.model_dump(exclude={"id"})
        for key, value in values.items():
            if isinstance(value, datetime):
                values[key] = naive_utc(value)
        result = await session.execute(
            insert(Delivery).values(**values).on_conflict_do_nothing().returning(col(Delivery.id))
        )
        new_id = result.scalar_one_or_none()
        if new_id is None:
            query = select(Delivery).where(
                col(Delivery.kind) == delivery.kind,
                col(Delivery.channel) == delivery.channel,
            )
            if delivery.event_id is not None:
                query = query.where(col(Delivery.event_id) == delivery.event_id)
            elif delivery.digest_slot is not None:
                query = query.where(col(Delivery.digest_slot) == delivery.digest_slot)
            else:
                raise ValueError("Delivery conflict lacks an event or digest slot identity")
            existing = (await session.execute(query)).scalar_one()
            if existing.id is None:
                raise ValueError("Stored delivery has no id")
            return int(existing.id)
        delivery_id = int(new_id)
        if delivery.kind == "digest" and delivery.status == "shadow":
            stored = await session.get(Delivery, delivery_id)
            if stored is not None:
                await DeliveryDAO._consume_completed_digest(session, stored)
        return delivery_id

    async def ready(
        self,
        now: datetime,
        limit: int = 100,
        *,
        allowed_kinds: tuple[str, ...] | None = None,
    ) -> list[Delivery]:
        at = naive_utc(now)
        async with self.db.session() as session:
            query = select(Delivery).where(
                or_(
                    (col(Delivery.status) == "pending")
                    & (
                        col(Delivery.next_attempt_at).is_(None)
                        | (col(Delivery.next_attempt_at) <= at)
                    ),
                    col(Delivery.status).in_(["pending", "failed"])
                    & (col(Delivery.kind) == "immediate")
                    & (col(Delivery.created_at) <= at - timedelta(minutes=30)),
                )
            )
            if allowed_kinds is not None:
                query = query.where(col(Delivery.kind).in_(allowed_kinds))
            result = await session.execute(
                query.order_by(col(Delivery.created_at), col(Delivery.id)).limit(limit)
            )
            return list(result.scalars())

    async def reserve_attempt(self, delivery_id: int, now: datetime) -> Delivery | None:
        at = naive_utc(now)
        async with self.db.session() as session:
            # Serialize the rate check and reservation across processes and SQLite connections.
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(Delivery, delivery_id)
            if row is None or row.status not in {"pending", "failed"}:
                return None
            if row.kind == "immediate" and row.event_id is not None:
                legacy_send = await session.execute(
                    select(col(PushLog.id))
                    .join(NewsProcessed, col(NewsProcessed.id) == col(PushLog.news_id))
                    .join(EventArticle, col(EventArticle.raw_id) == col(NewsProcessed.raw_id))
                    .where(
                        col(EventArticle.event_id) == row.event_id,
                        col(PushLog.channel) == row.channel,
                        col(PushLog.status).in_(["ok", "sent"]),
                        col(PushLog.sent_at) <= at,
                    )
                    .limit(1)
                )
                if legacy_send.scalar_one_or_none() is not None:
                    row.status = "superseded"
                    row.next_attempt_at = None
                    row.last_error = "Already sent by legacy on this channel"
                    await session.commit()
                    return None
            if row.kind == "immediate" and row.created_at <= at - timedelta(minutes=30):
                row.status = "expired"
                row.next_attempt_at = None
                if row.event_id is not None:
                    event = await session.get(Event, row.event_id)
                    if event is not None:
                        event.decision = "digest"
                        event.decision_reason = "delivery_expired"
                        event.decided_at = at
                await session.commit()
                return None
            if row.status != "pending" or (row.next_attempt_at and row.next_attempt_at > at):
                return None
            cutoff = at - timedelta(seconds=60)
            histories = (
                await session.execute(
                    select(col(Delivery.attempt_timestamps)).where(
                        col(Delivery.channel) == row.channel,
                        func.json_extract(col(Delivery.attempt_timestamps), "$[#-1]")
                        > cutoff.isoformat(),
                    )
                )
            ).scalars()
            timestamps = sorted(
                naive_utc(datetime.fromisoformat(timestamp))
                for history in histories
                for timestamp in history
                if naive_utc(datetime.fromisoformat(timestamp)) > cutoff
            )
            available_at = at
            if timestamps:
                available_at = max(available_at, timestamps[-1] + timedelta(seconds=1))
            if len(timestamps) >= 20:
                available_at = max(available_at, timestamps[-20] + timedelta(seconds=60))
            if available_at > at:
                row.next_attempt_at = available_at
                await session.commit()
                return None
            row.attempt_timestamps = [*row.attempt_timestamps, at.isoformat()]
            # A crashed worker's reservation becomes retryable after a bounded lease.
            row.next_attempt_at = at + timedelta(seconds=60)
            await session.commit()
            return row

    async def finish_attempt(
        self,
        delivery_id: int,
        *,
        ok: bool,
        now: datetime,
        error: str = "",
    ) -> None:
        at = naive_utc(now)
        async with self.db.session() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(Delivery, delivery_id)
            if row is None or row.status != "pending":
                return
            if ok:
                row.status = "sent"
                row.sent_at = at
                row.next_attempt_at = None
                row.last_error = None
                await session.flush()
                await self._consume_completed_digest(session, row)
            else:
                row.attempts += 1
                row.last_error = error[:2000]
                delay = RETRY_SECONDS[min(row.attempts, len(RETRY_SECONDS)) - 1]
                row.next_attempt_at = at + timedelta(seconds=delay)
                if row.attempts >= len(RETRY_SECONDS):
                    row.status = "failed"
            await session.commit()

    @staticmethod
    async def _consume_completed_digest(session: AsyncSession, delivery: Delivery) -> None:
        if delivery.kind != "digest" or delivery.digest_slot is None:
            return
        rows = list(
            (
                await session.execute(
                    select(Delivery).where(
                        col(Delivery.kind) == "digest",
                        col(Delivery.market) == delivery.market,
                        col(Delivery.digest_slot) == delivery.digest_slot,
                    )
                )
            ).scalars()
        )
        if not rows or any(row.status not in {"sent", "shadow"} for row in rows):
            return
        consumed = {event_id for row in rows for event_id in row.consumed_event_ids}
        for event_id in consumed:
            event = await session.get(Event, event_id)
            if event is not None and event.digest_delivery_id is None:
                event.digest_delivery_id = delivery.id

    async def release_failed_digest(self, delivery_id: int) -> None:
        async with self.db.session() as session:
            row = await session.get(Delivery, delivery_id)
            if row is not None and row.kind == "digest" and row.status == "failed":
                row.status = "expired"
                await session.commit()

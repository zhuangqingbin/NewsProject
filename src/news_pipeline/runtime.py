"""Composition and transactional decisions for the staged news pipeline."""

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlmodel import col

from news_pipeline.assess.assessor import EventAssessor
from news_pipeline.assess.client import ChatClient
from news_pipeline.config.loader import ConfigSnapshot
from news_pipeline.deliver.cards import build_event_card
from news_pipeline.deliver.digest import DigestBuilder
from news_pipeline.deliver.outbox import Outbox
from news_pipeline.deliver.policy import decide, markets_for_event
from news_pipeline.events.clusterer import EventClusterer
from news_pipeline.health.ops_report import build_ops_report
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.storage.dao.deliveries import DeliveryDAO
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Delivery, Event
from shared.common.timeutil import utc_now
from shared.observability.alert import BarkAlerter
from shared.push.dispatcher import PusherDispatcher


class PipelineRuntime:
    def __init__(
        self,
        db: Database,
        snap: ConfigSnapshot,
        dispatcher: PusherDispatcher,
        bark: BarkAlerter | None = None,
    ) -> None:
        self.db = db
        self.snap = snap
        self.dispatcher = dispatcher
        self.raw = RawNewsDAO(db)
        self.events = EventsDAO(db)
        self.deliveries = DeliveryDAO(db)
        self.rules = RulesEngine(
            snap.watchlist.rules, scoring=snap.scoring, first_party=snap.first_party
        )
        self.clusterer = EventClusterer(
            self.events,
            self.raw,
            self.rules,
            merge_window_min=snap.first_party.juchao.merge_window_min,
            merge_max_items=snap.first_party.juchao.merge_max_items,
        )
        self.client = ChatClient(
            api_key=snap.secrets.llm.get("dashscope_api_key", ""), base_url=snap.app.llm.base_url
        )
        self.assessor = EventAssessor(
            self.events, self.client, snap.app.llm, snap.watchlist, bark=bark
        )
        self.outbox = Outbox(self.deliveries, dispatcher)
        self.digest_builder = DigestBuilder(self.events, snap.app.digest, self.assessor)
        self.ticker_market = {
            entry.ticker: market
            for market in ("cn", "us")
            for entry in getattr(snap.watchlist.rules, market)
        }
        self.channels = {
            market: [
                name
                for name, ch in snap.channels.channels.items()
                if ch.enabled and ch.market == market and not name.endswith("_alert")
            ]
            for market in ("cn", "us")
        }

    async def process_v2(self) -> int:
        count = await self.clusterer.process()
        await self.assessor.run()
        await self.decide_pending()
        return count

    async def decide_pending(self) -> int:
        count = 0
        for event in await self.events.list_undecided():
            assert event.id is not None
            async with self.db.session() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                current = await session.get(Event, event.id)
                if (
                    current is None
                    or current.decision is not None
                    or current.assess_status == "pending"
                ):
                    continue
                decision = decide(current, utc_now(), self.snap.app.push)
                if decision.reason == "repeat" and current.same_as_event_id:
                    target_id, version = current.same_as_event_id, current.article_count
                    await session.rollback()
                    if await self.events.merge_repeat(
                        event.id, target_id, expected_article_count=version
                    ):
                        count += 1
                    continue
                action, reason = decision.action, decision.reason
                targets = [
                    channel
                    for market in markets_for_event(current, self.ticker_market)
                    for channel in self.channels.get(market, [])
                ]
                if action == "push":
                    cutoff = (
                        utc_now()
                        - timedelta(minutes=self.snap.app.push.same_ticker_burst_window_min)
                    ).replace(tzinfo=None)
                    result = await session.execute(
                        select(Event)
                        .join(Delivery, col(Delivery.event_id) == col(Event.id))
                        .where(
                            col(Delivery.kind) == "immediate",
                            col(Delivery.created_at) >= cutoff,
                            col(Delivery.status).in_(["sent", "pending"]),
                        )
                        .distinct()
                    )
                    sent = list(result.scalars())
                    if any(
                        sum(ticker in old.subject_tickers for old in sent)
                        >= self.snap.app.push.same_ticker_burst_threshold
                        for ticker in current.subject_tickers
                    ):
                        action, reason = "digest", "burst"
                    elif not targets:
                        action, reason = "digest", "no_channel"
                current.decision, current.decision_reason = action, reason
                current.decided_at = utc_now().replace(tzinfo=None)
                if action == "push":
                    articles = await self.events.articles(event.id)
                    msg = build_event_card(
                        current, articles, color_scheme=self.snap.app.push.color_scheme
                    )
                    for channel in targets:
                        await DeliveryDAO.enqueue_session(
                            session,
                            Delivery(
                                kind="immediate",
                                event_id=current.id,
                                channel=channel,
                                market=self.snap.channels.channels[channel].market,
                                payload=msg.model_dump(mode="json"),
                            ),
                        )
                await session.commit()
            count += 1
        return count

    async def digest(self, market: str, slot: str) -> None:
        # Terminal failures release their reservation for a later digest slot.
        async with self.db.session() as session:
            failed = (
                (
                    await session.execute(
                        select(Delivery).where(
                            col(Delivery.kind) == "digest",
                            col(Delivery.market) == market,
                            col(Delivery.status) == "failed",
                        )
                    )
                )
                .scalars()
                .all()
            )
        for delivery in failed:
            assert delivery.id is not None
            await self.deliveries.release_failed_digest(delivery.id)
        built = await self.digest_builder.build(market, slot)
        if built is None:
            return
        msg, displayed, consumed = built
        async with self.db.session() as session:
            for channel in self.channels[market]:
                await DeliveryDAO.enqueue_session(
                    session,
                    Delivery(
                        kind="digest",
                        market=market,
                        channel=channel,
                        payload=msg.model_dump(mode="json"),
                        digest_slot=slot,
                        event_ids=displayed,
                        consumed_event_ids=consumed,
                    ),
                )
            await session.commit()

    async def ops_report(self, db_path: Path) -> None:
        msg = await build_ops_report(self.db, db_path=db_path, mode=self.snap.app.pipeline.mode)
        channel = self.snap.app.ops.report_channel
        if (
            channel not in self.snap.channels.channels
            or not self.snap.channels.channels[channel].enabled
        ):
            return
        date = utc_now().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        await self.deliveries.enqueue(
            Delivery(
                kind="ops",
                channel=channel,
                payload=msg.model_dump(mode="json"),
                digest_slot=f"ops@{date}",
            )
        )

    async def close(self) -> None:
        await self.client.close()

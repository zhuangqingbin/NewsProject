from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import (
    CommonMessage,
    EnrichedNews,
    ScoredNews,
)
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.scheduler.jobs import process_pending, send_digest


def _enriched() -> EnrichedNews:
    return EnrichedNews(
        raw_id=1,
        summary="s",
        related_tickers=["NVDA"],
        sectors=[],
        event_type=EventType.OTHER,
        sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH,
        confidence=0.9,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_process_pending_routes_critical_immediately():
    raw_dao = MagicMock()
    pending_row = MagicMock(
        id=1,
        source="finnhub",
        market="us",
        url="https://x/1",
        url_hash="h",
        title="t",
        title_simhash=0,
        body="b",
        raw_meta={},
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
    )
    raw_dao.list_pending = AsyncMock(return_value=[pending_row])
    raw_dao.mark_status = AsyncMock()

    llm = MagicMock()
    llm.process = AsyncMock(return_value=_enriched())
    importance = MagicMock()
    importance.score_news = AsyncMock(
        return_value=ScoredNews(
            enriched=_enriched(),
            score=80,
            is_critical=True,
            rule_hits=["sentiment_high"],
            llm_reason=None,
        )
    )
    proc_dao = MagicMock()
    proc_dao.insert = AsyncMock(return_value=99)
    builder = MagicMock()
    builder.build = MagicMock(
        return_value=CommonMessage(
            title="t",
            summary="s",
            source_label="x",
            source_url="https://x.com",
            badges=[],
            chart_url=None,
            deeplinks=[],
            market=Market.US,
        )
    )
    router = MagicMock()
    router.route = MagicMock(
        return_value=[
            MagicMock(channels=["tg_us"], immediate=True, message=builder.build.return_value)
        ]
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value={"tg_us": MagicMock(ok=True, http_status=200, response_body="", retries=0)}
    )
    push_log = MagicMock()
    push_log.write = AsyncMock()
    digest_dao = MagicMock()
    digest_dao.enqueue = AsyncMock()
    burst = MagicMock()
    burst.should_send = MagicMock(return_value=True)

    n = await process_pending(
        raw_dao=raw_dao,
        llm=llm,
        importance=importance,
        proc_dao=proc_dao,
        msg_builder=builder,
        router=router,
        dispatcher=dispatcher,
        push_log=push_log,
        digest_dao=digest_dao,
        burst=burst,
    )
    assert n == 1
    dispatcher.dispatch.assert_awaited_once()
    digest_dao.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_digest_consumes_buffer():
    digest_dao = MagicMock()
    digest_dao.list_pending = AsyncMock(
        return_value=[
            MagicMock(id=1, news_id=10),
            MagicMock(id=2, news_id=11),
        ]
    )
    digest_dao.mark_consumed = AsyncMock()
    builder = MagicMock()
    builder.build_digest = MagicMock(
        return_value=CommonMessage(
            title="d",
            summary="s",
            source_label="digest",
            source_url="https://x.com",
            badges=[],
            chart_url=None,
            deeplinks=[],
            market=Market.US,
        )
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value={"feishu_us": MagicMock(ok=True, http_status=200, response_body="", retries=0)}
    )
    proc_dao = MagicMock()
    proc_dao.get = AsyncMock(side_effect=lambda i: MagicMock(id=i))

    n = await send_digest(
        digest_key="morning_us",
        market="us",
        channels=["feishu_us"],
        digest_dao=digest_dao,
        proc_dao=proc_dao,
        digest_builder=builder,
        dispatcher=dispatcher,
    )
    assert n == 2
    digest_dao.mark_consumed.assert_awaited_once_with([1, 2])

"""Comprehensive end-to-end-ish tests for process_pending across 4 enable combos."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import (
    CommonMessage,
    EnrichedNews,
    RawArticle,
    ScoredNews,
)
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scheduler.jobs import process_pending, synth_enriched_from_rules


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
        extracted_at=datetime(2026, 4, 26),
    )


def _pending_row(rid: int = 1):
    return MagicMock(
        id=rid,
        source="finnhub",
        market="us",
        url="https://x/1",
        url_hash="h",
        title="NVDA news",
        title_simhash=0,
        body="NVDA earnings beat estimates by 10%",
        raw_meta={},
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
    )


def _common_msg() -> CommonMessage:
    return CommonMessage(
        title="t",
        summary="s",
        source_label="x",
        source_url="https://x.com",
        badges=[],
        chart_url=None,
        deeplinks=[],
        market=Market.US,
    )


def _setup_mocks():
    raw_dao = MagicMock()
    raw_dao.list_pending = AsyncMock(return_value=[_pending_row()])
    raw_dao.mark_status = AsyncMock()

    rules_engine = MagicMock()

    llm = MagicMock()
    llm.process = AsyncMock(return_value=_enriched())
    llm.process_with_rules = AsyncMock(return_value=_enriched())

    importance = MagicMock()
    importance.score_news = AsyncMock(
        return_value=ScoredNews(
            enriched=_enriched(),
            score=80,
            is_critical=True,
            rule_hits=[],
            llm_reason=None,
        )
    )

    proc_dao = MagicMock()
    proc_dao.insert = AsyncMock(return_value=42)

    msg_builder = MagicMock()
    msg_builder.build = MagicMock(return_value=_common_msg())
    msg_builder.build_from_rules = MagicMock(return_value=_common_msg())

    router = MagicMock()
    router.route = MagicMock(
        return_value=[
            MagicMock(channels=["tg_us"], immediate=True, message=msg_builder.build.return_value),
        ]
    )

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value={
            "tg_us": MagicMock(ok=True, http_status=200, response_body="", retries=0),
        }
    )

    push_log = MagicMock()
    push_log.write = AsyncMock()
    digest_dao = MagicMock()
    digest_dao.enqueue = AsyncMock()
    burst = MagicMock()
    burst.should_send = MagicMock(return_value=True)

    return dict(
        raw_dao=raw_dao,
        llm=llm,
        rules_engine=rules_engine,
        importance=importance,
        proc_dao=proc_dao,
        msg_builder=msg_builder,
        router=router,
        dispatcher=dispatcher,
        push_log=push_log,
        digest_dao=digest_dao,
        burst=burst,
    )


@pytest.mark.asyncio
async def test_rules_only_match_synth_path():
    """rules.enable=True, llm.enable=False → match → synth_enriched, push."""
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(
        return_value=RulesVerdict(
            matched=True,
            tickers=["NVDA"],
            markets=["us"],
            score_boost=50.0,
        )
    )
    n = await process_pending(rules_enabled=True, llm_enabled=False, **mocks)
    assert n == 1
    mocks["llm"].process.assert_not_awaited()
    mocks["llm"].process_with_rules.assert_not_awaited()
    mocks["msg_builder"].build_from_rules.assert_called_once()
    mocks["dispatcher"].dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_rules_only_no_match_skipped():
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(return_value=RulesVerdict(matched=False))
    n = await process_pending(rules_enabled=True, llm_enabled=False, **mocks)
    assert n == 0
    mocks["raw_dao"].mark_status.assert_awaited_with(1, "skipped_rules")
    mocks["dispatcher"].dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_rules_plus_llm_match_uses_process_with_rules():
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(
        return_value=RulesVerdict(
            matched=True,
            tickers=["NVDA"],
            markets=["us"],
            score_boost=50.0,
        )
    )
    n = await process_pending(rules_enabled=True, llm_enabled=True, **mocks)
    assert n == 1
    mocks["llm"].process_with_rules.assert_awaited_once()
    mocks["llm"].process.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_only_uses_legacy_process():
    """rules.enable=False, llm.enable=True → traditional Tier-0 path."""
    mocks = _setup_mocks()
    mocks_no_re = {k: v for k, v in mocks.items() if k != "rules_engine"}
    n = await process_pending(
        rules_enabled=False,
        llm_enabled=True,
        rules_engine=None,
        **mocks_no_re,
    )
    assert n == 1
    mocks["llm"].process.assert_awaited_once()
    mocks["llm"].process_with_rules.assert_not_awaited()
    mocks["msg_builder"].build.assert_called_once()
    mocks["msg_builder"].build_from_rules.assert_not_called()


@pytest.mark.asyncio
async def test_rules_only_grayzone_skip_no_push():
    mocks = _setup_mocks()
    mocks["importance"].score_news = AsyncMock(
        return_value=ScoredNews(
            enriched=_enriched(),
            score=50.0,
            is_critical=False,
            rule_hits=[],
            llm_reason="rules-only-grayzone-skip",
        )
    )
    mocks["rules_engine"].match = MagicMock(
        return_value=RulesVerdict(
            matched=True,
            sectors=["semi"],
            markets=["us"],
            score_boost=20.0,
        )
    )
    n = await process_pending(rules_enabled=True, llm_enabled=False, **mocks)
    assert n == 0
    mocks["raw_dao"].mark_status.assert_awaited_with(1, "skipped_grayzone")
    mocks["dispatcher"].dispatch.assert_not_awaited()


def test_synth_enriched_basic():
    """Inline test of synth helper (kept here to avoid extra file)."""
    art = RawArticle(
        source="finnhub",
        market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1",
        url_hash="h",
        title="t",
        body="hello world " * 30,
        title_simhash=0,
        raw_meta={},
    )
    verdict = RulesVerdict(
        matched=True,
        tickers=["NVDA"],
        related_tickers=["AMD"],
        sectors=["semi"],
        markets=["us"],
        score_boost=70.0,
    )
    e = synth_enriched_from_rules(art, verdict, raw_id=42)
    assert e.raw_id == 42
    assert len(e.summary) <= 200
    assert e.related_tickers == ["AMD", "NVDA"]
    assert e.sentiment == Sentiment.NEUTRAL
    assert e.confidence == 0.0
    assert e.model_used == "rules-only"

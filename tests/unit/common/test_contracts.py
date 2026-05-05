# tests/unit/common/test_contracts.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from news_pipeline.common.contracts import (
    Badge,
    CommonMessage,
    Deeplink,
    DispatchPlan,
    EnrichedNews,
    Entity,
    RawArticle,
    Relation,
    ScoredNews,
)
from news_pipeline.common.enums import (
    EntityType,
    EventType,
    Magnitude,
    Market,
    Predicate,
    Sentiment,
)


def _now() -> datetime:
    return datetime(2026, 4, 25, 12, 0, tzinfo=UTC)


def test_raw_article_roundtrip():
    a = RawArticle(
        source="finnhub",
        market=Market.US,
        fetched_at=_now(),
        published_at=_now(),
        url="https://example.com/x",
        url_hash="abc",
        title="t",
        body="b",
        raw_meta={"k": 1},
    )
    assert a.market == Market.US
    assert a.model_dump_json()  # serializable


def test_raw_article_requires_url_hash():
    with pytest.raises(ValidationError):
        RawArticle(
            source="x",
            market=Market.US,
            fetched_at=_now(),
            published_at=_now(),
            url="https://x.com",
            title="t",  # type: ignore[call-arg]
        )


def test_enriched_news_with_entities_relations():
    e = Entity(type=EntityType.COMPANY, name="NVIDIA", ticker="NVDA")
    rel = Relation(
        subject=e,
        predicate=Predicate.SUPPLIES,
        object=Entity(type=EntityType.COMPANY, name="TSMC", ticker="TSM"),
        confidence=0.9,
    )
    n = EnrichedNews(
        raw_id=1,
        summary="s",
        related_tickers=["NVDA"],
        sectors=["semiconductor"],
        event_type=EventType.POLICY,
        sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH,
        confidence=0.88,
        key_quotes=["q"],
        entities=[e],
        relations=[rel],
        model_used="claude-haiku-4-5",
        extracted_at=_now(),
    )
    assert n.relations[0].predicate == Predicate.SUPPLIES


def test_scored_news_critical_flag():
    e = EnrichedNews(
        raw_id=1,
        summary="s",
        related_tickers=[],
        sectors=[],
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.LOW,
        confidence=0.5,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="ds",
        extracted_at=_now(),
    )
    s = ScoredNews(
        enriched=e, score=72.0, is_critical=True, rule_hits=["price_5pct"], llm_reason=None
    )
    assert s.is_critical and s.score == 72.0


def test_common_message_minimal():
    m = CommonMessage(
        title="t",
        summary="s",
        source_label="Reuters",
        source_url="https://r.com/x",
        badges=[Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[Deeplink(label="原文", url="https://r.com/x")],
        market=Market.US,
    )
    assert m.market == Market.US
    assert m.badges[0].text == "bearish"


def test_dispatch_plan():
    msg = CommonMessage(
        title="t",
        summary="s",
        source_label="x",
        source_url="https://x.com",
        badges=[],
        chart_url=None,
        deeplinks=[],
        market=Market.CN,
    )
    p = DispatchPlan(message=msg, channels=["wecom_cn", "feishu_cn"], immediate=True)
    assert "wecom_cn" in p.channels

# tests/unit/archive/test_schema.py
from datetime import datetime

from news_pipeline.archive.schema import enriched_to_row
from news_pipeline.common.contracts import EnrichedNews, RawArticle, ScoredNews
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment


def test_enriched_to_row():
    art = RawArticle(
        source="reuters",
        market=Market.US,
        fetched_at=datetime(2026, 4, 25, 10),
        published_at=datetime(2026, 4, 25, 10),
        url="https://reut/x",
        url_hash="h",
        title="t",
        body="b",
    )
    e = EnrichedNews(
        raw_id=1,
        summary="出口管制",
        related_tickers=["NVDA"],
        sectors=["semiconductor"],
        event_type=EventType.POLICY,
        sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH,
        confidence=0.9,
        key_quotes=["…"],
        entities=[],
        relations=[],
        model_used="haiku",
        extracted_at=datetime(2026, 4, 25, 10),
    )
    s = ScoredNews(
        enriched=e, score=80.0, is_critical=True,
        rule_hits=["sentiment_high"], llm_reason=None,
    )
    row = enriched_to_row(
        art, s, news_processed_id=42,
        sent_to=["tg_us", "feishu_us"], chart_url=None,
    )
    assert row["news_id"] == 42
    assert row["market"] == "美股"
    assert row["sentiment"] == "🔴看跌"
    assert "tg_us" in row["sent_to"]

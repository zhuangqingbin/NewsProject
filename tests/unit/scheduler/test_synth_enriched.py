from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scheduler.jobs import synth_enriched_from_rules


def test_synth_basic():
    art = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1", url_hash="h", title="t",
        body="hello world " * 30,
        title_simhash=0, raw_meta={},
    )
    verdict = RulesVerdict(
        matched=True, tickers=["NVDA"], related_tickers=["AMD"],
        sectors=["semiconductor"], markets=["us"], score_boost=70.0,
    )
    e = synth_enriched_from_rules(art, verdict, raw_id=42)
    assert e.raw_id == 42
    assert len(e.summary) <= 200
    assert e.related_tickers == ["AMD", "NVDA"]
    assert e.sectors == ["semiconductor"]
    assert e.event_type == EventType.OTHER
    assert e.sentiment == Sentiment.NEUTRAL
    assert e.magnitude == Magnitude.LOW
    assert e.confidence == 0.0
    assert e.model_used == "rules-only"


def test_synth_empty_body_uses_title():
    art = RawArticle(
        source="x", market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1", url_hash="h", title="The Title",
        body=None, title_simhash=0, raw_meta={},
    )
    verdict = RulesVerdict(matched=True, tickers=["NVDA"], score_boost=50.0)
    e = synth_enriched_from_rules(art, verdict, raw_id=1)
    assert e.summary == "The Title"

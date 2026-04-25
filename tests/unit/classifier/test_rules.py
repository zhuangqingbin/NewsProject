# tests/unit/classifier/test_rules.py
from datetime import datetime

from news_pipeline.classifier.rules import RuleEngine, RuleHit
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment
from news_pipeline.config.schema import ClassifierRulesCfg


def _enriched(magnitude="medium", sentiment="neutral", event="other", tickers=None) -> EnrichedNews:
    return EnrichedNews(
        raw_id=1,
        summary="s",
        related_tickers=tickers or [],
        sectors=[],
        event_type=EventType(event),
        sentiment=Sentiment(sentiment),
        magnitude=Magnitude(magnitude),
        confidence=0.8,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


def _cfg() -> ClassifierRulesCfg:
    return ClassifierRulesCfg(
        price_move_critical_pct=5.0,
        sources_always_critical=["sec_edgar", "juchao"],
        sentiment_high_magnitude_critical=True,
    )


def test_first_party_source_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(), source="sec_edgar")
    assert any(h.name == "first_party_source" for h in hits)


def test_high_magnitude_sentiment_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(magnitude="high", sentiment="bearish"), source="finnhub")
    assert any(h.name == "sentiment_high" for h in hits)


def test_low_neutral_no_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(magnitude="low"), source="finnhub")
    assert hits == []


def test_score_combines_hits():
    e = RuleEngine(_cfg())
    hits = [RuleHit("first_party_source", 30), RuleHit("sentiment_high", 40)]
    assert e.score(hits) == 70

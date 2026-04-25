# tests/unit/common/test_enums.py
from news_pipeline.common.enums import (
    Market, Sentiment, Magnitude, EventType, EntityType, Predicate,
)


def test_markets():
    assert Market.US.value == "us"
    assert Market.CN.value == "cn"


def test_sentiment_membership():
    assert Sentiment("bullish") == Sentiment.BULLISH


def test_event_type_includes_core():
    for v in ("earnings", "m_and_a", "policy", "price_move",
              "downgrade", "upgrade", "filing", "other"):
        assert EventType(v)


def test_predicate_includes_core():
    for v in ("supplies", "competes_with", "owns",
              "regulates", "partners_with", "mentions"):
        assert Predicate(v)


def test_entity_type_includes_core():
    for v in ("company", "person", "event", "sector", "policy", "product"):
        assert EntityType(v)

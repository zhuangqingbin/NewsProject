# tests/unit/pushers/test_message_builder.py
from datetime import datetime

from news_pipeline.common.contracts import EnrichedNews, RawArticle, ScoredNews
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.pushers.common.message_builder import MessageBuilder


def _make() -> tuple[RawArticle, ScoredNews]:
    art = RawArticle(
        source="reuters", market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25, 22, 30),
        url="https://reut.com/x", url_hash="h",
        title="NVDA -8% on export controls", body="...",
    )
    e = EnrichedNews(
        raw_id=1, summary="出口管制升级",
        related_tickers=["NVDA", "TSM"], sectors=["semiconductor"],
        event_type=EventType.POLICY, sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH, confidence=0.92,
        key_quotes=["将 H100 列入实体清单"],
        entities=[], relations=[],
        model_used="claude-haiku-4-5", extracted_at=datetime(2026, 4, 25),
    )
    s = ScoredNews(enriched=e, score=80, is_critical=True,
                   rule_hits=["sentiment_high"], llm_reason=None)
    return art, s


def test_build_includes_badges_and_deeplinks():
    art, scored = _make()
    b = MessageBuilder(source_labels={"reuters": "Reuters"})
    msg = b.build(art, scored, chart_url=None)
    badge_texts = [bd.text for bd in msg.badges]
    assert "bearish" in badge_texts and "high" in badge_texts
    assert any(d.label.startswith("原文") or d.label == "原文" for d in msg.deeplinks)
    assert msg.market == Market.US

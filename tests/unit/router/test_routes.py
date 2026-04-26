# tests/unit/router/test_routes.py
from datetime import datetime

from news_pipeline.common.contracts import (
    CommonMessage,
    EnrichedNews,
    ScoredNews,
)
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.router.routes import DispatchRouter


def _scored(market: str = "us", critical: bool = False) -> ScoredNews:
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
        model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )
    return ScoredNews(enriched=e, score=50.0, is_critical=critical, rule_hits=[], llm_reason=None)


def _msg(market: Market) -> CommonMessage:
    return CommonMessage(
        title="t",
        summary="s",
        source_label="x",
        source_url="https://x.com",
        badges=[],
        chart_url=None,
        deeplinks=[],
        market=market,
    )


def test_critical_us_routes_to_us_channels_immediate():
    r = DispatchRouter(
        channels_by_market={
            "us": ["tg_us", "feishu_us", "wecom_us"],
            "cn": ["tg_cn", "feishu_cn", "wecom_cn"],
        }
    )
    plans = r.route(_scored("us", critical=True), _msg(Market.US))
    assert len(plans) == 1
    p = plans[0]
    assert set(p.channels) == {"tg_us", "feishu_us", "wecom_us"}
    assert p.immediate is True


def test_non_critical_routes_to_digest():
    r = DispatchRouter(
        channels_by_market={
            "cn": ["tg_cn", "feishu_cn"],
        }
    )
    plans = r.route(_scored("cn", critical=False), _msg(Market.CN))
    assert plans[0].immediate is False


def test_route_with_markets_param_multi():
    r = DispatchRouter(channels_by_market={
        "us": ["tg_us", "feishu_us"],
        "cn": ["tg_cn", "feishu_cn"],
    })
    plans = r.route(
        _scored("us", critical=True), _msg(Market.US),
        markets=["us", "cn"],
    )
    assert len(plans) == 2
    market_channels = {tuple(sorted(p.channels)) for p in plans}
    assert ("feishu_us", "tg_us") in market_channels
    assert ("feishu_cn", "tg_cn") in market_channels


def test_route_without_markets_falls_back_to_msg_market():
    r = DispatchRouter(channels_by_market={
        "us": ["tg_us"],
        "cn": ["tg_cn"],
    })
    plans = r.route(_scored("us", critical=True), _msg(Market.US))
    assert len(plans) == 1
    assert "tg_us" in plans[0].channels

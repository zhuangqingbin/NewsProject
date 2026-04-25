# src/news_pipeline/archive/schema.py
from typing import Any

from news_pipeline.common.contracts import RawArticle, ScoredNews
from news_pipeline.common.enums import Market, Sentiment

_MARKET_LABEL = {Market.US: "美股", Market.CN: "A股"}
_SENTIMENT_LABEL = {
    Sentiment.BULLISH: "🟢看涨",
    Sentiment.BEARISH: "🔴看跌",
    Sentiment.NEUTRAL: "⚪中性",
}
_MAG_LABEL = {"low": "低", "medium": "中", "high": "高"}


def enriched_to_row(
    art: RawArticle,
    scored: ScoredNews,
    *,
    news_processed_id: int,
    sent_to: list[str],
    chart_url: str | None,
) -> dict[str, Any]:
    e = scored.enriched
    return {
        "news_id": news_processed_id,
        "published_at": int(art.published_at.timestamp() * 1000),
        "market": _MARKET_LABEL[art.market],
        "source": art.source,
        "tickers": e.related_tickers,
        "event_type": e.event_type.value,
        "sentiment": _SENTIMENT_LABEL[e.sentiment],
        "magnitude": _MAG_LABEL[e.magnitude.value],
        "score": scored.score,
        "is_critical": scored.is_critical,
        "title": art.title,
        "summary": e.summary,
        "key_quotes": "\n".join(e.key_quotes),
        "url": str(art.url),
        "chart_url": chart_url or "",
        "sent_to": sent_to,
    }

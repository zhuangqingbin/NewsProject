# src/news_pipeline/pushers/common/message_builder.py
from news_pipeline.common.contracts import (
    Badge,
    CommonMessage,
    Deeplink,
    RawArticle,
    ScoredNews,
)
from news_pipeline.common.enums import Market, Sentiment
from news_pipeline.rules.verdict import RulesVerdict

_SENTIMENT_COLOR = {
    Sentiment.BULLISH: "green",
    Sentiment.BEARISH: "red",
    Sentiment.NEUTRAL: "gray",
}


class MessageBuilder:
    def __init__(self, *, source_labels: dict[str, str]) -> None:
        self._labels = source_labels

    def build(
        self,
        art: RawArticle,
        scored: ScoredNews,
        *,
        chart_url: str | None = None,
    ) -> CommonMessage:
        e = scored.enriched
        badges: list[Badge] = []
        for t in e.related_tickers[:5]:
            badges.append(Badge(text=t, color="blue"))
        for s in e.sectors[:2]:
            badges.append(Badge(text=f"#{s}", color="gray"))
        badges.append(Badge(text=e.sentiment.value, color=_SENTIMENT_COLOR[e.sentiment]))
        badges.append(Badge(text=e.magnitude.value, color="yellow"))

        deeplinks = [Deeplink(label="原文", url=str(art.url))]
        for t in e.related_tickers[:3]:
            if art.market == Market.US:
                deeplinks.append(
                    Deeplink(
                        label=f"Yahoo {t}",
                        url=f"https://finance.yahoo.com/quote/{t}",
                    )
                )
            else:
                prefix = "sh" if t.startswith("6") else "sz"
                deeplinks.append(
                    Deeplink(
                        label=f"东财 {t}",
                        url=f"https://quote.eastmoney.com/{prefix}{t}.html",
                    )
                )

        return CommonMessage(
            title=art.title,
            summary=e.summary,
            source_label=self._labels.get(art.source, art.source),
            source_url=str(art.url),
            badges=badges,
            chart_url=chart_url,
            deeplinks=deeplinks,
            market=art.market,
        )

    def build_from_rules(
        self,
        art: RawArticle,
        scored: ScoredNews,
        verdict: RulesVerdict,
        *,
        chart_url: str | None = None,
    ) -> CommonMessage:
        """Rules-only mode: badges driven by verdict (tickers/sectors/macros/generic),
        summary from EnrichedNews (body[:200] in rules-only)."""
        e = scored.enriched
        badges: list[Badge] = []
        for t in (verdict.tickers + verdict.related_tickers)[:5]:
            badges.append(Badge(text=t, color="blue"))
        for s in verdict.sectors[:2]:
            badges.append(Badge(text=f"#{s}", color="gray"))
        if verdict.macros:
            badges.append(Badge(text=f"📊 {verdict.macros[0]}", color="yellow"))
        if verdict.generic_hits:
            badges.append(Badge(text=f"🔖 {verdict.generic_hits[0]}", color="gray"))
        badges.append(Badge(text="rules", color="green"))

        deeplinks = [Deeplink(label="原文", url=str(art.url))]
        for t in (verdict.tickers + verdict.related_tickers)[:3]:
            if art.market == Market.US:
                deeplinks.append(
                    Deeplink(
                        label=f"Yahoo {t}",
                        url=f"https://finance.yahoo.com/quote/{t}",
                    )
                )
            else:
                prefix = "sh" if t.startswith("6") else "sz"
                deeplinks.append(
                    Deeplink(
                        label=f"东财 {t}",
                        url=f"https://quote.eastmoney.com/{prefix}{t}.html",
                    )
                )

        return CommonMessage(
            title=art.title,
            summary=e.summary,
            source_label=self._labels.get(art.source, art.source),
            source_url=str(art.url),
            badges=badges,
            chart_url=chart_url,
            deeplinks=deeplinks,
            market=art.market,
        )

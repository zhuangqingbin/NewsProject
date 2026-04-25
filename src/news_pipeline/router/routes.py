# src/news_pipeline/router/routes.py
from news_pipeline.common.contracts import CommonMessage, DispatchPlan, ScoredNews


class DispatchRouter:
    def __init__(self, *, channels_by_market: dict[str, list[str]]) -> None:
        self._by_market = channels_by_market

    def route(self, scored: ScoredNews, msg: CommonMessage) -> list[DispatchPlan]:
        channels = self._by_market.get(msg.market.value, [])
        if not channels:
            return []
        return [
            DispatchPlan(
                message=msg,
                channels=channels,
                immediate=scored.is_critical,
            )
        ]

# src/news_pipeline/router/routes.py
from news_pipeline.common.contracts import CommonMessage, DispatchPlan, ScoredNews


class DispatchRouter:
    def __init__(self, *, channels_by_market: dict[str, list[str]]) -> None:
        self._by_market = channels_by_market

    def route(
        self,
        scored: ScoredNews,
        msg: CommonMessage,
        *,
        markets: list[str] | None = None,
    ) -> list[DispatchPlan]:
        """Route a scored news to one or more market channel sets.

        `markets`: explicit list of markets (used by rules engine when an
        article hits multiple markets — e.g., 'FOMC 影响 A 股'). None defaults
        to [msg.market.value].
        """
        target_markets = markets or [msg.market.value]
        plans: list[DispatchPlan] = []
        for mkt in target_markets:
            channels = self._by_market.get(mkt, [])
            if not channels:
                continue
            plans.append(
                DispatchPlan(
                    message=msg,
                    channels=channels,
                    immediate=scored.is_critical,
                )
            )
        return plans

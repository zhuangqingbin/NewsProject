# src/news_pipeline/llm/cost_tracker.py
from collections import defaultdict
from dataclasses import dataclass

from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.clients.base import TokenUsage


@dataclass(frozen=True)
class ModelPricing:
    input_per_m_cny: float
    output_per_m_cny: float


class CostTracker:
    def __init__(self, *, daily_ceiling_cny: float, pricing: dict[str, ModelPricing]) -> None:
        self._ceiling = daily_ceiling_cny
        self._pricing = pricing
        self._daily_total: dict[str, float] = defaultdict(float)

    def record(self, *, model: str, usage: TokenUsage) -> None:
        p = self._pricing.get(model)
        if p is None:
            return
        cost = (usage.input_tokens / 1_000_000) * p.input_per_m_cny + (
            usage.output_tokens / 1_000_000
        ) * p.output_per_m_cny
        key = utc_now().date().isoformat()
        self._daily_total[key] += cost

    def today_cost_cny(self) -> float:
        return self._daily_total[utc_now().date().isoformat()]

    def check(self) -> None:
        if self.today_cost_cny() >= self._ceiling:
            raise CostCeilingExceeded(
                f"daily LLM cost {self.today_cost_cny():.2f} >= {self._ceiling:.2f}"
            )

    def remaining_today(self) -> float:
        return max(0.0, self._ceiling - self.today_cost_cny())

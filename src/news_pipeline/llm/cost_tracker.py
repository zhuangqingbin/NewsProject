# src/news_pipeline/llm/cost_tracker.py
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.clients.base import TokenUsage

if TYPE_CHECKING:
    from news_pipeline.observability.alert import BarkAlerter


@dataclass(frozen=True)
class ModelPricing:
    input_per_m_cny: float
    output_per_m_cny: float


class CostTracker:
    def __init__(
        self,
        *,
        daily_ceiling_cny: float,
        pricing: dict[str, ModelPricing],
        bark: BarkAlerter | None = None,
        warn_threshold: float = 0.8,
    ) -> None:
        self._ceiling = daily_ceiling_cny
        self._pricing = pricing
        self._daily_total: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()
        self._bark = bark
        self._warn_threshold = warn_threshold
        # Track which dates we already sent the 80% warn to avoid repeat alerts
        self._warned_today: set[str] = set()

    def record(self, *, model: str, usage: TokenUsage) -> None:
        p = self._pricing.get(model)
        if p is None:
            return
        cost = (usage.input_tokens / 1_000_000) * p.input_per_m_cny + (
            usage.output_tokens / 1_000_000
        ) * p.output_per_m_cny
        key = utc_now().date().isoformat()
        with self._lock:
            self._daily_total[key] += cost

    def today_cost_cny(self) -> float:
        with self._lock:
            return self._daily_total[utc_now().date().isoformat()]

    def check(self) -> None:
        """Synchronous cost ceiling check (no alerts). Raises CostCeilingExceeded if over limit."""
        if self.today_cost_cny() >= self._ceiling:
            raise CostCeilingExceeded(
                f"daily LLM cost {self.today_cost_cny():.2f} >= {self._ceiling:.2f}"
            )

    async def check_async(self) -> None:
        """Async cost ceiling check with Bark alerts.

        - C-3: If cost >= ceiling → Bark urgent + raise CostCeilingExceeded
        - C-2: If cost >= 80% of ceiling → Bark warn (once per day)
        """
        from news_pipeline.observability.alert import AlertLevel

        today_cost = self.today_cost_cny()
        today_key = utc_now().date().isoformat()

        if today_cost >= self._ceiling:
            if self._bark is not None:
                await self._bark.send(
                    "llm_cost_exceeded",
                    f"今日 LLM 成本 {today_cost:.2f} CNY >= ceiling {self._ceiling:.2f}",
                    level=AlertLevel.URGENT,
                )
            raise CostCeilingExceeded(f"daily LLM cost {today_cost:.2f} >= {self._ceiling:.2f}")

        if (
            today_cost >= self._ceiling * self._warn_threshold
            and today_key not in self._warned_today
        ):
            self._warned_today.add(today_key)
            if self._bark is not None:
                await self._bark.send(
                    "llm_cost_warn",
                    (
                        f"今日 LLM 成本 {today_cost:.2f} CNY 已达"
                        f" ceiling {self._ceiling:.2f} 的"
                        f" {int(self._warn_threshold * 100)}%"
                    ),
                    level=AlertLevel.WARN,
                )

    def remaining_today(self) -> float:
        return max(0.0, self._ceiling - self.today_cost_cny())

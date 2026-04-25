# tests/unit/llm/test_cost_tracker.py
import concurrent.futures

import pytest

from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.llm.clients.base import TokenUsage
from news_pipeline.llm.cost_tracker import CostTracker, ModelPricing


def _pricing() -> dict[str, ModelPricing]:
    return {
        "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
        "claude-haiku-4-5-20251001": ModelPricing(input_per_m_cny=7.0, output_per_m_cny=35.0),
    }


def test_record_usage_accumulates(monkeypatch):
    monkeypatch.setattr(
        "news_pipeline.llm.cost_tracker.utc_now",
        lambda: __import__("datetime").datetime(2026, 4, 25),
    )
    tr = CostTracker(daily_ceiling_cny=5.0, pricing=_pricing())
    tr.record(model="deepseek-v3", usage=TokenUsage(input_tokens=1_000_000, output_tokens=200_000))
    assert tr.today_cost_cny() == pytest.approx(0.5 + 0.3)


def test_check_raises_when_over(monkeypatch):
    monkeypatch.setattr(
        "news_pipeline.llm.cost_tracker.utc_now",
        lambda: __import__("datetime").datetime(2026, 4, 25),
    )
    tr = CostTracker(daily_ceiling_cny=0.5, pricing=_pricing())
    tr.record(
        model="claude-haiku-4-5-20251001",
        usage=TokenUsage(input_tokens=200_000, output_tokens=20_000),
    )
    with pytest.raises(CostCeilingExceeded):
        tr.check()


def test_concurrent_record_is_thread_safe(monkeypatch):
    """1000 parallel record() calls must not lose updates (race condition check)."""
    monkeypatch.setattr(
        "news_pipeline.llm.cost_tracker.utc_now",
        lambda: __import__("datetime").datetime(2026, 4, 25),
    )
    tr = CostTracker(daily_ceiling_cny=10_000.0, pricing=_pricing())
    # Each call: 1_000_000 input tokens at 0.5 CNY/M = 0.5 CNY
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    n = 1000

    def _record() -> None:
        tr.record(model="deepseek-v3", usage=usage)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(_record) for _ in range(n)]
        concurrent.futures.wait(futures)

    expected = n * 0.5  # 500.0 CNY
    assert tr.today_cost_cny() == pytest.approx(expected, rel=1e-9)

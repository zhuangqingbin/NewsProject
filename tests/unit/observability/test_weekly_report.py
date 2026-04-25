from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.observability.weekly_report import build_weekly_report


@pytest.mark.asyncio
async def test_report_includes_metrics() -> None:
    metrics = MagicMock()
    metrics.get = AsyncMock(side_effect=lambda **kw: 5.0)
    text = await build_weekly_report(
        metrics=metrics,
        sources=["finnhub", "caixin_telegram"],
        channels=["tg_us", "feishu_us"],
    )
    assert "周报" in text or "Weekly" in text
    assert "finnhub" in text


@pytest.mark.asyncio
async def test_report_includes_all_sources_and_channels() -> None:
    metrics = MagicMock()
    metrics.get = AsyncMock(side_effect=lambda **kw: 3.0)
    text = await build_weekly_report(
        metrics=metrics,
        sources=["finnhub", "caixin_telegram"],
        channels=["tg_us", "feishu_us"],
    )
    assert "caixin_telegram" in text
    assert "tg_us" in text
    assert "feishu_us" in text


@pytest.mark.asyncio
async def test_report_sums_7_days() -> None:
    """Each of 7 days × each source/channel returns 2.0 → total 14."""
    metrics = MagicMock()
    metrics.get = AsyncMock(side_effect=lambda **kw: 2.0)
    text = await build_weekly_report(
        metrics=metrics,
        sources=["src_a"],
        channels=["ch_a"],
    )
    # 7 days × 2.0 = 14
    assert "14" in text


@pytest.mark.asyncio
async def test_report_handles_none_metrics() -> None:
    """Missing metrics (None) should be treated as zero."""
    metrics = MagicMock()
    metrics.get = AsyncMock(return_value=None)
    text = await build_weekly_report(
        metrics=metrics,
        sources=["finnhub"],
        channels=["tg_us"],
    )
    assert "0" in text

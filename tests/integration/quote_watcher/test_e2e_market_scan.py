"""S4 acceptance: fake akshare DataFrame → MarketScanFeed → ranker → builder → mock dispatcher."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.scheduler.jobs import scan_market

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_e2e_market_scan_dispatches_anomalies():
    df = pd.DataFrame([
        {"代码": "688256", "名称": "寒武纪", "最新价": 200.0, "涨跌幅": 9.2,
         "成交量": 50000, "成交额": 1.2e10, "量比": 5.2},
        {"代码": "688981", "名称": "中芯国际", "最新价": 80.0, "涨跌幅": 8.5,
         "成交量": 30000, "成交额": 8e9, "量比": 4.0},
        {"代码": "600519", "名称": "贵州茅台", "最新价": 1700.0, "涨跌幅": -3.2,
         "成交量": 28000, "成交额": 5.04e9, "量比": 2.1},
        {"代码": "300750", "名称": "宁德时代", "最新价": 220.5, "涨跌幅": 0.5,
         "成交量": 50000, "成交额": 1.1e9, "量比": 0.9},
    ])
    with patch("quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em", return_value=df):
        feed = MarketScanFeed()
        cal = MarketCalendar()
        dispatcher = AsyncMock()
        dispatcher.dispatch.return_value = {"feishu_cn": "ok"}
        cfg = MarketScansCfg(
            top_gainers_n=50, top_losers_n=50, top_volume_ratio_n=50,
            push_top_n=5, only_when_score_above=3.0,
        )

        open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
        n = await scan_market(
            feed=feed, calendar=cal, dispatcher=dispatcher,
            channels=["feishu_cn"], cfg=cfg, now=open_dt,
        )

    assert n == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "market_scan"
    # Gainers ≥ 3% threshold: 寒武纪 + 中芯国际
    assert "寒武纪" in msg.summary
    assert "中芯国际" in msg.summary
    # Loser: 贵州茅台 (-3.2)
    assert "贵州茅台" in msg.summary
    # Volume ratio ≥ 3: 寒武纪(5.2), 中芯国际(4.0); 贵州茅台(2.1) excluded
    assert "5.2" in msg.summary or "5.20" in msg.summary


@pytest.mark.asyncio
async def test_e2e_market_scan_no_dispatch_when_no_anomalies():
    df = pd.DataFrame([
        {"代码": "600519", "名称": "贵州茅台", "最新价": 1700.0, "涨跌幅": 0.5,
         "成交量": 28000, "成交额": 5.04e9, "量比": 1.1},
        {"代码": "300750", "名称": "宁德时代", "最新价": 220.5, "涨跌幅": -0.5,
         "成交量": 50000, "成交额": 1.1e9, "量比": 0.9},
    ])
    with patch("quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em", return_value=df):
        feed = MarketScanFeed()
        cal = MarketCalendar()
        dispatcher = AsyncMock()
        cfg = MarketScansCfg(push_top_n=5, only_when_score_above=8.0)

        open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
        n = await scan_market(
            feed=feed, calendar=cal, dispatcher=dispatcher,
            channels=["feishu_cn"], cfg=cfg, now=open_dt,
        )

    assert n == 0
    dispatcher.dispatch.assert_not_called()

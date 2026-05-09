"""MarketScanFeed unit tests with mocked akshare DataFrame."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from quote_watcher.feeds.market_scan import MarketScanFeed


@pytest.fixture
def fake_spot_df() -> pd.DataFrame:
    # akshare stock_zh_a_spot_em column names (subset, real names)
    return pd.DataFrame([
        {
            "代码": "600519", "名称": "贵州茅台",
            "最新价": 1789.5, "涨跌幅": -3.2,
            "成交量": 28230, "成交额": 5.04e9, "量比": 2.1,
        },
        {
            "代码": "300750", "名称": "宁德时代",
            "最新价": 220.5, "涨跌幅": 5.8,
            "成交量": 50000, "成交额": 1.1e9, "量比": 3.5,
        },
        {
            "代码": "688981", "名称": "中芯国际",
            "最新价": 80.0, "涨跌幅": 0.0,
            "成交量": 10000, "成交额": 8e8, "量比": 0.9,
        },
    ])


@pytest.mark.asyncio
async def test_fetch_parses_rows(fake_spot_df: pd.DataFrame):
    with patch("quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em", return_value=fake_spot_df):
        feed = MarketScanFeed()
        rows = await feed.fetch()
    assert len(rows) == 3
    maotai = next(r for r in rows if r.ticker == "600519")
    assert maotai.name == "贵州茅台"
    assert maotai.market == "SH"
    assert maotai.price == 1789.5
    assert maotai.pct_change == -3.2
    assert maotai.volume == 28230
    assert maotai.amount == pytest.approx(5.04e9)
    assert maotai.volume_ratio == 2.1


@pytest.mark.asyncio
async def test_fetch_market_inference():
    df = pd.DataFrame([
        {"代码": "600519", "名称": "X", "最新价": 1, "涨跌幅": 0, "成交量": 0, "成交额": 0, "量比": 1},  # noqa: E501
        {"代码": "300750", "名称": "Y", "最新价": 1, "涨跌幅": 0, "成交量": 0, "成交额": 0, "量比": 1},  # noqa: E501
        {"代码": "688256", "名称": "Z", "最新价": 1, "涨跌幅": 0, "成交量": 0, "成交额": 0, "量比": 1},  # noqa: E501
        {"代码": "002594", "名称": "W", "最新价": 1, "涨跌幅": 0, "成交量": 0, "成交额": 0, "量比": 1},  # noqa: E501
        {"代码": "832735", "名称": "B", "最新价": 1, "涨跌幅": 0, "成交量": 0, "成交额": 0, "量比": 1},  # noqa: E501
    ])
    with patch("quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em", return_value=df):
        feed = MarketScanFeed()
        rows = await feed.fetch()
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["600519"].market == "SH"
    assert by_ticker["688256"].market == "SH"
    assert by_ticker["300750"].market == "SZ"
    assert by_ticker["002594"].market == "SZ"
    assert by_ticker["832735"].market == "BJ"


@pytest.mark.asyncio
async def test_fetch_drops_invalid_rows():
    df = pd.DataFrame([
        {"代码": "600519", "名称": "OK", "最新价": 1.0, "涨跌幅": 0, "成交量": 100, "成交额": 1, "量比": 1},  # noqa: E501
        {"代码": "300001", "名称": "halted", "最新价": float("nan"), "涨跌幅": float("nan"),
         "成交量": 0, "成交额": 0, "量比": float("nan")},
    ])
    with patch("quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em", return_value=df):
        feed = MarketScanFeed()
        rows = await feed.fetch()
    # halted row dropped
    assert len(rows) == 1
    assert rows[0].ticker == "600519"


@pytest.mark.asyncio
async def test_fetch_handles_akshare_error():
    target = "quote_watcher.feeds.market_scan.ak.stock_zh_a_spot_em"
    with patch(target, side_effect=RuntimeError("net")):
        feed = MarketScanFeed()
        rows = await feed.fetch()
    assert rows == []

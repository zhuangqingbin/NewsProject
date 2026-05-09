# tests/unit/quote_watcher/feeds/test_sector.py
from unittest.mock import patch

import pandas as pd
import pytest

from quote_watcher.feeds.sector import SectorFeed


def _fake_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"板块名称": "半导体", "涨跌幅": 3.5, "换手率": 5.2},
        {"板块名称": "新能源", "涨跌幅": -1.8, "换手率": 3.1},
        {"板块名称": "白酒", "涨跌幅": 0.5, "换手率": 1.5},
    ])


@pytest.mark.asyncio
async def test_fetch_pct_changes_normal():
    with patch(
        "quote_watcher.feeds.sector.ak.stock_board_industry_name_em",
        return_value=_fake_df(),
    ):
        feed = SectorFeed()
        out = await feed.fetch_pct_changes()
    assert isinstance(out, dict)
    assert "半导体" in out
    assert out["半导体"].pct_change == 3.5
    assert out["半导体"].turnover_rate == 5.2
    assert out["新能源"].pct_change == -1.8


@pytest.mark.asyncio
async def test_fetch_pct_changes_handles_error():
    with patch(
        "quote_watcher.feeds.sector.ak.stock_board_industry_name_em",
        side_effect=RuntimeError("net"),
    ):
        feed = SectorFeed()
        out = await feed.fetch_pct_changes()
    assert out == {}


@pytest.mark.asyncio
async def test_fetch_pct_changes_drops_invalid_rows():
    df = pd.DataFrame([
        {"板块名称": "OK", "涨跌幅": 1.0, "换手率": 2.0},
        {"板块名称": "", "涨跌幅": 1.0, "换手率": 2.0},  # empty name
        {"板块名称": "NaN占跌幅", "涨跌幅": float("nan"), "换手率": 2.0},
    ])
    with patch("quote_watcher.feeds.sector.ak.stock_board_industry_name_em", return_value=df):
        feed = SectorFeed()
        out = await feed.fetch_pct_changes()
    assert "OK" in out
    assert "" not in out
    assert "NaN占跌幅" not in out


@pytest.mark.asyncio
async def test_fetch_pct_changes_handles_missing_columns():
    """If akshare changes column names, drop rows gracefully."""
    df = pd.DataFrame([
        {"foo": "bar", "baz": 1.0},
    ])
    with patch("quote_watcher.feeds.sector.ak.stock_board_industry_name_em", return_value=df):
        feed = SectorFeed()
        out = await feed.fetch_pct_changes()
    assert out == {}

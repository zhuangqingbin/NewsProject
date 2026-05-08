import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg


def test_minimal_holdings():
    h = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    assert h.holdings[0].ticker == "600519"
    assert h.portfolio.base_currency == "CNY"


def test_duplicate_holding_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        HoldingsFile(holdings=[
            HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
            HoldingEntry(ticker="600519", qty=200, cost_per_share=1900.0),
        ])


def test_negative_qty_rejected():
    with pytest.raises(ValidationError):
        HoldingEntry(ticker="600519", qty=-10, cost_per_share=1850.0)


def test_zero_cost_rejected():
    with pytest.raises(ValidationError):
        HoldingEntry(ticker="600519", qty=100, cost_per_share=0)


def test_portfolio_defaults():
    pf = PortfolioCfg()
    assert pf.total_capital is None
    assert pf.base_currency == "CNY"


def test_empty_holdings_ok():
    f = HoldingsFile()
    assert f.holdings == []

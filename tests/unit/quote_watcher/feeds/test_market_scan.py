"""Direct Eastmoney market scans and the existing row conversion contract."""

import httpx
import pytest
import respx

from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.alerts.scan_ranker import rank_market
from quote_watcher.feeds.market_scan import MarketScanFeed, _row_to_market_row

URL = "https://push2.eastmoney.com/api/qt/clist/get"
MARKET_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"


def em_row(code="600519", *, pct=-3.2, ratio=2.1):
    return {
        "f12": code,
        "f14": "贵州茅台",
        "f2": 1789.5,
        "f3": pct,
        "f5": 28230,
        "f6": 5.04e9,
        "f10": ratio,
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_uses_three_sorted_pages_and_deduplicates_tickers():
    gain = em_row("300750", pct=15.8, ratio=3.5)
    loss = em_row("600519", pct=-9.2, ratio=2.1)
    volume = em_row("688981", pct=2, ratio=9.8)
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": {"total": 5921, "diff": [gain, loss]}}),
            httpx.Response(200, json={"data": {"total": 5921, "diff": [loss]}}),
            httpx.Response(200, json={"data": {"total": 5921, "diff": [volume, gain]}}),
        ]
    )
    rows = await MarketScanFeed().fetch()
    assert len(rows) == 3
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["600519"].name == "贵州茅台"
    assert by_ticker["600519"].price == 1789.5
    assert by_ticker["600519"].volume == 28230
    assert by_ticker["600519"].amount == 5.04e9
    params = [call.request.url.params for call in route.calls]
    assert [(p["fid"], p["po"]) for p in params] == [("f3", "1"), ("f3", "0"), ("f10", "1")]
    for p in params:
        assert p["fs"] == MARKET_FS
        assert p["fields"] == "f12,f14,f2,f3,f5,f6,f10"
        assert p["pn"] == "1"
        assert p["pz"] == "100"
        assert p["np"] == "1"
        assert p["fltt"] == "2"
        assert p["invt"] == "2"
    ranked = rank_market(rows, MarketScansCfg(push_top_n=2, only_when_score_above=3.0))
    assert [row.ticker for row in ranked.top_gainers] == ["300750"]
    assert [row.ticker for row in ranked.top_losers] == ["600519"]
    assert [row.ticker for row in ranked.top_volume_ratio] == ["688981", "300750"]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_handles_missing_ratio_and_suspended_rows():
    valid = em_row(ratio="-")
    halted = {**em_row("300001"), "f2": "-", "f3": "-"}
    respx.get(URL).mock(
        return_value=httpx.Response(200, json={"data": {"total": 2, "diff": [valid, halted]}})
    )
    rows = await MarketScanFeed().fetch()
    assert len(rows) == 1
    assert rows[0].volume_ratio is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_propagates_http_failure():
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await MarketScanFeed().fetch()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {}},
        {"data": {"total": 1, "diff": "bad"}},
        {"data": {"total": "bad", "diff": []}},
        {"data": {"total": 1, "diff": [None]}},
    ],
)
async def test_fetch_rejects_invalid_response_contract(payload):
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await MarketScanFeed().fetch()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_accepts_valid_empty_market():
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json={"data": {"total": 0, "diff": []}})
    )
    assert await MarketScanFeed().fetch() == []
    assert route.call_count == 3


@pytest.mark.parametrize(
    ("code", "market"),
    [("600519", "SH"), ("688256", "SH"), ("300750", "SZ"), ("002594", "SZ"), ("832735", "BJ")],
)
def test_row_converter_market_inference(code, market):
    row = _row_to_market_row(
        {
            "代码": code,
            "名称": "X",
            "最新价": 1,
            "涨跌幅": 0,
            "成交量": 0,
            "成交额": 0,
            "量比": 1,
        }
    )
    assert row is not None
    assert row.market == market


def test_row_converter_preserves_existing_akshare_columns():
    row = _row_to_market_row(
        {
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1789.5,
            "涨跌幅": -3.2,
            "成交量": 28230,
            "成交额": 5.04e9,
            "量比": 2.1,
        }
    )
    assert row is not None
    assert (row.price, row.pct_change, row.volume, row.amount, row.volume_ratio) == (
        1789.5,
        -3.2,
        28230,
        5.04e9,
        2.1,
    )


def test_row_converter_drops_invalid_rows():
    assert _row_to_market_row({"代码": "300001", "最新价": float("nan")}) is None
    assert _row_to_market_row({"代码": "", "最新价": 1, "涨跌幅": 0}) is None

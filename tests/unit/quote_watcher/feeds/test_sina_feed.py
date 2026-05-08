# tests/unit/quote_watcher/feeds/test_sina_feed.py
import httpx
import pytest
import respx

from quote_watcher.feeds.sina import SinaFeed

SAMPLE = (
    'var hq_str_sh600519="贵州茅台,1820.000,1815.500,1789.500,1825.000,'
    '1788.000,1789.500,1789.510,2823100,5043500000.00,'
    '200,1789.500,500,1789.450,300,1789.400,400,1789.350,500,1789.300,'
    '100,1789.510,200,1789.520,300,1789.530,400,1789.540,500,1789.550,'
    '2026-05-08,15:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_builds_url_and_parses():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SAMPLE.encode("gbk"))
    )
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1
    assert snaps[0].ticker == "600519"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_5xx():
    route = respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, content=SAMPLE.encode("gbk")),
        ]
    )
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_empty_tickers_returns_empty():
    feed = SinaFeed()
    snaps = await feed.fetch([])
    assert snaps == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_exhausted_retries_returns_empty():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        side_effect=[httpx.Response(503), httpx.Response(503)]
    )
    feed = SinaFeed(max_retries=1)
    snaps = await feed.fetch([("SH", "600519")])
    assert snaps == []

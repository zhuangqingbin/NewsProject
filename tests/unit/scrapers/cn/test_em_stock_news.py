import json
from datetime import UTC, datetime
from importlib import import_module
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from news_pipeline.scrapers.common.contract import SourceContractError

URL = "https://search-api-web.eastmoney.com/search/jsonp"
SAMPLE = {
    "result": {
        "cmsArticleWebOld": [
            {
                "code": "300308",
                "content": "收购落地",
                "date": "2026-10-04 00:10:49",
                "mediaName": "第一财经",
                "title": "中际旭创17亿入股落地",
                "url": "https://finance.eastmoney.com/a/1.html",
            }
        ]
    }
}


def scraper(tickers=None):
    return import_module("news_pipeline.scrapers.cn.em_stock_news").EmStockNewsScraper(
        tickers=tickers or ["300308"]
    )


async def test_jsonp_request_sorts_by_time_and_parses_beijing_date():
    with respx.mock() as mock:
        route = mock.get(URL).respond(200, text=f"cb({json.dumps(SAMPLE)});")
        items = await scraper().fetch(datetime(2026, 10, 1, tzinfo=UTC))
    request = route.calls[0].request
    params = json.loads(request.url.params["param"])
    assert params["keyword"] == "300308"
    assert params["param"]["cmsArticleWebOld"] == {
        "searchScope": "default",
        "sort": "time",
        "pageIndex": 1,
        "pageSize": 10,
        "preTag": "",
        "postTag": "",
    }
    assert request.url.params["cb"] == "cb"
    assert request.headers["referer"] == "https://so.eastmoney.com/news/s?keyword=300308"
    assert len(items) == 1
    assert items[0].published_at == datetime(2026, 10, 3, 16, 10, 49, tzinfo=UTC)
    assert items[0].raw_meta == {"ticker": "300308", "media": "第一财经"}


async def test_requests_for_tickers_are_spaced(monkeypatch):
    module = import_module("news_pipeline.scrapers.cn.em_stock_news")
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    with respx.mock() as mock:
        route = mock.get(URL).respond(200, text='cb({"result":{"cmsArticleWebOld":[]}})')
        assert (
            await scraper(["300308", "300502", "300394"]).fetch(datetime(2020, 1, 1, tzinfo=UTC))
            == []
        )
    assert route.call_count == 3
    assert sleep.await_count == 2
    assert all(call.args == (0.3,) for call in sleep.await_args_list)


@pytest.mark.parametrize(
    "text",
    [
        "cb({})",
        'cb({"result":{"cmsArticleWebOld":null}})',
        'cb({"result":{"cmsArticleWebOld":[{}]}})',
        "not jsonp",
    ],
)
async def test_missing_path_or_invalid_jsonp_raises(text):
    with respx.mock() as mock:
        mock.get(URL).respond(200, text=text)
        with pytest.raises(SourceContractError):
            await scraper().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_http_error_propagates():
    with respx.mock() as mock:
        mock.get(URL).respond(503)
        with pytest.raises(httpx.HTTPStatusError):
            await scraper().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_since_filter_skips_old_search_results():
    with respx.mock() as mock:
        mock.get(URL).respond(200, text=f"cb({json.dumps(SAMPLE)})")
        assert await scraper().fetch(datetime(2030, 1, 1, tzinfo=UTC)) == []

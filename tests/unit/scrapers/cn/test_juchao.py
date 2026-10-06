from datetime import UTC, datetime
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from freezegun import freeze_time

from news_pipeline.scrapers.cn.juchao import JuchaoScraper
from news_pipeline.scrapers.common.contract import SourceContractError

STOCKS_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
ANN_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STOCKS = {"stockList": [{"code": "300308", "orgId": "9900022016", "zwjc": "中际旭创"}]}
ANN = {
    "announcementId": "1225589955",
    "announcementTitle": "关于完成过户登记的公告",
    "announcementTime": 1790784000000,
    "adjunctUrl": "finalpage/2026-10-01/1225589955.PDF",
    "secCode": "300308",
    "secName": "中际旭创",
    "announcementType": "01010503||010112||010115||011507",
}


@freeze_time("2026-10-06 10:00:00")
async def test_org_id_form_title_metadata_and_no_since_filter():
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=STOCKS)
        route = mock.post(ANN_URL).respond(200, json={"announcements": [ANN]})
        items = await JuchaoScraper(tickers=["300308"]).fetch(datetime(2030, 1, 1, tzinfo=UTC))
    assert parse_qs(route.calls[0].request.content.decode()) == {
        "stock": ["300308,9900022016"],
        "tabName": ["fulltext"],
        "pageSize": ["30"],
        "pageNum": ["1"],
    }
    assert len(items) == 1
    assert items[0].title == "中际旭创\N{FULLWIDTH COLON}关于完成过户登记的公告"
    assert items[0].published_at == items[0].fetched_at
    assert items[0].raw_meta == {
        "ann_id": "1225589955",
        "code": "300308",
        "ann_time_ms": 1790784000000,
        "ann_type": "01010503||010112||010115||011507",
    }


@pytest.mark.parametrize(
    "published,expected",
    [
        ("2026-10-05T16:00:00+00:00", "2026-10-06T10:00:00+00:00"),
        ("2026-10-07T13:00:00+00:00", "2026-10-06T10:00:00+00:00"),
        ("2026-10-05T13:00:00+00:00", "2026-10-05T13:00:00+00:00"),
    ],
)
@freeze_time("2026-10-06 10:00:00")
async def test_coarse_or_future_timestamp_uses_fetch_time(published, expected):
    ann = {**ANN, "announcementTime": int(datetime.fromisoformat(published).timestamp() * 1000)}
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=STOCKS)
        mock.post(ANN_URL).respond(200, json={"announcements": [ann]})
        items = await JuchaoScraper(tickers=["300308"]).fetch(datetime(2030, 1, 1, tzinfo=UTC))
    assert items[0].published_at == datetime.fromisoformat(expected)
    assert items[0].raw_meta["ann_time_ms"] == ann["announcementTime"]


async def test_org_id_table_is_cached_and_refreshed_daily():
    source = JuchaoScraper(tickers=["300308"])
    with respx.mock() as mock:
        table = mock.get(STOCKS_URL).respond(200, json=STOCKS)
        query = mock.post(ANN_URL).respond(200, json={"announcements": []})
        with freeze_time("2026-10-06 10:00:00"):
            await source.initialize()
            await source.fetch(datetime(2020, 1, 1, tzinfo=UTC))
            await source.fetch(datetime(2020, 1, 1, tzinfo=UTC))
            assert table.call_count == 1
        with freeze_time("2026-10-07 10:00:00"):
            await source.fetch(datetime(2020, 1, 1, tzinfo=UTC))
        assert table.call_count == 2
        assert query.call_count == 3


async def test_unknown_configured_ticker_fails_initialization():
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=STOCKS)
        with pytest.raises(ValueError, match=r"juchao.*999999"):
            await JuchaoScraper(tickers=["999999"]).initialize()


@pytest.mark.parametrize("payload", [{}, {"announcements": {}}, {"announcements": [{}]}])
async def test_announcement_schema_errors_propagate(payload):
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=STOCKS)
        mock.post(ANN_URL).respond(200, json=payload)
        with pytest.raises(SourceContractError):
            await JuchaoScraper(tickers=["300308"]).fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_null_announcements_with_zero_total_are_a_valid_empty_result():
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=STOCKS)
        mock.post(ANN_URL).respond(200, json={"announcements": None, "totalAnnouncement": 0})
        assert await JuchaoScraper(tickers=["300308"]).fetch(datetime(2020, 1, 1, tzinfo=UTC)) == []


async def test_stock_table_schema_error_propagates():
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json={})
        with pytest.raises(SourceContractError, match="stockList"):
            await JuchaoScraper(tickers=["300308"]).initialize()


@pytest.mark.parametrize("failure_url", [STOCKS_URL, ANN_URL])
async def test_http_errors_propagate(failure_url):
    with respx.mock(assert_all_called=False) as mock:
        table = mock.get(STOCKS_URL).respond(200, json=STOCKS)
        query = mock.post(ANN_URL).respond(200, json={"announcements": []})
        (table if failure_url == STOCKS_URL else query).respond(503)
        with pytest.raises(httpx.HTTPStatusError):
            await JuchaoScraper(tickers=["300308"]).fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_multiple_ticker_requests_are_spaced(monkeypatch):
    from news_pipeline.scrapers.cn import juchao

    sleep = AsyncMock()
    monkeypatch.setattr(juchao.asyncio, "sleep", sleep)
    stocks = {"stockList": STOCKS["stockList"] + [{"code": "300750", "orgId": "GD165627"}]}
    with respx.mock() as mock:
        mock.get(STOCKS_URL).respond(200, json=stocks)
        query = mock.post(ANN_URL).respond(200, json={"announcements": []})
        await JuchaoScraper(tickers=["300308", "300750"]).fetch(datetime(2020, 1, 1, tzinfo=UTC))
    assert query.call_count == 2
    sleep.assert_awaited_once_with(0.4)

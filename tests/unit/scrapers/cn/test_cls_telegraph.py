import hashlib
from datetime import UTC, datetime
from importlib import import_module
from urllib.parse import urlencode

import httpx
import pytest
import respx
from freezegun import freeze_time

from news_pipeline.scrapers.common.contract import SourceContractError

URL = "https://www.cls.cn/v1/roll/get_roll_list"
SAMPLE = {
    "data": {
        "roll_data": [
            {
                "id": 2498191,
                "ctime": 1791271079,
                "level": "B",
                "title": "",
                "brief": "【英伟达回购】财联社10月6日电",
                "content": "公司宣布回购。",
                "stock_list": [{"stock_code": "NVDA"}],
                "subjects": [{"subject_id": 1501, "subject_name": "期货市场情报"}],
            }
        ]
    }
}


def scraper():
    return import_module("news_pipeline.scrapers.cn.cls_telegraph").ClsTelegraphScraper()


@freeze_time("2026-10-06 10:00:00")
async def test_signed_request_and_article_metadata():
    with respx.mock() as mock:
        route = mock.get(URL).respond(200, json=SAMPLE)
        items = await scraper().fetch(datetime(2026, 10, 1, tzinfo=UTC))
    request = route.calls[0].request
    params = dict(request.url.params)
    sign = params.pop("sign")
    encoded = urlencode(sorted(params.items()))
    assert sign == hashlib.md5(hashlib.sha1(encoded.encode()).hexdigest().encode()).hexdigest()
    assert params == {
        "app": "CailianpressWeb",
        "category": "",
        "last_time": "1791280800",
        "os": "web",
        "refresh_type": "1",
        "rn": "20",
        "sv": "8.4.6",
    }
    assert request.headers["referer"] == "https://www.cls.cn/telegraph"
    assert len(items) == 1
    assert items[0].title == SAMPLE["data"]["roll_data"][0]["brief"]
    assert str(items[0].url) == "https://www.cls.cn/detail/2498191"
    assert items[0].raw_meta == {
        "cls_id": 2498191,
        "level": "B",
        "stocks": ["NVDA"],
        "subjects": ["期货市场情报"],
    }


@pytest.mark.parametrize(
    "payload", [{}, {"data": {"roll_data": None}}, {"data": {"roll_data": [{}]}}]
)
async def test_missing_structure_raises(payload):
    with respx.mock() as mock:
        mock.get(URL).respond(200, json=payload)
        with pytest.raises(SourceContractError):
            await scraper().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_http_error_propagates():
    with respx.mock() as mock:
        mock.get(URL).respond(503)
        with pytest.raises(httpx.HTTPStatusError):
            await scraper().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_since_filter_and_empty_upstream():
    with respx.mock() as mock:
        route = mock.get(URL).respond(200, json=SAMPLE)
        assert await scraper().fetch(datetime(2030, 1, 1, tzinfo=UTC)) == []
        route.respond(200, json={"data": {"roll_data": []}})
        assert await scraper().fetch(datetime(2020, 1, 1, tzinfo=UTC)) == []

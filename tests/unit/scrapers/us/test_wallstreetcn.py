from datetime import UTC, datetime

import httpx
import pytest
import respx

from news_pipeline.scrapers.common.contract import SourceContractError
from news_pipeline.scrapers.us.wallstreetcn import WallStreetCnScraper

SAMPLE = {
    "code": 20000,
    "data": {
        "items": [
            {
                "id": 3174348,
                "title": "国家发改委\N{FULLWIDTH COLON}六张网不只是国家的工程",
                "content_text": "正文。",
                "display_time": 1791271146,
                "score": 1,
                "uri": "https://wallstreetcn.com/livenews/3174348",
                "channels": ["global-channel"],
            },
            {
                "id": 3174349,
                "title": "",
                "content_text": "英伟达公布重大合同",
                "display_time": 1791271147,
                "score": 3,
                "uri": "https://wallstreetcn.com/livenews/3174349",
                "channels": ["global-channel"],
            },
        ]
    },
}


async def fake_fetch(channel, limit):
    return SAMPLE


async def test_fetch_parses_lives_and_title_fallback():
    items = await WallStreetCnScraper(http_callable=fake_fetch).fetch(
        datetime(2026, 10, 1, tzinfo=UTC)
    )
    assert len(items) == 2
    assert items[0].source == "wallstreetcn"
    assert items[1].title == "英伟达公布重大合同"
    assert items[1].body == "英伟达公布重大合同"
    assert items[1].raw_meta == {"wscn_id": 3174349, "score": 3, "channels": ["global-channel"]}


async def test_default_endpoint_and_request_parameters():
    with respx.mock() as mock:
        route = mock.get("https://api-one.wallstcn.com/apiv1/content/lives").respond(
            200, json=SAMPLE
        )
        items = await WallStreetCnScraper().fetch(datetime(2026, 10, 1, tzinfo=UTC))
    assert len(items) == 2
    assert dict(route.calls[0].request.url.params) == {"channel": "global-channel", "limit": "40"}


async def test_since_filter_skips_old():
    assert (
        await WallStreetCnScraper(http_callable=fake_fetch).fetch(datetime(2030, 1, 1, tzinfo=UTC))
        == []
    )


@pytest.mark.parametrize("payload", [{}, {"data": {"items": None}}, {"data": {"items": [{}]}}])
async def test_structure_errors_propagate(payload):
    async def fetch(channel, limit):
        return payload

    with pytest.raises(SourceContractError):
        await WallStreetCnScraper(http_callable=fetch).fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_http_error_propagates():
    async def fetch(channel, limit):
        raise httpx.ConnectError("upstream unavailable")

    with pytest.raises(httpx.ConnectError):
        await WallStreetCnScraper(http_callable=fetch).fetch(datetime(2020, 1, 1, tzinfo=UTC))

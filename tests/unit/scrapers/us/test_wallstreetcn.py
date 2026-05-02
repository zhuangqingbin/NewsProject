from datetime import UTC, datetime

import pytest

from news_pipeline.scrapers.us.wallstreetcn import WallStreetCnScraper


async def _fake_fetch(channel: str, limit: int) -> dict:  # type: ignore[type-arg]
    return {
        "code": 20000,
        "data": {
            "items": [
                {
                    "id": 1,
                    "title": "美股股指创新高",
                    "content_short": "高盛警告动量拥挤。",
                    "display_time": int(datetime(2026, 5, 2, 10, 0, tzinfo=UTC).timestamp()),
                    "uri": "https://wallstreetcn.com/articles/3771483",
                },
                {
                    "id": 2,
                    "title": "",  # missing title → skipped
                    "content_short": "x",
                    "display_time": int(datetime(2026, 5, 2, 10, 1, tzinfo=UTC).timestamp()),
                    "uri": "https://wallstreetcn.com/articles/2",
                },
            ]
        },
    }


@pytest.mark.asyncio
async def test_fetch_parses_payload():
    s = WallStreetCnScraper(http_callable=_fake_fetch)
    items = await s.fetch(datetime(2026, 5, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "wallstreetcn"
    assert items[0].title == "美股股指创新高"


@pytest.mark.asyncio
async def test_since_filter_skips_old():
    s = WallStreetCnScraper(http_callable=_fake_fetch)
    items = await s.fetch(datetime(2026, 5, 3, tzinfo=UTC))
    assert len(items) == 0

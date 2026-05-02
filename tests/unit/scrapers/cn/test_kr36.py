import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from news_pipeline.scrapers.cn.kr36 import Kr36Scraper


def _fake_parse(_url: str) -> SimpleNamespace:
    pp = time.struct_time((2026, 5, 2, 9, 37, 20, 5, 122, 0))
    entry = {
        "title": "周杰伦伙伴 要被卖了",
        "link": "https://36kr.com/p/3791838183234816?f=rss",
        "published_parsed": pp,
        "summary": "<p><img src='x'>正文摘要内容</p>",
    }
    return SimpleNamespace(entries=[entry, {"title": "", "link": "x", "published_parsed": pp}])


@pytest.mark.asyncio
async def test_fetch_parses_feed():
    s = Kr36Scraper(parser=_fake_parse)
    items = await s.fetch(datetime(2026, 5, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "kr36"
    # HTML stripped from summary
    assert items[0].body == "正文摘要内容"


@pytest.mark.asyncio
async def test_since_filter_skips_old():
    s = Kr36Scraper(parser=_fake_parse)
    items = await s.fetch(datetime(2026, 5, 3, tzinfo=UTC))
    assert len(items) == 0

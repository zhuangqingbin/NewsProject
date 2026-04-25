# tests/unit/scrapers/us/test_sec_edgar.py
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>NVIDIA Corp 8-K</title>
    <link href="https://www.sec.gov/Archives/edgar/data/X/x.htm"/>
    <updated>2026-04-25T14:00:00Z</updated>
    <id>tag:sec.gov,2008:filing/x</id>
    <summary>Filing summary</summary>
  </entry>
</feed>"""


@pytest.mark.asyncio
async def test_fetch_parses_atom():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar.*").mock(
            return_value=Response(200, text=ATOM)
        )
        scraper = SecEdgarScraper(ciks=["1045810"])  # NVIDIA
        items = await scraper.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 1
        assert items[0].source == "sec_edgar"
        assert "NVIDIA" in items[0].title

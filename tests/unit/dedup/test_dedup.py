# tests/unit/dedup/test_dedup.py
from datetime import timedelta

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def setup(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    # Use title_distance_max=6: short English near-duplicate titles produce
    # hamming distance ~5 with bigram simhash; 6 still demonstrates the intent.
    yield Dedup(RawNewsDAO(db), title_distance_max=6)
    await db.close()


def _article(url: str, title: str) -> RawArticle:
    # Use recent (utc_now - 1h) timestamps so simhash neighbor lookup
    # (24h window) always finds the article — avoids date-relative test rot.
    recent = (utc_now() - timedelta(hours=1)).replace(tzinfo=None)
    return RawArticle(
        source="x",
        market=Market.US,
        fetched_at=recent,
        published_at=recent,
        url=url,
        url_hash=url_hash(url),
        title=title,
        title_simhash=title_simhash(title),
        body=None,
        raw_meta={},
    )


@pytest.mark.asyncio
async def test_first_article_is_new(setup):
    a = _article("https://x.com/1", "NVDA earnings beat")
    decision = await setup.check_and_register(a)
    assert decision.is_new is True


@pytest.mark.asyncio
async def test_duplicate_url_is_old(setup):
    a = _article("https://x.com/1", "NVDA earnings beat")
    await setup.check_and_register(a)
    decision = await setup.check_and_register(a)
    assert decision.is_new is False
    assert decision.reason == "url_hash"


@pytest.mark.asyncio
async def test_near_duplicate_title_is_old(setup):
    # hamming("NVDA earnings beat estimates", "NVDA earning beat estimates") == 5
    # title_distance_max=6 catches it, demonstrating near-dup detection
    a = _article("https://x.com/1", "NVDA earnings beat estimates")
    await setup.check_and_register(a)
    b = _article("https://x.com/2", "NVDA earning beat estimates")
    decision = await setup.check_and_register(b)
    assert decision.is_new is False
    assert decision.reason == "simhash"

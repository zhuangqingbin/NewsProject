from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from news_pipeline.config.schema import SourceDef
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.scheduler.jobs import scrape_one_source
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from shared.common.timeutil import utc_now
from shared.observability.heartbeat import Heartbeat, heartbeat_healthy
from tests.unit.optimization.test_ingest_health import article


async def test_lookback_catches_late_article_and_seeds_first_success(db):
    raw, state = RawNewsDAO(db), SourceStateDAO(db)
    scraper = MagicMock(source_id="sina_global")
    scraper.fetch = AsyncMock(return_value=[article(1)])
    store = ArticleStore(raw)
    cfg = SourceDef(lookback_min=360, interval_sec=60)
    assert await scrape_one_source(scraper=scraper, store=store, state_dao=state, cfg=cfg) == 1
    assert (await raw.get(1)).status == "seeded"
    scraper.fetch.return_value = [article(1), article(2)]
    assert await scrape_one_source(scraper=scraper, store=store, state_dao=state, cfg=cfg) == 1
    since = scraper.fetch.call_args.args[0]
    assert abs((utc_now() - since).total_seconds() - 360 * 60) < 2
    assert (await raw.get(2)).status == "pending"


async def test_fetch_timeout_records_failure_without_per_attempt_alert(db):
    raw, state = RawNewsDAO(db), SourceStateDAO(db)
    scraper = MagicMock(source_id="test")
    scraper.fetch = AsyncMock(side_effect=TimeoutError("upstream hung"))
    bark = AsyncMock()
    assert (
        await scrape_one_source(
            scraper=scraper,
            store=ArticleStore(raw),
            state_dao=state,
            cfg=SourceDef(interval_sec=60),
            bark=bark,
        )
        == 0
    )
    assert (await state.get("test")).consecutive_failures == 1
    bark.send.assert_not_awaited()


def test_heartbeat_is_atomic_and_expires(tmp_path):
    path = tmp_path / "heartbeat.json"
    heartbeat = Heartbeat(path)
    heartbeat.complete("scrape_sina")
    heartbeat.write()
    assert heartbeat_healthy(path)
    assert not heartbeat_healthy(path, now=utc_now() + timedelta(minutes=4))
    path.write_text("incomplete")
    assert not heartbeat_healthy(path)

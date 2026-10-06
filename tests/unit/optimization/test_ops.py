import asyncio
from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
from sqlalchemy import select, text

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.config.schema import SourceDef, SourcesFile
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import (
    Delivery,
    Event,
    EventArticle,
    LLMCall,
    NewsProcessed,
    PushLog,
    SourceState,
)

NOW = datetime(2026, 10, 6, 10, tzinfo=UTC)


def article(index, age_min=30, title=None, source="wire"):
    title = title or f"新闻 {index}"
    link = f"https://news.example.com/{index}"
    return RawArticle(
        source=source,
        market=Market.CN,
        fetched_at=NOW,
        published_at=NOW - timedelta(minutes=age_min),
        url=link,
        url_hash=url_hash(link),
        title=title,
        title_simhash=title_simhash(title),
    )


class Source:
    market = Market.CN

    def __init__(self, source_id, articles=None, error=None):
        self.source_id, self.articles, self.error = source_id, articles or [], error
        self.since = None

    async def fetch(self, since):
        self.since = since
        if self.error:
            raise self.error
        return self.articles


async def test_smoke_asserts_high_frequency_output_and_never_inserts(db):
    module = import_module("news_pipeline.health.smoke")
    registry = ScraperRegistry()
    for source in [
        Source("wire", [article(1)]),
        Source("empty"),
        Source("daily"),
        Source("broken", error=RuntimeError("secret token must not be printed")),
    ]:
        registry.register(source)
    configs = SourcesFile(
        sources={
            "wire": SourceDef(interval_sec=60, lookback_min=120),
            "empty": SourceDef(interval_sec=300),
            "daily": SourceDef(interval_sec=86400),
            "broken": SourceDef(interval_sec=60),
        }
    )
    results = {
        row["source_id"]: row for row in await module.run_smoke(registry, configs, RawNewsDAO(db))
    }
    assert results["wire"]["ok"] and results["wire"]["count"] == 1
    assert not results["empty"]["ok"] and results["empty"]["error_type"] == "EmptySource"
    assert results["daily"]["ok"]
    assert results["broken"]["error_type"] == "RuntimeError"
    assert "secret" not in str(results)
    assert await RawNewsDAO(db).list_pending() == []


async def test_smoke_timeout_is_reported(monkeypatch):
    module = import_module("news_pipeline.health.smoke")
    registry = ScraperRegistry()
    registry.register(Source("wire"))
    actual_wait_for = asyncio.wait_for

    async def timeout(coro, timeout):
        return await actual_wait_for(coro, timeout=0)

    monkeypatch.setattr(module.asyncio, "wait_for", timeout)
    result = await module.run_smoke(
        registry, SourcesFile(sources={"wire": SourceDef(interval_sec=60)})
    )
    assert result[0]["error_type"] == "TimeoutError" and not result[0]["ok"]


async def test_leak_check_distinguishes_present_legacy_simhash_and_true_misses(db):
    module = import_module("news_pipeline.health.leak_check")
    raw = RawNewsDAO(db)
    await raw.insert_article(article(1))
    await raw.insert_article(article(2, title="同一条重复标题"))
    registry = ScraperRegistry()
    registry.register(
        Source(
            "wire",
            [article(1), article(3, title="同一条重复标题"), article(4), article(5, age_min=5)],
        )
    )
    result = await module.run_leak_check(
        registry, SourcesFile(sources={"wire": SourceDef()}), raw, now=NOW
    )
    assert result[0]["checked"] == 3
    assert result[0]["present"] == 1
    assert result[0]["title_duplicates"] == 1
    assert result[0]["missing"] == 1
    assert result[0]["missing_urls"] == ["https://news.example.com/4"]
    assert len(await raw.list_pending()) == 2


async def test_ops_report_counts_sent_separately_from_shadow_and_compares_legacy(db, tmp_path):
    report_module = import_module("news_pipeline.health.ops_report")
    raw = RawNewsDAO(db)
    for i in (1, 2, 3):
        await raw.insert_article(article(i))
    at = NOW.replace(tzinfo=None)
    async with db.session() as session:
        session.add_all(
            [
                SourceState(source="wire", health="ok"),
                SourceState(source="broken", health="down", health_reason="failing"),
                Event(
                    id=1,
                    first_seen_at=at,
                    last_seen_at=at,
                    headline="双方都推",
                    decision="push",
                    decided_at=at,
                ),
                Event(
                    id=2,
                    first_seen_at=at,
                    last_seen_at=at,
                    headline="新路径独有",
                    decision="push",
                    decided_at=at,
                ),
                Event(
                    id=3,
                    first_seen_at=at,
                    last_seen_at=at,
                    headline="过期内容",
                    decision="digest",
                    decision_reason="stale",
                    decided_at=at,
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                EventArticle(event_id=1, raw_id=1, source="wire", joined_at=at),
                EventArticle(event_id=2, raw_id=2, source="wire", joined_at=at),
                EventArticle(event_id=3, raw_id=3, source="wire", joined_at=at),
                NewsProcessed(
                    id=1,
                    raw_id=1,
                    summary="共同事件",
                    event_type="other",
                    sentiment="neutral",
                    magnitude="low",
                    confidence=0.9,
                    score=80,
                    is_critical=True,
                    model_used="rules",
                    extracted_at=at,
                ),
                NewsProcessed(
                    id=2,
                    raw_id=3,
                    summary="旧路径独有",
                    event_type="other",
                    sentiment="neutral",
                    magnitude="low",
                    confidence=0.9,
                    score=80,
                    is_critical=True,
                    model_used="rules",
                    extracted_at=at,
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                PushLog(news_id=1, channel="cn", sent_at=at, status="sent"),
                PushLog(news_id=2, channel="cn", sent_at=at, status="sent"),
                Delivery(
                    kind="immediate",
                    event_id=1,
                    channel="cn",
                    status="sent",
                    created_at=at,
                    sent_at=at,
                ),
                Delivery(
                    kind="immediate", event_id=2, channel="cn", status="shadow", created_at=at
                ),
                Delivery(
                    kind="digest",
                    channel="cn",
                    status="sent",
                    created_at=at,
                    sent_at=at,
                    event_ids=[1, 3],
                    digest_slot="morning",
                ),
                Delivery(kind="ops", channel="cn", status="failed", created_at=at),
                LLMCall(
                    purpose="assess", model="test", prompt_version="v1", created_at=at, cost_cny=0.2
                ),
                LLMCall(
                    purpose="assess",
                    model="test",
                    prompt_version="v1",
                    created_at=at,
                    cost_cny=0.3,
                    ok=False,
                ),
            ]
        )
        await session.commit()
    report = await report_module.build_ops_report(
        db, db_path=tmp_path / "news.db", mode="shadow", now=NOW
    )
    assert report.title == "系统日报"
    assert report.summary.index("broken") < report.summary.index("wire")
    for expected in [
        "入库 3",
        "候选 3",
        "即时推送 1",
        "影子推送 1",
        "新鲜度 1",
        "简报 1 期 / 2 条",
        "推送失败 1",
        "LLM 2 次",
        "0.50",
        "LLM失败 1",
        "数据库",
        "共同 1",
        "新路径独有 1",
        "旧路径独有 1",
    ]:
        assert expected in report.summary
    assert "旧路径独有" in report.summary
    async with db.session() as session:
        assert len((await session.execute(select(Delivery))).scalars().all()) == 4


async def test_cli_database_connection_is_readonly(db, tmp_path, monkeypatch):
    import pytest
    from sqlalchemy.exc import OperationalError

    module = import_module("news_pipeline.health.smoke")
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(tmp_path / "news.db"))
    readonly = module.readonly_database()
    try:
        async with readonly.session() as session:
            assert (await session.execute(select(SourceState))).all() == []
            with pytest.raises(OperationalError, match="readonly"):
                await session.execute(
                    text(
                        "INSERT INTO source_state(source,health,health_reason,"
                        "consecutive_failures,error_count) VALUES ('forbidden','ok','',0,0)"
                    )
                )
    finally:
        await readonly.close()


async def test_leak_check_propagates_failures_as_safe_result_rows(db):
    module = import_module("news_pipeline.health.leak_check")
    registry = ScraperRegistry()
    registry.register(Source("broken", error=RuntimeError("token=do-not-print")))
    result = await module.run_leak_check(
        registry, SourcesFile(sources={"broken": SourceDef()}), RawNewsDAO(db), now=NOW
    )
    assert result == [{"source_id": "broken", "ok": False, "error_type": "RuntimeError"}]


async def test_legacy_ops_counts_successful_ok_push_log_status(db, tmp_path):
    module = import_module("news_pipeline.health.ops_report")
    raw = RawNewsDAO(db)
    await raw.insert_article(article(10))
    at = NOW.replace(tzinfo=None)
    async with db.session() as session:
        session.add(
            NewsProcessed(
                id=10,
                raw_id=1,
                summary="Old pipeline",
                event_type="other",
                sentiment="neutral",
                magnitude="low",
                confidence=0.9,
                score=80,
                is_critical=True,
                model_used="rules",
                extracted_at=at,
            )
        )
        await session.commit()
        session.add(PushLog(news_id=10, channel="cn", sent_at=at, status="ok"))
        await session.commit()
    report = await module.build_ops_report(db, db_path=tmp_path / "news.db", mode="legacy", now=NOW)
    assert "即时推送 1" in report.summary


@pytest.mark.parametrize(
    ("markets", "expected"),
    [
        (["cn", "cn"], "简报 1 期 / 2 条"),
        (["cn", "cn", "us"], "简报 2 期 / 3 条"),
    ],
)
async def test_ops_digest_counts_displayed_events_once_per_slot_and_market(
    db, tmp_path, markets, expected
):
    module = import_module("news_pipeline.health.ops_report")
    at = NOW.replace(tzinfo=None)
    async with db.session() as session:
        session.add_all(
            Delivery(
                kind="digest",
                market=market,
                channel=f"channel{index}",
                status="sent",
                created_at=at,
                sent_at=at,
                digest_slot="2026-10-06@08:27",
                event_ids=[1, 2] if market == "cn" else [3],
                consumed_event_ids=list(range(1, 61)),
            )
            for index, market in enumerate(markets)
        )
        await session.commit()
    report = await module.build_ops_report(db, db_path=tmp_path / "news.db", mode="v2", now=NOW)
    assert expected in report.summary


async def test_legacy_ops_uses_interception_statuses_and_legacy_digest_audits(db, tmp_path):
    module = import_module("news_pipeline.health.ops_report")
    raw = RawNewsDAO(db)
    for index in range(1, 5):
        await raw.insert_article(article(index))
    at = NOW.replace(tzinfo=None)
    async with db.session() as session:
        session.add_all(
            NewsProcessed(
                id=index,
                raw_id=index,
                summary=f"Legacy item {index}",
                event_type="other",
                sentiment="neutral",
                magnitude="low",
                confidence=0.9,
                score=80,
                is_critical=True,
                model_used="rules",
                extracted_at=at,
                push_status=status,
            )
            for index, status in enumerate(["dup", "burst_digest", "stale_digest", "digest"], 1)
        )
        session.add_all(
            Delivery(
                kind="legacy_digest",
                market="cn",
                channel=channel,
                status="sent",
                created_at=at,
                sent_at=at,
                digest_slot="2026-10-06@08:27",
                event_ids=[2, 3],
                consumed_event_ids=list(range(1, 61)),
            )
            for channel in ["legacy_feishu", "legacy_bark"]
        )
        session.add_all(
            [
                Delivery(
                    kind="legacy_digest",
                    market="cn",
                    channel="legacy_failed_channel",
                    status="legacy_failed",
                    created_at=at,
                    digest_slot="2026-10-06@08:27",
                ),
                Delivery(
                    kind="digest",
                    market="cn",
                    channel="v2_feishu",
                    status="sent",
                    created_at=at,
                    sent_at=at,
                    digest_slot="2026-10-06@08:27",
                    event_ids=[99],
                ),
            ]
        )
        await session.commit()
    report = await module.build_ops_report(db, db_path=tmp_path / "news.db", mode="legacy", now=NOW)
    assert "候选 4" in report.summary
    assert "去重 1 · 突发 1 · 新鲜度 1" in report.summary
    assert "简报 1 期 / 2 条 · 推送失败 1" in report.summary

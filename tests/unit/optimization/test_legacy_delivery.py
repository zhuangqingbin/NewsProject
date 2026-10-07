from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from news_pipeline.events.sent_cache import SentEventCache
from news_pipeline.events.similarity import features
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import Delivery, Event, EventArticle
from shared.common.timeutil import utc_now
from tests.unit.optimization.test_ingest_health import article


async def test_sent_event_cache_survives_restart(db):
    raw = RawNewsDAO(db)
    item = article(1)
    rid = await raw.insert_article(item)
    proc_id = await NewsProcessedDAO(db).insert(
        raw_id=rid,
        summary=item.title,
        event_type="other",
        sentiment="neutral",
        magnitude="low",
        confidence=0,
        score=90,
        is_critical=True,
        key_quotes=[],
        rule_hits=[],
        llm_reason=None,
        model_used="rules-only",
        extracted_at=utc_now(),
    )
    await PushLogDAO(db).write(news_id=proc_id, channel="feishu_us", status="ok")
    from tests.unit.optimization.test_events import engine

    cache = SentEventCache(db, rules=engine())
    await cache.rebuild()
    assert cache.duplicate(
        features("英伟达宣布回购授权增加1500亿美元", ["NVDA"], item.published_at)
    )
    assert not cache.duplicate(features("英伟达目标价上调至200美元", ["NVDA"], item.published_at))


@pytest.mark.parametrize(
    ("kind", "status", "sent_hours_ago", "duplicate"),
    [
        ("immediate", "sent", 0, True),
        ("immediate", "shadow", 0, False),
        ("immediate", "pending", 0, False),
        ("immediate", "failed", 0, False),
        ("immediate", "expired", 0, False),
        ("immediate", "sent", 7, False),
        ("immediate", "sent", None, False),
        ("digest", "sent", 0, False),
    ],
)
async def test_rollback_cache_uses_only_recent_real_immediate_sends(
    db, kind, status, sent_hours_ago, duplicate
):
    from tests.unit.optimization.test_events import engine

    at = utc_now().replace(tzinfo=None)
    item = article("v2-cache")
    raw_id = await RawNewsDAO(db).insert_article(item)
    ev = Event(
        first_seen_at=item.published_at.replace(tzinfo=None),
        last_seen_at=item.published_at.replace(tzinfo=None),
        headline=item.title,
        subject_tickers=["NVDA"],
    )
    async with db.session() as session:
        session.add(ev)
        await session.flush()
        session.add(EventArticle(event_id=ev.id, raw_id=raw_id, source=item.source, joined_at=at))
        session.add(
            Delivery(
                kind=kind,
                event_id=ev.id,
                channel="feishu_us",
                status=status,
                created_at=at - timedelta(hours=8),
                sent_at=None if sent_hours_ago is None else at - timedelta(hours=sent_hours_ago),
            )
        )
        await session.commit()
    cache = SentEventCache(db, rules=engine())
    await cache.rebuild()
    assert cache.duplicate(features(item.title, ["NVDA"], item.published_at)) is duplicate


async def test_burst_suppression_is_enqueued_for_digest():
    from news_pipeline.rules.verdict import RulesVerdict
    from news_pipeline.scheduler.jobs import process_pending
    from tests.unit.scheduler.test_process_pending_rules import _setup_mocks

    mocks = _setup_mocks()
    mocks["rules_engine"].match.return_value = RulesVerdict(
        decision="push", reason="event:回购", subject_tickers=["NVDA"], markets=["us"]
    )
    mocks["burst"].should_send.return_value = False
    mocks["proc_dao"].mark_push_status = AsyncMock()
    await process_pending(**mocks, rules_enabled=True, llm_enabled=False)
    mocks["dispatcher"].dispatch.assert_not_awaited()
    mocks["digest_dao"].enqueue.assert_awaited_once()
    assert mocks["digest_dao"].enqueue.call_args.kwargs["scheduled_digest"] == "us"
    mocks["proc_dao"].mark_push_status.assert_awaited_with(42, "burst_digest")


async def test_stale_push_becomes_digest():
    from news_pipeline.config.schema import PushCfg
    from news_pipeline.rules.verdict import RulesVerdict
    from news_pipeline.scheduler.jobs import process_pending
    from tests.unit.scheduler.test_process_pending_rules import _setup_mocks

    mocks = _setup_mocks()
    mocks["rules_engine"].match.return_value = RulesVerdict(
        decision="push", reason="event:回购", subject_tickers=["NVDA"], markets=["us"]
    )
    mocks["proc_dao"].mark_push_status = AsyncMock()
    await process_pending(**mocks, rules_enabled=True, llm_enabled=False, push_cfg=PushCfg())
    mocks["dispatcher"].dispatch.assert_not_awaited()
    mocks["digest_dao"].enqueue.assert_awaited_once()
    mocks["proc_dao"].mark_push_status.assert_awaited_with(42, "stale_digest")


async def test_digest_failure_does_not_consume():
    from unittest.mock import MagicMock

    from news_pipeline.scheduler.jobs import send_digest
    from shared.push.base import SendResult

    digest = MagicMock()
    digest.list_pending = AsyncMock(return_value=[MagicMock(id=1, news_id=2)])
    digest.mark_consumed = AsyncMock()
    proc = MagicMock()
    proc.get = AsyncMock(return_value=MagicMock())
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value={"cn": SendResult(ok=False)})
    await send_digest(
        digest_key="cn",
        market="cn",
        channels=["cn"],
        digest_dao=digest,
        proc_dao=proc,
        digest_builder=MagicMock(),
        dispatcher=dispatcher,
    )
    digest.mark_consumed.assert_not_awaited()


async def test_same_ticker_announcements_send_one_card():
    from news_pipeline.rules.verdict import RulesVerdict
    from news_pipeline.scheduler.jobs import process_pending
    from tests.unit.scheduler.test_process_pending_rules import _pending_row, _setup_mocks

    mocks = _setup_mocks()
    rows = [_pending_row(n) for n in (1, 2, 3)]
    for n, row in enumerate(rows):
        row.source = "juchao"
        row.market = "cn"
        row.title = f"宁德时代：第{n}份回购公告"  # noqa: RUF001
        row.url = f"https://example.com/{n}"
    mocks["raw_dao"].list_pending.return_value = rows
    mocks["rules_engine"].match.return_value = RulesVerdict(
        decision="push", reason="tier:high", subject_tickers=["300750"], markets=["cn"]
    )
    mocks["proc_dao"].mark_push_status = AsyncMock()
    from unittest.mock import MagicMock

    mocks["router"].route.side_effect = lambda scored, msg, **kw: [
        MagicMock(message=msg, immediate=True, channels=["feishu_cn"])
    ]
    await process_pending(**mocks, rules_enabled=True, llm_enabled=False)
    assert mocks["dispatcher"].dispatch.await_count == 1
    message = mocks["dispatcher"].dispatch.call_args.args[0]
    assert len(message.digest_items) == 3
    assert "3 份公告" in message.title


def test_just_sent_old_announcement_deduplicates(db):
    cache = SentEventCache(db)
    f = features("宁德时代股份回购方案", ["300750"], utc_now() - timedelta(hours=7))
    cache.record(f)
    assert cache.duplicate(f)


async def test_legacy_digest_groups_subject_evidence_and_renders_sections(db):
    from types import SimpleNamespace

    from news_pipeline.config.schema import DigestCfg
    from news_pipeline.scheduler.jobs import run_legacy_digest
    from news_pipeline.storage.dao.deliveries import DeliveryDAO
    from shared.push.base import SendResult
    from shared.push.common.message_builder import MessageBuilder
    from shared.push.feishu import FeishuPusher
    from tests.unit.optimization.test_events import engine

    titles = [
        "英伟达：将股票回购授权规模增加1500亿美元",  # noqa: RUF001
        "英伟达将股票回购授权增加1500亿美元，使回购计划总额达到2350亿美元",  # noqa: RUF001
        "市场宏观与行业动态",
    ]
    raw_rows = {
        n: article(n).model_copy(update={"id": n, "title": title})
        for n, title in enumerate(titles, 1)
    }
    buffers = [SimpleNamespace(id=n, news_id=n) for n in raw_rows]
    procs = {
        n: SimpleNamespace(id=n, raw_id=n, score=90 if n < 3 else 30, push_status="digest")
        for n in raw_rows
    }
    digest_dao = AsyncMock()
    digest_dao.list_pending_market.return_value = buffers
    proc_dao, raw_dao, dispatcher = AsyncMock(), AsyncMock(), AsyncMock()
    proc_dao.get.side_effect = lambda n: procs[n]
    raw_dao.get.side_effect = lambda n: raw_rows[n]
    dispatcher.dispatch.return_value = {"feishu_us": SendResult(ok=True)}
    audit = DeliveryDAO(db)
    count = await run_legacy_digest(
        market="us",
        channels=["feishu_us"],
        digest_dao=digest_dao,
        proc_dao=proc_dao,
        raw_dao=raw_dao,
        msg_builder=MessageBuilder(source_labels={}),
        dispatcher=dispatcher,
        cfg=DigestCfg(),
        rules_engine=engine(),
        deliveries=audit,
        slot="test-slot",
    )
    assert count == 2
    msg = dispatcher.dispatch.call_args.args[0]
    rendered = FeishuPusher(channel_id="test", webhook="https://example.com/")._build_card(msg)
    body = rendered["card"]["elements"][0]["text"]["content"]
    assert "**自选相关**" in body and "**宏观与行业**" in body
    row = await audit.get(1)
    assert row.kind == "legacy_digest" and row.status == "sent"
    assert len(row.event_ids) == 2


async def test_high_hint_macro_digest_stays_in_macro_section():
    from pathlib import Path
    from types import SimpleNamespace

    from news_pipeline.config.schema import DigestCfg
    from news_pipeline.scheduler.jobs import run_legacy_digest
    from news_pipeline.tools.replay import _configuration
    from shared.push.base import SendResult
    from shared.push.common.message_builder import MessageBuilder

    _, _, rules = _configuration(Path("config"))
    raw = article("macro", source="wallstreetcn").model_copy(
        update={"id": 1, "title": "美联储宣布降息", "raw_meta": {"score": 3}}
    )
    verdict = rules.match(raw)
    assert verdict.decision == "digest_lo" and verdict.rank_score == 60
    digest, proc, raw_dao, dispatcher = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    digest.list_pending_market.return_value = [SimpleNamespace(id=1, news_id=1)]
    proc.get.return_value = SimpleNamespace(id=1, raw_id=1, score=60, push_status="digest")
    raw_dao.get.return_value = raw
    dispatcher.dispatch.return_value = {"feishu_us": SendResult(ok=True)}
    await run_legacy_digest(
        market="us",
        channels=["feishu_us"],
        digest_dao=digest,
        proc_dao=proc,
        raw_dao=raw_dao,
        msg_builder=MessageBuilder(source_labels={}),
        dispatcher=dispatcher,
        cfg=DigestCfg(),
        rules_engine=rules,
    )
    assert dispatcher.dispatch.call_args.args[0].digest_items[0].section == "宏观与行业"

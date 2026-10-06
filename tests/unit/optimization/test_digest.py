from datetime import UTC, datetime, timedelta

from news_pipeline.config.schema import DigestCfg
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.models import Delivery, Event, EventArticle, RawNews
from tests.unit.optimization.test_cards import card_size
from tests.unit.optimization.test_outbox import Dispatcher

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


async def make_event(db, number=1, **values):
    defaults = dict(
        first_seen_at=NOW.replace(tzinfo=None),
        last_seen_at=NOW.replace(tzinfo=None),
        headline=f"英伟达回购授权增加{number}",
        markets=["us"],
        subject_tickers=["NVDA"],
        decision="digest",
        assess_status="done",
        materiality=3,
        source_count=2,
    )
    row = Event(**(defaults | values))
    async with db.session() as session:
        session.add(row)
        await session.flush()
        raw = RawNews(
            source="sina_global",
            market="us",
            title=row.headline,
            body="内容",
            url=f"https://example.com/{row.id}",
            url_hash=str(row.id),
            fetched_at=NOW,
            published_at=NOW,
        )
        session.add(raw)
        await session.flush()
        session.add(EventArticle(event_id=row.id, raw_id=raw.id, source=raw.source, joined_at=NOW))
        await session.commit()
    return row


class Assessor:
    def __init__(self, response):
        self.response = response
        self.inputs = []

    async def digest_json(self, system, user):
        self.inputs.append(user)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def test_fallback_selects_sixty_consumes_candidates_and_displays_twenty(db):
    from news_pipeline.deliver.digest import DigestBuilder

    rows = [await make_event(db, n, materiality=5 if n == 0 else 3) for n in range(65)]
    result = await DigestBuilder(EventsDAO(db), DigestCfg()).build("us", "morning", NOW)
    msg, displayed, consumed = result
    assert len(consumed) == 60
    assert len(displayed) == 20
    assert displayed[0] == rows[0].id
    assert len(msg.digest_items) == 20
    assert card_size(msg) <= 19000


async def test_candidates_respect_market_age_consumption_and_pending_reservations(db):
    from news_pipeline.deliver.digest import DigestBuilder
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    eligible = await make_event(db)
    await make_event(db, markets=["cn"])
    await make_event(db, first_seen_at=(NOW - timedelta(hours=25)).replace(tzinfo=None))
    await make_event(db, digest_delivery_id=99)
    reserved = await make_event(db)
    await DeliveryDAO(db).enqueue(
        Delivery(
            kind="digest",
            market="us",
            channel="feishu_us",
            digest_slot="previous",
            consumed_event_ids=[reserved.id],
            payload={},
        )
    )
    _msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg()).build(
        "us", "new", NOW
    )
    assert displayed == consumed == [eligible.id]


async def test_structured_digest_drops_unknown_references_and_unknown_tickers(db):
    from news_pipeline.deliver.digest import DigestBuilder

    first, second = await make_event(db), await make_event(db, 2)
    assessor = Assessor(
        {
            "overview": "概述" * 100,
            "holdings": [
                {"ticker": "UNKNOWN", "lines": [{"text": "未知持仓", "event_ids": [first.id]}]},
                {
                    "ticker": "NVDA",
                    "lines": [
                        {"text": "回购增厚每股价值", "event_ids": [first.id]},
                        {"text": "不应出现", "event_ids": [first.id, 999999]},
                    ],
                },
            ],
            "themes": [
                {"title": "资本回报", "lines": [{"text": "授权提升", "event_ids": [second.id]}]}
            ],
            "macro": [{"text": "编造", "event_ids": [999999]}],
        }
    )
    msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg(), assessor).build(
        "us", "evening", NOW
    )
    rendered = " ".join(item.summary for item in msg.digest_items)
    assert "回购增厚每股价值" in rendered and "授权提升" in rendered
    assert "不应出现" not in rendered and "编造" not in rendered and "未知持仓" not in rendered
    assert len(msg.summary) == 120
    assert set(displayed) == set(consumed) == {first.id, second.id}
    assert str(first.id) in assessor.inputs[0]


async def test_invalid_or_failed_llm_digest_falls_back_to_list(db):
    from news_pipeline.deliver.digest import DigestBuilder

    row = await make_event(db)
    for response in [
        None,
        {},
        {"macro": [{"text": "假新闻", "event_ids": [9999]}]},
        {"holdings": "bad"},
        RuntimeError("network"),
    ]:
        msg, displayed, consumed = await DigestBuilder(
            EventsDAO(db), DigestCfg(), Assessor(response)
        ).build("us", "slot", NOW)
        assert row.headline in msg.digest_items[0].summary
        assert displayed == consumed == [row.id]


async def test_structured_digest_caps_sections_and_line_lengths(db):
    from news_pipeline.deliver.digest import DigestBuilder

    row = await make_event(db)
    line = {"text": "长" * 100, "event_ids": [row.id]}
    assessor = Assessor(
        {
            "holdings": [{"ticker": "NVDA", "lines": [line] * 8}],
            "themes": [{"title": "主题" * 20, "lines": [line] * 8}] * 8,
            "macro": [line] * 8,
        }
    )
    msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg(), assessor).build(
        "us", "slot", NOW
    )
    assert len(msg.digest_items) == 3 + 4 * 3 + 5
    assert all(len(item.source_label) <= 12 for item in msg.digest_items)
    assert all(len(item.summary) <= 50 for item in msg.digest_items)
    assert displayed == consumed == [row.id]


async def test_sent_and_shadow_immediates_are_recalled_since_previous_digest(db):
    from news_pipeline.deliver.digest import DigestBuilder
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    old = await make_event(db, decision="push")
    recent = await make_event(db, 2, decision="push")
    queued = await make_event(db, 3, decision="push")
    dao = DeliveryDAO(db)
    await dao.enqueue(
        Delivery(
            kind="immediate",
            channel="feishu_us",
            market="us",
            event_id=old.id,
            status="sent",
            created_at=(NOW - timedelta(hours=4)).replace(tzinfo=None),
            sent_at=(NOW - timedelta(hours=4)).replace(tzinfo=None),
        )
    )
    await dao.enqueue(
        Delivery(
            kind="digest",
            channel="feishu_us",
            market="us",
            digest_slot="old",
            status="shadow",
            created_at=(NOW - timedelta(hours=2)).replace(tzinfo=None),
        )
    )
    await dao.enqueue(
        Delivery(
            kind="immediate",
            channel="feishu_us",
            market="us",
            event_id=recent.id,
            status="shadow",
            created_at=(NOW - timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    await dao.enqueue(
        Delivery(kind="immediate", channel="feishu_us", market="us", event_id=queued.id)
    )
    msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg()).build(
        "us", "new", NOW
    )
    assert displayed == [recent.id]
    assert consumed == []
    assert "已推送" in msg.digest_items[0].summary


async def test_failed_digest_does_not_consume_and_reserves_until_release(db):
    from news_pipeline.deliver.digest import DigestBuilder
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    row = await make_event(db)
    builder = DigestBuilder(EventsDAO(db), DigestCfg())
    msg, displayed, consumed = await builder.build("us", "first", NOW)
    dao = DeliveryDAO(db)
    delivery_id = await dao.enqueue(
        Delivery(
            kind="digest",
            channel="feishu_us",
            market="us",
            digest_slot="first",
            event_ids=displayed,
            consumed_event_ids=consumed,
            payload=msg.model_dump(mode="json"),
            created_at=NOW.replace(tzinfo=None),
        )
    )
    dispatcher = Dispatcher([False] * 5)
    at = NOW
    for seconds in (0, 10, 30, 120, 600):
        at += timedelta(seconds=seconds)
        await Outbox(dao, dispatcher).run(now=at)
    assert (await EventsDAO(db).get(row.id)).digest_delivery_id is None
    assert await builder.build("us", "second", at) is None
    await dao.release_failed_digest(delivery_id)
    assert await builder.build("us", "second", at) is not None


async def test_byte_trimming_reports_displayed_ids_and_retains_all_consumed_candidates(db):
    from sqlalchemy import update

    from news_pipeline.deliver.digest import DigestBuilder

    for n in range(25):
        ev = await make_event(db, n)
        async with db.session() as session:
            await session.execute(
                update(RawNews)
                .where(RawNews.url_hash == str(ev.id))
                .values(url=f"https://example.com/{ev.id}/" + "x" * 1800)
            )
            await session.commit()
    msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg()).build(
        "us", "slot", NOW
    )
    assert card_size(msg) <= 19000
    assert 0 < len(displayed) < 20
    assert len(consumed) == 25
    assert len(displayed) == len(msg.digest_items)


async def test_structured_digest_cannot_expand_already_pushed_recap(db):
    from news_pipeline.deliver.digest import DigestBuilder
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    recap = await make_event(db, decision="push")
    candidate = await make_event(db, 2)
    await DeliveryDAO(db).enqueue(
        Delivery(
            kind="immediate",
            channel="feishu_us",
            market="us",
            event_id=recap.id,
            status="sent",
            sent_at=(NOW - timedelta(minutes=1)).replace(tzinfo=None),
        )
    )
    assessor = Assessor(
        {
            "macro": [
                {"text": "不能重复展开", "event_ids": [recap.id]},
                {"text": "新的候选", "event_ids": [candidate.id]},
            ]
        }
    )
    msg, displayed, consumed = await DigestBuilder(EventsDAO(db), DigestCfg(), assessor).build(
        "us", "new", NOW
    )
    assert "不能重复展开" not in " ".join(item.summary for item in msg.digest_items)
    assert "已推送回顾" in msg.digest_items[0].summary
    assert set(displayed) == {recap.id, candidate.id}
    assert consumed == [candidate.id]


async def test_candidate_cap_displays_unshown_event_count(db):
    from news_pipeline.deliver.digest import DigestBuilder
    from shared.push.feishu import FeishuPusher

    for n in range(25):
        await make_event(db, n)
    msg, _displayed, _consumed = await DigestBuilder(EventsDAO(db), DigestCfg()).build(
        "us", "slot", NOW
    )
    rendered = FeishuPusher(channel_id="test", webhook="https://example.com/")._build_card(msg)
    assert "另有 5 条未展示" in rendered["card"]["elements"][0]["text"]["content"]


async def test_preselection_prefers_source_count_after_equal_materiality(db):
    from news_pipeline.deliver.digest import DigestBuilder

    narrow = await make_event(db, materiality=4, source_count=1, rank_score=90)
    corroborated = await make_event(db, 2, materiality=4, source_count=10, rank_score=60)
    _, displayed, _ = await DigestBuilder(EventsDAO(db), DigestCfg()).build("us", "slot", NOW)
    assert displayed == [corroborated.id, narrow.id]


async def test_us_digest_title_uses_market_local_date(db):
    from news_pipeline.deliver.digest import DigestBuilder

    await make_event(db)
    # New York 16:27, Shanghai next day 04:27.
    msg, _, _ = await DigestBuilder(EventsDAO(db), DigestCfg()).build(
        "us", "close", NOW.replace(hour=20, minute=27)
    )
    assert "10/06" in msg.title

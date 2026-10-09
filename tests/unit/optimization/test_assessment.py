import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy import select
from sqlmodel import SQLModel

from news_pipeline.assess.assessor import EventAssessor
from news_pipeline.assess.client import ChatClient, ChatRequestError, ChatResult
from news_pipeline.assess.prompts import assessment_messages, digest_system
from news_pipeline.assess.schema import EventAssessment, parse_assessment
from news_pipeline.config.schema import LLMCfg, RulesSection, TickerEntry, WatchlistFile
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Event, EventArticle, LLMCall, RawNews

AT = datetime(2026, 10, 6, 12, tzinfo=UTC)


def output(**overrides):
    return dict(
        event_type="capital_action",
        scope="company",
        holdings=[{"ticker": "NVDA", "relation": "subject", "direction": "positive"}],
        materiality=4,
        novelty="new",
        same_as_event_id=None,
        summary="英伟达增加回购额度",
        so_what="增加股东回报",
        confidence=0.9,
        **overrides,
    )


def config(**overrides):
    return LLMCfg(enabled=True, pricing={"qwen-plus": {"input": 1, "output": 2}}, **overrides)


def watchlist():
    return WatchlistFile(rules=RulesSection(us=[TickerEntry(ticker="NVDA", name="NVIDIA")]))


@pytest.fixture
async def assessment_db():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    async with db.engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    yield db
    await db.close()


async def event(db, n=1, **overrides):
    row = Event(
        id=n,
        first_seen_at=AT.replace(tzinfo=None),
        last_seen_at=AT.replace(tzinfo=None),
        headline="英伟达增加回购额度",
        tagged_tickers=["NVDA"],
        subject_tickers=["NVDA"],
        sources=["wire"],
        markets=["us"],
        rule_decision="push",
        **overrides,
    )
    async with db.session() as session:
        session.add(row)
        await session.commit()
    return row


@pytest.mark.parametrize("value", [0, 6, 4.0, "4", True])
def test_materiality_is_a_strict_integer(value):
    payload = output()
    payload["materiality"] = value
    with pytest.raises(ValidationError):
        EventAssessment.model_validate(payload)


def test_assessment_sanitizes_unknown_tickers_recent_ids_and_text():
    payload = output()
    payload.update(
        holdings=[{"ticker": "WRONG", "relation": "subject", "direction": "positive"}],
        novelty="repeat",
        same_as_event_id=999,
        summary="中文摘要" * 25,
    )
    result = parse_assessment(json.dumps(payload), {"NVDA"}, {7})
    assert result.holdings == []
    assert result.novelty == "new" and result.same_as_event_id is None
    assert len(result.summary) == 60


@respx.mock
async def test_client_reuses_session_and_retries_only_transient_status(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("news_pipeline.assess.client.asyncio.sleep", sleep)
    route = respx.post("https://example.com/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 123, "completion_tokens": 45},
                },
            ),
        ]
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    result = await client.chat_json(model="model", system="system", user="user", max_tokens=40)
    assert (result.content, result.tokens_in, result.tokens_out) == ("{}", 123, 45)
    assert len(result.attempts) == 3
    assert sleep.await_args_list[0].args == (2,)
    assert sleep.await_args_list[1].args == (6,)
    assert route.call_count == 3
    request = json.loads(route.calls[-1].request.content)
    assert request["response_format"] == {"type": "json_object"}
    await client.close()
    assert client._http.is_closed


@respx.mock
async def test_client_does_not_retry_other_4xx():
    route = respx.post("https://example.com/v1/chat/completions").mock(
        return_value=httpx.Response(400)
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    with pytest.raises(ChatRequestError):
        await client.chat_json(model="model", system="system", user="user", max_tokens=40)
    assert route.call_count == 1
    await client.close()


async def test_assessor_persists_validation_failure_and_success_tokens(assessment_db):
    await event(assessment_db)
    client = AsyncMock()
    client.chat_json.side_effect = [
        ChatResult("not json", 100, 20, 12),
        ChatResult(json.dumps(output()), 120, 30, 14),
    ]
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    assert await assessor.run() == 1
    saved = await assessor.events.get(1)
    assert saved.assess_status == "done" and saved.materiality == 4
    assert saved.assess_attempts == 2
    async with assessment_db.session() as session:
        calls = (await session.execute(select(LLMCall).order_by(LLMCall.id))).scalars().all()
    assert [call.ok for call in calls] == [False, True]
    assert [call.tokens_in for call in calls] == [100, 120]
    assert sum(call.cost_cny for call in calls) == pytest.approx(0.00032)
    assert "validation" in client.chat_json.await_args_list[1].kwargs["user"].lower()


async def test_disabled_assessor_skips_without_calls(assessment_db):
    await event(assessment_db)
    client = AsyncMock()
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, LLMCfg(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    assert (await assessor.events.get(1)).assess_status == "skipped"
    client.chat_json.assert_not_awaited()


async def test_assessor_skips_unimportant_untagged_candidates(assessment_db):
    row = await event(assessment_db)
    await EventsDAO(assessment_db).update(row.id, tagged_tickers=[], subject_tickers=[])
    client = AsyncMock()
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    client.chat_json.assert_not_awaited()
    assert (await assessor.events.get(1)).assess_status == "skipped"


async def test_budget_is_persisted_across_assessor_instances(assessment_db):
    await event(assessment_db)
    async with assessment_db.session() as session:
        session.add(
            LLMCall(
                purpose="assess",
                model="qwen-plus",
                prompt_version="assess_v1",
                cost_cny=5,
                created_at=AT.replace(tzinfo=None),
            )
        )
        await session.commit()
    client, bark = AsyncMock(), AsyncMock()
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), bark, clock=lambda: AT
    )
    await assessor.run()
    await assessor.digest_json("system", "user")
    client.chat_json.assert_not_awaited()
    assert bark.send.await_count == 1
    assert (await assessor.events.get(1)).assess_status == "failed"


async def test_budget_uses_shanghai_calendar_day(assessment_db):
    await event(assessment_db)
    async with assessment_db.session() as session:
        session.add(
            LLMCall(
                purpose="assess",
                model="qwen-plus",
                prompt_version="assess_v1",
                cost_cny=5,
                created_at=datetime(2026, 10, 5, 15, 59),
            )
        )
        await session.commit()
    client = AsyncMock()
    client.chat_json.return_value = ChatResult(json.dumps(output()), 100, 20, 5)
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    assert client.chat_json.await_count == 1


async def test_budget_reservations_prevent_concurrent_overspend(assessment_db):
    await event(assessment_db, 1)
    await event(assessment_db, 2)
    client = AsyncMock()
    gate = asyncio.Event()

    async def call(**kwargs):
        await gate.wait()
        return ChatResult(json.dumps(output()), 100, 20, 5)

    client.chat_json.side_effect = call
    assessor = EventAssessor(
        EventsDAO(assessment_db),
        client,
        config(daily_cost_ceiling_cny=0.005),
        watchlist(),
        clock=lambda: AT,
    )
    task = asyncio.create_task(assessor.run())
    for _ in range(50):
        await asyncio.sleep(0.005)
        if client.chat_json.await_count:
            break
    assert client.chat_json.await_count == 1
    gate.set()
    await task
    assert client.chat_json.await_count == 1


async def test_concurrency_is_limited_to_four(assessment_db):
    for n in range(1, 9):
        await event(assessment_db, n)
    active, maximum = 0, 0
    client = AsyncMock()
    four_active = asyncio.Event()
    release = asyncio.Event()

    async def call(**kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 4:
            four_active.set()
        await release.wait()
        active -= 1
        return ChatResult(json.dumps(output()), 100, 20, 5)

    client.chat_json.side_effect = call
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    task = asyncio.create_task(assessor.run())
    try:
        await asyncio.wait_for(four_active.wait(), timeout=5)
        assert active == 4
        assert client.chat_json.await_count == 4
    finally:
        release.set()
        await task
    assert maximum == 4
    assert client.chat_json.await_count == 8


async def test_circuit_opens_after_ten_failures_then_recovers(assessment_db):
    client, bark = AsyncMock(), AsyncMock()
    client.chat_json.side_effect = RuntimeError("offline")
    now = [AT]
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), bark, clock=lambda: now[0]
    )
    for _ in range(10):
        assert await assessor.digest_json("system", "user") is None
    assert client.chat_json.await_count == 10
    assert await assessor.digest_json("system", "user") is None
    assert client.chat_json.await_count == 10
    assert bark.send.await_count == 1
    now[0] += timedelta(minutes=10)
    client.chat_json.side_effect = None
    client.chat_json.return_value = ChatResult("{}", 10, 2, 3)
    assert await assessor.digest_json("system", "user") == {}
    assert bark.send.await_count == 2


async def test_arriving_evidence_is_not_overwritten_by_stale_assessment(assessment_db):
    await event(assessment_db)
    client = AsyncMock()

    async def call(**kwargs):
        await EventsDAO(assessment_db).update(1, article_count=2, rule_decision="push")
        return ChatResult(json.dumps(output()), 100, 20, 5)

    client.chat_json.side_effect = call
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    saved = await assessor.events.get(1)
    assert saved.assess_status == "pending"
    assert saved.materiality is None


async def test_prompt_limits_body_and_recent_events_to_grounded_evidence(assessment_db):
    current = await event(assessment_db)
    for n in range(2, 12):
        await event(assessment_db, n)
    await EventsDAO(assessment_db).update(2, decision="drop")
    body = "A" * 1100 + "M" * 500 + "Z" * 600
    raw = RawNews(
        id=1,
        source="wire",
        market="us",
        url="https://example.com",
        url_hash="hash",
        title="英伟达增加回购额度",
        body=body,
        fetched_at=AT,
        published_at=AT,
    )
    async with assessment_db.session() as session:
        session.add(raw)
        await session.flush()
        session.add(EventArticle(event_id=1, raw_id=1, source="wire", joined_at=AT))
        await session.commit()
    system, user, recent = await assessment_messages(
        EventsDAO(assessment_db), current, watchlist(), AT
    )
    assert len(recent) == 8 and 1 not in recent and 2 not in recent
    assert "A" * 1000 in user and "Z" * 500 in user
    assert "M" * 500 not in user
    assert "NVDA | NVIDIA" in system
    assert "指令" in system
    assert "event_ids" in digest_system(watchlist())


@respx.mock
async def test_client_retries_timeouts_twice_and_preserves_attempts(monkeypatch):
    monkeypatch.setattr("news_pipeline.assess.client.asyncio.sleep", AsyncMock())
    route = respx.post("https://example.com/v1/chat/completions").mock(
        side_effect=[
            httpx.ReadTimeout("timeout"),
            httpx.ReadTimeout("timeout"),
            httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
        ]
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    result = await client.chat_json(model="model", system="system", user="user", max_tokens=40)
    assert route.call_count == 3
    assert [attempt.error for attempt in result.attempts] == ["ReadTimeout", "ReadTimeout", None]
    await client.close()


@respx.mock
async def test_each_http_invocation_is_persisted_even_internal_retries(assessment_db, monkeypatch):
    await event(assessment_db)
    monkeypatch.setattr("news_pipeline.assess.client.asyncio.sleep", AsyncMock())

    def response(content):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    route = respx.post("https://example.com/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            response("not JSON"),
            response(json.dumps(output())),
        ]
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    async with assessment_db.session() as session:
        calls = (await session.execute(select(LLMCall).order_by(LLMCall.id))).scalars().all()
    assert route.call_count == 4
    assert [call.ok for call in calls] == [False, False, False, True]
    assert [call.tokens_in for call in calls] == [0, 0, 100, 100]
    await client.close()


async def test_second_invalid_output_marks_event_failed_and_preserves_rule_fallback(assessment_db):
    await event(assessment_db)
    client = AsyncMock()
    client.chat_json.return_value = ChatResult("[]", 100, 20, 10)
    assessor = EventAssessor(
        EventsDAO(assessment_db), client, config(), watchlist(), clock=lambda: AT
    )
    await assessor.run()
    row = await assessor.events.get(1)
    assert row.assess_status == "failed" and row.rule_decision == "push"
    assert client.chat_json.await_count == 2


async def test_budget_notice_is_once_per_day_across_restarts(assessment_db):
    async with assessment_db.session() as session:
        session.add(
            LLMCall(
                purpose="digest",
                model="qwen-plus",
                prompt_version="digest_v1",
                cost_cny=5,
                created_at=AT.replace(tzinfo=None),
            )
        )
        await session.commit()
    bark = AsyncMock()
    for _ in range(2):
        assessor = EventAssessor(
            EventsDAO(assessment_db), AsyncMock(), config(), watchlist(), bark, clock=lambda: AT
        )
        assert await assessor.digest_json("system", "user") is None
    assert bark.send.await_count == 1


def test_valid_recent_repeat_id_and_known_tickers_are_kept():
    payload = output()
    payload.update(novelty="repeat", same_as_event_id=7)
    result = parse_assessment(json.dumps(payload), {"NVDA"}, {7})
    assert result.novelty == "repeat" and result.same_as_event_id == 7
    assert result.holdings[0].ticker == "NVDA"


async def test_recent_prompt_excludes_future_and_expired_evidence(assessment_db):
    current = await event(assessment_db)
    await event(assessment_db, 2)
    await event(assessment_db, 3)
    await EventsDAO(assessment_db).update(
        2, last_seen_at=(AT + timedelta(hours=1)).replace(tzinfo=None)
    )
    await EventsDAO(assessment_db).update(
        3, last_seen_at=(AT - timedelta(hours=25)).replace(tzinfo=None)
    )
    _, _, recent = await assessment_messages(EventsDAO(assessment_db), current, watchlist(), AT)
    assert recent == set()


async def test_prompt_history_uses_replay_clock_not_wall_clock(assessment_db, monkeypatch):
    current = await event(assessment_db)
    await event(assessment_db, 2)
    monkeypatch.setattr("news_pipeline.storage.dao.events.utc_now", lambda: AT + timedelta(days=30))
    _, _, recent = await assessment_messages(EventsDAO(assessment_db), current, watchlist(), AT)
    assert recent == {2}

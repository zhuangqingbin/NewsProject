"""Digest selection, grounded model-output validation, and list fallback."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlmodel import col, select

from news_pipeline.config.schema import DigestCfg
from news_pipeline.deliver.cards import primary_article, trim_message
from news_pipeline.storage.dao.deliveries import naive_utc
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.models import Delivery, Event, RawNews
from shared.common.contracts import Badge, CommonMessage, DigestItem
from shared.common.enums import Market
from shared.common.timeutil import utc_now
from shared.observability.log import get_logger

log = get_logger(__name__)
_SYSTEM = """你是投资新闻简报编辑。只使用输入事件的事实,每一行必须引用输入中的 event_ids。
返回 JSON\uff1aoverview 不超过120字;holdings=[{ticker,lines:[{text,event_ids}]}],每只票最多3行;
themes=[{title,lines:[{text,event_ids}]}],最多4主题,每主题3行,标题12字;
macro=[{text,event_ids}],最多5行。行文50字以内。同主题多事件合为一行。
已推送事件只作开头回顾,不重复展开。不得编造标的、事件编号或输入以外的事实。"""


class DigestAssessor(Protocol):
    async def digest_json(self, system: str, user: str) -> dict[str, Any] | None: ...


@dataclass
class _Item:
    item: DigestItem
    event_ids: list[int]


def _rank(event: Event) -> tuple[float, int, int, datetime, int]:
    materiality = event.materiality or {"push": 4, "digest_hi": 3, "digest_lo": 2}.get(
        event.rule_decision, 1
    )
    return (
        materiality,
        event.source_count,
        event.importance_hint,
        naive_utc(event.first_seen_at),
        event.id or 0,
    )


class DigestBuilder:
    def __init__(
        self,
        events_dao: EventsDAO,
        cfg: DigestCfg,
        assessor: DigestAssessor | None = None,
    ) -> None:
        self.events = events_dao
        self.cfg = cfg
        self.assessor = assessor

    async def _select(self, market: str, now: datetime) -> tuple[list[Event], set[int]]:
        at = naive_utc(now)
        cutoff = at - timedelta(hours=min(24, self.cfg.max_age_hours))
        async with self.events.db.session() as session:
            deliveries = list(
                (
                    await session.execute(select(Delivery).where(col(Delivery.market) == market))
                ).scalars()
            )
            reserved = {
                event_id
                for delivery in deliveries
                if delivery.kind == "digest" and delivery.status in {"pending", "failed"}
                for event_id in delivery.consumed_event_ids
            }
            digests: dict[str, list[Delivery]] = {}
            for delivery in deliveries:
                if delivery.kind == "digest" and delivery.digest_slot:
                    digests.setdefault(delivery.digest_slot, []).append(delivery)
            previous = max(
                (
                    naive_utc(row.sent_at or row.created_at)
                    for rows in digests.values()
                    if all(row.status in {"sent", "shadow"} for row in rows)
                    for row in rows
                ),
                default=cutoff,
            )
            candidates = list(
                (
                    await session.execute(
                        select(Event).where(
                            col(Event.decision) == "digest",
                            col(Event.digest_delivery_id).is_(None),
                            col(Event.first_seen_at) >= cutoff,
                            col(Event.first_seen_at) <= at,
                        )
                    )
                ).scalars()
            )
            by_id = {
                event.id: event
                for event in candidates
                if event.id is not None and market in event.markets and event.id not in reserved
            }
            recap_ids: set[int] = set()
            for delivery in deliveries:
                if delivery.kind != "immediate" or delivery.status not in {"sent", "shadow"}:
                    continue
                delivered_at = naive_utc(delivery.sent_at or delivery.created_at)
                if delivery.event_id is None or not previous < delivered_at <= at:
                    continue
                event = await session.get(Event, delivery.event_id)
                if event is not None and market in event.markets:
                    by_id[delivery.event_id] = event
                    recap_ids.add(delivery.event_id)
            chosen = sorted(by_id.values(), key=_rank, reverse=True)[:60]
            return chosen, recap_ids

    async def build(
        self,
        market: str,
        slot: str,
        now: datetime | None = None,
    ) -> tuple[CommonMessage, list[int], list[int]] | None:
        at = now or utc_now()
        candidates, recap_ids = await self._select(market, at)
        if not candidates:
            return None
        events = {ev.id: ev for ev in candidates if ev.id is not None}
        origins: dict[int, RawNews] = {}
        for event_id in events:
            articles = await self.events.articles(event_id)
            if articles:
                origins[event_id] = primary_article(articles)
        events = {event_id: event for event_id, event in events.items() if event_id in origins}
        if not events:
            return None
        recap_ids &= set(events)
        consumed = [event_id for event_id in events if event_id not in recap_ids]
        recap = [
            _Item(
                DigestItem(
                    source_label="原文",
                    url=origins[event_id].url,
                    summary="**已推送回顾** · " + (ev.summary or ev.headline)[:60],
                ),
                [event_id],
            )
            for event_id, ev in events.items()
            if event_id in recap_ids
        ][:5]
        items: list[_Item] = []
        overview = ""
        if self.assessor is not None and consumed:
            user = "\n".join(
                f"{event_id} | {ev.first_seen_at:%H:%M} | {','.join(ev.subject_tickers)} | "
                f"实质性={ev.materiality or ev.rule_decision} | 来源={ev.source_count} | "
                f"{'已推送' if event_id in recap_ids else '候选'} | "
                f"{(ev.summary or ev.headline)[:60]}"
                for event_id, ev in events.items()
            )
            try:
                response = await self.assessor.digest_json(_SYSTEM, user)
                if isinstance(response, dict):
                    items = self._structured(
                        response,
                        {
                            event_id: ev
                            for event_id, ev in events.items()
                            if event_id not in recap_ids
                        },
                        origins,
                    )
                    if items:
                        overview_raw = response.get("overview", "")
                        overview = overview_raw[:120] if isinstance(overview_raw, str) else ""
            except Exception as exc:
                log.warning("digest_llm_failed", error=repr(exc))
        if not items:
            items = self._fallback(events, origins, recap_ids)
        items = [*recap, *items][: min(20, self.cfg.max_items)]
        if not items:
            return None
        if overview:
            items[0].item.summary = f"概览\uff1a{overview}\n\n" + items[0].item.summary
        origin = origins[items[0].event_ids[0]]
        local = at.replace(tzinfo=ZoneInfo("UTC")) if at.tzinfo is None else at
        title_market = "A股" if market == "cn" else "美股"
        timezone = "America/New_York" if market == "us" else "Asia/Shanghai"
        local_date = local.astimezone(ZoneInfo(timezone)).strftime("%m/%d")
        message = CommonMessage(
            title=f"{title_market}简报 · {local_date} {slot}",
            summary=overview,
            source_label="事件简报",
            source_url=origin.url,
            badges=[Badge(text="简报", color="blue")],
            chart_url=None,
            deeplinks=[],
            market=Market(market),
            kind="digest",
            digest_items=[item.item for item in items],
        )
        while True:
            trimmed = trim_message(message)
            displayed = list(
                dict.fromkeys(
                    event_id
                    for item in items[: len(trimmed.digest_items)]
                    for event_id in item.event_ids
                )
            )
            omitted = len(set(consumed) - set(displayed))
            if trimmed.omitted_count == omitted:
                break
            message = trimmed.model_copy(update={"omitted_count": omitted})
        return trimmed, displayed, consumed

    @staticmethod
    def _fallback(
        events: dict[int, Event],
        origins: dict[int, RawNews],
        recap_ids: set[int],
    ) -> list[_Item]:
        output: list[_Item] = []
        for label, high in (("重点关注", True), ("其他动态", False)):
            section = [
                event_id
                for event_id, ev in events.items()
                if event_id not in recap_ids
                and ((ev.materiality or 0) >= 3 or ev.rule_decision in {"push", "digest_hi"})
                == high
            ]
            for index, event_id in enumerate(section):
                event = events[event_id]
                heading = f"**{label}**\n" if index == 0 else ""
                output.append(
                    _Item(
                        DigestItem(
                            source_label="原文",
                            url=origins[event_id].url,
                            summary=heading + (event.summary or event.headline)[:60],
                        ),
                        [event_id],
                    )
                )
        return output

    @staticmethod
    def _structured(
        payload: dict[str, Any],
        events: dict[int, Event],
        origins: dict[int, RawNews],
    ) -> list[_Item]:
        output: list[_Item] = []
        tickers = {
            ticker
            for event in events.values()
            for ticker in [
                *event.subject_tickers,
                *event.tagged_tickers,
                *(holding.get("ticker", "") for holding in event.holdings or []),
            ]
            if ticker
        }

        def lines(values: Any, label: str, maximum: int) -> None:
            if not isinstance(values, list):
                return
            accepted = 0
            for value in values:
                if not isinstance(value, dict):
                    continue
                refs, content = value.get("event_ids"), value.get("text")
                if (
                    not isinstance(refs, list)
                    or not refs
                    or not isinstance(content, str)
                    or not content.strip()
                    or any(type(ref) is not int or ref not in events for ref in refs)
                ):
                    continue
                refs = list(dict.fromkeys(refs))
                output.append(
                    _Item(
                        DigestItem(
                            source_label=label[:12],
                            url=origins[refs[0]].url,
                            summary=content.strip()[:50],
                        ),
                        refs,
                    )
                )
                accepted += 1
                if accepted >= maximum:
                    break

        holdings = payload.get("holdings", [])
        if isinstance(holdings, list):
            used_tickers: set[str] = set()
            for holding in holdings:
                if not isinstance(holding, dict):
                    continue
                ticker = holding.get("ticker")
                if isinstance(ticker, str) and ticker in tickers and ticker not in used_tickers:
                    lines(holding.get("lines"), ticker, 3)
                    used_tickers.add(ticker)
        themes = payload.get("themes", [])
        if isinstance(themes, list):
            for theme in themes[:4]:
                if isinstance(theme, dict) and isinstance(theme.get("title"), str):
                    lines(theme.get("lines"), theme["title"], 3)
        lines(payload.get("macro"), "宏观与政策", 5)
        return output

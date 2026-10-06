from sqlalchemy import text

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.events.similarity import Features, features, same_event, within_event_window
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.headline import headline
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import Event, EventArticle, RawNews
from shared.common.timeutil import ensure_utc, utc_now

STRENGTH = {"drop": 0, "digest_lo": 1, "digest_hi": 2, "push": 3}


class EventClusterer:
    def __init__(
        self,
        events: EventsDAO,
        raw: RawNewsDAO,
        rules: RulesEngine,
        *,
        merge_window_min: int = 10,
        merge_max_items: int = 5,
    ) -> None:
        self._merge_window_min = merge_window_min
        self._merge_max_items = merge_max_items
        self._events = events
        self._raw = raw
        self._rules = rules
        self._index: dict[int, tuple[Event, list[Features]]] = {}
        self._initialized = False

    async def rebuild(self) -> None:
        self._index.clear()
        for event in await self._events.list_recent():
            if event.id is None or event.decision_reason == "repeat":
                continue
            articles = await self._events.articles(event.id)
            samples = articles[:2] + articles[-6:]
            self._index[event.id] = (
                event,
                [
                    features(
                        headline(a.title, a.body), event.subject_tickers, ensure_utc(a.published_at)
                    )
                    for a in samples
                ],
            )
        self._initialized = True

    async def process(self, limit: int = 200) -> int:
        if not self._initialized:
            await self.rebuild()
        elif self._index.keys() & await self._events.recent_repeat_ids():
            # Assessment may reparent articles between clustering runs.
            await self.rebuild()
        now = utc_now()
        self._index = {
            key: value
            for key, value in self._index.items()
            if (now - ensure_utc(value[0].last_seen_at)).total_seconds() <= 21600
            and (now - ensure_utc(value[0].first_seen_at)).total_seconds() <= 43200
        }
        count = 0
        for row in await self._raw.list_v2_pending(limit):
            if row.id is None:
                continue
            article = RawArticle(
                source=row.source,
                market=Market(row.market),
                url=row.url,
                url_hash=row.url_hash,
                title=row.title,
                body=row.body,
                raw_meta=row.raw_meta or {},
                published_at=ensure_utc(row.published_at),
                fetched_at=ensure_utc(row.fetched_at),
                title_simhash=row.title_simhash,
            )
            verdict = self._rules.match(article)
            f = features(
                headline(row.title, row.body), verdict.subject_tickers, article.published_at
            )
            target_id = (
                next(
                    (
                        eid
                        for eid, (event, fs) in self._index.items()
                        if within_event_window(
                            article.published_at,
                            ensure_utc(event.first_seen_at),
                            ensure_utc(event.last_seen_at),
                        )
                        and (
                            any(same_event(f, old) for old in fs)
                            or (
                                row.source == "juchao"
                                and verdict.reason == "tier:high"
                                and event.rule_reason == "tier:high"
                                and "juchao" in event.sources
                                and event.subject_tickers == verdict.subject_tickers
                                and event.article_count < self._merge_max_items
                                and abs(
                                    (
                                        article.published_at - ensure_utc(event.first_seen_at)
                                    ).total_seconds()
                                )
                                <= self._merge_window_min * 60
                            )
                        )
                    ),
                    None,
                )
                if verdict.matched
                else None
            )
            async with self._events.db.session() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                stored_raw = await session.get(RawNews, row.id)
                if stored_raw is None or stored_raw.v2_state is not None:
                    continue
                if not verdict.matched:
                    stored_raw.v2_state = (
                        "skipped_low" if verdict.reason == "tier:low" else "skipped_rules"
                    )
                    await session.commit()
                    count += 1
                    continue
                event = await session.get(Event, target_id) if target_id else None
                first_party = row.source in {"juchao", "sec_edgar"}
                at = ensure_utc(row.published_at).replace(tzinfo=None)
                if event is None or event.decision_reason == "repeat":
                    event = Event(
                        first_seen_at=at,
                        last_seen_at=at,
                        headline=headline(row.title, row.body),
                        norm_headline=f.norm,
                        key_numbers=sorted(f.numbers),
                        subject_tickers=verdict.subject_tickers,
                        tagged_tickers=verdict.tagged_tickers,
                        markets=verdict.markets,
                        sources=[row.source],
                        first_party=first_party,
                        importance_hint=verdict.importance_hint,
                        rule_decision=verdict.decision,
                        rule_reason=verdict.reason,
                        rank_score=verdict.rank_score,
                        assess_status="pending"
                        if (verdict.tagged_tickers or first_party or verdict.importance_hint >= 2)
                        else "skipped",
                    )
                    session.add(event)
                    await session.flush()
                else:
                    event.first_seen_at = min(event.first_seen_at, at)
                    event.last_seen_at = max(event.last_seen_at, at)
                    event.article_count += 1
                    event.sources = sorted(set(event.sources) | {row.source})
                    event.source_count = len(event.sources)
                    event.tagged_tickers = sorted(
                        set(event.tagged_tickers) | set(verdict.tagged_tickers)
                    )
                    event.subject_tickers = sorted(
                        set(event.subject_tickers) | set(verdict.subject_tickers)
                    )
                    event.markets = sorted(set(event.markets) | set(verdict.markets))
                    event.importance_hint = max(event.importance_hint, verdict.importance_hint)
                    event.rank_score = max(event.rank_score, verdict.rank_score)
                    if first_party and not event.first_party:
                        event.headline = headline(row.title, row.body)
                        event.norm_headline = f.norm
                        event.key_numbers = sorted(f.numbers)
                    event.first_party |= first_party
                    if first_party and verdict.reason == "tier:high":
                        event.rule_reason = verdict.reason
                    if STRENGTH[verdict.decision] > STRENGTH[event.rule_decision]:
                        event.rule_decision, event.rule_reason = verdict.decision, verdict.reason
                    if event.decision != "push":
                        event.decision = None
                        event.assess_status = (
                            "pending"
                            if (
                                event.tagged_tickers
                                or event.first_party
                                or event.importance_hint >= 2
                            )
                            else "skipped"
                        )
                assert event.id is not None
                session.add(
                    EventArticle(
                        event_id=event.id,
                        raw_id=row.id,
                        source=row.source,
                        joined_at=now.replace(tzinfo=None),
                    )
                )
                stored_raw.v2_state = "clustered"
                await session.commit()
                prior = self._index.get(event.id)
                fs = (prior[1] + [f]) if prior else [f]
                self._index[event.id] = (event, fs[:2] + fs[-6:] if len(fs) > 8 else fs)
            count += 1
        return count

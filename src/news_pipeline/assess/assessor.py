import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlmodel import col

from news_pipeline.assess.client import ChatAttempt, ChatResult
from news_pipeline.assess.prompts import assessment_messages, utc_aware
from news_pipeline.assess.schema import parse_assessment
from news_pipeline.config.schema import AppConfig, LLMCfg, LLMTaskCfg, WatchlistFile
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.models import DailyMetric, Event, LLMCall
from shared.common.timeutil import utc_now
from shared.observability.alert import AlertLevel, BarkAlerter
from shared.observability.log import get_logger

log = get_logger(__name__)
T = TypeVar("T")


class ChatProtocol(Protocol):
    async def chat_json(
        self, *, model: str, system: str, user: str, max_tokens: int
    ) -> ChatResult: ...


class BudgetUnavailable(Exception):
    pass


class EventAssessor:
    def __init__(
        self,
        events: EventsDAO,
        client: ChatProtocol,
        cfg: AppConfig | LLMCfg,
        watchlist: WatchlistFile,
        bark: BarkAlerter | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.events = events
        self.client = client
        self.cfg = cfg.llm if isinstance(cfg, AppConfig) else cfg
        self.watchlist = watchlist
        self.bark = bark
        self._clock = clock
        self._known = set(watchlist.effective_us()) | set(watchlist.effective_cn())
        self._semaphore = asyncio.Semaphore(4)
        self._budget_lock = asyncio.Lock()
        self._reserved = 0.0
        self._failures = 0
        self._open_until: datetime | None = None

    async def run(self, limit: int = 20) -> int:
        pending = await self.events.list_pending(limit=min(max(limit, 0), 20))
        await asyncio.gather(*(self._process(event) for event in pending))
        return len(pending)

    async def _process(self, event: Event) -> None:
        eligible = bool(event.tagged_tickers) or event.first_party or event.importance_hint >= 2
        if not self.cfg.enabled or not eligible:
            await self._write(event, assess_status="skipped")
            return
        async with self._semaphore:
            if not await self._circuit_available():
                await self._write(event, assess_status="failed")
                return
            attempts = 0
            try:
                system, user, recent = await assessment_messages(
                    self.events, event, self.watchlist, self._clock()
                )
                for attempt in range(2):
                    attempts += 1
                    try:
                        result = await self._invoke(
                            "assess",
                            event.id,
                            self.cfg.assess,
                            system,
                            user,
                            lambda content: parse_assessment(content, self._known, recent),
                        )
                        await self._write(
                            event,
                            **result.model_dump(),
                            assess_status="done",
                            assess_attempts=event.assess_attempts + attempts,
                            model_used=self.cfg.assess.model,
                            assessed_at=utc_aware(self._clock()).replace(tzinfo=None),
                        )
                        await self._success()
                        return
                    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                        if attempt == 1:
                            raise
                        user += (
                            f"\n\nOutput validation failed: {error}. "
                            "Return one corrected JSON object."
                        )
            except BudgetUnavailable:
                await self._write(
                    event,
                    assess_status="failed",
                    assess_attempts=event.assess_attempts + max(attempts - 1, 0),
                )
                return
            except Exception as error:
                log.warning(
                    "event_assess_failed", event_id=event.id, error_type=type(error).__name__
                )
                await self._write(
                    event, assess_status="failed", assess_attempts=event.assess_attempts + attempts
                )
                await self._failure()

    async def digest_json(self, system: str, user: str) -> dict[str, Any] | None:
        if not self.cfg.enabled:
            return None
        async with self._semaphore:
            if not await self._circuit_available():
                return None
            for attempt in range(2):
                try:
                    result = await self._invoke(
                        "digest", None, self.cfg.digest, system, user, self._json_object
                    )
                    await self._success()
                    return result
                except BudgetUnavailable:
                    return None
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    if attempt == 0:
                        user += (
                            f"\n\nOutput validation failed: {error}. "
                            "Return one corrected JSON object."
                        )
                        continue
                    await self._failure()
                except Exception as error:
                    log.warning("digest_assess_failed", error_type=type(error).__name__)
                    await self._failure()
                return None
        return None

    @staticmethod
    def _json_object(content: str) -> dict[str, Any]:
        value: Any = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value

    async def _invoke(
        self,
        purpose: str,
        event_id: int | None,
        task: LLMTaskCfg,
        system: str,
        user: str,
        parse: Callable[[str], T],
    ) -> T:
        reservation = await self._reserve(task, system, user)
        recorded = False
        result: ChatResult | None = None
        try:
            result = await self.client.chat_json(
                model=task.model, system=system, user=user, max_tokens=task.max_tokens
            )
            try:
                parsed = parse(result.content)
            except Exception as error:
                await self._record(purpose, event_id, task, result, error)
                recorded = True
                raise
            await self._record(purpose, event_id, task, result, None)
            recorded = True
            return parsed
        except Exception as error:
            if not recorded:
                await self._record(purpose, event_id, task, result, error)
            raise
        finally:
            async with self._budget_lock:
                self._reserved -= reservation

    async def _reserve(self, task: LLMTaskCfg, system: str, user: str) -> float:
        price = self.cfg.pricing[task.model]
        # UTF-8 bytes conservatively bound text tokens; allowance covers message framing.
        input_bound = len((system + user).encode("utf-8")) + 128
        reservation = (input_bound * price.input + task.max_tokens * price.output) / 1_000_000
        now = utc_aware(self._clock())
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        end = start + timedelta(days=1)
        over_budget = False
        async with self._budget_lock:
            async with self.events.db.session() as session:
                spent = await session.scalar(
                    select(func.coalesce(func.sum(col(LLMCall.cost_cny)), 0)).where(
                        col(LLMCall.created_at) >= start.replace(tzinfo=None),
                        col(LLMCall.created_at) < end.replace(tzinfo=None),
                    )
                )
            if float(spent or 0) + self._reserved + reservation > self.cfg.daily_cost_ceiling_cny:
                over_budget = True
            else:
                self._reserved += reservation
        if over_budget:
            await self._budget_notice(local.date().isoformat())
            raise BudgetUnavailable("daily cost ceiling")
        return reservation

    async def _record(
        self,
        purpose: str,
        event_id: int | None,
        task: LLMTaskCfg,
        result: ChatResult | None,
        error: Exception | None,
    ) -> None:
        raw_attempts = result.attempts if result is not None else getattr(error, "attempts", ())
        attempts = list(raw_attempts) or [
            ChatAttempt(
                result.tokens_in if result else 0,
                result.tokens_out if result else 0,
                result.latency_ms if result else 0,
                type(error).__name__ if error else None,
            )
        ]
        price = self.cfg.pricing[task.model]
        async with self.events.db.session() as session:
            for index, attempt in enumerate(attempts):
                last_error = type(error).__name__ if error and index == len(attempts) - 1 else None
                message = attempt.error or last_error
                session.add(
                    LLMCall(
                        purpose=purpose,
                        event_id=event_id,
                        model=task.model,
                        prompt_version=task.prompt_version,
                        tokens_in=attempt.tokens_in,
                        tokens_out=attempt.tokens_out,
                        cost_cny=(
                            attempt.tokens_in * price.input + attempt.tokens_out * price.output
                        )
                        / 1_000_000,
                        latency_ms=attempt.latency_ms,
                        ok=message is None,
                        error=message,
                        created_at=utc_aware(self._clock()).replace(tzinfo=None),
                    )
                )
            await session.commit()

    async def _write(self, event: Event, **values: Any) -> None:
        if event.id is None:
            return
        # Clusterer may add stronger evidence while this HTTP call is in progress.
        async with self.events.db.session() as session:
            await session.execute(
                update(Event)
                .where(
                    col(Event.id) == event.id,
                    col(Event.article_count) == event.article_count,
                    col(Event.assess_status) == "pending",
                )
                .values(**values)
            )
            await session.commit()

    async def _budget_notice(self, day: str) -> None:
        if self.bark is None:
            return
        async with self._budget_lock, self.events.db.session() as session:
            key = (day, "llm_budget_notice", "")
            if await session.get(DailyMetric, key) is not None:
                return
            session.add(DailyMetric(metric_date=day, metric_name=key[1], metric_value=1))
            await session.commit()
        await self._notify(
            "LLM daily budget reached", "Remaining events use rule fallback.", AlertLevel.WARN
        )

    async def _circuit_available(self) -> bool:
        if self._open_until is None:
            return True
        if utc_aware(self._clock()) < self._open_until:
            return False
        self._open_until = None
        self._failures = 0
        await self._notify(
            "LLM circuit recovered", "Assessment requests are enabled again.", AlertLevel.INFO
        )
        return True

    async def _success(self) -> None:
        self._failures = 0

    async def _failure(self) -> None:
        self._failures += 1
        if self._failures >= 10 and self._open_until is None:
            self._open_until = utc_aware(self._clock()) + timedelta(minutes=10)
            await self._notify(
                "LLM circuit open",
                "Ten consecutive failures; rule fallback for ten minutes.",
                AlertLevel.WARN,
            )

    async def _notify(self, title: str, body: str, level: AlertLevel) -> None:
        if self.bark is not None:
            try:
                await self.bark.send(title, body, level)
            except Exception as error:
                log.warning("llm_alert_failed", error_type=type(error).__name__)

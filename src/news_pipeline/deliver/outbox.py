"""One bounded outbox pass; scheduled by the runtime with max_instances=1."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from news_pipeline.storage.dao.deliveries import DeliveryDAO
from shared.common.contracts import CommonMessage
from shared.common.timeutil import utc_now
from shared.push.base import SendResult


class Dispatcher(Protocol):
    async def dispatch(
        self, msg: CommonMessage, *, channels: list[str]
    ) -> Mapping[str, SendResult]: ...


class Outbox:
    def __init__(self, dao: DeliveryDAO, dispatcher: Dispatcher) -> None:
        self.dao = dao
        self.dispatcher = dispatcher

    async def run(self, now: datetime | None = None) -> int:
        at = now or utc_now()
        attempted = 0
        for candidate in await self.dao.ready(at):
            if candidate.id is None:
                continue
            row = await self.dao.reserve_attempt(candidate.id, at)
            if row is None:
                continue
            attempted += 1
            try:
                message = CommonMessage.model_validate(row.payload)
                results = await self.dispatcher.dispatch(message, channels=[row.channel])
                result = results.get(row.channel)
                ok = result is not None and result.ok
                error = result.response_body if result is not None else "Missing dispatcher result"
            except Exception as exc:
                ok, error = False, repr(exc)
            await self.dao.finish_attempt(candidate.id, ok=ok, now=at, error=error)
        return attempted

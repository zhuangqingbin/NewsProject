# src/news_pipeline/pushers/dispatcher.py
import asyncio

from shared.common.contracts import CommonMessage
from shared.push.base import PusherProtocol, SendResult


class PusherDispatcher:
    def __init__(self, registry: dict[str, PusherProtocol]) -> None:
        self._reg = registry

    async def dispatch(self, msg: CommonMessage, *, channels: list[str]) -> dict[str, SendResult]:
        present = [(cid, self._reg[cid]) for cid in channels if cid in self._reg]
        coros = [p.send(msg) for _, p in present]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[str, SendResult] = {}
        for (cid, _), r in zip(present, results, strict=True):
            if isinstance(r, BaseException):
                out[cid] = SendResult(ok=False, response_body=str(r))
            else:
                out[cid] = r
        return out

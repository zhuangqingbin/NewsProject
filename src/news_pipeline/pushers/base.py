# src/news_pipeline/pushers/base.py
from dataclasses import dataclass
from typing import Protocol

from news_pipeline.common.contracts import CommonMessage


@dataclass
class SendResult:
    ok: bool
    http_status: int | None = None
    response_body: str = ""
    retries: int = 0


class PusherProtocol(Protocol):
    channel_id: str

    async def send(self, msg: CommonMessage) -> SendResult: ...

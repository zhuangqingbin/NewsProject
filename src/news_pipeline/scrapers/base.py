# src/news_pipeline/scrapers/base.py
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market


@runtime_checkable
class ScraperProtocol(Protocol):
    source_id: str
    market: Market

    async def fetch(self, since: datetime) -> Sequence[RawArticle]: ...

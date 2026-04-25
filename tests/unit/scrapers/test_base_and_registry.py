# tests/unit/scrapers/test_base_and_registry.py
from collections.abc import Sequence
from datetime import datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.scrapers.registry import ScraperRegistry


class _Fake:
    source_id = "fake"
    market = Market.US

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return []


def test_registry_register_and_get():
    reg = ScraperRegistry()
    reg.register(_Fake())
    assert reg.get("fake").source_id == "fake"
    assert "fake" in reg.list_ids()


def test_protocol_compliance():
    f = _Fake()
    assert isinstance(f, ScraperProtocol)

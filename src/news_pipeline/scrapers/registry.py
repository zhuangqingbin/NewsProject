# src/news_pipeline/scrapers/registry.py
from news_pipeline.scrapers.base import ScraperProtocol


class ScraperRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ScraperProtocol] = {}

    def register(self, scraper: ScraperProtocol) -> None:
        self._items[scraper.source_id] = scraper

    def get(self, source_id: str) -> ScraperProtocol:
        return self._items[source_id]

    def list_ids(self) -> list[str]:
        return list(self._items.keys())

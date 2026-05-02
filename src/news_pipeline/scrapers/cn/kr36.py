"""36氪 RSS — Chinese tech/VC coverage."""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import feedparser

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now

_FEED_URL = "https://36kr.com/feed"


def _strip_html(text: str) -> str:
    """Crude HTML strip — feedparser leaves <p>/<img> tags in summary fields."""
    import re

    return re.sub(r"<[^>]+>", "", text).strip()


class Kr36Scraper:
    source_id = "kr36"
    market = Market.CN

    def __init__(
        self,
        *,
        feed_url: str = _FEED_URL,
        parser: Callable[[str], Any] = feedparser.parse,
    ) -> None:
        self._feed_url = feed_url
        self._parser = parser

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        feed = self._parser(self._feed_url)
        out: list[RawArticle] = []
        now = utc_now()
        for entry in getattr(feed, "entries", []) or []:
            pp = entry.get("published_parsed")
            if not pp:
                continue
            ts = datetime(pp[0], pp[1], pp[2], pp[3], pp[4], pp[5], tzinfo=UTC)
            if ts < since:
                continue
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            body = _strip_html(entry.get("summary") or "")[:1000] or None
            out.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=link,
                    url_hash=url_hash(link),
                    title=title,
                    title_simhash=title_simhash(title),
                    body=body,
                    raw_meta={"provider": "rss_36kr"},
                )
            )
        return out

"""WallStreetCN's public global live news feed."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.contract import (
    require_json_list,
    require_json_mapping,
    require_json_path,
    require_json_string,
)
from news_pipeline.scrapers.common.http import make_async_client

_API_URL = "https://api-one.wallstcn.com/apiv1/content/lives"


async def _default_fetch(channel: str, limit: int) -> object:
    async with make_async_client() as client:
        response = await client.get(_API_URL, params={"channel": channel, "limit": limit})
        response.raise_for_status()
        return response.json()


class WallStreetCnScraper:
    source_id = "wallstreetcn"
    market = Market.US

    def __init__(
        self,
        *,
        channel: str = "global-channel",
        limit: int = 40,
        http_callable: Callable[[str, int], Awaitable[Any]] = _default_fetch,
    ) -> None:
        self._channel = channel
        self._limit = limit
        self._http = http_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        payload = await self._http(self._channel, self._limit)
        items = require_json_list(payload, "data.items", source=self.source_id)
        articles: list[RawArticle] = []
        now = utc_now()
        for entry in items:
            item = require_json_mapping(entry, "", source=self.source_id)
            ts = datetime.fromtimestamp(
                int(require_json_path(item, "display_time", source=self.source_id)), tz=UTC
            )
            title = require_json_string(item, "title", source=self.source_id).strip()
            body = require_json_string(item, "content_text", source=self.source_id).strip()
            link = require_json_string(item, "uri", source=self.source_id).strip()
            title = title or body[:80]
            wscn_id = require_json_path(item, "id", source=self.source_id)
            score = require_json_path(item, "score", source=self.source_id)
            channels = require_json_list(item, "channels", source=self.source_id)
            if ts < since or not title or not link:
                continue
            articles.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=link,
                    url_hash=url_hash(link),
                    title=title,
                    title_simhash=title_simhash(title),
                    body=body or None,
                    raw_meta={"wscn_id": wscn_id, "score": score, "channels": channels},
                )
            )
        return articles

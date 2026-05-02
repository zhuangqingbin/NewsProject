"""华尔街见闻 (WallStreetCN) — global / US-focused finance coverage.

Uses the public JSON API (`api-prod.wallstreetcn.com`) — no auth required
for the `articles` endpoint. The `live` (快讯) endpoint requires auth, so
we stick to deep articles, which is the higher-signal stream anyway.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import httpx

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client

_API_URL = "https://api-prod.wallstreetcn.com/apiv1/content/articles"


async def _default_fetch(channel: str, limit: int) -> dict:  # type: ignore[type-arg]
    async with make_async_client() as client:
        r = await client.get(_API_URL, params={"channel": channel, "limit": limit})
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]


class WallStreetCnScraper:
    source_id = "wallstreetcn"
    market = Market.US  # 'global' channel skews to US/macro

    def __init__(
        self,
        *,
        channel: str = "global",
        limit: int = 30,
        http_callable: Callable[[str, int], Awaitable[dict]] = _default_fetch,  # type: ignore[type-arg]
    ) -> None:
        self._channel = channel
        self._limit = limit
        self._http = http_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        try:
            payload = await self._http(self._channel, self._limit)
        except httpx.HTTPError:
            return []
        items = (payload.get("data") or {}).get("items") or []
        out: list[RawArticle] = []
        now = utc_now()
        for it in items:
            display_time = it.get("display_time")
            if not display_time:
                continue
            ts = datetime.fromtimestamp(int(display_time), tz=UTC)
            if ts < since:
                continue
            title = (it.get("title") or "").strip()
            link = (it.get("uri") or "").strip()
            body = (it.get("content_short") or "").strip() or None
            if not title or not link:
                continue
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
                    raw_meta={"id": it.get("id"), "channel": self._channel},
                )
            )
        return out

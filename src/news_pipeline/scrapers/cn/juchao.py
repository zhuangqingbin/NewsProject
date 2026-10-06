"""CNInfo announcements with daily cached stock organization identifiers."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx

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


class JuchaoScraper:
    source_id = "juchao"
    market = Market.CN

    def __init__(self, *, tickers: list[str]) -> None:
        self._tickers = tickers
        self._org_ids: dict[str, str] = {}
        self._cache_day: date | None = None

    async def initialize(self) -> None:
        """Resolve all configured tickers before scheduling announcement requests."""
        async with make_async_client() as client:
            await self._resolve_org_ids(client)

    async def _resolve_org_ids(self, client: httpx.AsyncClient) -> None:
        today = utc_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        if self._cache_day == today:
            return
        response = await client.get("http://www.cninfo.com.cn/new/data/szse_stock.json")
        response.raise_for_status()
        stocks = require_json_list(response.json(), "stockList", source=self.source_id)
        org_ids = {
            require_json_string(stock, "code", source=self.source_id): require_json_string(
                stock, "orgId", source=self.source_id
            )
            for stock in stocks
        }
        missing = [ticker for ticker in self._tickers if not org_ids.get(ticker)]
        if missing:
            raise ValueError(f"juchao: cannot resolve configured tickers {missing} to orgId")
        self._org_ids = org_ids
        self._cache_day = today

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        # Page one is intentionally unfiltered: announcementTime can be a date,
        # including the next day's midnight for an evening publication.
        articles: list[RawArticle] = []
        async with make_async_client() as client:
            await self._resolve_org_ids(client)
            for index, ticker in enumerate(self._tickers):
                if index:
                    await asyncio.sleep(0.4)
                response = await client.post(
                    "http://www.cninfo.com.cn/new/hisAnnouncement/query",
                    data={
                        "stock": f"{ticker},{self._org_ids[ticker]}",
                        "tabName": "fulltext",
                        "pageSize": 30,
                        "pageNum": 1,
                    },
                )
                response.raise_for_status()
                now = utc_now()
                payload = require_json_mapping(response.json(), "", source=self.source_id)
                value = require_json_path(payload, "announcements", source=self.source_id)
                if value is None and payload.get("totalAnnouncement") == 0:
                    continue
                announcements = require_json_list(payload, "announcements", source=self.source_id)
                for announcement in announcements:
                    ann = require_json_mapping(announcement, "", source=self.source_id)
                    ann_time = require_json_path(ann, "announcementTime", source=self.source_id)
                    ts = datetime.fromtimestamp(int(ann_time) / 1000, tz=UTC)
                    local = ts.astimezone(ZoneInfo("Asia/Shanghai"))
                    if (local.hour, local.minute, local.second) == (0, 0, 0) or ts > now:
                        ts = now
                    sec_name = require_json_string(ann, "secName", source=self.source_id)
                    ann_title = require_json_string(ann, "announcementTitle", source=self.source_id)
                    title = f"{sec_name}\N{FULLWIDTH COLON}{ann_title}"
                    link = "http://static.cninfo.com.cn/" + require_json_string(
                        ann, "adjunctUrl", source=self.source_id
                    )
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
                            body=None,
                            raw_meta={
                                "ann_id": require_json_string(
                                    ann, "announcementId", source=self.source_id
                                ),
                                "code": require_json_string(ann, "secCode", source=self.source_id),
                                "ann_type": require_json_string(
                                    ann, "announcementType", source=self.source_id
                                ),
                                "ann_time_ms": ann_time,
                            },
                        )
                    )
        return articles

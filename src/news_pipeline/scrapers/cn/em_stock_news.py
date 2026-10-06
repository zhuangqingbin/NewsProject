"""Eastmoney stock news search, ordered by publication time."""

import asyncio
import json
import re
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now
from news_pipeline.scrapers.common.contract import (
    SourceContractError,
    require_json_list,
    require_json_mapping,
    require_json_string,
)
from news_pipeline.scrapers.common.http import make_async_client


class EmStockNewsScraper:
    source_id = "em_stock_news"
    market = Market.CN

    def __init__(self, *, tickers: list[str]) -> None:
        self._tickers = tickers

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        articles: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for index, ticker in enumerate(self._tickers):
                if index:
                    await asyncio.sleep(0.3)
                query = {
                    "uid": "",
                    "keyword": ticker,
                    "type": ["cmsArticleWebOld"],
                    "client": "web",
                    "clientType": "web",
                    "clientVersion": "curr",
                    "param": {
                        "cmsArticleWebOld": {
                            "searchScope": "default",
                            "sort": "time",
                            "pageIndex": 1,
                            "pageSize": 10,
                            "preTag": "",
                            "postTag": "",
                        }
                    },
                }
                response = await client.get(
                    "https://search-api-web.eastmoney.com/search/jsonp",
                    params={
                        "cb": "cb",
                        "_": str(int(utc_now().timestamp() * 1000)),
                        "param": json.dumps(query, ensure_ascii=False),
                    },
                    headers={"Referer": f"https://so.eastmoney.com/news/s?keyword={ticker}"},
                )
                response.raise_for_status()
                match = re.fullmatch(r"\s*cb\((.*)\)\s*;?\s*", response.text, re.DOTALL)
                if not match:
                    raise SourceContractError(f"{self.source_id}: invalid cb JSONP wrapper")
                try:
                    payload = json.loads(match.group(1))
                except json.JSONDecodeError as error:
                    raise SourceContractError(f"{self.source_id}: invalid JSONP payload") from error
                entries = require_json_list(
                    payload, "result.cmsArticleWebOld", source=self.source_id
                )
                for entry in entries:
                    item = require_json_mapping(entry, "", source=self.source_id)
                    title = require_json_string(item, "title", source=self.source_id).strip()
                    body = require_json_string(item, "content", source=self.source_id).strip()
                    date = require_json_string(item, "date", source=self.source_id)
                    link = require_json_string(item, "url", source=self.source_id).strip()
                    media = require_json_string(item, "mediaName", source=self.source_id)
                    ts = ensure_utc(
                        datetime.strptime(date, "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=ZoneInfo("Asia/Shanghai")
                        )
                    )
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
                            raw_meta={"ticker": ticker, "media": media},
                        )
                    )
        return articles

# src/news_pipeline/scrapers/cn/xueqiu.py
from collections.abc import Sequence
from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.cookies import parse_cookie_string
from news_pipeline.scrapers.common.http import make_async_client


class XueqiuScraper:
    source_id = "xueqiu"
    market = Market.CN

    def __init__(self, *, tickers: list[str], cookie: str) -> None:
        self._tickers = tickers
        self._cookies = parse_cookie_string(cookie)

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for t in self._tickers:
                stock = self._symbol(t)
                url = (
                    f"https://xueqiu.com/v4/statuses/stock_timeline.json"
                    f"?symbol_id={stock}&count=20"
                )
                resp = await client.get(url, cookies=self._cookies)
                if resp.status_code in (401, 403):
                    raise AntiCrawlError(
                        "xueqiu blocked",
                        source=self.source_id,
                        status=resp.status_code,
                    )
                resp.raise_for_status()
                for item in resp.json().get("list", []):
                    ts = datetime.fromtimestamp(
                        int(item["created_at"]) / 1000, tz=UTC
                    )
                    if ts < since:
                        continue
                    link = "https://xueqiu.com" + item["target"]
                    title = item.get("title") or item.get("description", "")[:80]
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
                            body=item.get("description"),
                            raw_meta={"id": item["id"], "ticker": t},
                        )
                    )
        return out

    @staticmethod
    def _symbol(ticker: str) -> str:
        if ticker.startswith("6"):
            return f"SH{ticker}"
        if ticker.startswith(("0", "3")):
            return f"SZ{ticker}"
        return ticker

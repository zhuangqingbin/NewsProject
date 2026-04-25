# src/news_pipeline/scrapers/cn/ths.py
from collections.abc import Sequence
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.cookies import parse_cookie_string
from news_pipeline.scrapers.common.http import make_async_client


class ThsScraper:
    source_id = "ths"
    market = Market.CN

    def __init__(self, *, tickers: list[str], cookie: str) -> None:
        self._tickers = tickers
        self._cookies = parse_cookie_string(cookie)

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for ticker in self._tickers:
                url = f"https://news.10jqka.com.cn/{ticker}/list.shtml"
                resp = await client.get(url, cookies=self._cookies)
                if resp.status_code in (401, 403):
                    raise AntiCrawlError("ths blocked", source=self.source_id)
                resp.raise_for_status()
                body_text = resp.text
                if not body_text.strip():
                    raise AntiCrawlError(
                        "ths returned empty body",
                        source=self.source_id,
                        status=resp.status_code,
                    )
                if "登录" in body_text or "captcha" in body_text.lower():
                    raise AntiCrawlError(
                        "ths returned login/captcha page",
                        source=self.source_id,
                        status=resp.status_code,
                    )
                soup = BeautifulSoup(body_text, "html.parser")
                for a in soup.select(".news-link"):
                    href = a.get("href", "")
                    if not href:
                        continue
                    link = href if href.startswith("http") else f"https://news.10jqka.com.cn{href}"
                    ts_raw = a.get("data-time")
                    if not ts_raw:
                        continue
                    ts = datetime.fromtimestamp(int(ts_raw), tz=UTC)
                    if ts < since:
                        continue
                    title_el = a.select_one(".news-title")
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title:
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
                            body=None,
                            raw_meta={"ticker": ticker},
                        )
                    )
        return out

# src/news_pipeline/scrapers/cn/caixin_telegram.py
from collections.abc import Sequence
from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class CaixinTelegramScraper:
    source_id = "caixin_telegram"
    market = Market.CN

    def __init__(self, *, count: int = 20) -> None:
        self._count = count

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        # NOTE: The exact endpoint may need adjustment after real-world inspection.
        # Replace _endpoint() with the working URL when wiring up.
        url = self._endpoint()
        async with make_async_client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        items = (payload.get("data") or {}).get("roll_data") or []
        out: list[RawArticle] = []
        now = utc_now()
        for it in items:
            ts = datetime.fromtimestamp(int(it["ctime"]), tz=UTC)
            if ts < since:
                continue
            link = it["shareurl"]
            title = it.get("title") or it.get("brief", "")[:80]
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
                    body=it.get("brief"),
                    raw_meta={"cls_id": it["id"]},
                )
            )
        return out

    def _endpoint(self) -> str:
        return "https://www.cls.cn/v3/depth/home/assembled/1000"

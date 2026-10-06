"""Signed public CLS telegraph endpoint."""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlencode

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


class ClsTelegraphScraper:
    source_id = "cls_telegraph"
    market = Market.CN

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        now = utc_now()
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "last_time": str(int(now.timestamp())),
            "os": "web",
            "refresh_type": "1",
            "rn": "20",
            "sv": "8.4.6",
        }
        encoded = urlencode(sorted(params.items()))
        params["sign"] = hashlib.md5(
            hashlib.sha1(encoded.encode()).hexdigest().encode()
        ).hexdigest()
        async with make_async_client() as client:
            response = await client.get(
                "https://www.cls.cn/v1/roll/get_roll_list",
                params=params,
                headers={"Referer": "https://www.cls.cn/telegraph"},
            )
            response.raise_for_status()
            entries = require_json_list(response.json(), "data.roll_data", source=self.source_id)
        articles: list[RawArticle] = []
        for entry in entries:
            item = require_json_mapping(entry, "", source=self.source_id)
            cls_id = require_json_path(item, "id", source=self.source_id)
            ts = datetime.fromtimestamp(
                int(require_json_path(item, "ctime", source=self.source_id)), tz=UTC
            )
            title = require_json_string(item, "title", source=self.source_id).strip()
            brief = require_json_string(item, "brief", source=self.source_id).strip()
            body = require_json_string(item, "content", source=self.source_id).strip()
            level = require_json_string(item, "level", source=self.source_id)
            stocks = require_json_list(item, "stock_list", source=self.source_id)
            subjects = require_json_list(item, "subjects", source=self.source_id)
            title = title or brief[:80]
            if ts < since or not title:
                continue
            link = f"https://www.cls.cn/detail/{cls_id}"
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
                    raw_meta={
                        "cls_id": cls_id,
                        "level": level,
                        "stocks": [
                            require_json_string(s, "stock_code", source=self.source_id)
                            for s in stocks
                        ],
                        "subjects": [
                            require_json_string(s, "subject_name", source=self.source_id)
                            for s in subjects
                        ],
                    },
                )
            )
        return articles

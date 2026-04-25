import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import RawNews


async def _check() -> int:
    db_path = os.environ.get("NEWS_PIPELINE_DB", "data/news.db")
    if not Path(db_path).exists():
        print("FAIL: db missing")
        return 1
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()
    cutoff = (utc_now() - timedelta(minutes=30)).replace(tzinfo=None)
    async with db.session() as s:
        res = await s.execute(select(RawNews).where(RawNews.fetched_at >= cutoff).limit(1))
        if res.first() is None:
            print("FAIL: no recent scrape")
            await db.close()
            return 1
    await db.close()
    print("OK")
    return 0


def main() -> int:
    return asyncio.run(_check())


if __name__ == "__main__":
    sys.exit(main())

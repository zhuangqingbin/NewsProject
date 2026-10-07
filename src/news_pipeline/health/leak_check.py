"""Read-only comparison of upstream wires against stored URLs."""

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from news_pipeline.common.contracts import RawArticle
from news_pipeline.config.schema import SourcesFile
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from shared.common.timeutil import ensure_utc, utc_now


async def check_articles(
    raw_dao: RawNewsDAO,
    articles: Sequence[RawArticle],
    *,
    now: datetime,
) -> dict[str, Any]:
    eligible = [
        article
        for article in articles
        if ensure_utc(article.published_at) < ensure_utc(now) - timedelta(minutes=15)
    ]
    known = await raw_dao.existing_url_hashes([article.url_hash for article in eligible])
    present = 0
    missing: list[str] = []
    for article in eligible:
        if article.url_hash in known:
            present += 1
        else:
            missing.append(str(article.url))
    return {
        "checked": len(eligible),
        "present": present,
        "missing": len(missing),
        "missing_urls": missing,
    }


async def run_leak_check(
    registry: ScraperRegistry,
    sources: SourcesFile,
    raw_dao: RawNewsDAO,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    at = now or utc_now()
    for source_id in registry.list_ids():
        config = sources.sources.get(source_id)
        if config is None or not config.enabled:
            continue
        row: dict[str, Any] = {"source_id": source_id, "ok": False}
        try:
            articles = await asyncio.wait_for(
                registry.get(source_id).fetch(at - timedelta(minutes=config.lookback_min)),
                timeout=config.fetch_timeout_sec,
            )
            row.update(await check_articles(raw_dao, articles, now=at))
            row["ok"] = True
        except Exception as error:
            row["error_type"] = type(error).__name__
        results.append(row)
    return results


async def _main() -> None:
    from news_pipeline.health.smoke import cli_registry, readonly_database

    snapshot, registry = cli_registry()
    database = readonly_database()
    try:
        print(
            json.dumps(
                await run_leak_check(registry, snapshot.sources, RawNewsDAO(database)),
                ensure_ascii=False,
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(_main())

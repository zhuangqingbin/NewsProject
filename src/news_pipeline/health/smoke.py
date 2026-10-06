"""Read-only upstream probes, usable at startup and from the command line."""

import argparse
import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from news_pipeline.config.loader import ConfigLoader, ConfigSnapshot
from news_pipeline.config.schema import SourcesFile
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.db import Database
from shared.common.contracts import Badge, CommonMessage
from shared.common.enums import Market
from shared.common.timeutil import utc_now


def build_smoke_report(results: list[dict[str, Any]]) -> CommonMessage:
    lines = []
    for row in results:
        line = f"{row['source_id']}: {'正常' if row['ok'] else '失败'} · {row.get('count', 0)} 条"
        if row.get("error_type"):
            line += f" · {row['error_type']}"
        leak = row.get("leak")
        if isinstance(leak, dict):
            line += (
                f" · 检查 {leak.get('checked', 0)} · 丢失 {leak.get('missing', 0)}"
                f" · 标题重复 {leak.get('title_duplicates', 0)}"
            )
        lines.append(line)
    return CommonMessage(
        title="源冒烟检查",
        summary="\n".join(lines),
        source_label="系统",
        source_url="https://example.com/system",
        market=Market.CN,
        badges=[Badge(text="系统")],
        chart_url=None,
        deeplinks=[],
    )


async def run_smoke(
    registry: ScraperRegistry,
    sources: SourcesFile,
    raw_dao: RawNewsDAO | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for source_id in registry.list_ids():
        config = sources.sources.get(source_id)
        if config is None or not config.enabled:
            continue
        row: dict[str, Any] = {"source_id": source_id, "ok": False, "count": 0}
        now = utc_now()
        try:
            articles = list(
                await asyncio.wait_for(
                    registry.get(source_id).fetch(now - timedelta(minutes=config.lookback_min)),
                    timeout=config.fetch_timeout_sec,
                )
            )
            row["count"] = len(articles)
            if config.interval_sec is not None and config.interval_sec <= 300 and not articles:
                row["error_type"] = "EmptySource"
            else:
                row["ok"] = True
            if raw_dao is not None:
                from news_pipeline.health.leak_check import check_articles

                row["leak"] = await check_articles(raw_dao, articles, now=now)
        except Exception as error:
            # Exception text may contain token-bearing request URLs.
            row["error_type"] = type(error).__name__
        results.append(row)
    return results


def cli_registry() -> tuple[ConfigSnapshot, ScraperRegistry]:
    snapshot = ConfigLoader(Path(os.environ.get("NEWS_PIPELINE_CONFIG_DIR", "config"))).load()
    sec_cfg = snapshot.sources.sources.get("sec_edgar")
    if sec_cfg and os.environ.get("SEC_USER_AGENT"):
        sec_cfg.options["user_agent"] = os.environ["SEC_USER_AGENT"]
    return snapshot, build_registry(snapshot.sources, snapshot.watchlist, snapshot.secrets)


def readonly_database() -> Database:
    path = Path(os.environ.get("NEWS_PIPELINE_DB", "data/news.db")).resolve()
    if not path.is_file():
        raise FileNotFoundError("Existing news database is required for this read-only command")
    return Database(f"sqlite+aiosqlite:///file:{path.as_posix()}?mode=ro&uri=true")


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Source and ingestion probe with an ops report")
    reporting = parser.add_mutually_exclusive_group()
    reporting.add_argument(
        "--report",
        dest="report",
        action="store_true",
        help="Send the report to the configured ops channel (default)",
    )
    reporting.add_argument(
        "--no-report",
        dest="report",
        action="store_false",
        help="Only print JSON without sending a report",
    )
    parser.set_defaults(report=True)
    args = parser.parse_args()
    snapshot, registry = cli_registry()
    path = Path(os.environ.get("NEWS_PIPELINE_DB", "data/news.db"))
    database = readonly_database() if path.is_file() else None
    try:
        results = await run_smoke(
            registry,
            snapshot.sources,
            RawNewsDAO(database) if database else None,
        )
        print(json.dumps(results, ensure_ascii=False))
        if args.report:
            from shared.push.dispatcher import PusherDispatcher
            from shared.push.factory import build_pushers

            channel = snapshot.app.ops.report_channel
            configured = snapshot.channels.channels.get(channel)
            if configured is None or not configured.enabled:
                raise ValueError("The configured ops report channel must be enabled")
            dispatcher = PusherDispatcher(build_pushers(snapshot.channels, snapshot.secrets))
            sent = await dispatcher.dispatch(build_smoke_report(results), channels=[channel])
            if channel not in sent or not sent[channel].ok:
                raise RuntimeError("Smoke report delivery failed")
    finally:
        if database:
            await database.close()


if __name__ == "__main__":
    asyncio.run(_main())

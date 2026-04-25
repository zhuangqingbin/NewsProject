"""Weekly metrics report builder."""

from datetime import timedelta

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.dao.metrics import MetricsDAO


async def build_weekly_report(
    *,
    metrics: MetricsDAO,
    sources: list[str],
    channels: list[str],
) -> str:
    """Build a markdown summary of the past 7 days of pipeline metrics.

    Args:
        metrics: MetricsDAO instance to query.
        sources: List of source IDs to include.
        channels: List of channel IDs to include.

    Returns:
        Markdown-formatted weekly report string.
    """
    today = utc_now().date()
    days = [today - timedelta(days=i) for i in range(7)]
    lines = ["**周报: 抓取/LLM/推送 7 天汇总**\n"]

    lines.append("\n_抓取新闻数 (按源)_")
    for s in sources:
        total = 0.0
        for d in days:
            v = await metrics.get(
                date_iso=d.isoformat(),
                name="scrape_new",
                dimensions=f"source={s}",
            )
            total += v or 0.0
        lines.append(f"  {s}: {int(total)}")

    lines.append("\n_推送成功数 (按渠道)_")
    for c in channels:
        total = 0.0
        for d in days:
            v = await metrics.get(
                date_iso=d.isoformat(),
                name="push_ok",
                dimensions=f"channel={c}",
            )
            total += v or 0.0
        lines.append(f"  {c}: {int(total)}")

    return "\n".join(lines)

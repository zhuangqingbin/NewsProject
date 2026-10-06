from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from news_pipeline.config.schema import SourceDef
from news_pipeline.storage.dao.source_state import SourceStateDAO
from shared.common.calendar import MarketCalendar
from shared.common.timeutil import ensure_utc, utc_now
from shared.observability.alert import AlertLevel, BarkAlerter


async def check_source_health(
    dao: SourceStateDAO,
    sources: dict[str, SourceDef],
    *,
    bark: BarkAlerter | None = None,
    now: datetime | None = None,
) -> int:
    at = ensure_utc(now or utc_now())
    local = at.astimezone(ZoneInfo("Asia/Shanghai"))
    daytime = MarketCalendar().session(at) != "closed" and 9 <= local.hour < 23
    changes = 0
    for state in await dao.list_all():
        cfg = sources.get(state.source)
        if cfg is None or not cfg.enabled:
            continue
        threshold = cfg.max_silence_min if daytime else cfg.max_silence_off_min
        baseline = state.last_item_at or state.first_success_at or state.last_success_at
        reason = ""
        if state.consecutive_failures >= 5:
            reason = "failing"
        elif threshold and baseline and at - ensure_utc(baseline) > timedelta(minutes=threshold):
            reason = "silent"
        health = "down" if reason else "ok"
        changed = await dao.transition_health(state.source, health=health, reason=reason, now=at)
        if changed:
            changes += 1
            if bark:
                if reason:
                    await bark.send(
                        f"源失效：{state.source}",  # noqa: RUF001
                        f"{reason}；{state.last_error or '长时间没有新条目'}",  # noqa: RUF001
                        level=AlertLevel.URGENT,
                    )
                else:
                    duration = (
                        (at - ensure_utc(state.health_changed_at)).total_seconds() / 60
                        if state.health_changed_at
                        else 0
                    )
                    await bark.send(
                        f"源恢复：{state.source}",  # noqa: RUF001
                        f"已恢复，中断 {duration:.0f} 分钟",  # noqa: RUF001
                        level=AlertLevel.INFO,
                    )
    return changes

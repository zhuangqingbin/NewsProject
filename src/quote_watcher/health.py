from datetime import datetime, timedelta

from shared.common.timeutil import ensure_utc, utc_now
from shared.observability.alert import AlertLevel, BarkAlerter


class QuoteFeedHealth:
    def __init__(self, bark: BarkAlerter | None) -> None:
        self._bark = bark
        self._baseline: datetime | None = None
        self._down = False

    async def observe(self, success: bool, *, trading: bool, now: datetime | None = None) -> None:
        at = ensure_utc(now or utc_now())
        if not trading:
            self._baseline = None
            return
        if success:
            self._baseline = at
            if self._down:
                self._down = False
                if self._bark:
                    await self._bark.send(
                        "quote_watcher 已恢复", "行情快照已恢复", level=AlertLevel.INFO
                    )
            return
        if self._baseline is None:
            self._baseline = at
        if not self._down and at - self._baseline >= timedelta(minutes=5):
            self._down = True
            if self._bark:
                await self._bark.send(
                    "quote_watcher 行情失效",
                    "交易时段连续 5 分钟无成功快照",
                    level=AlertLevel.URGENT,
                )

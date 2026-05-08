"""Sina HQ feed parser and HTTP client."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quote_watcher.feeds.base import QuoteSnapshot
from shared.observability.log import get_logger

log = get_logger(__name__)

BJ = ZoneInfo("Asia/Shanghai")
_LINE_RE = re.compile(
    r'var hq_str_(?P<mkt>sh|sz|bj)(?P<code>\d{6})="(?P<payload>[^"]*)";'
)


def parse_sina_response(text: str) -> list[QuoteSnapshot]:
    """Parse Sina hq.sinajs.cn response into QuoteSnapshot list.

    Suspended/halted stocks return empty payload — skipped.
    """
    out: list[QuoteSnapshot] = []
    for m in _LINE_RE.finditer(text):
        payload = m.group("payload")
        if not payload.strip():
            continue
        fields = payload.split(",")
        if len(fields) < 32:
            continue
        try:
            snap = QuoteSnapshot(
                ticker=m.group("code"),
                market=m.group("mkt").upper(),
                name=fields[0],
                ts=_parse_ts(fields[30], fields[31]),
                open=float(fields[1]),
                prev_close=float(fields[2]),
                price=float(fields[3]),
                high=float(fields[4]),
                low=float(fields[5]),
                bid1=float(fields[6]),
                ask1=float(fields[7]),
                volume=int(fields[8]),
                amount=float(fields[9]),
            )
        except (ValueError, IndexError):
            continue
        out.append(snap)
    return out


def _parse_ts(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)


class SinaFeed:
    source_id = "sina_hq"

    def __init__(self, *, timeout_sec: float = 5.0, max_retries: int = 1) -> None:
        self._timeout = timeout_sec
        self._max_retries = max_retries

    async def fetch(self, tickers: list[tuple[str, str]]) -> Sequence[QuoteSnapshot]:
        if not tickers:
            return []
        codes = ",".join(f"{m.lower()}{c}" for m, c in tickers)
        url = f"https://hq.sinajs.cn/list={codes}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        url, headers={"Referer": "https://finance.sina.com.cn/"}
                    )
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"sina {resp.status_code}", request=resp.request, response=resp
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(0)  # cooperative yield only — keep tests fast
                    continue
                resp.raise_for_status()
                text = resp.content.decode("gbk", errors="replace")
                return parse_sina_response(text)
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_exc = e
                if attempt < self._max_retries:
                    await asyncio.sleep(0)
                    continue
                log.warning("sina_fetch_failed", error=str(e), tickers=len(tickers))
        if last_exc is not None:
            log.warning("sina_fetch_exhausted", error=str(last_exc))
        return []

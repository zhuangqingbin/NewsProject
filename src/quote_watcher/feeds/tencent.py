"""Tencent's batched, GBK-encoded A-share quote feed."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quote_watcher.feeds.base import QuoteSnapshot
from shared.observability.log import get_logger

log = get_logger(__name__)
BJ = ZoneInfo("Asia/Shanghai")
_LINE_RE = re.compile(r'v_(?P<market>sh|sz|bj)(?P<code>\d{6})="(?P<payload>[^"]*)";')


def _number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite Tencent quote value")
    return number


def _optional_number(fields: list[str], index: int) -> float | None:
    try:
        return _number(fields[index])
    except (ValueError, IndexError):
        return None


def parse_tencent_response(text: str) -> list[QuoteSnapshot]:
    """Skip empty or malformed individual quotes; normalize volume to shares."""
    out: list[QuoteSnapshot] = []
    for match in _LINE_RE.finditer(text):
        fields = match.group("payload").split("~")
        if len(fields) < 36:
            continue
        try:
            code = fields[2]
            if code != match.group("code") or len(fields[30]) != 14:
                continue
            volume = int(fields[6])
            if not code.startswith(("688", "689")):
                volume *= 100
            snap = QuoteSnapshot(
                ticker=code,
                market=match.group("market").upper(),
                name=fields[1],
                price=_number(fields[3]),
                prev_close=_number(fields[4]),
                open=_number(fields[5]),
                volume=volume,
                bid1=_number(fields[9]),
                ask1=_number(fields[19]),
                ts=datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=BJ),
                high=_number(fields[33]),
                low=_number(fields[34]),
                amount=_number(fields[35].split("/")[2]),
                limit_up=_optional_number(fields, 47),
                limit_down=_optional_number(fields, 48),
                volume_ratio=_optional_number(fields, 49),
            )
        except (ValueError, IndexError):
            continue
        out.append(snap)
    return out


class TencentFeed:
    source_id = "tencent_hq"

    def __init__(self, *, timeout_sec: float = 8.0, max_retries: int = 1) -> None:
        self._timeout = timeout_sec
        self._max_retries = max_retries

    async def fetch(self, tickers: list[tuple[str, str]]) -> Sequence[QuoteSnapshot]:
        if not tickers:
            return []
        codes = ",".join(f"{market.lower()}{code}" for market, code in tickers)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.get(f"https://qt.gtimg.cn/q={codes}")
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(0)
                        continue
                    log.warning("tencent_fetch_failed", error=repr(exc), tickers=len(tickers))
                    raise
                text = response.content.decode("gbk", errors="replace")
                matches = list(_LINE_RE.finditer(text))
                snapshots = parse_tencent_response(text)
                if not matches or (
                    not snapshots and any(match.group("payload").strip() for match in matches)
                ):
                    raise ValueError("Tencent response contains no valid quote records")
                return snapshots
        raise ValueError("max_retries must be nonnegative")

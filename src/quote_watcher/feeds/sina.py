"""Sina HQ feed parser. Network layer follows in Task 2.3."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.feeds.base import QuoteSnapshot

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

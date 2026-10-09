"""Adjusted Tencent daily history, with exact shares and amounts in yuan."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
type BarValues = tuple[date, float, float, float, float, float, int, float]


@dataclass(frozen=True)
class DailyHistory:
    bars: list[BarValues]
    volume_shares: dict[date, int]


async def fetch_tencent_daily(
    ticker: str,
    *,
    start: date,
    end: date,
    days: int,
    timeout_sec: float = 8.0,
) -> DailyHistory:
    if len(ticker) != 6 or not ticker.isdigit() or not 1 <= days < 640:
        raise ValueError("Invalid Tencent daily ticker or history window")
    if ticker.startswith(("60", "688")):
        code = f"sh{ticker}"
    elif ticker.startswith(("00", "30")):
        code = f"sz{ticker}"
    else:
        raise ValueError("Tencent daily volume units are not verified for this market")
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        response = await client.get(
            URL, params={"param": f"{code},day,{start},{end},{days + 1},qfq"}
        )
        response.raise_for_status()
        payload = response.json()
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 0
    ):
        raise ValueError("Tencent daily returned an invalid response or upstream error")
    data = payload.get("data")
    stock = data.get(code) if isinstance(data, dict) else None
    raw_rows = stock.get("qfqday") if isinstance(stock, dict) else None
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Tencent daily is missing adjusted history")
    rows: list[BarValues] = []
    shares_by_date: dict[date, int] = {}
    previous_close: float | None = None
    for raw in sorted(raw_rows, key=lambda row: row[0] if isinstance(row, list) and row else ""):
        if not isinstance(raw, list) or len(raw) < 9:
            raise ValueError("Tencent daily is missing OHLC, volume or amount")
        day = date.fromisoformat(raw[0])
        if day > end:
            continue
        opened, closed, high, low, amount = (float(raw[i]) for i in (1, 2, 3, 4, 8))
        volume = Decimal(str(raw[5])) * (1 if ticker.startswith("688") else 100)
        if (
            not all(math.isfinite(n) for n in (opened, closed, high, low, amount))
            or min(opened, closed, high, low) <= 0
            or amount < 0
            or not volume.is_finite()
            or volume < 0
            or volume != volume.to_integral_value()
        ):
            raise ValueError("Tencent daily contains invalid numeric values")
        if day >= start:
            if day in shares_by_date:
                raise ValueError("Tencent daily contains duplicate trading dates")
            shares = int(volume)
            shares_by_date[day] = shares
            # Keep the old lot column compatible; consumers use the exact share override.
            amount_yuan = float(Decimal(str(raw[8])) * 10_000)
            if not math.isfinite(amount_yuan):
                raise ValueError("Tencent daily amount is out of range")
            rows.append(
                (
                    day,
                    opened,
                    high,
                    low,
                    closed,
                    previous_close if previous_close is not None else closed,
                    round(volume / 100),
                    amount_yuan,
                )
            )
        previous_close = closed
    if not rows or rows[-1][0] != end:
        raise ValueError("Tencent daily is missing the required completed session")
    return DailyHistory(bars=rows, volume_shares=shares_by_date)

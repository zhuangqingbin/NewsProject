# src/news_pipeline/scrapers/common/ratelimit.py
from aiolimiter import AsyncLimiter


def per_minute(rate: int) -> AsyncLimiter:
    return AsyncLimiter(max_rate=rate, time_period=60)

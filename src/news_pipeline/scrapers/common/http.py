# src/news_pipeline/scrapers/common/http.py
import random

import httpx

DEFAULT_UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]


def make_async_client(
    timeout: float = 15.0,
    ua_pool: list[str] | None = None,
) -> httpx.AsyncClient:
    pool = ua_pool or DEFAULT_UA_POOL
    headers = {
        "User-Agent": random.choice(pool),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    return httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)

# src/news_pipeline/pushers/common/retry.py
import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

T = TypeVar("T")


def async_retry(
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            attempt = 0
            while True:
                try:
                    return await fn(*args, **kwargs)
                except retry_on:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

        return wrapper

    return deco

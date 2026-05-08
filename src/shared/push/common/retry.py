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
    exclude_on: tuple[type[BaseException], ...] = (),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Retry an async function on specified exception types.

    Args:
        max_attempts: Maximum number of total attempts (including the first).
        backoff_seconds: Base backoff in seconds (doubles each retry).
        retry_on: Exception types that trigger a retry.
        exclude_on: Exception types that are explicitly NOT retried even if they
            match retry_on (e.g. a permanent-error subclass of RuntimeError).
            Exclusions are checked before retry_on, so subclasses take priority.
    """

    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            attempt = 0
            while True:
                try:
                    return await fn(*args, **kwargs)
                except BaseException as exc:
                    # Excluded types are never retried — re-raise immediately
                    if exclude_on and isinstance(exc, exclude_on):
                        raise
                    # Only retry if the exception matches retry_on
                    if not isinstance(exc, retry_on):
                        raise
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

        return wrapper

    return deco

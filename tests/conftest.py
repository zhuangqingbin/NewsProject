"""Shared database lifecycle for quote watcher tests."""

from collections.abc import AsyncIterator

import pytest

from quote_watcher.storage.db import QuoteDatabase


@pytest.fixture
async def quote_db() -> AsyncIterator[QuoteDatabase]:
    database = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    try:
        await database.initialize()
        yield database
    finally:
        await database.close()

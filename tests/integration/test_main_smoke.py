import asyncio
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.config import Config

from news_pipeline.main import _amain
from news_pipeline.scrapers.registry import ScraperRegistry
from shared.observability.heartbeat import heartbeat_healthy
from tests.unit.optimization.test_v2_runtime import snapshot


@pytest.mark.parametrize("mode", ["legacy", "shadow", "v2"])
async def test_main_starts_and_exits_clean(mode, tmp_path, monkeypatch):
    db_path = tmp_path / "news.db"
    heartbeat_path = tmp_path / "heartbeat.json"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    monkeypatch.setenv("HEARTBEAT_PATH", str(heartbeat_path))
    monkeypatch.setenv("NEWS_PIPELINE_ONCE", "1")
    loader = MagicMock()
    loader.load.return_value = snapshot(mode)
    monkeypatch.setattr("news_pipeline.main.ConfigLoader", lambda _: loader)
    monkeypatch.setattr("news_pipeline.main.build_pushers", lambda *args: {})
    monkeypatch.setattr("news_pipeline.main.build_registry", lambda *args: ScraperRegistry())
    migration = Config("alembic.ini")
    migration.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    await asyncio.to_thread(command.upgrade, migration, "head")
    await _amain()
    assert db_path.is_file()
    assert heartbeat_healthy(heartbeat_path)

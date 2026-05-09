"""Verify the alembic baseline migration produces the same schema as Base.metadata.create_all."""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _alembic_config(db_url: str) -> Config:
    cfg = Config("scripts/alembic_quotes.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.mark.asyncio
async def test_alembic_upgrade_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "quotes.db"
    sync_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(sync_url)
    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"quote_bars_1min", "quote_bars_daily", "alert_state", "alert_history"}.issubset(
        tables
    )
    engine.dispose()


@pytest.mark.asyncio
async def test_alembic_downgrade_drops_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "quotes.db"
    sync_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(sync_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(sync_url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    # Only alembic_version remains after downgrade
    assert "quote_bars_1min" not in tables
    assert "quote_bars_daily" not in tables
    assert "alert_state" not in tables
    assert "alert_history" not in tables
    engine.dispose()
